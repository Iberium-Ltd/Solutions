from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError

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
from ariadne_core.domain.remediation import RemediationAction, RemediationStatus
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.intake_identity_repository import IntakeIdentityRepository
from ariadne_core.infrastructure.db.migrate import migration_config, upgrade_to_head
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.infrastructure.db.phase6_repository import (
    AuditSnapshotCapacity,
    AuditSnapshotOrderConflict,
    DuplicatePhase6Id,
    Phase6AuditRepository,
    Phase6RemediationRepository,
    RemediationPersistenceConflict,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian

NOW_US = 1_750_000_000_000_000
PROVIDER_ID = "provider-synthetic-local"


def _profile(manager: VaultManager, suffix: str) -> str:
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=b"6" * 32)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label=f"Synthetic Phase 6 profile {suffix}",
        purpose="Synthetic audit and remediation persistence verification",
    )
    repository.close()
    return profile.id


def _phase5_repositories(
    manager: VaultManager,
    profile_id: str,
) -> tuple[Phase5AttributionRepository, Phase5EvidenceRepository]:
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    return (
        Phase5AttributionRepository(manager.engine, **scope),
        Phase5EvidenceRepository(manager.engine, **scope),
    )


def _finding(
    repository: Phase5AttributionRepository,
    finding_id: str,
    *,
    observed_at_us: int = NOW_US,
) -> None:
    repository.persist_finding(
        FindingDraft(
            finding_id=finding_id,
            title="Synthetic audit finding",
            summary="Synthetic Phase 6 repository verification material.",
            outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
            severity=FindingSeverity.MEDIUM,
            visibility=FindingVisibility.PUBLICLY_ATTRIBUTABLE,
            provider_id=PROVIDER_ID,
            provider_label="Synthetic local provider",
            observed_at_us=observed_at_us,
        )
    )


def _artifact(
    repository: Phase5EvidenceRepository,
    artifact_id: str,
    finding_id: str,
    *,
    captured_at_us: int,
) -> None:
    content = f"synthetic:{artifact_id}".encode()
    EvidenceArtifactService(repository).manual_local_import(
        artifact_id=artifact_id,
        kind=EvidenceArtifactKind.RAW_JSON,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=captured_at_us,
        provider_id=PROVIDER_ID,
        run_id="run-synthetic-phase6-evidence",
        finding_id=finding_id,
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(f"synthetic:{value}".encode()).hexdigest()


def _snapshot(
    run: int,
    findings: tuple[tuple[str, str], ...],
    *,
    sequence: int | None = None,
) -> AuditRunSnapshot:
    return AuditRunSnapshot(
        run_id=f"run-synthetic-phase6-{run}",
        sequence=run if sequence is None else sequence,
        captured_at_us=NOW_US + run,
        run_state=SnapshotRunState.COMPLETED,
        findings=tuple(
            FindingSnapshot(
                stable_id=finding_id,
                provider_id=PROVIDER_ID,
                content_fingerprint=_fingerprint(content),
            )
            for finding_id, content in findings
        ),
        provider_coverage=(ProviderCoverage(PROVIDER_ID, ProviderCoverageState.COMPLETE),),
    )


def test_phase6_schema_upgrades_forward_from_phase5_head(tmp_path: Path) -> None:
    key = bytearray(b"6" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007_phase5_evidence_attribution")
    upgrade_to_head(engine)
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        tables = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'phase6_%'"
            ).all()
        }
    assert revision == "0011_profile_purge"
    assert tables == {
        "phase6_audit_snapshots",
        "phase6_audit_snapshot_findings",
        "phase6_audit_snapshot_coverage",
        "phase6_remediation_revisions",
        "phase6_remediation_findings",
        "phase6_remediation_evidence",
        "phase6_remediation_provider_responses",
        "phase6_remediation_provider_response_evidence",
        "phase6_remediation_history",
        "phase6_remediation_history_evidence",
    }
    engine.dispose()
    key[:] = b"\x00" * len(key)


