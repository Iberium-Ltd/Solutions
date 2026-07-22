"""Pure application service for remediation planning; it never sends actions.

Drafts and transitions are local workflow proposals. Any provider submission is
a distinct, explicitly authorised integration outside this module.
"""

from __future__ import annotations

from dataclasses import replace

from ariadne_core.domain.remediation import (
    LOCAL_ACTIONS,
    MAX_DRAFT_TEXT,
    MAX_EVIDENCE_REFERENCES,
    MAX_FINDING_LINKS,
    MAX_HISTORY_ENTRIES,
    MAX_NOTE_TEXT,
    MAX_PROVIDER_RESPONSES,
    OUTBOUND_OR_LEGAL_ACTIONS,
    ActionDisposition,
    ProviderResponse,
    RemediationAction,
    RemediationCase,
    RemediationEventType,
    RemediationHistoryEntry,
    RemediationStatus,
    default_action_disposition,
    validate_opaque_id,
    validate_references,
    validate_text,
    validate_timestamp,
    validate_transition,
)


class RemediationConflict(RuntimeError):
    """The caller's revision or timestamp no longer matches the aggregate."""


class RemediationService:
    """Coordinate local drafts and history without sending or providing legal advice."""

    def create_case(
        self,
        *,
        case_id: str,
        finding_ids: tuple[str, ...],
        action: RemediationAction,
        actor_id: str,
        occurred_at_us: int,
        deadline_at_us: int | None = None,
        evidence_references: tuple[str, ...] = (),
        draft_text: str | None = None,
    ) -> RemediationCase:
        validate_opaque_id(case_id, "remediation case id")
        validate_opaque_id(actor_id, "remediation actor id")
        validate_timestamp(occurred_at_us, "remediation event time")
        if deadline_at_us is not None:
            validate_timestamp(deadline_at_us, "remediation deadline")
            if deadline_at_us <= occurred_at_us:
                raise ValueError("remediation deadline must be in the future")
        validate_references(
            evidence_references,
            label="remediation evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=True,
        )
        if draft_text is not None and action in LOCAL_ACTIONS:
            raise ValueError("local remediation actions do not use outbound drafts")
        disposition = default_action_disposition(action)
        status = (
            RemediationStatus.AWAITING_EXPLICIT_APPROVAL
            if disposition is ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
            else RemediationStatus.OPEN
        )
        history = (
            RemediationHistoryEntry(
                revision=1,
                event_type=RemediationEventType.CASE_CREATED,
                actor_id=actor_id,
                occurred_at_us=occurred_at_us,
                previous_status=None,
                current_status=status,
                detail_code="CASE_CREATED",
                evidence_references=tuple(sorted(evidence_references)),
            ),
        )
        return RemediationCase(
            case_id=case_id,
            finding_ids=tuple(sorted(finding_ids)),
            action=action,
            action_disposition=disposition,
            status=status,
            deadline_at_us=deadline_at_us,
            draft_text=draft_text,
            evidence_references=tuple(sorted(evidence_references)),
            provider_responses=(),
            reappearance_count=0,
            last_reappearance_at_us=None,
            revision=1,
            created_at_us=occurred_at_us,
            updated_at_us=occurred_at_us,
            history=history,
        )

    def update_draft(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        draft_text: str,
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        if case.action not in OUTBOUND_OR_LEGAL_ACTIONS:
            raise ValueError("local remediation actions do not use outbound drafts")
        validate_text(draft_text, "remediation draft", MAX_DRAFT_TEXT)
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        target_status = (
            RemediationStatus.AWAITING_EXPLICIT_APPROVAL
            if case.action_disposition is ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
            else RemediationStatus.IN_PROGRESS
        )
        if target_status is not case.status:
            validate_transition(case.status, target_status)
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.DRAFT_UPDATED,
            detail_code="DRAFT_UPDATED",
            target_status=target_status,
            draft_text=draft_text,
            change_draft=True,
        )

    def require_explicit_approval(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        if case.action in LOCAL_ACTIONS:
            raise ValueError("local remediation actions do not require outbound approval")
        if case.action_disposition is ActionDisposition.REQUIRE_EXPLICIT_APPROVAL:
            raise ValueError("remediation action already requires explicit approval")
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        validate_transition(case.status, RemediationStatus.AWAITING_EXPLICIT_APPROVAL)
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.APPROVAL_REQUIRED,
            detail_code="EXPLICIT_APPROVAL_REQUIRED",
            target_status=RemediationStatus.AWAITING_EXPLICIT_APPROVAL,
            action_disposition=ActionDisposition.REQUIRE_EXPLICIT_APPROVAL,
        )

    def transition_status(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        target_status: RemediationStatus,
        actor_id: str,
        occurred_at_us: int,
        note: str | None = None,
    ) -> RemediationCase:
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        validate_transition(case.status, target_status)
        if target_status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL and (
            case.action_disposition is not ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
        ):
            raise ValueError("approval status requires explicit approval disposition")
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.STATUS_CHANGED,
            detail_code="STATUS_CHANGED",
            target_status=target_status,
            note=note,
        )

    def set_deadline(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        deadline_at_us: int | None,
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        if deadline_at_us is not None:
            validate_timestamp(deadline_at_us, "remediation deadline")
            if deadline_at_us <= occurred_at_us:
                raise ValueError("remediation deadline must be in the future")
        if deadline_at_us == case.deadline_at_us:
            raise ValueError("remediation deadline is unchanged")
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.DEADLINE_CHANGED,
            detail_code="DEADLINE_CHANGED",
            target_status=case.status,
            deadline_at_us=deadline_at_us,
            change_deadline=True,
        )

    def link_evidence(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        evidence_references: tuple[str, ...],
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        validate_references(
            evidence_references,
            label="remediation evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=False,
        )
        additions = tuple(sorted(set(evidence_references) - set(case.evidence_references)))
        if not additions:
            raise ValueError("remediation evidence is already linked")
        combined = tuple(sorted((*case.evidence_references, *additions)))
        if len(combined) > MAX_EVIDENCE_REFERENCES:
            raise ValueError("remediation evidence references are outside the allowed bounds")
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.EVIDENCE_LINKED,
            detail_code="EVIDENCE_LINKED",
            target_status=case.status,
            evidence_references=combined,
            event_evidence_references=additions,
        )

    def record_provider_response(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        provider_id: str,
        response_code: str,
        summary: str,
        evidence_references: tuple[str, ...],
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        if case.action in LOCAL_ACTIONS:
            raise ValueError("local remediation actions cannot have provider responses")
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        response = ProviderResponse(
            provider_id=provider_id,
            response_code=response_code,
            summary=summary,
            received_at_us=occurred_at_us,
            evidence_references=tuple(sorted(evidence_references)),
        )
        if len(case.provider_responses) >= MAX_PROVIDER_RESPONSES:
            raise ValueError("provider responses are outside the allowed bounds")
        combined_evidence = tuple(
            sorted(set(case.evidence_references) | set(response.evidence_references))
        )
        if len(combined_evidence) > MAX_EVIDENCE_REFERENCES:
            raise ValueError("remediation evidence references are outside the allowed bounds")
        target_status = (
            RemediationStatus.IN_PROGRESS
            if case.status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL
            else case.status
        )
        if target_status is not case.status:
            validate_transition(case.status, target_status)
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.PROVIDER_RESPONSE_RECORDED,
            detail_code=response.response_code,
            target_status=target_status,
            subject_id=response.provider_id,
            evidence_references=combined_evidence,
            event_evidence_references=response.evidence_references,
            provider_responses=(*case.provider_responses, response),
        )

    def record_reappearance(
        self,
        case: RemediationCase,
        *,
        expected_revision: int,
        finding_id: str,
        evidence_references: tuple[str, ...],
        actor_id: str,
        occurred_at_us: int,
    ) -> RemediationCase:
        self._guard(case, expected_revision, actor_id, occurred_at_us)
        validate_opaque_id(finding_id, "remediation finding id")
        validate_references(
            evidence_references,
            label="remediation reappearance evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=False,
        )
        finding_ids = tuple(sorted(set(case.finding_ids) | {finding_id}))
        if len(finding_ids) > MAX_FINDING_LINKS:
            raise ValueError("remediation finding ids are outside the allowed bounds")
        combined_evidence = tuple(sorted(set(case.evidence_references) | set(evidence_references)))
        if len(combined_evidence) > MAX_EVIDENCE_REFERENCES:
            raise ValueError("remediation evidence references are outside the allowed bounds")
        return self._append(
            case,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            event_type=RemediationEventType.REAPPEARANCE_RECORDED,
            detail_code="FINDING_REAPPEARED",
            target_status=RemediationStatus.IN_PROGRESS,
            subject_id=finding_id,
            evidence_references=combined_evidence,
            event_evidence_references=tuple(sorted(evidence_references)),
            finding_ids=finding_ids,
            reappearance_count=case.reappearance_count + 1,
            last_reappearance_at_us=occurred_at_us,
        )

    @staticmethod
    def _guard(
        case: RemediationCase,
        expected_revision: int,
        actor_id: str,
        occurred_at_us: int,
    ) -> None:
        if expected_revision != case.revision:
            raise RemediationConflict("remediation case revision conflict")
        validate_opaque_id(actor_id, "remediation actor id")
        validate_timestamp(occurred_at_us, "remediation event time")
        if occurred_at_us <= case.updated_at_us:
            raise RemediationConflict("remediation event timestamp conflict")
        if case.revision >= MAX_HISTORY_ENTRIES:
            raise ValueError("remediation history is at capacity")

    @staticmethod
    def _append(
        case: RemediationCase,
        *,
        actor_id: str,
        occurred_at_us: int,
        event_type: RemediationEventType,
        detail_code: str,
        target_status: RemediationStatus,
        action_disposition: ActionDisposition | None = None,
        deadline_at_us: int | None = None,
        change_deadline: bool = False,
        draft_text: str | None = None,
        change_draft: bool = False,
        evidence_references: tuple[str, ...] | None = None,
        event_evidence_references: tuple[str, ...] = (),
        provider_responses: tuple[ProviderResponse, ...] | None = None,
        finding_ids: tuple[str, ...] | None = None,
        reappearance_count: int | None = None,
        last_reappearance_at_us: int | None = None,
        subject_id: str | None = None,
        note: str | None = None,
    ) -> RemediationCase:
        if note is not None:
            validate_text(note, "remediation history note", MAX_NOTE_TEXT)
        next_revision = case.revision + 1
        event = RemediationHistoryEntry(
            revision=next_revision,
            event_type=event_type,
            actor_id=actor_id,
            occurred_at_us=occurred_at_us,
            previous_status=case.status,
            current_status=target_status,
            detail_code=detail_code,
            subject_id=subject_id,
            evidence_references=event_evidence_references,
            note=note,
        )
        return replace(
            case,
            action_disposition=action_disposition or case.action_disposition,
            status=target_status,
            deadline_at_us=deadline_at_us if change_deadline else case.deadline_at_us,
            draft_text=draft_text if change_draft else case.draft_text,
            evidence_references=(
                case.evidence_references if evidence_references is None else evidence_references
            ),
            provider_responses=(
                case.provider_responses if provider_responses is None else provider_responses
            ),
            finding_ids=case.finding_ids if finding_ids is None else finding_ids,
            reappearance_count=(
                case.reappearance_count if reappearance_count is None else reappearance_count
            ),
            last_reappearance_at_us=(
                case.last_reappearance_at_us
                if last_reappearance_at_us is None
                else last_reappearance_at_us
            ),
            revision=next_revision,
            updated_at_us=occurred_at_us,
            history=(*case.history, event),
        )
