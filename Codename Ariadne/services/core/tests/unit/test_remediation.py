from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace

import pytest

from ariadne_core.application.remediation import RemediationConflict, RemediationService
from ariadne_core.domain.remediation import (
    MAX_DRAFT_TEXT,
    MAX_EVIDENCE_REFERENCES,
    ActionDisposition,
    RemediationAction,
    RemediationEventType,
    RemediationStatus,
)

NOW_US = 1_750_000_000_000_000


def _create(
    service: RemediationService,
    action: RemediationAction = RemediationAction.CONTACT,
):
    return service.create_case(
        case_id=f"case-synthetic-{action.value.lower()}",
        finding_ids=("finding-synthetic-primary",),
        action=action,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US,
        evidence_references=("evidence-synthetic-initial",),
    )


def test_action_catalog_is_closed_and_outbound_or_legal_actions_never_become_executable() -> None:
    assert {action.value for action in RemediationAction} == {
        "MONITOR",
        "PRESERVE_EVIDENCE",
        "DELETE_OWNED_ACCOUNT",
        "REQUEST_CORRECTION",
        "DRAFT_ERASURE_OR_DEINDEX",
        "DRAFT_IMPERSONATION_REPORT",
        "CONTACT",
        "ESCALATE",
        "MARK_LEGALLY_PERSISTENT",
    }
    service = RemediationService()
    for action in RemediationAction:
        case = _create(service, action)
        if action in {RemediationAction.MONITOR, RemediationAction.PRESERVE_EVIDENCE}:
            assert case.action_disposition is ActionDisposition.LOCAL_ONLY
        else:
            assert case.action_disposition in {
                ActionDisposition.DRAFT,
                ActionDisposition.REQUIRE_EXPLICIT_APPROVAL,
            }
            with pytest.raises(ValueError, match="cannot be executable"):
                replace(case, action_disposition=ActionDisposition.LOCAL_ONLY)

    assert not hasattr(service, "send")
    assert not hasattr(service, "submit")
    assert not hasattr(service, "dispatch")
    assert not hasattr(service, "approve")
    assert "legal_advice" not in {item.name for item in fields(_create(service))}


def test_case_draft_and_explicit_approval_are_revisioned_append_only_history() -> None:
    service = RemediationService()
    created = _create(service, RemediationAction.REQUEST_CORRECTION)
    drafted = service.update_draft(
        created,
        expected_revision=1,
        draft_text="Synthetic correction draft for local review only.",
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 1,
    )
    awaiting = service.require_explicit_approval(
        drafted,
        expected_revision=2,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 2,
    )

    assert created.revision == 1
    assert drafted.revision == 2
    assert awaiting.revision == 3
    assert created.history[0].event_type is RemediationEventType.CASE_CREATED
    assert [entry.event_type for entry in awaiting.history] == [
        RemediationEventType.CASE_CREATED,
        RemediationEventType.DRAFT_UPDATED,
        RemediationEventType.APPROVAL_REQUIRED,
    ]
    assert awaiting.status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL
    assert awaiting.action_disposition is ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
    assert drafted.draft_text == "Synthetic correction draft for local review only."
    assert created.draft_text is None
    with pytest.raises(FrozenInstanceError):
        created.revision = 9  # type: ignore[misc]


