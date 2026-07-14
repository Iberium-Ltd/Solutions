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
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.attribution import (
    AttributionAssessment,
    AttributionConfidenceBand,
    HumanAttributionDecision,
    HumanAttributionState,
    PositiveAttributionSignal,
    PositiveSignalContribution,
)
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind, EvidenceMetadataEntry
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.infrastructure.db.phase6_repository import Phase6AuditRepository
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4597"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()
NOW_US = 1_750_000_000_000_000
PROVIDER_A = "synthetic-checkpoint-a"
PROVIDER_B = "synthetic-checkpoint-b"


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


def _headers(*, authenticated: bool = True) -> dict[str, str]:
    headers = {
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }
    if authenticated:
        headers["Ariadne-Session"] = TOKEN
    return headers


async def _profile(client: httpx.AsyncClient, label: str) -> str:
    response = await client.post(
        "/v1/profiles",
        json={
            "idempotencyKey": str(uuid4()),
            "displayLabel": label,
            "purpose": "Synthetic local checkpoint verification",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


def _finding(
    repository: Phase5AttributionRepository,
    *,
    finding_id: str,
    provider_id: str,
) -> None:
    repository.persist_finding(
        FindingDraft(
            finding_id=finding_id,
            title="Synthetic checkpoint finding",
            summary="Synthetic material for deterministic local checkpoint verification.",
            outcome=FindingOutcome.FOUND,
            severity=FindingSeverity.LOW,
            visibility=FindingVisibility.PUBLIC_PSEUDONYMOUS,
            provider_id=provider_id,
            provider_label="Synthetic local provider",
            observed_at_us=NOW_US,
        )
    )


def _evidence(
    service: EvidenceArtifactService,
    *,
    artifact_id: str,
    finding_id: str,
    content: bytes,
    captured_at_us: int,
) -> None:
    service.manual_local_import(
        artifact_id=artifact_id,
        kind=EvidenceArtifactKind.RAW_JSON,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=captured_at_us,
        provider_id=PROVIDER_A,
        run_id=str(uuid4()),
        finding_id=finding_id,
        metadata=(EvidenceMetadataEntry("synthetic", "checkpoint"),),
    )


async def _checkpoint(
    client: httpx.AsyncClient,
    profile_id: str,
    *,
    coverage: list[dict[str, str]] | None = None,
    authenticated: bool = True,
) -> httpx.Response:
    return await client.post(
        "/v1/phase6/audits/local-checkpoint",
        json={
            "profileId": profile_id,
            "runState": "COMPLETED",
            "providerCoverage": coverage
            if coverage is not None
            else [
                {"providerId": PROVIDER_A, "state": "COMPLETE"},
                {"providerId": "synthetic-empty", "state": "NOT_CHECKED"},
            ],
        },
        headers=_headers(authenticated=authenticated),
    )


@pytest.mark.anyio
async def test_local_checkpoint_materializes_current_phase5_state_without_content(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic local checkpoint vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic checkpoint profile")
        other_profile_id = await _profile(client, "Synthetic empty checkpoint profile")
        scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
        attribution = Phase5AttributionRepository(manager.engine, **scope)
        evidence = Phase5EvidenceRepository(manager.engine, **scope)
        evidence_service = EvidenceArtifactService(evidence)
        finding_id = str(uuid4())
        excluded_finding_id = str(uuid4())
        artifact_id = str(uuid4())
        _finding(attribution, finding_id=finding_id, provider_id=PROVIDER_A)
        _finding(attribution, finding_id=excluded_finding_id, provider_id=PROVIDER_B)
        _evidence(
            evidence_service,
            artifact_id=artifact_id,
            finding_id=finding_id,
            content=b'{"synthetic":"checkpoint-one"}',
            captured_at_us=NOW_US + 1,
        )

        audits = Phase6AuditRepository(manager.engine, **scope)
        first_response = await _checkpoint(client, profile_id)
        assert first_response.status_code == 200
        first_body = first_response.json()
        assert first_body == {
            "runId": first_body["runId"],
            "sequence": 1,
            "capturedAtUs": first_body["capturedAtUs"],
            "runState": "COMPLETED",
            "findingCount": 1,
            "providerCount": 2,
            "profileId": profile_id,
            "localOnly": True,
        }
        assert str(UUID(first_body["runId"])) == first_body["runId"]
        first = audits.get_snapshot(first_body["runId"]).snapshot
        assert [item.stable_id for item in first.findings] == [finding_id]
        assert excluded_finding_id not in first_response.text
        assert "contentFingerprint" not in first_response.text
        first_fingerprint = first.findings[0].content_fingerprint

        assessment_id = str(uuid4())
        assessment = AttributionAssessment(
            case_id=finding_id,
            weight_profile_version="synthetic-checkpoint-v1",
            score=200,
            contributing_signals=(
                PositiveSignalContribution(
                    signal=PositiveAttributionSignal.SAME_PROJECT,
                    weight=200,
                    evidence_references=(artifact_id,),
                ),
            ),
            contradictions=(),
            missing_evidence=(),
            confidence_band=AttributionConfidenceBand.MEDIUM,
            recommended_next_evidence=(),
        )
        attribution.persist_assessment(
            assessment_id=assessment_id,
            assessment=assessment,
            assessed_at_us=NOW_US + 2,
        )
        second_body = (await _checkpoint(client, profile_id)).json()
        second = audits.get_snapshot(second_body["runId"]).snapshot
        assert second.sequence == 2
        assert second.captured_at_us > first.captured_at_us
        assert second.findings[0].stable_id == finding_id
        assert second.findings[0].content_fingerprint != first_fingerprint

        attribution.persist_decision(
            decision_id=str(uuid4()),
            assessment_id=assessment_id,
            decision=HumanAttributionDecision(
                case_id=finding_id,
                state=HumanAttributionState.CONFIRMED_MATCH,
                actor_id="local-user",
                decided_at_us=NOW_US + 3,
                weight_profile_version="synthetic-checkpoint-v1",
            ),
            expected_previous_decision_id=None,
        )
        third_body = (await _checkpoint(client, profile_id)).json()
        third = audits.get_snapshot(third_body["runId"]).snapshot
        assert third.sequence == 3
        assert third.findings[0].content_fingerprint != second.findings[0].content_fingerprint

        fourth_body = (await _checkpoint(client, profile_id)).json()
        fourth = audits.get_snapshot(fourth_body["runId"]).snapshot
        assert fourth.sequence == 4
        assert fourth.findings[0].content_fingerprint == third.findings[0].content_fingerprint

        second_artifact_id = str(uuid4())
        _evidence(
            evidence_service,
            artifact_id=second_artifact_id,
            finding_id=finding_id,
            content=b'{"synthetic":"checkpoint-two"}',
            captured_at_us=NOW_US + 4,
        )
        fifth_body = (await _checkpoint(client, profile_id)).json()
        fifth = audits.get_snapshot(fifth_body["runId"]).snapshot
        assert fifth.sequence == 5
        assert fifth.findings[0].content_fingerprint != fourth.findings[0].content_fingerprint

        derivative = b'{"synthetic":"redacted"}'
        evidence_service.create_redacted_derivative(
            derivative_id=str(uuid4()),
            original_artifact_id=artifact_id,
            content=derivative,
            content_sha256=sha256_hex(derivative),
            created_at_us=NOW_US + 5,
            redaction_policy_version="synthetic-redaction-v1",
            redaction_summary_code="SYNTHETIC_REDACTION",
        )
        sixth_body = (await _checkpoint(client, profile_id)).json()
        sixth = audits.get_snapshot(sixth_body["runId"]).snapshot
        assert sixth.sequence == 6
        assert sixth.findings[0].content_fingerprint != fifth.findings[0].content_fingerprint

        for state in ("NOT_CHECKED", "BLOCKED"):
            rejected = await _checkpoint(
                client,
                profile_id,
                coverage=[{"providerId": PROVIDER_A, "state": state}],
            )
            assert rejected.status_code == 400
        assert audits.count_snapshots() == 6

        cross_profile = await _checkpoint(
            client,
            other_profile_id,
            coverage=[{"providerId": PROVIDER_A, "state": "COMPLETE"}],
        )
        assert cross_profile.status_code == 200
        assert cross_profile.json()["findingCount"] == 0
        other_scope = {
            "vault_id": manager.manifest.vault_id,
            "profile_id": other_profile_id,
        }
        other_snapshot = Phase6AuditRepository(manager.engine, **other_scope).get_snapshot(
            cross_profile.json()["runId"]
        )
        assert other_snapshot.snapshot.findings == ()

    manager.lock()


@pytest.mark.anyio
async def test_local_checkpoint_requires_authentication_unlock_and_strict_coverage(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic checkpoint boundary vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic checkpoint boundary profile")
        unauthenticated = await _checkpoint(client, profile_id, authenticated=False)
        assert unauthenticated.status_code == 401

        duplicate_coverage = await _checkpoint(
            client,
            profile_id,
            coverage=[
                {"providerId": PROVIDER_A, "state": "COMPLETE"},
                {"providerId": PROVIDER_A, "state": "CHECK_FAILED"},
            ],
        )
        assert duplicate_coverage.status_code == 400
        empty_coverage = await _checkpoint(client, profile_id, coverage=[])
        assert empty_coverage.status_code == 400

        manager.lock()
        locked = await _checkpoint(client, profile_id)
        assert locked.status_code == 409
