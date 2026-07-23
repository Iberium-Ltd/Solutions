from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.attribution import (
    AttributionCase,
    AttributionConfidenceBand,
    HumanAttributionDecision,
    HumanAttributionState,
    PositiveAttributionSignal,
    PositiveSignalObservation,
)
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.intake_identity_repository import IntakeIdentityRepository
from ariadne_core.infrastructure.db.migrate import migration_config, upgrade_to_head
from ariadne_core.infrastructure.db.phase5_repository import (
    AttributionRevisionConflict,
    DuplicatePhase5Id,
    EvidenceIntegrityState,
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian


def _profile(manager: VaultManager, suffix: str) -> str:
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=b"f" * 32)
    record = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label=f"Synthetic Phase 5 profile {suffix}",
        purpose="Synthetic durable evidence verification",
    )
    repository.close()
    return record.id


def _finding(finding_id: str, observed_at_us: int = 1_000_000) -> FindingDraft:
    return FindingDraft(
        finding_id=finding_id,
        title="Synthetic public profile",
        summary="Synthetic evidence created only for repository verification.",
        outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
        severity=FindingSeverity.MEDIUM,
        visibility=FindingVisibility.PUBLICLY_ATTRIBUTABLE,
        provider_id="provider-synthetic-local",
        provider_label="Synthetic local source",
        observed_at_us=observed_at_us,
    )


def _repositories(
    manager: VaultManager,
    profile_id: str,
) -> tuple[Phase5AttributionRepository, Phase5EvidenceRepository]:
    scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
    return (
        Phase5AttributionRepository(manager.engine, **scope),
        Phase5EvidenceRepository(manager.engine, **scope),
    )


def test_phase5_schema_upgrades_forward_from_query_policy_head(tmp_path: Path) -> None:
    key = bytearray(b"p" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0006_query_policy_core")
    upgrade_to_head(engine)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "0011_profile_purge"
        )
        tables = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).all()
        }
    assert {
        "phase5_findings",
        "phase5_evidence_originals",
        "phase5_finding_evidence",
        "phase5_evidence_derivatives",
        "phase5_attribution_assessments",
        "phase5_attribution_signals",
        "phase5_attribution_signal_evidence",
        "phase5_attribution_missing_evidence",
        "phase5_attribution_decisions",
    } <= tables
    engine.dispose()
    key[:] = b"\x00" * len(key)


def test_evidence_dedup_links_one_original_to_multiple_findings_and_survives_reopen(
    tmp_path: Path,
) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manager.create(display_name="Synthetic Phase 5 vault")
    profile_id = _profile(manager, "primary")
    attribution, evidence = _repositories(manager, profile_id)
    attribution.persist_finding(_finding("finding-synthetic-one"))
    attribution.persist_finding(_finding("finding-synthetic-two", 1_000_001))
    service = EvidenceArtifactService(evidence)
    content = b"<html><body>Synthetic public result</body></html>"
    first = service.manual_local_import(
        artifact_id="artifact-synthetic-one",
        kind=EvidenceArtifactKind.HTML,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=1_100_000,
        provider_id="provider-synthetic-local",
        run_id="run-synthetic-one",
        finding_id="finding-synthetic-one",
    )
    duplicate = service.manual_local_import(
        artifact_id="artifact-synthetic-two",
        kind=EvidenceArtifactKind.HTML,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=1_100_001,
        provider_id="provider-synthetic-local",
        run_id="run-synthetic-one",
        finding_id="finding-synthetic-two",
    )
    assert duplicate.deduplicated is True
    assert duplicate.artifact.artifact_id == first.artifact.artifact_id
    assert evidence.count_originals_for_finding("finding-synthetic-one") == 1
    assert evidence.count_originals_for_finding("finding-synthetic-two") == 1
    assert (
        evidence.verify_original(first.artifact.artifact_id).state
        is EvidenceIntegrityState.VERIFIED
    )

    manager.lock()
    manager.unlock()
    reopened_attribution, reopened_evidence = _repositories(manager, profile_id)
    assert reopened_attribution.count_findings() == 2
    assert reopened_evidence.get_original(first.artifact.artifact_id) == first.artifact
    assert reopened_evidence.count_originals_for_finding("finding-synthetic-two") == 1
    manager.lock()


