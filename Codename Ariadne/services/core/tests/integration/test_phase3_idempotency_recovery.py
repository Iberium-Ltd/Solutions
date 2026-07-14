from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from ariadne_core.api.intake_schemas import (
    EntityDecisionRequest,
    EntityDecisionType,
    EntityReviewRequest,
    PasteIntakeRequest,
    ProfileCreateRequest,
    ReviewState,
    SearchPolicy,
    Sensitivity,
    TemporalState,
    TransmissionPolicy,
)
from ariadne_core.application import phase3 as phase3_module
from ariadne_core.application.phase3 import (
    Phase3Conflict,
    Phase3Coordinator,
    _IdempotencyReservation,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.intake_identity_repository import IntakeIdentityRepository
from ariadne_core.infrastructure.db.models import (
    entity_decisions,
    idempotency_records,
    intake_sources,
    jobs,
    profiles,
)
from ariadne_core.infrastructure.db.repositories import RevisionConflict
from ariadne_core.security.key_custody import MemoryKeyCustodian


def _coordinator(tmp_path: Path) -> tuple[VaultManager, Phase3Coordinator]:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic recovery vault")
    return manager, Phase3Coordinator(manager)


def _profile_request(key: str = "synthetic-profile-key-0001") -> ProfileCreateRequest:
    return ProfileCreateRequest(
        idempotency_key=key,
        display_label="Synthetic recovery profile",
        purpose="Synthetic idempotency recovery verification",
    )


def _paste_request(profile_id: str) -> PasteIntakeRequest:
    return PasteIntakeRequest(
        idempotency_key="synthetic-intake-key-0001",
        profile_id=profile_id,
        display_name="Synthetic repeated intake",
        content=(
            "Contact: repeated.person@example.invalid.\nRecovery: repeated.person@example.invalid."
        ),
        consent_confirmed=True,
        retain_raw_source=False,
        semantic_enrichment_enabled=False,
    )


def test_compilation_fault_rolls_back_job_and_all_intake_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    profile = coordinator.create_profile(_profile_request())
    request = _paste_request(profile.profile_id)
    original = IntakeIdentityRepository.persist_compilation

    def fail_after_compilation(self, **kwargs):  # type: ignore[no-untyped-def]
        original(self, **kwargs)
        raise RuntimeError("synthetic process death inside intake transaction")

    monkeypatch.setattr(IntakeIdentityRepository, "persist_compilation", fail_after_compilation)
    with pytest.raises(RuntimeError, match="process death"):
        coordinator.ingest_paste(request)

    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(jobs)).scalar_one() == 0
        assert (
            connection.execute(select(func.count()).select_from(intake_sources)).scalar_one() == 0
        )
        job_keys = connection.execute(
            select(func.count())
            .select_from(idempotency_records)
            .where(idempotency_records.c.route_code == "LOCAL_JOB_CREATE")
        ).scalar_one()
        assert job_keys == 0

    monkeypatch.setattr(IntakeIdentityRepository, "persist_compilation", original)
    receipt = coordinator.ingest_paste(request)
    assert receipt.duplicate_count >= 1
    manager.lock()


def test_lost_intake_response_replays_original_receipt_without_duplicate_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    profile = coordinator.create_profile(_profile_request())
    request = _paste_request(profile.profile_id)
    original_receipt = phase3_module._receipt

    def lose_response(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic response loss after commit")

    monkeypatch.setattr(phase3_module, "_receipt", lose_response)
    with pytest.raises(RuntimeError, match="response loss"):
        coordinator.ingest_paste(request)

    monkeypatch.setattr(phase3_module, "_receipt", original_receipt)
    replay = coordinator.ingest_paste(request)
    assert replay.duplicate_count >= 1
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(jobs)).scalar_one() == 1
        assert (
            connection.execute(select(func.count()).select_from(intake_sources)).scalar_one() == 1
        )
    manager.lock()


def test_expired_incomplete_profile_reservation_recovers_committed_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    request = _profile_request()
    original_complete = _IdempotencyReservation.complete

    def lose_completion(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic completion loss")

    monkeypatch.setattr(_IdempotencyReservation, "complete", lose_completion)
    with pytest.raises(RuntimeError, match="completion loss"):
        coordinator.create_profile(request)

    with manager.engine.begin() as connection:
        original_profile_id = connection.execute(select(profiles.c.id)).scalar_one()
        connection.execute(
            update(idempotency_records)
            .where(idempotency_records.c.route_code == "PHASE3_PROFILE_CREATE")
            .values(expires_at_us=1)
        )

    with pytest.raises(Phase3Conflict, match="idempotency request conflict"):
        coordinator.create_profile(
            ProfileCreateRequest(
                idempotency_key=request.idempotency_key,
                display_label="Different synthetic profile",
                purpose=request.purpose,
            )
        )
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(profiles)).scalar_one() == 1
        assert (
            connection.execute(
                select(func.count())
                .select_from(idempotency_records)
                .where(idempotency_records.c.route_code == "PHASE3_PROFILE_CREATE")
            ).scalar_one()
            == 1
        )

    monkeypatch.setattr(_IdempotencyReservation, "complete", original_complete)
    recovered = coordinator.create_profile(request)
    assert recovered.profile_id == original_profile_id
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(profiles)).scalar_one() == 1
    manager.lock()


