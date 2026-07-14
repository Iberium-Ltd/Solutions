"""Strict wire contracts for durable audit comparison and local remediation."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel, _canonical_uuid
from ariadne_core.domain.audit_comparison import (
    ComparisonIncompleteReason,
    FindingDiffState,
    ProviderCoverageState,
    SnapshotRunState,
)
from ariadne_core.domain.remediation import (
    ActionDisposition,
    RemediationAction,
    RemediationEventType,
    RemediationStatus,
)

MAX_PHASE6_RUNS = 32
MAX_PHASE6_DIFFS = 100
MAX_PHASE6_COVERAGE = 256
MAX_PHASE6_LIFECYCLES = 100
MAX_PHASE6_LIFECYCLE_EVENTS = 32
MAX_PHASE6_CASES = 100
MAX_PHASE6_FINDING_LINKS = 64
MAX_PHASE6_EVIDENCE_REFERENCES = 64
MAX_PHASE6_PROVIDER_RESPONSES = 32
MAX_PHASE6_HISTORY_ENTRIES = 256
MAX_TIMESTAMP_US = 9_007_199_254_740_991

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def _uuid(value: str, label: str) -> str:
    return _canonical_uuid(value, label=label)


def _unique_uuids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(_uuid(value, label) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label}s are duplicated")
    return normalized


def _safe_text(value: str, *, multiline: bool) -> str:
    if value != value.strip():
        raise ValueError("text has surrounding whitespace")
    for character in value:
        if ord(character) < 32 and (not multiline or character not in "\n\t"):
            raise ValueError("text contains control characters")
    return value


class Phase6AuditRunListRequest(ApiModel):
    profile_id: str
    limit: int = Field(default=MAX_PHASE6_RUNS, ge=2, le=MAX_PHASE6_RUNS)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")


class Phase6AuditRunSummary(ApiModel):
    run_id: str
    sequence: int = Field(ge=1)
    captured_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    run_state: SnapshotRunState = Field(strict=False)
    finding_count: int = Field(ge=0, le=2_000)
    provider_count: int = Field(ge=1, le=256)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return _uuid(value, "audit run id")


class Phase6LocalCheckpointCoverage(ApiModel):
    provider_id: str = Field(min_length=1, max_length=128)
    state: ProviderCoverageState = Field(strict=False)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value


class Phase6LocalCheckpointRequest(ApiModel):
    profile_id: str
    run_state: SnapshotRunState = Field(strict=False)
    provider_coverage: tuple[Phase6LocalCheckpointCoverage, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_COVERAGE,
    )

    @field_validator("provider_coverage", mode="before")
    @classmethod
    def parse_provider_coverage(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")

    @model_validator(mode="after")
    def validate_unique_coverage(self) -> Phase6LocalCheckpointRequest:
        provider_ids = tuple(item.provider_id for item in self.provider_coverage)
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("local checkpoint provider coverage is duplicated")
        return self


class Phase6LocalCheckpointResult(Phase6AuditRunSummary):
    profile_id: str
    local_only: Literal[True]

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")


class Phase6AuditRunListResult(ApiModel):
    profile_id: str
    runs: tuple[Phase6AuditRunSummary, ...] = Field(max_length=MAX_PHASE6_RUNS)
    has_more: bool

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")

    @model_validator(mode="after")
    def validate_order(self) -> Phase6AuditRunListResult:
        if len({item.run_id for item in self.runs}) != len(self.runs):
            raise ValueError("audit runs are duplicated")
        if any(
            current.sequence >= previous.sequence
            for previous, current in zip(self.runs, self.runs[1:], strict=False)
        ):
            raise ValueError("audit runs must be ordered newest first")
        return self


class Phase6CompareRunsRequest(ApiModel):
    profile_id: str
    baseline_run_id: str
    current_run_id: str

    @field_validator("profile_id", "baseline_run_id", "current_run_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_distinct_runs(self) -> Phase6CompareRunsRequest:
        if self.baseline_run_id == self.current_run_id:
            raise ValueError("comparison requires two distinct runs")
        return self


class Phase6FindingDiff(ApiModel):
    stable_id: str
    provider_id: str = Field(min_length=1, max_length=128)
    state: FindingDiffState = Field(strict=False)
    previous_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("stable_id")
    @classmethod
    def validate_stable_id(cls, value: str) -> str:
        return _uuid(value, "stable finding id")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value

    @model_validator(mode="after")
    def validate_fingerprints(self) -> Phase6FindingDiff:
        if self.state is FindingDiffState.NEW and (
            self.previous_fingerprint is not None or self.current_fingerprint is None
        ):
            raise ValueError("new finding fingerprints are inconsistent")
        if self.state is FindingDiffState.REMOVED and (
            self.previous_fingerprint is None or self.current_fingerprint is not None
        ):
            raise ValueError("removed finding fingerprints are inconsistent")
        if self.state in {
            FindingDiffState.CHANGED,
            FindingDiffState.UNCHANGED,
            FindingDiffState.REAPPEARED,
        } and (self.previous_fingerprint is None or self.current_fingerprint is None):
            raise ValueError("observed finding fingerprints are incomplete")
        if self.state is FindingDiffState.CHANGED and (
            self.previous_fingerprint == self.current_fingerprint
        ):
            raise ValueError("changed finding fingerprints must differ")
        if self.state is FindingDiffState.UNCHANGED and (
            self.previous_fingerprint != self.current_fingerprint
        ):
            raise ValueError("unchanged finding fingerprints must match")
        return self


class Phase6UnresolvedAbsence(ApiModel):
    stable_id: str
    provider_id: str = Field(min_length=1, max_length=128)
    previous_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_coverage: ProviderCoverageState | None = Field(strict=False)

    @field_validator("stable_id")
    @classmethod
    def validate_stable_id(cls, value: str) -> str:
        return _uuid(value, "stable finding id")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value


class Phase6ProviderCoverageComparison(ApiModel):
    provider_id: str = Field(min_length=1, max_length=128)
    baseline_state: ProviderCoverageState | None = Field(strict=False)
    current_state: ProviderCoverageState | None = Field(strict=False)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value


class Phase6LifecycleEvent(ApiModel):
    run_id: str
    sequence: int = Field(ge=1)
    run_state: SnapshotRunState = Field(strict=False)
    provider_coverage: ProviderCoverageState | None = Field(strict=False)
    observed: bool
    content_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return _uuid(value, "audit run id")

    @model_validator(mode="after")
    def validate_observation(self) -> Phase6LifecycleEvent:
        if self.observed != (self.content_fingerprint is not None):
            raise ValueError("lifecycle observation and fingerprint do not match")
        return self


class Phase6FindingLifecycle(ApiModel):
    stable_id: str
    provider_id: str = Field(min_length=1, max_length=128)
    events: tuple[Phase6LifecycleEvent, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_LIFECYCLE_EVENTS,
    )

    @field_validator("stable_id")
    @classmethod
    def validate_stable_id(cls, value: str) -> str:
        return _uuid(value, "stable finding id")

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value

    @model_validator(mode="after")
    def validate_events(self) -> Phase6FindingLifecycle:
        if any(
            current.sequence <= previous.sequence
            for previous, current in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError("lifecycle events must increase")
        return self


class Phase6ComparisonResult(ApiModel):
    profile_id: str
    baseline_run_id: str
    current_run_id: str
    diffs: tuple[Phase6FindingDiff, ...] = Field(max_length=MAX_PHASE6_DIFFS)
    unresolved_absences: tuple[Phase6UnresolvedAbsence, ...] = Field(max_length=MAX_PHASE6_DIFFS)
    coverage: tuple[Phase6ProviderCoverageComparison, ...] = Field(max_length=MAX_PHASE6_COVERAGE)
    lifecycles: tuple[Phase6FindingLifecycle, ...] = Field(max_length=MAX_PHASE6_LIFECYCLES)
    incomplete_comparison: bool
    incomplete_reasons: tuple[ComparisonIncompleteReason, ...] = Field(max_length=6)

    @field_validator("profile_id", "baseline_run_id", "current_run_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_consistency(self) -> Phase6ComparisonResult:
        diff_ids = tuple(item.stable_id for item in self.diffs)
        unresolved_ids = tuple(item.stable_id for item in self.unresolved_absences)
        if len(diff_ids) + len(unresolved_ids) > MAX_PHASE6_DIFFS:
            raise ValueError("comparison output is outside the wire bound")
        if len(set(diff_ids)) != len(diff_ids) or len(set(unresolved_ids)) != len(unresolved_ids):
            raise ValueError("comparison finding ids are duplicated")
        if set(diff_ids) & set(unresolved_ids):
            raise ValueError("comparison findings cannot be both diffed and unresolved")
        if len({item.provider_id for item in self.coverage}) != len(self.coverage):
            raise ValueError("comparison provider coverage is duplicated")
        lifecycle_ids = tuple(item.stable_id for item in self.lifecycles)
        if len(set(lifecycle_ids)) != len(lifecycle_ids):
            raise ValueError("comparison lifecycles are duplicated")
        if set(lifecycle_ids) != set(diff_ids) | set(unresolved_ids):
            raise ValueError("comparison lifecycle coverage is incomplete")
        if any(item.events[-1].run_id != self.current_run_id for item in self.lifecycles):
            raise ValueError("comparison lifecycles must end at the current run")
        if self.incomplete_comparison != bool(self.incomplete_reasons):
            raise ValueError("comparison incomplete state is inconsistent")
        if len(set(self.incomplete_reasons)) != len(self.incomplete_reasons):
            raise ValueError("comparison incomplete reasons are duplicated")
        return self


class Phase6RemediationListRequest(ApiModel):
    profile_id: str
    limit: int = Field(default=MAX_PHASE6_CASES, ge=1, le=MAX_PHASE6_CASES)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")


class Phase6RemediationDetailRequest(ApiModel):
    profile_id: str
    case_id: str

    @field_validator("profile_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, info.field_name.replace("_", " "))


class Phase6RemediationCreateRequest(ApiModel):
    profile_id: str
    finding_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_FINDING_LINKS,
    )
    action: RemediationAction = Field(strict=False)
    deadline_at_us: int | None = Field(ge=1, le=MAX_TIMESTAMP_US)
    evidence_references: tuple[str, ...] = Field(
        max_length=MAX_PHASE6_EVIDENCE_REFERENCES,
    )
    draft_text: str | None = Field(min_length=1, max_length=10_000, repr=False)

    @field_validator("finding_ids", "evidence_references", mode="before")
    @classmethod
    def parse_references(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")

    @field_validator("finding_ids")
    @classmethod
    def validate_finding_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "finding id")

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")

    @field_validator("draft_text")
    @classmethod
    def validate_draft(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, multiline=True)

    @model_validator(mode="after")
    def validate_local_action(self) -> Phase6RemediationCreateRequest:
        if (
            self.action
            in {
                RemediationAction.MONITOR,
                RemediationAction.PRESERVE_EVIDENCE,
            }
            and self.draft_text is not None
        ):
            raise ValueError("local remediation actions do not use outbound drafts")
        return self


class Phase6RemediationMutationRequest(ApiModel):
    profile_id: str
    case_id: str
    expected_revision: int = Field(ge=1, lt=MAX_PHASE6_HISTORY_ENTRIES)

    @field_validator("profile_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, info.field_name.replace("_", " "))


class Phase6RemediationDraftUpdateRequest(Phase6RemediationMutationRequest):
    draft_text: str = Field(min_length=1, max_length=10_000, repr=False)

    @field_validator("draft_text")
    @classmethod
    def validate_draft(cls, value: str) -> str:
        return _safe_text(value, multiline=True)


class Phase6RemediationRequireApprovalRequest(Phase6RemediationMutationRequest):
    pass


class Phase6RemediationStatusTransitionRequest(Phase6RemediationMutationRequest):
    target_status: RemediationStatus = Field(strict=False)
    note: str | None = Field(min_length=1, max_length=1_000, repr=False)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, multiline=True)


class Phase6RemediationDeadlineUpdateRequest(Phase6RemediationMutationRequest):
    deadline_at_us: int | None = Field(ge=1, le=MAX_TIMESTAMP_US)


class Phase6RemediationEvidenceLinkRequest(Phase6RemediationMutationRequest):
    evidence_references: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_EVIDENCE_REFERENCES,
    )

    @field_validator("evidence_references", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")


class Phase6RemediationProviderResponseRequest(Phase6RemediationMutationRequest):
    provider_id: str = Field(min_length=1, max_length=128)
    response_code: str = Field(min_length=2, max_length=64)
    summary: str = Field(min_length=1, max_length=2_048, repr=False)
    evidence_references: tuple[str, ...] = Field(
        max_length=MAX_PHASE6_EVIDENCE_REFERENCES,
    )

    @field_validator("evidence_references", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value

    @field_validator("response_code")
    @classmethod
    def validate_response_code(cls, value: str) -> str:
        if _CODE.fullmatch(value) is None:
            raise ValueError("provider response code is invalid")
        return value

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _safe_text(value, multiline=False)

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")


class Phase6RemediationReappearanceRequest(Phase6RemediationMutationRequest):
    finding_id: str
    evidence_references: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_EVIDENCE_REFERENCES,
    )

    @field_validator("evidence_references", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("finding_id")
    @classmethod
    def validate_finding_id(cls, value: str) -> str:
        return _uuid(value, "finding id")

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")


class Phase6RemediationCaseSummary(ApiModel):
    case_id: str
    finding_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_FINDING_LINKS,
    )
    action: RemediationAction = Field(strict=False)
    action_disposition: ActionDisposition = Field(strict=False)
    status: RemediationStatus = Field(strict=False)
    deadline_at_us: int | None = Field(ge=1, le=MAX_TIMESTAMP_US)
    reappearance_count: int = Field(ge=0)
    revision: int = Field(ge=1, le=MAX_PHASE6_HISTORY_ENTRIES)
    updated_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _uuid(value, "remediation case id")

    @field_validator("finding_ids")
    @classmethod
    def validate_finding_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "finding id")

    @model_validator(mode="after")
    def validate_disposition(self) -> Phase6RemediationCaseSummary:
        local_actions = {RemediationAction.MONITOR, RemediationAction.PRESERVE_EVIDENCE}
        if (self.action in local_actions) != (
            self.action_disposition is ActionDisposition.LOCAL_ONLY
        ):
            raise ValueError("remediation action disposition is inconsistent")
        if self.status is RemediationStatus.AWAITING_EXPLICIT_APPROVAL and (
            self.action_disposition is not ActionDisposition.REQUIRE_EXPLICIT_APPROVAL
        ):
            raise ValueError("approval status requires explicit approval disposition")
        return self


class Phase6RemediationListResult(ApiModel):
    profile_id: str
    cases: tuple[Phase6RemediationCaseSummary, ...] = Field(max_length=MAX_PHASE6_CASES)
    has_more: bool

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")

    @model_validator(mode="after")
    def validate_cases(self) -> Phase6RemediationListResult:
        if len({item.case_id for item in self.cases}) != len(self.cases):
            raise ValueError("remediation cases are duplicated")
        if any(
            current.updated_at_us > previous.updated_at_us
            for previous, current in zip(self.cases, self.cases[1:], strict=False)
        ):
            raise ValueError("remediation cases must be ordered newest first")
        return self


class Phase6ProviderResponse(ApiModel):
    provider_id: str = Field(min_length=1, max_length=128)
    response_code: str = Field(min_length=2, max_length=64)
    summary: str = Field(min_length=1, max_length=2_048, repr=False)
    received_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    evidence_references: tuple[str, ...] = Field(max_length=MAX_PHASE6_EVIDENCE_REFERENCES)

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        if _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("provider id is invalid")
        return value

    @field_validator("response_code")
    @classmethod
    def validate_response_code(cls, value: str) -> str:
        if _CODE.fullmatch(value) is None:
            raise ValueError("provider response code is invalid")
        return value

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _safe_text(value, multiline=False)

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")


class Phase6RemediationHistoryEntry(ApiModel):
    revision: int = Field(ge=1, le=MAX_PHASE6_HISTORY_ENTRIES)
    event_type: RemediationEventType = Field(strict=False)
    actor_label: Literal["Local user"]
    occurred_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    previous_status: RemediationStatus | None = Field(strict=False)
    current_status: RemediationStatus = Field(strict=False)
    detail_code: str = Field(min_length=2, max_length=64)
    subject_id: str | None
    evidence_references: tuple[str, ...] = Field(max_length=MAX_PHASE6_EVIDENCE_REFERENCES)
    note: str | None = Field(min_length=1, max_length=1_000, repr=False)

    @field_validator("detail_code")
    @classmethod
    def validate_detail_code(cls, value: str) -> str:
        if _CODE.fullmatch(value) is None:
            raise ValueError("remediation detail code is invalid")
        return value

    @field_validator("subject_id")
    @classmethod
    def validate_subject_id(cls, value: str | None) -> str | None:
        if value is not None and _OPAQUE_ID.fullmatch(value) is None:
            raise ValueError("history subject id is invalid")
        return value

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, multiline=True)


class Phase6RemediationCase(Phase6RemediationCaseSummary):
    draft_text: str | None = Field(min_length=1, max_length=10_000, repr=False)
    evidence_references: tuple[str, ...] = Field(max_length=MAX_PHASE6_EVIDENCE_REFERENCES)
    provider_responses: tuple[Phase6ProviderResponse, ...] = Field(
        max_length=MAX_PHASE6_PROVIDER_RESPONSES
    )
    last_reappearance_at_us: int | None = Field(ge=1, le=MAX_TIMESTAMP_US)
    created_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    history: tuple[Phase6RemediationHistoryEntry, ...] = Field(
        min_length=1,
        max_length=MAX_PHASE6_HISTORY_ENTRIES,
    )

    @field_validator("draft_text")
    @classmethod
    def validate_draft(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, multiline=True)

    @field_validator("evidence_references")
    @classmethod
    def validate_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_uuids(values, "evidence reference")

    @model_validator(mode="after")
    def validate_case(self) -> Phase6RemediationCase:
        if self.created_at_us > self.updated_at_us:
            raise ValueError("remediation timestamps are inconsistent")
        if self.deadline_at_us is not None and self.deadline_at_us <= self.created_at_us:
            raise ValueError("remediation deadline must follow creation")
        if (self.reappearance_count == 0) != (self.last_reappearance_at_us is None):
            raise ValueError("remediation reappearance state is inconsistent")
        if self.last_reappearance_at_us is not None and (
            self.last_reappearance_at_us < self.created_at_us
            or self.last_reappearance_at_us > self.updated_at_us
        ):
            raise ValueError("remediation reappearance time is inconsistent")
        if len(self.history) != self.revision:
            raise ValueError("remediation history is incomplete")
        if tuple(item.revision for item in self.history) != tuple(range(1, self.revision + 1)):
            raise ValueError("remediation history revisions are invalid")
        if self.history[-1].current_status is not self.status:
            raise ValueError("remediation history status is inconsistent")
        if self.history[-1].occurred_at_us != self.updated_at_us:
            raise ValueError("remediation history timestamp is inconsistent")
        if self.history[0].previous_status is not None:
            raise ValueError("remediation history must start without a previous status")
        for previous, current in zip(self.history, self.history[1:], strict=False):
            if current.previous_status is not previous.current_status:
                raise ValueError("remediation history continuity is invalid")
            if current.occurred_at_us <= previous.occurred_at_us:
                raise ValueError("remediation history timestamps must increase")
        if any(
            item.received_at_us < self.created_at_us or item.received_at_us > self.updated_at_us
            for item in self.provider_responses
        ):
            raise ValueError("provider response timestamp is inconsistent")
        nested_evidence = {
            reference
            for response in self.provider_responses
            for reference in response.evidence_references
        } | {
            reference
            for history_entry in self.history
            for reference in history_entry.evidence_references
        }
        if not nested_evidence <= set(self.evidence_references):
            raise ValueError("nested remediation evidence is not linked to the case")
        return self


class Phase6RemediationDetailResult(ApiModel):
    profile_id: str
    case: Phase6RemediationCase

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")