def test_manual_finding_and_neutral_assessment_are_atomic_and_durable(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic manual finding vault")
    profile_id = _profile(manager, "manual-atomic")
    attribution, _evidence = _repositories(manager, profile_id)
    draft = _finding("finding-synthetic-manual-atomic")
    assessment = AttributionScoringService().assess(
        AttributionCase(
            case_id=draft.finding_id,
            missing_evidence=frozenset(PositiveAttributionSignal),
        )
    )

    stored_finding, stored_assessment = attribution.persist_manual_finding_with_initial_assessment(
        draft=draft,
        assessment_id="assessment-synthetic-manual-atomic",
        assessment=assessment,
        assessed_at_us=1_000_001,
    )

    assert stored_finding.finding_id == draft.finding_id
    assert stored_assessment.assessment.score == 0
    assert stored_assessment.assessment.confidence_band is AttributionConfidenceBand.LOW
    assert stored_assessment.assessment.contributing_signals == ()
    assert stored_assessment.assessment.contradictions == ()
    assert {item.signal for item in stored_assessment.assessment.missing_evidence} == set(
        PositiveAttributionSignal
    )
    assert stored_assessment.assessment.human_review_required is True
    assert attribution.latest_decision(draft.finding_id) is None

    manager.lock()
    manager.unlock()
    reopened, _evidence = _repositories(manager, profile_id)
    assert reopened.get_finding(draft.finding_id) == stored_finding
    assert reopened.get_assessment(stored_assessment.assessment_id) == stored_assessment
    manager.lock()


def test_manual_finding_transaction_rolls_back_if_initial_assessment_fails(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic manual finding rollback vault")
    profile_id = _profile(manager, "manual-rollback")
    attribution, _evidence = _repositories(manager, profile_id)
    draft = _finding("finding-synthetic-manual-rollback")
    assessment_id = "assessment-synthetic-manual-rollback"
    assessment = AttributionScoringService().assess(
        AttributionCase(
            case_id=draft.finding_id,
            missing_evidence=frozenset(PositiveAttributionSignal),
        )
    )
    with manager.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER test_reject_manual_assessment_missing "
            "BEFORE INSERT ON phase5_attribution_missing_evidence "
            "WHEN NEW.assessment_id = 'assessment-synthetic-manual-rollback' BEGIN "
            "SELECT RAISE(ABORT, 'synthetic assessment failure'); END"
        )

    with pytest.raises(DuplicatePhase5Id):
        attribution.persist_manual_finding_with_initial_assessment(
            draft=draft,
            assessment_id=assessment_id,
            assessment=assessment,
            assessed_at_us=1_000_001,
        )

    assert attribution.count_findings() == 0
    with pytest.raises(LookupError, match="unavailable"):
        attribution.get_finding(draft.finding_id)
    with pytest.raises(LookupError, match="unavailable"):
        attribution.get_assessment(assessment_id)
    manager.lock()


def test_evidence_and_attribution_are_profile_scoped_and_require_finding_links(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic isolated Phase 5 vault")
    first_profile = _profile(manager, "one")
    second_profile = _profile(manager, "two")
    first_attribution, first_evidence = _repositories(manager, first_profile)
    second_attribution, second_evidence = _repositories(manager, second_profile)
    first_attribution.persist_finding(_finding("finding-synthetic-a"))
    first_attribution.persist_finding(_finding("finding-synthetic-b", 1_000_001))
    second_attribution.persist_finding(_finding("finding-synthetic-c"))
    service = EvidenceArtifactService(first_evidence)
    content = b"synthetic isolated evidence"
    artifact = service.manual_local_import(
        artifact_id="artifact-synthetic-isolated",
        kind=EvidenceArtifactKind.RAW_JSON,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=1_200_000,
        provider_id="provider-synthetic-local",
        run_id="run-synthetic-isolated",
        finding_id="finding-synthetic-a",
    ).artifact
    with pytest.raises(LookupError, match="unavailable"):
        second_evidence.link_original_to_finding(artifact.artifact_id, "finding-synthetic-c")

    assessment = AttributionScoringService().assess(
        AttributionCase(
            case_id="finding-synthetic-b",
            positive_observations=(
                PositiveSignalObservation(
                    PositiveAttributionSignal.EXACT_EMAIL,
                    (artifact.artifact_id,),
                ),
            ),
        )
    )
    with pytest.raises(LookupError, match="not linked"):
        first_attribution.persist_assessment(
            assessment_id="assessment-synthetic-unlinked",
            assessment=assessment,
            assessed_at_us=1_300_000,
        )
    with manager.engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(first_attribution.assessments)
            ).scalar_one()
            == 0
        )
    manager.lock()