def test_audit_snapshots_exact_replay_comparison_summary_and_reopen(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 6 audit vault")
    profile_id = _profile(manager, "audit")
    attribution, _ = _phase5_repositories(manager, profile_id)
    _finding(attribution, "finding-synthetic-phase6-one")
    _finding(attribution, "finding-synthetic-phase6-two", observed_at_us=NOW_US + 1)
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    repository = Phase6AuditRepository(manager.engine, **scope)
    baseline = _snapshot(1, (("finding-synthetic-phase6-one", "before"),))
    middle = _snapshot(2, (("finding-synthetic-phase6-one", "middle"),))
    current = _snapshot(
        3,
        (
            ("finding-synthetic-phase6-one", "after"),
            ("finding-synthetic-phase6-two", "new"),
        ),
    )

    first = repository.persist_snapshot(baseline)
    repository.persist_snapshot(middle)
    repository.persist_snapshot(current)
    assert repository.persist_snapshot(baseline) == first
    assert repository.list_timeline() == (baseline, middle, current)
    assert repository.list_timeline_through(current.run_id) == (baseline, middle, current)
    assert repository.comparison_timeline(baseline.run_id, current.run_id) == (
        baseline,
        middle,
        current,
    )
    summaries = repository.list_run_summaries()
    assert [(item.run_id, item.finding_count, item.provider_count) for item in summaries] == [
        (current.run_id, 2, 1),
        (middle.run_id, 1, 1),
        (baseline.run_id, 1, 1),
    ]

    manager.lock()
    manager.unlock()
    reopened = Phase6AuditRepository(manager.engine, **scope)
    assert reopened.get_snapshot(current.run_id).snapshot == current
    assert reopened.count_snapshots() == 3
    manager.lock()


def test_audit_snapshot_bounds_order_profile_isolation_and_immutability(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic isolated Phase 6 audit vault")
    first_profile = _profile(manager, "first")
    second_profile = _profile(manager, "second")
    first_attribution, _ = _phase5_repositories(manager, first_profile)
    second_attribution, _ = _phase5_repositories(manager, second_profile)
    _finding(first_attribution, "finding-synthetic-phase6-first")
    _finding(second_attribution, "finding-synthetic-phase6-second")
    first = Phase6AuditRepository(
        manager.engine,
        vault_id=manager.manifest.vault_id,
        profile_id=first_profile,
        maximum_snapshots=2,
    )
    second = Phase6AuditRepository(
        manager.engine,
        vault_id=manager.manifest.vault_id,
        profile_id=second_profile,
    )

    with pytest.raises(LookupError, match="this profile"):
        first.persist_snapshot(
            _snapshot(1, (("finding-synthetic-phase6-second", "cross-profile"),))
        )
    mismatched_provider = AuditRunSnapshot(
        run_id="run-synthetic-phase6-provider-mismatch",
        sequence=1,
        captured_at_us=NOW_US + 1,
        run_state=SnapshotRunState.COMPLETED,
        findings=(
            FindingSnapshot(
                stable_id="finding-synthetic-phase6-first",
                provider_id="provider-synthetic-mismatch",
                content_fingerprint=_fingerprint("provider-mismatch"),
            ),
        ),
        provider_coverage=(
            ProviderCoverage(
                "provider-synthetic-mismatch",
                ProviderCoverageState.COMPLETE,
            ),
        ),
    )
    with pytest.raises(LookupError, match="this profile"):
        first.persist_snapshot(mismatched_provider)
    baseline = _snapshot(1, (("finding-synthetic-phase6-first", "one"),))
    current = _snapshot(2, (("finding-synthetic-phase6-first", "two"),))
    first.persist_snapshot(baseline)
    first.persist_snapshot(current)
    with pytest.raises(AuditSnapshotCapacity):
        first.persist_snapshot(_snapshot(3, (("finding-synthetic-phase6-first", "three"),)))
    with pytest.raises(AuditSnapshotOrderConflict):
        Phase6AuditRepository(
            manager.engine,
            vault_id=manager.manifest.vault_id,
            profile_id=first_profile,
        ).persist_snapshot(
            _snapshot(4, (("finding-synthetic-phase6-first", "old-sequence"),), sequence=2)
        )
    with pytest.raises(LookupError, match="unavailable"):
        second.get_snapshot(baseline.run_id)
    with pytest.raises(DuplicatePhase6Id):
        first.persist_snapshot(_snapshot(1, (("finding-synthetic-phase6-first", "changed"),)))
    with (
        pytest.raises(DBAPIError, match="immutable Phase 6 record"),
        manager.engine.begin() as connection,
    ):
        connection.exec_driver_sql(
            "UPDATE phase6_audit_snapshots SET sequence = 99 "
            "WHERE vault_id = ? AND profile_id = ? AND run_id = ?",
            (manager.manifest.vault_id, first_profile, baseline.run_id),
        )
    manager.lock()


def test_remediation_revisions_are_cas_append_only_exactly_replayable_and_bounded(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 6 remediation vault")
    profile_id = _profile(manager, "remediation")
    attribution, evidence = _phase5_repositories(manager, profile_id)
    finding_id = "finding-synthetic-phase6-remediation"
    artifact_id = "artifact-synthetic-phase6-remediation"
    _finding(attribution, finding_id)
    _artifact(evidence, artifact_id, finding_id, captured_at_us=NOW_US + 1)
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    repository = Phase6RemediationRepository(manager.engine, **scope)
    service = RemediationService()
    created = service.create_case(
        case_id="case-synthetic-phase6-remediation",
        finding_ids=(finding_id,),
        action=RemediationAction.REQUEST_CORRECTION,
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 2,
        evidence_references=(artifact_id,),
    )
    drafted = service.update_draft(
        created,
        expected_revision=1,
        draft_text="Synthetic local correction draft; no action is sent.",
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 3,
    )
    responded = service.record_provider_response(
        drafted,
        expected_revision=2,
        provider_id=PROVIDER_ID,
        response_code="SYNTHETIC_ACKNOWLEDGED",
        summary="Synthetic response recorded from a manual workflow.",
        evidence_references=(artifact_id,),
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 4,
    )

    first = repository.persist_case(created, expected_previous_revision=None)
    repository.persist_case(drafted, expected_previous_revision=1)
    latest = repository.persist_case(responded, expected_previous_revision=2)
    assert repository.persist_case(responded, expected_previous_revision=2) == latest
    assert repository.get_case(created.case_id, revision=1) == first
    assert repository.get_case(created.case_id).case == responded
    summary = repository.list_case_summaries()[0]
    assert (
        summary.case_id,
        summary.finding_ids,
        summary.revision,
        summary.status,
        summary.finding_count,
        summary.evidence_count,
        summary.provider_response_count,
    ) == (
        created.case_id,
        (finding_id,),
        3,
        RemediationStatus.IN_PROGRESS,
        1,
        1,
        1,
    )
    assert repository.count_cases() == 1
    assert not hasattr(repository, "send")
    assert not hasattr(repository, "submit")
    assert not hasattr(repository, "dispatch")

    next_revision = service.transition_status(
        responded,
        expected_revision=3,
        target_status=RemediationStatus.MONITORING,
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 5,
    )
    with pytest.raises(RemediationPersistenceConflict, match="revision"):
        repository.persist_case(next_revision, expected_previous_revision=1)
    with pytest.raises(RemediationPersistenceConflict, match="draft"):
        repository.persist_case(
            replace(next_revision, draft_text="Synthetic unrecorded draft mutation."),
            expected_previous_revision=3,
        )
    alternate_draft = service.update_draft(
        created,
        expected_revision=1,
        draft_text="Different synthetic draft content.",
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 3,
    )
    with pytest.raises(DuplicatePhase6Id, match="different content"):
        repository.persist_case(alternate_draft, expected_previous_revision=1)
    with (
        pytest.raises(DBAPIError, match="immutable Phase 6 record"),
        manager.engine.begin() as connection,
    ):
        connection.exec_driver_sql(
            "UPDATE phase6_remediation_revisions SET status = 'CLOSED' "
            "WHERE vault_id = ? AND profile_id = ? AND case_id = ? AND revision = 3",
            (manager.manifest.vault_id, profile_id, created.case_id),
        )
    with (
        pytest.raises(DBAPIError, match="immutable Phase 6 record"),
        manager.engine.begin() as connection,
    ):
        connection.exec_driver_sql(
            "UPDATE phase6_remediation_history SET detail_code = 'SYNTHETIC_MUTATION' "
            "WHERE vault_id = ? AND profile_id = ? AND case_id = ? AND revision = 3",
            (manager.manifest.vault_id, profile_id, created.case_id),
        )

    manager.lock()
    manager.unlock()
    reopened = Phase6RemediationRepository(manager.engine, **scope)
    assert reopened.get_case(created.case_id).case == responded
    manager.lock()


def test_remediation_rejects_cross_profile_findings_and_evidence(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic isolated Phase 6 remediation vault")
    first_profile = _profile(manager, "first-remediation")
    second_profile = _profile(manager, "second-remediation")
    first_attribution, _ = _phase5_repositories(manager, first_profile)
    second_attribution, second_evidence = _phase5_repositories(manager, second_profile)
    first_finding = "finding-synthetic-phase6-remediation-first"
    second_finding = "finding-synthetic-phase6-remediation-second"
    second_artifact = "artifact-synthetic-phase6-remediation-second"
    _finding(first_attribution, first_finding)
    _finding(second_attribution, second_finding)
    _artifact(second_evidence, second_artifact, second_finding, captured_at_us=NOW_US + 1)
    repository = Phase6RemediationRepository(
        manager.engine,
        vault_id=manager.manifest.vault_id,
        profile_id=first_profile,
    )
    service = RemediationService()
    cross_finding = service.create_case(
        case_id="case-synthetic-phase6-cross-finding",
        finding_ids=(second_finding,),
        action=RemediationAction.MONITOR,
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 2,
    )
    with pytest.raises(LookupError, match="finding"):
        repository.persist_case(cross_finding, expected_previous_revision=None)

    cross_evidence = service.create_case(
        case_id="case-synthetic-phase6-cross-evidence",
        finding_ids=(first_finding,),
        action=RemediationAction.PRESERVE_EVIDENCE,
        actor_id="actor-synthetic-local",
        occurred_at_us=NOW_US + 3,
        evidence_references=(second_artifact,),
    )
    with pytest.raises(LookupError, match="evidence"):
        repository.persist_case(cross_evidence, expected_previous_revision=None)
    assert repository.count_cases() == 0
    manager.lock()
