from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.remediation import RemediationService
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.audit_comparison import (
    AuditRunSnapshot,
    FindingSnapshot,
    ProviderCoverage,
    ProviderCoverageState,
    SnapshotRunState,
)
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind
from ariadne_core.domain.remediation import RemediationAction
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.infrastructure.db.phase6_repository import (
    Phase6AuditRepository,
    Phase6RemediationRepository,
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
            "purpose": "Synthetic monitoring and remediation review",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


def _seed_phase6(manager: VaultManager, profile_id: str) -> tuple[str, str, str, str, str]:
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    attribution = Phase5AttributionRepository(manager.engine, **scope)
    evidence = Phase5EvidenceRepository(manager.engine, **scope)
    finding_id = str(uuid4())
    artifact_id = str(uuid4())
    attribution.persist_finding(
        FindingDraft(
            finding_id=finding_id,
            title="Synthetic monitored record",
            summary="A synthetic record used to verify local audit comparison.",
            outcome=FindingOutcome.FOUND,
            severity=FindingSeverity.LOW,
            visibility=FindingVisibility.PUBLIC_PSEUDONYMOUS,
            provider_id="manual-import",
            provider_label="Synthetic manual provider",
            observed_at_us=1_750_000_000_000_000,
        )
    )
    content = b'{"synthetic":true,"phase":6}'
    EvidenceArtifactService(evidence).manual_local_import(
        artifact_id=artifact_id,
        kind=EvidenceArtifactKind.RAW_JSON,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=1_750_000_000_000_001,
        provider_id="manual-import",
        run_id=str(uuid4()),
        finding_id=finding_id,
    )

    run_ids = (str(uuid4()), str(uuid4()), str(uuid4()))
    fingerprints = tuple(
        hashlib.sha256(f"synthetic:{label}".encode()).hexdigest()
        for label in ("baseline", "intervening", "baseline")
    )
    audits = Phase6AuditRepository(manager.engine, **scope)
    for sequence, (run_id, fingerprint) in enumerate(
        zip(run_ids, fingerprints, strict=True),
        start=1,
    ):
        audits.persist_snapshot(
            AuditRunSnapshot(
                run_id=run_id,
                sequence=sequence,
                captured_at_us=1_750_000_000_000_010 + sequence,
                run_state=SnapshotRunState.COMPLETED,
                findings=(
                    FindingSnapshot(
                        stable_id=finding_id,
                        provider_id="manual-import",
                        content_fingerprint=fingerprint,
                    ),
                ),
                provider_coverage=(
                    ProviderCoverage(
                        provider_id="manual-import",
                        state=ProviderCoverageState.COMPLETE,
                    ),
                ),
            )
        )

    case_id = str(uuid4())
    case = RemediationService().create_case(
        case_id=case_id,
        finding_ids=(finding_id,),
        action=RemediationAction.REQUEST_CORRECTION,
        actor_id="local-user",
        occurred_at_us=1_750_000_000_000_020,
        evidence_references=(artifact_id,),
        draft_text="Synthetic correction request draft.",
    )
    Phase6RemediationRepository(manager.engine, **scope).persist_case(
        case,
        expected_previous_revision=None,
    )
    return finding_id, artifact_id, run_ids[0], run_ids[2], case_id


@pytest.mark.anyio
async def test_phase6_native_reads_compare_selected_runs_and_project_remediation(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 6 API vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic Phase 6 profile")
        other_profile_id = await _profile(client, "Synthetic empty Phase 6 profile")
        finding_id, artifact_id, baseline_id, current_id, case_id = _seed_phase6(
            manager,
            profile_id,
        )

        capabilities = await client.get("/v1/system/capabilities", headers=_headers())
        available = {
            item["key"] for item in capabilities.json()["features"] if item["status"] == "AVAILABLE"
        }
        assert {"audit_comparison", "remediation"} <= available

        run_list = await client.post(
            "/v1/phase6/audits/list",
            json={"profileId": profile_id, "limit": 32},
            headers=_headers(),
        )
        assert run_list.status_code == 200
        assert [item["sequence"] for item in run_list.json()["runs"]] == [3, 2, 1]

        comparison = await client.post(
            "/v1/phase6/audits/compare",
            json={
                "profileId": profile_id,
                "baselineRunId": baseline_id,
                "currentRunId": current_id,
            },
            headers=_headers(),
        )
        assert comparison.status_code == 200
        compared = comparison.json()
        assert compared["diffs"] == [
            {
                "stableId": finding_id,
                "providerId": "manual-import",
                "state": "UNCHANGED",
                "previousFingerprint": compared["diffs"][0]["previousFingerprint"],
                "currentFingerprint": compared["diffs"][0]["currentFingerprint"],
            }
        ]
        assert len(compared["lifecycles"][0]["events"]) == 3
        assert compared["lifecycles"][0]["events"][-1]["runId"] == current_id

        cases = await client.post(
            "/v1/phase6/remediation/list",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert cases.status_code == 200
        assert cases.json()["cases"][0]["caseId"] == case_id
        assert cases.json()["cases"][0]["findingIds"] == [finding_id]

        detail = await client.post(
            "/v1/phase6/remediation/detail",
            json={"profileId": profile_id, "caseId": case_id},
            headers=_headers(),
        )
        assert detail.status_code == 200
        body = detail.json()["case"]
        assert body["draftText"] == "Synthetic correction request draft."
        assert body["evidenceReferences"] == [artifact_id]
        assert body["history"][0]["actorLabel"] == "Local user"
        assert "actorId" not in detail.text

        cross_profile = await client.post(
            "/v1/phase6/audits/compare",
            json={
                "profileId": other_profile_id,
                "baselineRunId": baseline_id,
                "currentRunId": current_id,
            },
            headers=_headers(),
        )
        assert cross_profile.status_code == 404

    manager.lock()


@pytest.mark.anyio
async def test_phase6_routes_require_authentication_and_unlocked_vault(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 6 lock vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic locked Phase 6 profile")
        unauthenticated = await client.post(
            "/v1/phase6/audits/list",
            json={"profileId": profile_id, "limit": 32},
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated.status_code == 401
        unauthenticated_write = await client.post(
            "/v1/phase6/remediation/create",
            json={
                "profileId": profile_id,
                "findingIds": [str(uuid4())],
                "action": "MONITOR",
                "deadlineAtUs": None,
                "evidenceReferences": [],
                "draftText": None,
            },
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated_write.status_code == 401
        manager.lock()
        locked = await client.post(
            "/v1/phase6/audits/list",
            json={"profileId": profile_id, "limit": 32},
            headers=_headers(),
        )
        assert locked.status_code == 409
        locked_write = await client.post(
            "/v1/phase6/remediation/create",
            json={
                "profileId": profile_id,
                "findingIds": [str(uuid4())],
                "action": "MONITOR",
                "deadlineAtUs": None,
                "evidenceReferences": [],
                "draftText": None,
            },
            headers=_headers(),
        )
        assert locked_write.status_code == 409


@pytest.mark.anyio
async def test_phase6_remediation_mutations_persist_exact_cas_history(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 6 mutation vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic Phase 6 mutation profile")
        other_profile_id = await _profile(client, "Synthetic Phase 6 other profile")
        finding_id, artifact_id, *_ = _seed_phase6(manager, profile_id)
        other_finding_id, other_artifact_id, *_ = _seed_phase6(manager, other_profile_id)

        cross_profile_create = await client.post(
            "/v1/phase6/remediation/create",
            json={
                "profileId": profile_id,
                "findingIds": [other_finding_id],
                "action": "MONITOR",
                "deadlineAtUs": None,
                "evidenceReferences": [],
                "draftText": None,
            },
            headers=_headers(),
        )
        assert cross_profile_create.status_code == 404

        created = await client.post(
            "/v1/phase6/remediation/create",
            json={
                "profileId": profile_id,
                "findingIds": [finding_id],
                "action": "REQUEST_CORRECTION",
                "deadlineAtUs": None,
                "evidenceReferences": [],
                "draftText": None,
            },
            headers=_headers(),
        )
        assert created.status_code == 200
        created_body = created.json()
        case_id = created_body["case"]["caseId"]
        assert UUID(case_id).version == 4
        assert created_body["case"]["revision"] == 1
        assert created_body["case"]["history"][-1]["eventType"] == "CASE_CREATED"
        assert created_body["case"]["history"][-1]["actorLabel"] == "Local user"
        assert "actorId" not in created.text

        draft = await client.post(
            "/v1/phase6/remediation/draft",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 1,
                "draftText": "Synthetic correction draft for local review.",
            },
            headers=_headers(),
        )
        assert draft.status_code == 200
        assert draft.json()["case"]["revision"] == 2
        assert draft.json()["case"]["draftText"] == ("Synthetic correction draft for local review.")

        approval = await client.post(
            "/v1/phase6/remediation/require-approval",
            json={"profileId": profile_id, "caseId": case_id, "expectedRevision": 2},
            headers=_headers(),
        )
        assert approval.status_code == 200
        assert approval.json()["case"]["revision"] == 3
        assert approval.json()["case"]["actionDisposition"] == "REQUIRE_EXPLICIT_APPROVAL"
        assert approval.json()["case"]["status"] == "AWAITING_EXPLICIT_APPROVAL"

        status = await client.post(
            "/v1/phase6/remediation/status",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 3,
                "targetStatus": "IN_PROGRESS",
                "note": "Synthetic local tracking resumed.",
            },
            headers=_headers(),
        )
        assert status.status_code == 200
        assert status.json()["case"]["revision"] == 4
        assert status.json()["case"]["history"][-1]["note"] == ("Synthetic local tracking resumed.")

        deadline_at_us = time.time_ns() // 1_000 + 60_000_000
        deadline = await client.post(
            "/v1/phase6/remediation/deadline",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 4,
                "deadlineAtUs": deadline_at_us,
            },
            headers=_headers(),
        )
        assert deadline.status_code == 200
        assert deadline.json()["case"]["deadlineAtUs"] == deadline_at_us
        cleared = await client.post(
            "/v1/phase6/remediation/deadline",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 5,
                "deadlineAtUs": None,
            },
            headers=_headers(),
        )
        assert cleared.status_code == 200
        assert cleared.json()["case"]["revision"] == 6
        assert cleared.json()["case"]["deadlineAtUs"] is None

        evidence = await client.post(
            "/v1/phase6/remediation/evidence",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 6,
                "evidenceReferences": [artifact_id],
            },
            headers=_headers(),
        )
        assert evidence.status_code == 200
        assert evidence.json()["case"]["evidenceReferences"] == [artifact_id]

        provider_response = await client.post(
            "/v1/phase6/remediation/provider-response",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 7,
                "providerId": "synthetic-provider",
                "responseCode": "RECEIVED",
                "summary": "Synthetic acknowledgement recorded locally.",
                "evidenceReferences": [artifact_id],
            },
            headers=_headers(),
        )
        assert provider_response.status_code == 200
        provider_case = provider_response.json()["case"]
        assert provider_case["revision"] == 8
        assert provider_case["providerResponses"][0]["responseCode"] == "RECEIVED"

        reappearance = await client.post(
            "/v1/phase6/remediation/reappearance",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 8,
                "findingId": finding_id,
                "evidenceReferences": [artifact_id],
            },
            headers=_headers(),
        )
        assert reappearance.status_code == 200
        final_case = reappearance.json()["case"]
        assert final_case["revision"] == 9
        assert final_case["reappearanceCount"] == 1
        assert len(final_case["history"]) == 9
        assert final_case["history"][-1]["eventType"] == "REAPPEARANCE_RECORDED"

        stale = await client.post(
            "/v1/phase6/remediation/draft",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 1,
                "draftText": "Synthetic stale draft.",
            },
            headers=_headers(),
        )
        assert stale.status_code == 409

        cross_profile_evidence = await client.post(
            "/v1/phase6/remediation/evidence",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 9,
                "evidenceReferences": [other_artifact_id],
            },
            headers=_headers(),
        )
        assert cross_profile_evidence.status_code == 404
        cross_profile_finding = await client.post(
            "/v1/phase6/remediation/reappearance",
            json={
                "profileId": profile_id,
                "caseId": case_id,
                "expectedRevision": 9,
                "findingId": other_finding_id,
                "evidenceReferences": [artifact_id],
            },
            headers=_headers(),
        )
        assert cross_profile_finding.status_code == 404

        exact = await client.post(
            "/v1/phase6/remediation/detail",
            json={"profileId": profile_id, "caseId": case_id},
            headers=_headers(),
        )
        assert exact.status_code == 200
        assert exact.json()["case"] == final_case

    manager.lock()