def test_assessment_and_human_decision_exact_replay_are_idempotent_and_append_only(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic attribution recovery vault")
    profile_id = _profile(manager, "attribution")
    attribution, evidence = _repositories(manager, profile_id)
    finding = attribution.persist_finding(_finding("finding-synthetic-attribution"))
    content = b"synthetic attribution evidence"
    artifact = (
        EvidenceArtifactService(evidence)
        .manual_local_import(
            artifact_id="artifact-synthetic-attribution",
            kind=EvidenceArtifactKind.RAW_JSON,
            content=content,
            content_sha256=sha256_hex(content),
            captured_at_us=1_400_000,
            provider_id="provider-synthetic-local",
            run_id="run-synthetic-attribution",
            finding_id=finding.finding_id,
        )
        .artifact
    )
    assessment = AttributionScoringService().assess(
        AttributionCase(
            case_id=finding.finding_id,
            positive_observations=(
                PositiveSignalObservation(
                    PositiveAttributionSignal.EXACT_EMAIL,
                    (artifact.artifact_id,),
                ),
            ),
            missing_evidence=frozenset({PositiveAttributionSignal.SAME_PHOTOGRAPH}),
        )
    )
    stored = attribution.persist_assessment(
        assessment_id="assessment-synthetic-one",
        assessment=assessment,
        assessed_at_us=1_500_000,
    )
    replay = attribution.persist_assessment(
        assessment_id="assessment-synthetic-one",
        assessment=assessment,
        assessed_at_us=1_500_000,
    )
    assert replay == stored

    decision = HumanAttributionDecision(
        case_id=finding.finding_id,
        state=HumanAttributionState.PROBABLE,
        actor_id="local-user-synthetic",
        decided_at_us=1_600_000,
        weight_profile_version=assessment.weight_profile_version,
    )
    first = attribution.persist_decision(
        decision_id="decision-synthetic-one",
        assessment_id=stored.assessment_id,
        decision=decision,
        expected_previous_decision_id=None,
    )
    assert (
        attribution.persist_decision(
            decision_id="decision-synthetic-one",
            assessment_id=stored.assessment_id,
            decision=decision,
            expected_previous_decision_id=None,
        )
        == first
    )
    with pytest.raises(AttributionRevisionConflict):
        attribution.persist_decision(
            decision_id="decision-synthetic-stale",
            assessment_id=stored.assessment_id,
            decision=HumanAttributionDecision(
                case_id=finding.finding_id,
                state=HumanAttributionState.NEEDS_MORE_EVIDENCE,
                actor_id="local-user-synthetic",
                decided_at_us=1_700_000,
                weight_profile_version=assessment.weight_profile_version,
            ),
            expected_previous_decision_id=None,
        )
    with (
        pytest.raises(DBAPIError, match="immutable Phase 5 record"),
        manager.engine.begin() as connection,
    ):
        connection.exec_driver_sql(
            "UPDATE phase5_attribution_assessments SET score = 999 WHERE id = ?",
            (stored.assessment_id,),
        )
    assert attribution.latest_assessment(finding.finding_id) == stored
    assert attribution.latest_decision(finding.finding_id) == first
    manager.lock()
