from __future__ import annotations

import base64
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.attribution import (
    AttributionCase,
    HumanAttributionDecision,
    HumanAttributionState,
    PositiveAttributionSignal,
    PositiveSignalObservation,
)
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4595"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(manager: VaultManager) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            vault_manager=manager,
            key_lease_client=cast(KeyLeaseClient, object()),
            cipher_runtime=CipherRuntime(
                sqlite_version="3.53.3",
                cipher_version="4.17.0 community",
                foreign_keys=True,
                journal_mode="delete",
                temp_store=2,
                fts5=True,
                json=True,
            ),
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


async def _profile(client: httpx.AsyncClient, label: str) -> str:
    response = await client.post(
        "/v1/profiles",
        json={
            "idempotencyKey": str(uuid4()),
            "displayLabel": label,
            "purpose": "Synthetic encrypted evidence review",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


def _seed_phase5(
    manager: VaultManager,
    profile_id: str,
    *,
    include_decision: bool = True,
) -> tuple[str, str, bytes, str, str | None]:
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    attribution = Phase5AttributionRepository(manager.engine, **scope)
    evidence = Phase5EvidenceRepository(manager.engine, **scope)
    finding_id = str(uuid4())
    artifact_id = str(uuid4())
    run_id = str(uuid4())
    attribution.persist_finding(
        FindingDraft(
            finding_id=finding_id,
            title="Synthetic public profile record",
            summary="A synthetic local record retained for explainable review.",
            outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
            severity=FindingSeverity.MEDIUM,
            visibility=FindingVisibility.PUBLIC_PSEUDONYMOUS,
            provider_id="manual-import",
            provider_label="Manual local import",
            observed_at_us=1_750_000_000_000_000,
        )
    )
    content = b'{"synthetic":true,"record":"phase-five-local"}'
    artifact = (
        EvidenceArtifactService(evidence)
        .manual_local_import(
            artifact_id=artifact_id,
            kind=EvidenceArtifactKind.RAW_JSON,
            content=content,
            content_sha256=sha256_hex(content),
            captured_at_us=1_750_000_000_000_001,
            provider_id="manual-import",
            run_id=run_id,
            finding_id=finding_id,
        )
        .artifact
    )
    assessment = AttributionScoringService().assess(
        AttributionCase(
            case_id=finding_id,
            positive_observations=(
                PositiveSignalObservation(
                    PositiveAttributionSignal.SAME_PROJECT,
                    (artifact.artifact_id,),
                ),
            ),
            missing_evidence=frozenset(
                {
                    PositiveAttributionSignal.USER_CONFIRMATION,
                    PositiveAttributionSignal.SAME_PHOTOGRAPH,
                }
            ),
        )
    )
    stored = attribution.persist_assessment(
        assessment_id=str(uuid4()),
        assessment=assessment,
        assessed_at_us=1_750_000_000_000_002,
    )
    decision_id: str | None = None
    if include_decision:
        decision = attribution.persist_decision(
            decision_id=str(uuid4()),
            assessment_id=stored.assessment_id,
            decision=HumanAttributionDecision(
                case_id=finding_id,
                state=HumanAttributionState.PROBABLE,
                actor_id="local-user",
                decided_at_us=1_750_000_000_000_003,
                weight_profile_version=assessment.weight_profile_version,
            ),
            expected_previous_decision_id=None,
        )
        decision_id = decision.decision_id
    return finding_id, artifact_id, content, stored.assessment_id, decision_id


@pytest.mark.anyio
async def test_manual_finding_bootstraps_a_fresh_profile_with_neutral_attribution(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic manual finding API vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic fresh manual finding profile")
        payload = {
            "profileId": profile_id,
            "title": "Synthetic manually observed result",
            "summary": "Synthetic local-only record awaiting evidence and human review.",
            "outcome": "MANUAL_REVIEW_REQUIRED",
            "severity": "MEDIUM",
            "visibility": "UNKNOWN",
            "providerId": "manual.synthetic-local",
            "providerLabel": "Synthetic manual source",
        }

        unauthenticated = await client.post(
            "/v1/phase5/findings/manual",
            json=payload,
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated.status_code == 401
        invalid = await client.post(
            "/v1/phase5/findings/manual",
            json={**payload, "title": "Synthetic\ninvalid"},
            headers=_headers(),
        )
        assert invalid.status_code == 400

        created = await client.post(
            "/v1/phase5/findings/manual",
            json=payload,
            headers=_headers(),
        )
        assert created.status_code == 200
        body = created.json()
        finding_id = body["finding"]["findingId"]
        assessment_id = body["assessment"]["assessmentId"]
        assert str(UUID(finding_id)) == finding_id
        assert UUID(finding_id).version == 4
        assert str(UUID(assessment_id)) == assessment_id
        assert UUID(assessment_id).version == 4
        assert body["profileId"] == profile_id
        assert body["finding"] == {
            "findingId": finding_id,
            "title": payload["title"],
            "summary": payload["summary"],
            "outcome": payload["outcome"],
            "severity": payload["severity"],
            "visibility": payload["visibility"],
            "attributionState": None,
            "confidenceBand": "LOW",
            "score": 0,
            "humanReviewRequired": True,
            "providerLabel": payload["providerLabel"],
            "artifactCount": 0,
            "updatedAtUs": body["finding"]["updatedAtUs"],
        }
        assert body["assessment"]["caseId"] == finding_id
        assert body["assessment"]["score"] == 0
        assert body["assessment"]["confidenceBand"] == "LOW"
        assert body["assessment"]["contributingSignals"] == []
        assert body["assessment"]["contradictions"] == []
        assert {item["signal"] for item in body["assessment"]["missingEvidence"]} == {
            signal.value for signal in PositiveAttributionSignal
        }
        assert body["assessment"]["recommendedNextEvidence"] == [
            "IMMUTABLE_PLATFORM_ID_CONTINUITY",
            "USER_CONFIRMATION",
            "EXACT_EMAIL",
        ]
        assert body["assessment"]["humanReviewRequired"] is True
        assert body["artifacts"] == []
        assert body["humanDecision"] is None

        listing = await client.post(
            "/v1/phase5/findings/list",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert listing.status_code == 200
        assert listing.json()["findings"] == [body["finding"]]

        manager.lock()
        manager.unlock()
        reopened = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": profile_id, "findingId": finding_id},
            headers=_headers(),
        )
        assert reopened.status_code == 200
        assert reopened.json() == body

        missing_profile = await client.post(
            "/v1/phase5/findings/manual",
            json={**payload, "profileId": str(uuid4())},
            headers=_headers(),
        )
        assert missing_profile.status_code == 404

    manager.lock()


@pytest.mark.anyio
async def test_phase5_native_read_projection_is_profile_scoped_and_contentless(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 5 API vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic Phase 5 profile")
        other_profile_id = await _profile(client, "Synthetic empty profile")
        finding_id, artifact_id, content, assessment_id, decision_id = _seed_phase5(
            manager, profile_id
        )
        assert decision_id is not None

        capabilities = await client.get("/v1/system/capabilities", headers=_headers())
        available = {
            item["key"] for item in capabilities.json()["features"] if item["status"] == "AVAILABLE"
        }
        assert {"evidence", "attribution"} <= available

        listing = await client.post(
            "/v1/phase5/findings/list",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert listing.status_code == 200
        assert listing.json()["profileId"] == profile_id
        assert listing.json()["hasMore"] is False
        assert listing.json()["findings"][0]["findingId"] == finding_id
        assert listing.json()["findings"][0]["attributionState"] == "PROBABLE"
        assert listing.json()["findings"][0]["humanReviewRequired"] is True

        detail = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": profile_id, "findingId": finding_id},
            headers=_headers(),
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["assessment"]["humanReviewRequired"] is True
        assert body["assessment"]["assessmentId"] == assessment_id
        assert body["humanDecision"]["state"] == "PROBABLE"
        assert body["humanDecision"]["decisionId"] == decision_id
        assert body["humanDecision"]["assessmentId"] == assessment_id
        assert body["humanDecision"]["revision"] == 1
        assert body["humanDecision"]["supersedesDecisionId"] is None
        assert body["artifacts"] == [
            {
                "artifactId": artifact_id,
                "kind": "RAW_JSON",
                "contentSha256": sha256_hex(content),
                "capturedAtUs": 1_750_000_000_000_001,
                "sourceUrl": None,
                "httpStatus": None,
                "redirectCount": 0,
                "providerId": "manual-import",
                "runId": body["artifacts"][0]["runId"],
                "viewport": None,
                "captureMethod": "MANUAL_LOCAL_IMPORT",
                "encryptedAtRest": True,
                "integrityStatus": "VERIFIED",
                "derivativeCount": 0,
            }
        ]
        assert "content" not in body["artifacts"][0]
        assert content.decode() not in detail.text

        empty = await client.post(
            "/v1/phase5/findings/list",
            json={"profileId": other_profile_id, "limit": 100},
            headers=_headers(),
        )
        assert empty.status_code == 200
        assert empty.json()["findings"] == []
        assert empty.json()["hasMore"] is False

        cross_profile = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": other_profile_id, "findingId": finding_id},
            headers=_headers(),
        )
        assert cross_profile.status_code == 404

    manager.lock()


@pytest.mark.anyio
async def test_phase5_routes_require_authentication_and_an_unlocked_vault(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 5 lock vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic locked Phase 5 profile")
        unauthenticated = await client.post(
            "/v1/phase5/findings/list",
            json={"profileId": profile_id, "limit": 100},
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated.status_code == 401
        manager.lock()
        locked = await client.post(
            "/v1/phase5/findings/list",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert locked.status_code == 409


@pytest.mark.anyio
async def test_phase5_manual_import_and_caller_redacted_derivative_are_local_and_contentless(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 5 evidence-write vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic evidence-write profile")
        other_profile_id = await _profile(client, "Synthetic other evidence profile")
        finding_id, original_id, _seed_content, _assessment_id, _decision_id = _seed_phase5(
            manager, profile_id
        )
        imported_content = b'{"synthetic":true,"manual":"local-only"}'
        imported_base64 = base64.b64encode(imported_content).decode("ascii")
        import_payload = {
            "profileId": profile_id,
            "findingId": finding_id,
            "kind": "RAW_JSON",
            "contentBase64": imported_base64,
            "viewport": None,
            "metadata": [
                {"key": "source.label", "value": "Synthetic local fixture"},
            ],
        }

        imported = await client.post(
            "/v1/phase5/evidence/manual-import",
            json=import_payload,
            headers=_headers(),
        )
        assert imported.status_code == 200
        imported_body = imported.json()
        imported_id = imported_body["artifactId"]
        assert imported_body == {
            "profileId": profile_id,
            "findingId": finding_id,
            "artifactId": imported_id,
            "kind": "RAW_JSON",
            "contentSha256": sha256_hex(imported_content),
            "capturedAtUs": imported_body["capturedAtUs"],
            "captureMethod": "MANUAL_LOCAL_IMPORT",
            "encryptedAtRest": True,
            "localOnly": True,
            "deduplicated": False,
        }
        assert imported_base64 not in imported.text

        duplicate = await client.post(
            "/v1/phase5/evidence/manual-import",
            json=import_payload,
            headers=_headers(),
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["artifactId"] == imported_id
        assert duplicate.json()["deduplicated"] is True

        redacted_content = b'{"synthetic":true,"manual":"[REDACTED]"}'
        redacted_base64 = base64.b64encode(redacted_content).decode("ascii")
        redaction_payload = {
            "profileId": profile_id,
            "originalArtifactId": imported_id,
            "redactedContentBase64": redacted_base64,
            "alreadyRedacted": True,
            "redactionPolicyVersion": "manual-redaction-v1",
            "redactionSummaryCode": "SYNTHETIC_FIELD_MASKED",
        }
        derivative = await client.post(
            "/v1/phase5/evidence/redacted-derivative",
            json=redaction_payload,
            headers=_headers(),
        )
        assert derivative.status_code == 200
        derivative_body = derivative.json()
        derivative_id = derivative_body["derivativeId"]
        assert derivative_body == {
            "profileId": profile_id,
            "originalArtifactId": imported_id,
            "derivativeId": derivative_id,
            "contentSha256": sha256_hex(redacted_content),
            "createdAtUs": derivative_body["createdAtUs"],
            "redactionPolicyVersion": "manual-redaction-v1",
            "redactionSummaryCode": "SYNTHETIC_FIELD_MASKED",
            "redactionMode": "CALLER_SUPPLIED",
            "encryptedAtRest": True,
            "localOnly": True,
            "deduplicated": False,
        }
        assert redacted_base64 not in derivative.text

        duplicate_derivative = await client.post(
            "/v1/phase5/evidence/redacted-derivative",
            json=redaction_payload,
            headers=_headers(),
        )
        assert duplicate_derivative.status_code == 200
        assert duplicate_derivative.json()["derivativeId"] == derivative_id
        assert duplicate_derivative.json()["deduplicated"] is True

        detail = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": profile_id, "findingId": finding_id},
            headers=_headers(),
        )
        assert detail.status_code == 200
        artifacts = {item["artifactId"]: item for item in detail.json()["artifacts"]}
        assert set(artifacts) == {original_id, imported_id}
        assert artifacts[imported_id]["derivativeCount"] == 1
        assert "content" not in artifacts[imported_id]

        repository = Phase5EvidenceRepository(
            manager.engine,
            vault_id=manager.manifest.vault_id,
            profile_id=profile_id,
        )
        assert repository.get_original(imported_id).content == imported_content
        assert repository.derivatives_for(imported_id)[0].content == redacted_content

        wrong_profile = await client.post(
            "/v1/phase5/evidence/manual-import",
            json={**import_payload, "profileId": other_profile_id},
            headers=_headers(),
        )
        assert wrong_profile.status_code == 404
        wrong_profile_derivative = await client.post(
            "/v1/phase5/evidence/redacted-derivative",
            json={**redaction_payload, "profileId": other_profile_id},
            headers=_headers(),
        )
        assert wrong_profile_derivative.status_code == 404

        no_attestation = await client.post(
            "/v1/phase5/evidence/redacted-derivative",
            json={**redaction_payload, "alreadyRedacted": False},
            headers=_headers(),
        )
        assert no_attestation.status_code == 400
        assert redacted_base64 not in no_attestation.text

    manager.lock()


@pytest.mark.anyio
async def test_phase5_human_decisions_append_with_exact_optimistic_revision(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 5 decision-write vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic decision-write profile")
        other_profile_id = await _profile(client, "Synthetic other decision profile")
        finding_id, _artifact_id, _content, assessment_id, decision_id = _seed_phase5(
            manager,
            profile_id,
            include_decision=False,
        )
        assert decision_id is None
        initial_payload = {
            "profileId": profile_id,
            "findingId": finding_id,
            "assessmentId": assessment_id,
            "state": "POSSIBLE",
            "expectedPreviousDecisionId": None,
            "expectedPreviousRevision": 0,
        }

        initial = await client.post(
            "/v1/phase5/attribution/decision",
            json=initial_payload,
            headers=_headers(),
        )
        assert initial.status_code == 200
        initial_body = initial.json()
        initial_id = initial_body["decisionId"]
        assert initial_body["revision"] == 1
        assert initial_body["supersedesDecisionId"] is None
        assert initial_body["actorLabel"] == "Local user"

        supersede_payload = {
            **initial_payload,
            "state": "CONFIRMED_MATCH",
            "expectedPreviousDecisionId": initial_id,
            "expectedPreviousRevision": 1,
        }
        superseded = await client.post(
            "/v1/phase5/attribution/decision",
            json=supersede_payload,
            headers=_headers(),
        )
        assert superseded.status_code == 200
        superseded_body = superseded.json()
        assert superseded_body["revision"] == 2
        assert superseded_body["supersedesDecisionId"] == initial_id
        assert superseded_body["decisionId"] != initial_id

        stale = await client.post(
            "/v1/phase5/attribution/decision",
            json=supersede_payload,
            headers=_headers(),
        )
        assert stale.status_code == 409

        detail = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": profile_id, "findingId": finding_id},
            headers=_headers(),
        )
        assert detail.status_code == 200
        assert detail.json()["finding"]["attributionState"] == "CONFIRMED_MATCH"
        assert detail.json()["humanDecision"] == {
            "decisionId": superseded_body["decisionId"],
            "assessmentId": assessment_id,
            "state": "CONFIRMED_MATCH",
            "actorLabel": "Local user",
            "decidedAtUs": superseded_body["decidedAtUs"],
            "weightProfileVersion": "ariadne-core-attribution-v1",
            "supersedesDecisionId": initial_id,
            "revision": 2,
        }

        wrong_profile = await client.post(
            "/v1/phase5/attribution/decision",
            json={**initial_payload, "profileId": other_profile_id},
            headers=_headers(),
        )
        assert wrong_profile.status_code == 404

    manager.lock()
