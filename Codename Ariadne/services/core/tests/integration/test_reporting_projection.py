from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.reporting_schemas import (
    MAX_REPORT_API_RESPONSE_BYTES,
    ReportGenerateRequest,
)
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.remediation import RemediationService
from ariadne_core.application.reporting_projection import (
    ReportingNotFound,
    ReportingProjectionCoordinator,
    ReportingUnavailable,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.attribution import (
    AttributionCase,
    HumanAttributionDecision,
    HumanAttributionState,
    PositiveAttributionSignal,
    PositiveSignalObservation,
)
from ariadne_core.domain.audit_comparison import (
    AuditRunSnapshot,
    FindingSnapshot,
    ProviderCoverage,
    ProviderCoverageState,
    SnapshotRunState,
)
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
)
from ariadne_core.domain.remediation import RemediationAction
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.intake_identity_repository import (
    IntakeIdentityRepository,
)
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

NOW_US = 1_760_000_000_000_000
SENSITIVE_TITLE = "Synthetic private report title"
SENSITIVE_SUMMARY = "Synthetic private report summary"
SENSITIVE_PROVIDER = "Synthetic private provider label"
SENSITIVE_DRAFT = "Synthetic private remediation draft"
EVIDENCE_BYTES = b'{"synthetic":"private evidence bytes must never be exported"}'
EXACT_SOURCE_URL = "https://evidence.synthetic.example/report-source"
REDIRECT_SOURCE_URL = "https://redirect.synthetic.example/report-source"
HOST = "127.0.0.1:4595"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _hash(value: str) -> str:
    return hashlib.sha256(f"synthetic:{value}".encode()).hexdigest()


def _profile(manager: VaultManager, label: str) -> str:
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=bytes(range(32)))
    try:
        return repository.create_profile(
            vault_id=manager.manifest.vault_id,
            profile_id=str(uuid4()),
            display_label=label,
            purpose="Synthetic local report verification",
        ).id
    finally:
        repository.close()


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


def _seed_report(manager: VaultManager, profile_id: str) -> tuple[str, str, str, str]:
    vault_id = manager.manifest.vault_id
    attribution = Phase5AttributionRepository(
        manager.engine,
        vault_id=vault_id,
        profile_id=profile_id,
    )
    evidence = Phase5EvidenceRepository(
        manager.engine,
        vault_id=vault_id,
        profile_id=profile_id,
    )
    finding_id = str(uuid4())
    artifact_id = str(uuid4())
    evidence_run_id = str(uuid4())
    attribution.persist_finding(
        FindingDraft(
            finding_id=finding_id,
            title=SENSITIVE_TITLE,
            summary=SENSITIVE_SUMMARY,
            outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
            severity=FindingSeverity.MEDIUM,
            visibility=FindingVisibility.PUBLIC_PSEUDONYMOUS,
            provider_id="synthetic-provider",
            provider_label=SENSITIVE_PROVIDER,
            observed_at_us=NOW_US,
        )
    )
    artifact = (
        EvidenceArtifactService(evidence)
        .capture_original(
            artifact_id=artifact_id,
            kind=EvidenceArtifactKind.RAW_JSON,
            content=EVIDENCE_BYTES,
            content_sha256=sha256_hex(EVIDENCE_BYTES),
            captured_at_us=NOW_US + 1,
            source_url=EXACT_SOURCE_URL,
            http_status=200,
            redirect_chain=(REDIRECT_SOURCE_URL,),
            masked_query_reference="mq_0123456789abcdef",
            provider_id="synthetic-provider",
            run_id=evidence_run_id,
            finding_id=finding_id,
            viewport=None,
            capture_method=EvidenceCaptureMethod.PROVIDER_API,
            metadata=(
                EvidenceMetadataEntry(
                    key="capture.provider",
                    value="synthetic-provider-response",
                ),
            ),
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
            missing_evidence=frozenset({PositiveAttributionSignal.USER_CONFIRMATION}),
        )
    )
    stored_assessment = attribution.persist_assessment(
        assessment_id=str(uuid4()),
        assessment=assessment,
        assessed_at_us=NOW_US + 2,
    )
    attribution.persist_decision(
        decision_id=str(uuid4()),
        assessment_id=stored_assessment.assessment_id,
        decision=HumanAttributionDecision(
            case_id=finding_id,
            state=HumanAttributionState.PROBABLE,
            actor_id="local-user",
            decided_at_us=NOW_US + 3,
            weight_profile_version=assessment.weight_profile_version,
        ),
        expected_previous_decision_id=None,
    )

    baseline_run_id = str(uuid4())
    current_run_id = str(uuid4())
    audits = Phase6AuditRepository(
        manager.engine,
        vault_id=vault_id,
        profile_id=profile_id,
    )
    for sequence, (run_id, fingerprint) in enumerate(
        (
            (baseline_run_id, _hash("baseline")),
            (current_run_id, _hash("current")),
        ),
        start=1,
    ):
        audits.persist_snapshot(
            AuditRunSnapshot(
                run_id=run_id,
                sequence=sequence,
                captured_at_us=NOW_US + 10 + sequence,
                run_state=SnapshotRunState.COMPLETED,
                findings=(
                    FindingSnapshot(
                        stable_id=finding_id,
                        provider_id="synthetic-provider",
                        content_fingerprint=fingerprint,
                    ),
                ),
                provider_coverage=(
                    ProviderCoverage(
                        provider_id="synthetic-provider",
                        state=ProviderCoverageState.COMPLETE,
                    ),
                ),
            )
        )

    case = RemediationService().create_case(
        case_id=str(uuid4()),
        finding_ids=(finding_id,),
        action=RemediationAction.REQUEST_CORRECTION,
        actor_id="local-user",
        occurred_at_us=NOW_US + 20,
        evidence_references=(artifact_id,),
        draft_text=SENSITIVE_DRAFT,
    )
    Phase6RemediationRepository(
        manager.engine,
        vault_id=vault_id,
        profile_id=profile_id,
    ).persist_case(case, expected_previous_revision=None)
    return finding_id, artifact_id, baseline_run_id, current_run_id