def test_expired_completed_profile_key_is_cleaned_and_can_start_a_new_operation(
    tmp_path: Path,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    request = _profile_request()
    first = coordinator.create_profile(request)
    with manager.engine.begin() as connection:
        connection.execute(
            update(idempotency_records)
            .where(idempotency_records.c.route_code == "PHASE3_PROFILE_CREATE")
            .values(expires_at_us=1)
        )

    second = coordinator.create_profile(request)
    assert second.profile_id != first.profile_id
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(profiles)).scalar_one() == 2
        active_records = connection.execute(
            select(func.count())
            .select_from(idempotency_records)
            .where(idempotency_records.c.route_code == "PHASE3_PROFILE_CREATE")
        ).scalar_one()
        assert active_records == 1
    manager.lock()


def test_expired_incomplete_decision_recovers_without_a_second_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    profile = coordinator.create_profile(_profile_request())
    receipt = coordinator.ingest_paste(_paste_request(profile.profile_id))
    candidate = coordinator.review_entities(
        EntityReviewRequest(profile_id=profile.profile_id, source_id=receipt.source_id, limit=100)
    ).entities[0]
    request = EntityDecisionRequest(
        idempotency_key="synthetic-decision-key-0001",
        profile_id=profile.profile_id,
        entity_id=candidate.entity_id,
        expected_revision=candidate.revision,
        decision_type=EntityDecisionType.CONFIRM,
        review_state=ReviewState.CONFIRMED,
        sensitivity=Sensitivity.SENSITIVE,
        temporal_state=TemporalState.UNKNOWN,
        search_policy=SearchPolicy.REQUIRE_APPROVAL,
        transmission_policy=TransmissionPolicy.NEVER,
        reason="Synthetic recovery decision",
    )
    original_complete = _IdempotencyReservation.complete

    def lose_completion(self, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic decision completion loss")

    monkeypatch.setattr(_IdempotencyReservation, "complete", lose_completion)
    with pytest.raises(RuntimeError, match="completion loss"):
        coordinator.decide_entity(request)
    with manager.engine.begin() as connection:
        connection.execute(
            update(idempotency_records)
            .where(idempotency_records.c.route_code == "PHASE3_ENTITY_DECISION")
            .values(expires_at_us=1)
        )

    monkeypatch.setattr(_IdempotencyReservation, "complete", original_complete)
    recovered = coordinator.decide_entity(request)
    assert recovered.revision == candidate.revision + 1
    with manager.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(entity_decisions)).scalar_one() == 1
        )
    manager.lock()


def test_completed_decision_replay_returns_its_historical_response_after_later_decision(
    tmp_path: Path,
) -> None:
    manager, coordinator = _coordinator(tmp_path)
    profile = coordinator.create_profile(_profile_request())
    receipt = coordinator.ingest_paste(_paste_request(profile.profile_id))
    candidate = coordinator.review_entities(
        EntityReviewRequest(profile_id=profile.profile_id, source_id=receipt.source_id, limit=100)
    ).entities[0]
    first_request = EntityDecisionRequest(
        idempotency_key="synthetic-historical-decision-0001",
        profile_id=profile.profile_id,
        entity_id=candidate.entity_id,
        expected_revision=candidate.revision,
        decision_type=EntityDecisionType.CONFIRM,
        review_state=ReviewState.CONFIRMED,
        sensitivity=candidate.sensitivity,
        temporal_state=candidate.temporal_state,
        search_policy=candidate.search_policy,
        transmission_policy=candidate.transmission_policy,
        reason="Synthetic first decision",
    )
    first = coordinator.decide_entity(first_request)
    second = coordinator.decide_entity(
        EntityDecisionRequest(
            idempotency_key="synthetic-historical-decision-0002",
            profile_id=profile.profile_id,
            entity_id=candidate.entity_id,
            expected_revision=first.revision,
            decision_type=EntityDecisionType.POLICY_CHANGE,
            review_state=first.review_state,
            sensitivity=Sensitivity.HIGHLY_SENSITIVE,
            temporal_state=TemporalState.HISTORICAL,
            search_policy=SearchPolicy.STORE_ONLY,
            transmission_policy=TransmissionPolicy.NEVER,
            reason="Synthetic later policy decision",
        )
    )
    assert second.revision == first.revision + 1

    replayed_first = coordinator.decide_entity(first_request)
    assert replayed_first.model_dump(mode="json") == first.model_dump(mode="json")
    with manager.engine.connect() as connection:
        decision_ids = set(connection.execute(select(entity_decisions.c.id)).scalars())
        idempotency_results = set(
            connection.execute(
                select(idempotency_records.c.result_id).where(
                    idempotency_records.c.route_code == "PHASE3_ENTITY_DECISION"
                )
            ).scalars()
        )
        assert decision_ids == idempotency_results
        assert (
            connection.execute(select(func.count()).select_from(entity_decisions)).scalar_one() == 2
        )

    with manager.engine.begin() as connection:
        first_decision_id = connection.execute(
            select(entity_decisions.c.id).where(entity_decisions.c.after_revision == first.revision)
        ).scalar_one()
        connection.execute(
            update(idempotency_records)
            .where(idempotency_records.c.result_id == first_decision_id)
            .values(expires_at_us=1)
        )
    # Once the documented replay window expires, this is a new operation. Its
    # stale expected revision is rejected and cannot append another decision.
    with pytest.raises(RevisionConflict):
        coordinator.decide_entity(first_request)
    with manager.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(entity_decisions)).scalar_one() == 2
        )
    manager.lock()