def test_optimistic_revision_monotonic_timestamps_deadlines_and_transitions_fail_closed() -> None:
    service = RemediationService()
    created = _create(service, RemediationAction.MONITOR)

    with pytest.raises(RemediationConflict, match="revision"):
        service.transition_status(
            created,
            expected_revision=2,
            target_status=RemediationStatus.MONITORING,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
    with pytest.raises(RemediationConflict, match="timestamp"):
        service.transition_status(
            created,
            expected_revision=1,
            target_status=RemediationStatus.MONITORING,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US,
        )
    with pytest.raises(ValueError, match="deadline must be in the future"):
        service.set_deadline(
            created,
            expected_revision=1,
            deadline_at_us=NOW_US,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )

    monitoring = service.transition_status(
        created,
        expected_revision=1,
        target_status=RemediationStatus.MONITORING,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 1,
        note="Synthetic monitoring started.",
    )
    scheduled = service.set_deadline(
        monitoring,
        expected_revision=2,
        deadline_at_us=NOW_US + 100,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 2,
    )
    closed = service.transition_status(
        scheduled,
        expected_revision=3,
        target_status=RemediationStatus.CLOSED,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 3,
    )

    assert scheduled.deadline_at_us == NOW_US + 100
    with pytest.raises(ValueError, match="transition"):
        service.transition_status(
            closed,
            expected_revision=4,
            target_status=RemediationStatus.MONITORING,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 4,
        )


def test_provider_response_is_recorded_without_send_operation_and_preserves_evidence() -> None:
    service = RemediationService()
    created = _create(service, RemediationAction.DELETE_OWNED_ACCOUNT)
    assert created.status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL

    responded = service.record_provider_response(
        created,
        expected_revision=1,
        provider_id="provider-synthetic",
        response_code="REQUEST_ACKNOWLEDGED",
        summary="Synthetic acknowledgement recorded from an external manual workflow.",
        evidence_references=("evidence-synthetic-response",),
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 1,
    )

    assert responded.revision == 2
    assert responded.status is RemediationStatus.IN_PROGRESS
    assert responded.action_disposition is ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
    assert responded.provider_responses[0].response_code == "REQUEST_ACKNOWLEDGED"
    assert responded.evidence_references == (
        "evidence-synthetic-initial",
        "evidence-synthetic-response",
    )
    assert responded.history[-1].event_type is RemediationEventType.PROVIDER_RESPONSE_RECORDED
    assert not hasattr(service, "send")


def test_reappearance_reopens_closed_case_and_appends_finding_evidence_and_history() -> None:
    service = RemediationService()
    created = _create(service, RemediationAction.MONITOR)
    closed = service.transition_status(
        created,
        expected_revision=1,
        target_status=RemediationStatus.CLOSED,
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 1,
    )
    reappeared = service.record_reappearance(
        closed,
        expected_revision=2,
        finding_id="finding-synthetic-reappearance",
        evidence_references=("evidence-synthetic-reappearance",),
        actor_id="actor-local-reviewer",
        occurred_at_us=NOW_US + 2,
    )

    assert reappeared.status is RemediationStatus.IN_PROGRESS
    assert reappeared.reappearance_count == 1
    assert reappeared.last_reappearance_at_us == NOW_US + 2
    assert reappeared.finding_ids == (
        "finding-synthetic-primary",
        "finding-synthetic-reappearance",
    )
    assert reappeared.evidence_references == (
        "evidence-synthetic-initial",
        "evidence-synthetic-reappearance",
    )
    assert reappeared.history[-1].event_type is RemediationEventType.REAPPEARANCE_RECORDED
    assert reappeared.history[-1].subject_id == "finding-synthetic-reappearance"


def test_local_actions_reject_outbound_drafts_and_provider_responses() -> None:
    service = RemediationService()
    local = _create(service, RemediationAction.PRESERVE_EVIDENCE)

    with pytest.raises(ValueError, match="outbound drafts"):
        service.update_draft(
            local,
            expected_revision=1,
            draft_text="Synthetic draft.",
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
    with pytest.raises(ValueError, match="provider responses"):
        service.record_provider_response(
            local,
            expected_revision=1,
            provider_id="provider-synthetic",
            response_code="ACKNOWLEDGED",
            summary="Synthetic response.",
            evidence_references=(),
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
    with pytest.raises(ValueError, match="outbound drafts"):
        service.create_case(
            case_id="case-synthetic-invalid-local-draft",
            finding_ids=("finding-synthetic-primary",),
            action=RemediationAction.MONITOR,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US,
            draft_text="Synthetic invalid local draft.",
        )


def test_text_and_reference_bounds_are_enforced_without_echoing_content() -> None:
    service = RemediationService()
    case = _create(service)

    with pytest.raises(ValueError, match="draft is invalid"):
        service.update_draft(
            case,
            expected_revision=1,
            draft_text="x" * (MAX_DRAFT_TEXT + 1),
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
    excessive_references = tuple(
        f"evidence-synthetic-{index}" for index in range(MAX_EVIDENCE_REFERENCES + 1)
    )
    with pytest.raises(ValueError, match="outside the allowed bounds"):
        service.link_evidence(
            case,
            expected_revision=1,
            evidence_references=excessive_references,
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
    with pytest.raises(ValueError, match="summary is invalid"):
        service.record_provider_response(
            case,
            expected_revision=1,
            provider_id="provider-synthetic",
            response_code="ACKNOWLEDGED",
            summary="Synthetic\u0000response",
            evidence_references=(),
            actor_id="actor-local-reviewer",
            occurred_at_us=NOW_US + 1,
        )
