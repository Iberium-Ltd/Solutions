"""Immutable remediation case aggregates and fail-closed workflow rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Final

MAX_FINDING_LINKS: Final = 64
MAX_EVIDENCE_REFERENCES: Final = 64
MAX_PROVIDER_RESPONSES: Final = 32
MAX_HISTORY_ENTRIES: Final = 256
MAX_DRAFT_TEXT: Final = 10_000
MAX_NOTE_TEXT: Final = 1_000
MAX_PROVIDER_RESPONSE_TEXT: Final = 2_048
MAX_TIMESTAMP_US: Final = 9_007_199_254_740_991

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class RemediationAction(StrEnum):
    MONITOR = "MONITOR"
    PRESERVE_EVIDENCE = "PRESERVE_EVIDENCE"
    DELETE_OWNED_ACCOUNT = "DELETE_OWNED_ACCOUNT"
    REQUEST_CORRECTION = "REQUEST_CORRECTION"
    DRAFT_ERASURE_OR_DEINDEX = "DRAFT_ERASURE_OR_DEINDEX"
    DRAFT_IMPERSONATION_REPORT = "DRAFT_IMPERSONATION_REPORT"
    CONTACT = "CONTACT"
    ESCALATE = "ESCALATE"
    MARK_LEGALLY_PERSISTENT = "MARK_LEGALLY_PERSISTENT"


class ActionDisposition(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    DRAFT = "DRAFT"
    REQUIRE_EXPLICIT_APPROVAL = "REQUIRE_EXPLICIT_APPROVAL"


class RemediationStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_EXPLICIT_APPROVAL = "AWAITING_EXPLICIT_APPROVAL"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RemediationEventType(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    DRAFT_UPDATED = "DRAFT_UPDATED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    STATUS_CHANGED = "STATUS_CHANGED"
    DEADLINE_CHANGED = "DEADLINE_CHANGED"
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    PROVIDER_RESPONSE_RECORDED = "PROVIDER_RESPONSE_RECORDED"
    REAPPEARANCE_RECORDED = "REAPPEARANCE_RECORDED"


LOCAL_ACTIONS: Final = frozenset({RemediationAction.MONITOR, RemediationAction.PRESERVE_EVIDENCE})
OUTBOUND_OR_LEGAL_ACTIONS: Final = frozenset(RemediationAction) - LOCAL_ACTIONS

_ALLOWED_TRANSITIONS: Final = {
    RemediationStatus.OPEN: frozenset(
        {
            RemediationStatus.IN_PROGRESS,
            RemediationStatus.AWAITING_EXPLICIT_APPROVAL,
            RemediationStatus.MONITORING,
            RemediationStatus.RESOLVED,
            RemediationStatus.CLOSED,
        }
    ),
    RemediationStatus.IN_PROGRESS: frozenset(
        {
            RemediationStatus.AWAITING_EXPLICIT_APPROVAL,
            RemediationStatus.MONITORING,
            RemediationStatus.RESOLVED,
            RemediationStatus.CLOSED,
        }
    ),
    RemediationStatus.AWAITING_EXPLICIT_APPROVAL: frozenset(
        {
            RemediationStatus.IN_PROGRESS,
            RemediationStatus.MONITORING,
            RemediationStatus.CLOSED,
        }
    ),
    RemediationStatus.MONITORING: frozenset(
        {
            RemediationStatus.IN_PROGRESS,
            RemediationStatus.AWAITING_EXPLICIT_APPROVAL,
            RemediationStatus.RESOLVED,
            RemediationStatus.CLOSED,
        }
    ),
    RemediationStatus.RESOLVED: frozenset(
        {RemediationStatus.IN_PROGRESS, RemediationStatus.MONITORING, RemediationStatus.CLOSED}
    ),
    RemediationStatus.CLOSED: frozenset(),
}


def validate_opaque_id(value: str, label: str) -> None:
    """Normalize and reject malformed opaque id before it can reach persistence or an external
    transport.
    """

    if _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def validate_timestamp(value: int, label: str) -> None:
    """Normalize and reject malformed timestamp before it can reach persistence or an external
    transport.
    """

    if type(value) is not int or value < 1 or value > MAX_TIMESTAMP_US:
        raise ValueError(f"{label} is invalid")


def validate_text(value: str, label: str, maximum: int) -> None:
    """Normalize and reject malformed text before it can reach persistence or an external
    transport.
    """

    if (
        not value
        or len(value) > maximum
        or any(ord(char) < 32 and char not in "\n\t" for char in value)
    ):
        raise ValueError(f"{label} is invalid")


def validate_references(
    references: tuple[str, ...],
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
) -> None:
    """Normalize and reject malformed references before it can reach persistence or an external
    transport.
    """

    if type(references) is not tuple or len(references) > maximum:
        raise ValueError(f"{label} are outside the allowed bounds")
    if not allow_empty and not references:
        raise ValueError(f"{label} are required")
    if len(set(references)) != len(references):
        raise ValueError(f"{label} must be unique")
    for reference in references:
        validate_opaque_id(reference, label.removesuffix("s"))


def default_action_disposition(action: RemediationAction) -> ActionDisposition:
    """Provide the shared default action disposition operation used by this architectural layer."""

    if action in LOCAL_ACTIONS:
        return ActionDisposition.LOCAL_ONLY
    if action is RemediationAction.DELETE_OWNED_ACCOUNT:
        return ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
    return ActionDisposition.DRAFT


def validate_transition(current: RemediationStatus, target: RemediationStatus) -> None:
    """Normalize and reject malformed transition before it can reach persistence or an external
    transport.
    """

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError("remediation status transition is invalid")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider_id: str
    response_code: str
    summary: str = field(repr=False)
    received_at_us: int
    evidence_references: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        validate_opaque_id(self.provider_id, "provider id")
        if _CODE.fullmatch(self.response_code) is None:
            raise ValueError("provider response code is invalid")
        validate_text(self.summary, "provider response summary", MAX_PROVIDER_RESPONSE_TEXT)
        validate_timestamp(self.received_at_us, "provider response time")
        validate_references(
            self.evidence_references,
            label="provider response evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=True,
        )


@dataclass(frozen=True, slots=True)
class RemediationHistoryEntry:
    revision: int
    event_type: RemediationEventType
    actor_id: str
    occurred_at_us: int
    previous_status: RemediationStatus | None
    current_status: RemediationStatus
    detail_code: str
    subject_id: str | None = None
    evidence_references: tuple[str, ...] = field(default=(), repr=False)
    note: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("remediation history revision is invalid")
        if not isinstance(self.event_type, RemediationEventType):
            raise TypeError("remediation event type is invalid")
        validate_opaque_id(self.actor_id, "remediation actor id")
        validate_timestamp(self.occurred_at_us, "remediation event time")
        if _CODE.fullmatch(self.detail_code) is None:
            raise ValueError("remediation detail code is invalid")
        if self.subject_id is not None:
            validate_opaque_id(self.subject_id, "remediation history subject id")
        validate_references(
            self.evidence_references,
            label="remediation history evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=True,
        )
        if self.note is not None:
            validate_text(self.note, "remediation history note", MAX_NOTE_TEXT)


@dataclass(frozen=True, slots=True)
class RemediationCase:
    case_id: str
    finding_ids: tuple[str, ...]
    action: RemediationAction
    action_disposition: ActionDisposition
    status: RemediationStatus
    deadline_at_us: int | None
    draft_text: str | None = field(repr=False)
    evidence_references: tuple[str, ...] = field(repr=False)
    provider_responses: tuple[ProviderResponse, ...] = field(repr=False)
    reappearance_count: int
    last_reappearance_at_us: int | None
    revision: int
    created_at_us: int
    updated_at_us: int
    history: tuple[RemediationHistoryEntry, ...] = field(repr=False)

    def __post_init__(self) -> None:
        validate_opaque_id(self.case_id, "remediation case id")
        validate_references(
            self.finding_ids,
            label="remediation finding ids",
            maximum=MAX_FINDING_LINKS,
            allow_empty=False,
        )
        if not isinstance(self.action, RemediationAction):
            raise TypeError("remediation action is invalid")
        if not isinstance(self.action_disposition, ActionDisposition):
            raise TypeError("remediation action disposition is invalid")
        if not isinstance(self.status, RemediationStatus):
            raise TypeError("remediation status is invalid")
        if self.action in LOCAL_ACTIONS:
            if self.action_disposition is not ActionDisposition.LOCAL_ONLY:
                raise ValueError("local remediation actions must remain local-only")
        elif self.action_disposition not in {
            ActionDisposition.DRAFT,
            ActionDisposition.REQUIRE_EXPLICIT_APPROVAL,
        }:
            raise ValueError("outbound or legal remediation actions cannot be executable")
        if self.status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL and (
            self.action_disposition is not ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
        ):
            raise ValueError("approval status requires explicit approval disposition")
        if self.deadline_at_us is not None:
            validate_timestamp(self.deadline_at_us, "remediation deadline")
        if self.draft_text is not None:
            validate_text(self.draft_text, "remediation draft", MAX_DRAFT_TEXT)
        validate_references(
            self.evidence_references,
            label="remediation evidence references",
            maximum=MAX_EVIDENCE_REFERENCES,
            allow_empty=True,
        )
        if (
            type(self.provider_responses) is not tuple
            or len(self.provider_responses) > MAX_PROVIDER_RESPONSES
        ):
            raise ValueError("provider responses are outside the allowed bounds")
        if type(self.reappearance_count) is not int or self.reappearance_count < 0:
            raise ValueError("remediation reappearance count is invalid")
        if (self.reappearance_count == 0) != (self.last_reappearance_at_us is None):
            raise ValueError("remediation reappearance state is inconsistent")
        if self.last_reappearance_at_us is not None:
            validate_timestamp(self.last_reappearance_at_us, "remediation reappearance time")
        validate_timestamp(self.created_at_us, "remediation creation time")
        validate_timestamp(self.updated_at_us, "remediation update time")
        if self.updated_at_us < self.created_at_us:
            raise ValueError("remediation timestamps are inconsistent")
        if self.deadline_at_us is not None and self.deadline_at_us <= self.created_at_us:
            raise ValueError("remediation deadline must follow creation")
        if (
            self.last_reappearance_at_us is not None
            and self.last_reappearance_at_us > self.updated_at_us
        ):
            raise ValueError("remediation reappearance timestamp is inconsistent")
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.revision > MAX_HISTORY_ENTRIES
        ):
            raise ValueError("remediation revision is invalid")
        if type(self.history) is not tuple or len(self.history) != self.revision:
            raise ValueError("remediation history is incomplete")
        if tuple(entry.revision for entry in self.history) != tuple(range(1, self.revision + 1)):
            raise ValueError("remediation history revisions are invalid")
        if self.history[-1].occurred_at_us != self.updated_at_us:
            raise ValueError("remediation history timestamp is inconsistent")
        if self.history[-1].current_status is not self.status:
            raise ValueError("remediation history status is inconsistent")
        if self.history[0].previous_status is not None or any(
            current.previous_status is not previous.current_status
            for previous, current in pairwise(self.history)
        ):
            raise ValueError("remediation history continuity is invalid")
        if any(
            current.occurred_at_us <= previous.occurred_at_us
            for previous, current in pairwise(self.history)
        ):
            raise ValueError("remediation history timestamps must increase")