def _request(
    profile_id: str,
    baseline_run_id: str,
    current_run_id: str,
    *,
    artifact_format: str = "JSON",
    mode: str = "REDACTED",
    approval_id: str | None = None,
) -> ReportGenerateRequest:
    return ReportGenerateRequest.model_validate(
        {
            "profileId": profile_id,
            "baselineRunId": baseline_run_id,
            "currentRunId": current_run_id,
            "artifactFormat": artifact_format,
            "mode": mode,
            "fullExportApprovalId": approval_id,
        }
    )


def test_persisted_redacted_projection_leaks_no_sensitive_text_ids_or_evidence_bytes(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic reporting vault")
    profile_id = _profile(manager, "Synthetic private profile label")
    finding_id, artifact_id, baseline_run_id, current_run_id = _seed_report(
        manager,
        profile_id,
    )
    result = ReportingProjectionCoordinator(manager, clock=lambda: NOW_US + 100).generate(
        _request(profile_id, baseline_run_id, current_run_id),
    )

    document = json.loads(result.artifact.content)
    assert result.local_only is True
    assert result.artifact.filename == "report.json"
    assert result.artifact.byte_count == len(result.artifact.content.encode("utf-8"))
    assert (
        result.artifact.sha256
        == hashlib.sha256(result.artifact.content.encode("utf-8")).hexdigest()
    )
    assert result.manifest.generated_at_us == NOW_US + 100
    assert document["constraints"] == {
        "active_content_included": False,
        "evidence_bytes_included": False,
        "filesystem_writes_performed": False,
        "network_access_performed": False,
        "outbound_actions_performed": False,
    }
    sensitive = {
        SENSITIVE_TITLE,
        SENSITIVE_SUMMARY,
        SENSITIVE_PROVIDER,
        SENSITIVE_DRAFT,
        EVIDENCE_BYTES.decode(),
        finding_id,
        artifact_id,
        baseline_run_id,
        current_run_id,
        profile_id,
        EXACT_SOURCE_URL,
        REDIRECT_SOURCE_URL,
    }
    assert all(value not in result.artifact.content for value in sensitive)
    projected_evidence = document["findings"][0]["evidence"][0]
    assert projected_evidence["source_url"] is None
    assert projected_evidence["source_url_redaction"] == "REMOVED_IN_REDACTED_REPORT"
    assert (
        projected_evidence["source_url_sha256"]
        == hashlib.sha256(EXACT_SOURCE_URL.encode()).hexdigest()
    )
    assert projected_evidence["content_sha256"] == sha256_hex(EVIDENCE_BYTES)
    redacted_artifact_id = projected_evidence["artifact_id"]
    assert redacted_artifact_id.startswith("redacted-id-")
    assert document["findings"][0]["attribution"]["contributing_signal_sources"] == [
        {
            "evidence_references": [redacted_artifact_id],
            "signal": "SAME_PROJECT",
            "weight": 50,
        }
    ]
    assert all(
        item["value"] is not None and item["redaction"] is None
        for item in projected_evidence["metadata"]
        if item["key"].endswith("_sha256")
    )
    assert len(result.model_dump_json(by_alias=True).encode("utf-8")) <= (
        MAX_REPORT_API_RESPONSE_BYTES
    )
    assert [item.filename for item in result.manifest.artifacts] == [
        "report.json",
        "report.md",
    ]
    manager.lock()


def test_full_projection_binds_approval_and_still_excludes_evidence_bytes(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic full reporting vault")
    profile_id = _profile(manager, "Synthetic full profile")
    finding_id, artifact_id, baseline_run_id, current_run_id = _seed_report(
        manager,
        profile_id,
    )
    approval_id = str(uuid4())

    result = ReportingProjectionCoordinator(manager, clock=lambda: NOW_US + 101).generate(
        _request(
            profile_id,
            baseline_run_id,
            current_run_id,
            artifact_format="JSON",
            mode="FULL_EXPLICIT",
            approval_id=approval_id,
        )
    )

    assert result.artifact.filename == "report.json"
    assert result.manifest.full_export_approval_id == approval_id
    assert approval_id in result.artifact.content
    assert SENSITIVE_TITLE in result.artifact.content
    assert SENSITIVE_DRAFT in result.artifact.content
    assert finding_id in result.artifact.content
    assert artifact_id in result.artifact.content
    assert EVIDENCE_BYTES.decode() not in result.artifact.content
    document = json.loads(result.artifact.content)
    projected_finding = document["findings"][0]
    projected_evidence = projected_finding["evidence"][0]
    expected_source_fields = {
        "artifact_id": artifact_id,
        "capture_method": "PROVIDER_API",
        "captured_at_us": NOW_US + 1,
        "content_sha256": sha256_hex(EVIDENCE_BYTES),
        "http_status": 200,
        "kind": "RAW_JSON",
        "provider_id": "synthetic-provider",
        "redirect_count": 1,
        "source_url": EXACT_SOURCE_URL,
        "source_url_redaction": None,
        "source_url_sha256": hashlib.sha256(EXACT_SOURCE_URL.encode()).hexdigest(),
    }
    assert {
        key: projected_evidence[key] for key in expected_source_fields
    } == expected_source_fields
    assert projected_finding["attribution"]["contributing_signal_sources"] == [
        {
            "evidence_references": [artifact_id],
            "signal": "SAME_PROJECT",
            "weight": 50,
        }
    ]
    manager.lock()


def test_report_projection_never_selects_evidence_content_columns(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic metadata-only reporting vault")
    profile_id = _profile(manager, "Synthetic metadata-only profile")
    _, _, baseline_run_id, current_run_id = _seed_report(manager, profile_id)
    statements: list[str] = []

    def record_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(manager.engine, "before_cursor_execute", record_sql)
    try:
        ReportingProjectionCoordinator(manager, clock=lambda: NOW_US + 102).generate(
            _request(
                profile_id,
                baseline_run_id,
                current_run_id,
                mode="FULL_EXPLICIT",
                approval_id=str(uuid4()),
            )
        )
    finally:
        event.remove(manager.engine, "before_cursor_execute", record_sql)

    evidence_selects = [
        statement
        for statement in statements
        if "phase5_evidence_originals" in statement or "phase5_evidence_derivatives" in statement
    ]
    assert evidence_selects
    content_column = re.compile(
        r"\bphase5_evidence_(?:originals|derivatives)\.content\b(?!_)",
        flags=re.IGNORECASE,
    )
    assert all(content_column.search(statement) is None for statement in evidence_selects)
    manager.lock()


def test_projection_rejects_cross_profile_and_nonexistent_runs(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic scoped reporting vault")
    profile_id = _profile(manager, "Synthetic primary report profile")
    other_profile_id = _profile(manager, "Synthetic isolated report profile")
    _, _, baseline_run_id, current_run_id = _seed_report(manager, profile_id)
    coordinator = ReportingProjectionCoordinator(manager, clock=lambda: NOW_US + 102)

    with pytest.raises(ReportingNotFound):
        coordinator.generate(_request(other_profile_id, baseline_run_id, current_run_id))
    with pytest.raises(ReportingNotFound):
        coordinator.generate(_request(profile_id, str(uuid4()), current_run_id))

    manager.lock()
    with pytest.raises(ReportingUnavailable):
        coordinator.generate(_request(profile_id, baseline_run_id, current_run_id))


@pytest.mark.anyio
async def test_authenticated_report_route_exposes_exact_bounded_local_contract(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic report API vault")
    profile_id = _profile(manager, "Synthetic report API profile")
    _, _, baseline_run_id, current_run_id = _seed_report(manager, profile_id)
    app = _app(manager)
    payload = {
        "profileId": profile_id,
        "baselineRunId": baseline_run_id,
        "currentRunId": current_run_id,
        "artifactFormat": "JSON",
        "mode": "REDACTED",
        "fullExportApprovalId": None,
    }

    capability = app.openapi()["paths"]["/v1/reports/generate"]["post"]["x-ariadne-capability"]
    assert capability == {
        "routeId": "reports.generate",
        "maxRequestBytes": 1_024,
        "maxResponseBytes": MAX_REPORT_API_RESPONSE_BYTES,
        "requiredLockState": "UNLOCKED",
        "scopeClass": "PROFILE",
        "revealClass": "NONE",
        "authorizationClass": "USER_GESTURE",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        capabilities = await client.get("/v1/system/capabilities", headers=_headers())
        assert capabilities.status_code == 200
        available = {
            item["key"] for item in capabilities.json()["features"] if item["status"] == "AVAILABLE"
        }
        assert "import_export" in available

        unauthenticated = await client.post(
            "/v1/reports/generate",
            json=payload,
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated.status_code == 401

        oversized = await client.post(
            "/v1/reports/generate",
            json={**payload, "padding": "x" * 2_000},
            headers=_headers(),
        )
        assert oversized.status_code == 413

        response = await client.post(
            "/v1/reports/generate",
            json=payload,
            headers=_headers(),
        )
        assert response.status_code == 200
        result = response.json()
        assert set(result) == {
            "profileId",
            "baselineRunId",
            "currentRunId",
            "localOnly",
            "artifact",
            "manifest",
        }
        assert result["profileId"] == profile_id
        assert result["baselineRunId"] == baseline_run_id
        assert result["currentRunId"] == current_run_id
        assert result["localOnly"] is True
        assert set(result["artifact"]) == {
            "filename",
            "mediaType",
            "byteCount",
            "sha256",
            "schema",
            "version",
            "mode",
            "content",
        }
        assert set(result["manifest"]) == {
            "schema",
            "version",
            "mode",
            "generatedAtUs",
            "fullExportApprovalId",
            "artifacts",
        }
        assert EVIDENCE_BYTES.decode() not in response.text
        assert len(response.content) <= MAX_REPORT_API_RESPONSE_BYTES

        manager.lock()
        locked = await client.post(
            "/v1/reports/generate",
            json=payload,
            headers=_headers(),
        )
        assert locked.status_code == 409
