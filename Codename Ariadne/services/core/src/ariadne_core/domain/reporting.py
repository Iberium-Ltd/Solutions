"""Typed, bounded inputs for side-effect-free local report generation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from ariadne_core.domain.attribution import (
    AttributionConfidenceBand,
    HumanAttributionState,
    NegativeAttributionSignal,
    PositiveAttributionSignal,
)
from ariadne_core.domain.audit_comparison import (
    ComparisonIncompleteReason,
    FindingDiffState,
    ProviderCoverageState,
)
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
    validate_safe_url,
)
from ariadne_core.domain.remediation import (
    ActionDisposition,
    RemediationAction,
    RemediationEventType,
    RemediationStatus,
)

MAX_REPORT_BYTES: Final = 1_024 * 1_024
MAX_REPORT_FINDINGS: Final = 100
MAX_REPORT_EVIDENCE_PER_FINDING: Final = 64
MAX_REPORT_METADATA_PER_ARTIFACT: Final = 32
MAX_REPORT_COMPARISON_ITEMS: Final = 4_000
MAX_REPORT_PROVIDERS: Final = 256
MAX_REPORT_REMEDIATIONS: Final = 100
MAX_REPORT_FINDING_LINKS: Final = 64
MAX_REPORT_EVIDENCE_REFERENCES: Final = 64
MAX_REPORT_PROVIDER_RESPONSES: Final = 32
MAX_REPORT_HISTORY_ENTRIES: Final = 256
MAX_TIMESTAMP_US: Final = 9_007_199_254_740_991

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,47}$")
_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ReportFindingOutcome(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NOT_CHECKED = "NOT_CHECKED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    CHECK_FAILED = "CHECK_FAILED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    AUTHORITATIVE_ABSENCE = "AUTHORITATIVE_ABSENCE"


class ReportFindingSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ReportFindingVisibility(StrEnum):
    PUBLICLY_ATTRIBUTABLE = "PUBLICLY_ATTRIBUTABLE"
    PUBLIC_PSEUDONYMOUS = "PUBLIC_PSEUDONYMOUS"
    PRIVATELY_LINKABLE = "PRIVATELY_LINKABLE"
    HISTORICAL_RESIDUE = "HISTORICAL_RESIDUE"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    UNKNOWN = "UNKNOWN"


class ReportEvidenceIntegrity(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    FAILED = "FAILED"


def _normalise_text(value: str, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be text")
    normalised = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if (not allow_empty and not normalised) or len(normalised) > maximum:
        raise ValueError(f"{label} is outside the allowed bounds")
    if any(ord(character) < 32 and character not in "\n\t" for character in normalised):
        raise ValueError(f"{label} contains control characters")
    return normalised


def _validate_id(value: str, label: str) -> None:
    if _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _validate_hash(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _validate_timestamp(value: int, label: str) -> None:
    if type(value) is not int or value < 1 or value > MAX_TIMESTAMP_US:
        raise ValueError(f"{label} is invalid")


def _validate_ids(
    values: tuple[str, ...],
    label: str,
    maximum: int,
    *,
    allow_empty: bool = True,
) -> None:
    if type(values) is not tuple or len(values) > maximum or (not allow_empty and not values):
        raise ValueError(f"{label} are outside the allowed bounds")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        _validate_id(value, label.removesuffix("s"))


@dataclass(frozen=True, slots=True)
class ReportEvidenceMetadataEntry:
    key: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if _METADATA_KEY.fullmatch(self.key) is None:
            raise ValueError("report evidence metadata key is invalid")
        object.__setattr__(
            self,
            "value",
            _normalise_text(self.value, "report evidence metadata value", 256),
        )


@dataclass(frozen=True, slots=True)
class ReportEvidenceMetadata:
    artifact_id: str
    kind: EvidenceArtifactKind
    content_sha256: str
    captured_at_us: int
    source_url: str | None
    source_url_sha256: str | None
    http_status: int | None
    redirect_count: int
    provider_id: str
    run_id: str
    capture_method: EvidenceCaptureMethod
    integrity: ReportEvidenceIntegrity
    derivative_count: int
    metadata: tuple[ReportEvidenceMetadataEntry, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        _validate_id(self.artifact_id, "report evidence artifact id")
        _validate_hash(self.content_sha256, "report evidence content hash")
        _validate_timestamp(self.captured_at_us, "report evidence capture time")
        _validate_id(self.provider_id, "report evidence provider id")
        _validate_id(self.run_id, "report evidence run id")
        if not isinstance(self.kind, EvidenceArtifactKind):
            raise TypeError("report evidence kind is invalid")
        if not isinstance(self.capture_method, EvidenceCaptureMethod):
            raise TypeError("report evidence capture method is invalid")
        if not isinstance(self.integrity, ReportEvidenceIntegrity):
            raise TypeError("report evidence integrity state is invalid")
        if self.source_url is not None:
            validate_safe_url(self.source_url)
        if self.source_url_sha256 is not None:
            _validate_hash(self.source_url_sha256, "report evidence source URL hash")
        if (self.source_url is None) != (self.source_url_sha256 is None):
            raise ValueError("report evidence source URL identity is incomplete")
        if (
            self.source_url is not None
            and self.source_url_sha256
            != hashlib.sha256(self.source_url.encode("utf-8")).hexdigest()
        ):
            raise ValueError("report evidence source URL hash does not match")
        if self.http_status is not None and (
            type(self.http_status) is not int or self.http_status < 100 or self.http_status > 599
        ):
            raise ValueError("report evidence HTTP status is invalid")
        if self.http_status is not None and self.source_url is None:
            raise ValueError("report evidence HTTP status requires a source URL")
        if (
            type(self.redirect_count) is not int
            or self.redirect_count < 0
            or self.redirect_count > 10
            or (self.redirect_count > 0 and self.source_url is None)
        ):
            raise ValueError("report evidence redirect count is invalid")
        if type(self.derivative_count) is not int or self.derivative_count < 0:
            raise ValueError("report evidence derivative count is invalid")
        if (
            type(self.metadata) is not tuple
            or len(self.metadata) > MAX_REPORT_METADATA_PER_ARTIFACT
        ):
            raise ValueError("report evidence metadata is outside the allowed bounds")
        keys = tuple(item.key for item in self.metadata)
        if len(set(keys)) != len(keys):
            raise ValueError("report evidence metadata keys must be unique")


@dataclass(frozen=True, slots=True)
class ReportPositiveSignalSource:
    signal: PositiveAttributionSignal
    weight: int
    evidence_references: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, PositiveAttributionSignal):
            raise TypeError("report positive attribution signal is invalid")
        if type(self.weight) is not int or not 0 <= self.weight <= 1_000:
            raise ValueError("report positive attribution weight is invalid")
        _validate_ids(
            self.evidence_references,
            "report positive attribution evidence references",
            16,
            allow_empty=False,
        )


@dataclass(frozen=True, slots=True)
class ReportNegativeSignalSource:
    signal: NegativeAttributionSignal
    penalty: int
    evidence_references: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, NegativeAttributionSignal):
            raise TypeError("report negative attribution signal is invalid")
        if type(self.penalty) is not int or not 0 <= self.penalty <= 1_000:
            raise ValueError("report negative attribution penalty is invalid")
        _validate_ids(
            self.evidence_references,
            "report negative attribution evidence references",
            16,
            allow_empty=False,
        )


@dataclass(frozen=True, slots=True)
class ReportAttributionSummary:
    weight_profile_version: str
    score: int
    confidence_band: AttributionConfidenceBand
    human_state: HumanAttributionState | None
    human_decided_at_us: int | None
    contributing_signals: tuple[PositiveAttributionSignal, ...]
    contradiction_signals: tuple[NegativeAttributionSignal, ...]
    contributing_signal_sources: tuple[ReportPositiveSignalSource, ...]
    contradiction_signal_sources: tuple[ReportNegativeSignalSource, ...]
    missing_evidence: tuple[PositiveAttributionSignal, ...]
    recommended_next_evidence: tuple[PositiveAttributionSignal, ...]
    human_review_required: bool = True

    def __post_init__(self) -> None:
        if _VERSION.fullmatch(self.weight_profile_version) is None:
            raise ValueError("report attribution version is invalid")
        if type(self.score) is not int or self.score < -1_000 or self.score > 1_000:
            raise ValueError("report attribution score is invalid")
        if not isinstance(self.confidence_band, AttributionConfidenceBand):
            raise TypeError("report attribution confidence band is invalid")
        if self.human_state is not None and not isinstance(self.human_state, HumanAttributionState):
            raise TypeError("report human attribution state is invalid")
        if (self.human_state is None) != (self.human_decided_at_us is None):
            raise ValueError("report human attribution decision is inconsistent")
        if self.human_decided_at_us is not None:
            _validate_timestamp(self.human_decided_at_us, "report human decision time")
        if self.human_review_required is not True:
            raise ValueError("report attribution always requires human review")
        signal_groups: tuple[tuple[StrEnum, ...], ...] = (
            self.contributing_signals,
            self.contradiction_signals,
            self.missing_evidence,
            self.recommended_next_evidence,
        )
        if any(
            type(group) is not tuple or len(set(group)) != len(group) for group in signal_groups
        ):
            raise ValueError("report attribution signals must be unique tuples")
        if any(
            not isinstance(signal, PositiveAttributionSignal)
            for signal in (
                *self.contributing_signals,
                *self.missing_evidence,
                *self.recommended_next_evidence,
            )
        ):
            raise TypeError("report positive attribution signal is invalid")
        if any(
            not isinstance(signal, NegativeAttributionSignal)
            for signal in self.contradiction_signals
        ):
            raise TypeError("report negative attribution signal is invalid")
        if (
            type(self.contributing_signal_sources) is not tuple
            or type(self.contradiction_signal_sources) is not tuple
        ):
            raise TypeError("report attribution source mappings must be tuples")
        if any(
            not isinstance(item, ReportPositiveSignalSource)
            for item in self.contributing_signal_sources
        ) or any(
            not isinstance(item, ReportNegativeSignalSource)
            for item in self.contradiction_signal_sources
        ):
            raise TypeError("report attribution source mapping is invalid")
        if {item.signal for item in self.contributing_signal_sources} != set(
            self.contributing_signals
        ):
            raise ValueError("report positive attribution sources are incomplete")
        if {item.signal for item in self.contradiction_signal_sources} != set(
            self.contradiction_signals
        ):
            raise ValueError("report negative attribution sources are incomplete")
        if len({item.signal for item in self.contributing_signal_sources}) != len(
            self.contributing_signal_sources
        ) or len({item.signal for item in self.contradiction_signal_sources}) != len(
            self.contradiction_signal_sources
        ):
            raise ValueError("report attribution source mappings must be unique")
        if set(self.contributing_signals) & set(self.missing_evidence):
            raise ValueError("report observed and missing attribution evidence overlap")
        if not set(self.recommended_next_evidence) <= set(self.missing_evidence):
            raise ValueError("report recommendations must refer to missing evidence")


@dataclass(frozen=True, slots=True)
class ReportFindingSummary:
    finding_id: str
    provider_id: str
    provider_label: str
    provider_url: str | None
    title: str = field(repr=False)
    summary: str = field(repr=False)
    outcome: ReportFindingOutcome
    severity: ReportFindingSeverity
    visibility: ReportFindingVisibility
    updated_at_us: int
    attribution: ReportAttributionSummary
    evidence: tuple[ReportEvidenceMetadata, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _validate_id(self.finding_id, "report finding id")
        _validate_id(self.provider_id, "report finding provider id")
        object.__setattr__(
            self,
            "provider_label",
            _normalise_text(self.provider_label, "report provider label", 128),
        )
        if self.provider_url is not None:
            validate_safe_url(self.provider_url)
        object.__setattr__(self, "title", _normalise_text(self.title, "report finding title", 256))
        object.__setattr__(
            self,
            "summary",
            _normalise_text(self.summary, "report finding summary", 2_048),
        )
        if not isinstance(self.outcome, ReportFindingOutcome):
            raise TypeError("report finding outcome is invalid")
        if not isinstance(self.severity, ReportFindingSeverity):
            raise TypeError("report finding severity is invalid")
        if not isinstance(self.visibility, ReportFindingVisibility):
            raise TypeError("report finding visibility is invalid")
        _validate_timestamp(self.updated_at_us, "report finding update time")
        if type(self.evidence) is not tuple or len(self.evidence) > MAX_REPORT_EVIDENCE_PER_FINDING:
            raise ValueError("report finding evidence is outside the allowed bounds")
        artifact_ids = tuple(item.artifact_id for item in self.evidence)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("report finding evidence must be unique")
        attribution_references = {
            reference
            for item in self.attribution.contributing_signal_sources
            for reference in item.evidence_references
        } | {
            reference
            for item in self.attribution.contradiction_signal_sources
            for reference in item.evidence_references
        }
        if not attribution_references <= set(artifact_ids):
            raise ValueError("report attribution source is not linked to the finding")


@dataclass(frozen=True, slots=True)
class ReportComparisonDiff:
    finding_id: str
    provider_id: str
    state: FindingDiffState
    previous_fingerprint: str | None
    current_fingerprint: str | None

    def __post_init__(self) -> None:
        _validate_id(self.finding_id, "report comparison finding id")
        _validate_id(self.provider_id, "report comparison provider id")
        if not isinstance(self.state, FindingDiffState):
            raise TypeError("report comparison state is invalid")
        if self.previous_fingerprint is not None:
            _validate_hash(self.previous_fingerprint, "report previous finding fingerprint")
        if self.current_fingerprint is not None:
            _validate_hash(self.current_fingerprint, "report current finding fingerprint")
        if self.state is FindingDiffState.NEW and (
            self.previous_fingerprint is not None or self.current_fingerprint is None
        ):
            raise ValueError("report new finding fingerprints are inconsistent")
        if self.state is FindingDiffState.REMOVED and (
            self.previous_fingerprint is None or self.current_fingerprint is not None
        ):
            raise ValueError("report removed finding fingerprints are inconsistent")
        if self.state in {
            FindingDiffState.CHANGED,
            FindingDiffState.UNCHANGED,
            FindingDiffState.REAPPEARED,
        } and (self.previous_fingerprint is None or self.current_fingerprint is None):
            raise ValueError("report observed finding fingerprints are incomplete")


@dataclass(frozen=True, slots=True)
class ReportUnresolvedAbsence:
    finding_id: str
    provider_id: str
    previous_fingerprint: str
    current_coverage: ProviderCoverageState | None

    def __post_init__(self) -> None:
        _validate_id(self.finding_id, "report unresolved finding id")
        _validate_id(self.provider_id, "report unresolved provider id")
        _validate_hash(self.previous_fingerprint, "report unresolved finding fingerprint")
        if self.current_coverage is not None and not isinstance(
            self.current_coverage, ProviderCoverageState
        ):
            raise TypeError("report unresolved coverage state is invalid")


@dataclass(frozen=True, slots=True)
class ReportProviderCoverage:
    provider_id: str
    provider_url: str | None
    baseline_state: ProviderCoverageState | None
    current_state: ProviderCoverageState | None

    def __post_init__(self) -> None:
        _validate_id(self.provider_id, "report coverage provider id")
        if self.provider_url is not None:
            validate_safe_url(self.provider_url)
        if self.baseline_state is not None and not isinstance(
            self.baseline_state, ProviderCoverageState
        ):
            raise TypeError("report baseline coverage state is invalid")
        if self.current_state is not None and not isinstance(
            self.current_state, ProviderCoverageState
        ):
            raise TypeError("report current coverage state is invalid")


@dataclass(frozen=True, slots=True)
class ReportAuditComparison:
    baseline_run_id: str
    current_run_id: str
    diffs: tuple[ReportComparisonDiff, ...]
    unresolved_absences: tuple[ReportUnresolvedAbsence, ...]
    coverage: tuple[ReportProviderCoverage, ...]
    incomplete: bool
    incomplete_reasons: tuple[ComparisonIncompleteReason, ...]

    def __post_init__(self) -> None:
        _validate_id(self.baseline_run_id, "report baseline run id")
        _validate_id(self.current_run_id, "report current run id")
        if self.baseline_run_id == self.current_run_id:
            raise ValueError("report comparison runs must be distinct")
        if type(self.diffs) is not tuple or type(self.unresolved_absences) is not tuple:
            raise ValueError("report comparison items must be tuples")
        if len(self.diffs) + len(self.unresolved_absences) > MAX_REPORT_COMPARISON_ITEMS:
            raise ValueError("report comparison items are outside the allowed bounds")
        diff_ids = tuple(item.finding_id for item in self.diffs)
        unresolved_ids = tuple(item.finding_id for item in self.unresolved_absences)
        if len(set(diff_ids)) != len(diff_ids) or len(set(unresolved_ids)) != len(unresolved_ids):
            raise ValueError("report comparison finding ids must be unique")
        if set(diff_ids) & set(unresolved_ids):
            raise ValueError("report comparison findings cannot also be unresolved")
        if type(self.coverage) is not tuple or len(self.coverage) > MAX_REPORT_PROVIDERS:
            raise ValueError("report comparison coverage is outside the allowed bounds")
        if len({item.provider_id for item in self.coverage}) != len(self.coverage):
            raise ValueError("report comparison coverage providers must be unique")
        if type(self.incomplete) is not bool:
            raise TypeError("report comparison incomplete state is invalid")
        if type(self.incomplete_reasons) is not tuple or len(set(self.incomplete_reasons)) != len(
            self.incomplete_reasons
        ):
            raise ValueError("report comparison incomplete reasons must be a unique tuple")
        if any(
            not isinstance(reason, ComparisonIncompleteReason) for reason in self.incomplete_reasons
        ):
            raise TypeError("report comparison incomplete reason is invalid")
        if self.incomplete != bool(self.incomplete_reasons):
            raise ValueError("report comparison incomplete state is inconsistent")


@dataclass(frozen=True, slots=True)
class ReportProviderResponse:
    provider_id: str
    response_code: str
    summary: str = field(repr=False)
    received_at_us: int
    evidence_references: tuple[str, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        _validate_id(self.provider_id, "report provider response provider id")
        if _CODE.fullmatch(self.response_code) is None:
            raise ValueError("report provider response code is invalid")
        object.__setattr__(
            self,
            "summary",
            _normalise_text(self.summary, "report provider response summary", 2_048),
        )
        _validate_timestamp(self.received_at_us, "report provider response time")
        _validate_ids(
            self.evidence_references,
            "report provider response evidence references",
            MAX_REPORT_EVIDENCE_REFERENCES,
        )


@dataclass(frozen=True, slots=True)
class ReportRemediationHistoryEntry:
    revision: int
    event_type: RemediationEventType
    actor_id: str
    occurred_at_us: int
    previous_status: RemediationStatus | None
    current_status: RemediationStatus
    detail_code: str
    subject_id: str | None
    evidence_references: tuple[str, ...] = field(default=(), repr=False)
    note: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("report remediation history revision is invalid")
        if not isinstance(self.event_type, RemediationEventType):
            raise TypeError("report remediation history event type is invalid")
        _validate_id(self.actor_id, "report remediation history actor id")
        _validate_timestamp(self.occurred_at_us, "report remediation history time")
        if self.previous_status is not None and not isinstance(
            self.previous_status, RemediationStatus
        ):
            raise TypeError("report remediation previous status is invalid")
        if not isinstance(self.current_status, RemediationStatus):
            raise TypeError("report remediation current status is invalid")
        if _CODE.fullmatch(self.detail_code) is None:
            raise ValueError("report remediation history detail code is invalid")
        if self.subject_id is not None:
            _validate_id(self.subject_id, "report remediation history subject id")
        _validate_ids(
            self.evidence_references,
            "report remediation history evidence references",
            MAX_REPORT_EVIDENCE_REFERENCES,
        )
        if self.note is not None:
            object.__setattr__(
                self,
                "note",
                _normalise_text(self.note, "report remediation history note", 1_000),
            )


@dataclass(frozen=True, slots=True)
class ReportRemediationSummary:
    case_id: str
    finding_ids: tuple[str, ...]
    action: RemediationAction
    action_disposition: ActionDisposition
    status: RemediationStatus
    deadline_at_us: int | None
    draft_text: str | None = field(repr=False)
    evidence_references: tuple[str, ...] = field(repr=False)
    provider_responses: tuple[ReportProviderResponse, ...] = field(repr=False)
    reappearance_count: int
    last_reappearance_at_us: int | None
    revision: int
    created_at_us: int
    updated_at_us: int
    history: tuple[ReportRemediationHistoryEntry, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _validate_id(self.case_id, "report remediation case id")
        _validate_ids(
            self.finding_ids,
            "report remediation finding ids",
            MAX_REPORT_FINDING_LINKS,
            allow_empty=False,
        )
        if not isinstance(self.action, RemediationAction):
            raise TypeError("report remediation action is invalid")
        if not isinstance(self.action_disposition, ActionDisposition):
            raise TypeError("report remediation action disposition is invalid")
        if not isinstance(self.status, RemediationStatus):
            raise TypeError("report remediation status is invalid")
        if self.deadline_at_us is not None:
            _validate_timestamp(self.deadline_at_us, "report remediation deadline")
        if self.draft_text is not None:
            object.__setattr__(
                self,
                "draft_text",
                _normalise_text(self.draft_text, "report remediation draft", 10_000),
            )
        _validate_ids(
            self.evidence_references,
            "report remediation evidence references",
            MAX_REPORT_EVIDENCE_REFERENCES,
        )
        if (
            type(self.provider_responses) is not tuple
            or len(self.provider_responses) > MAX_REPORT_PROVIDER_RESPONSES
        ):
            raise ValueError("report remediation provider responses are outside the allowed bounds")
        if type(self.reappearance_count) is not int or self.reappearance_count < 0:
            raise ValueError("report remediation reappearance count is invalid")
        if (self.reappearance_count == 0) != (self.last_reappearance_at_us is None):
            raise ValueError("report remediation reappearance state is inconsistent")
        if self.last_reappearance_at_us is not None:
            _validate_timestamp(
                self.last_reappearance_at_us,
                "report remediation reappearance time",
            )
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("report remediation revision is invalid")
        _validate_timestamp(self.created_at_us, "report remediation creation time")
        _validate_timestamp(self.updated_at_us, "report remediation update time")
        if self.updated_at_us < self.created_at_us:
            raise ValueError("report remediation timestamps are inconsistent")
        if type(self.history) is not tuple or len(self.history) != self.revision:
            raise ValueError("report remediation history is incomplete")
        if len(self.history) > MAX_REPORT_HISTORY_ENTRIES or tuple(
            item.revision for item in self.history
        ) != tuple(range(1, self.revision + 1)):
            raise ValueError("report remediation history revisions are invalid")
        if self.history[-1].occurred_at_us != self.updated_at_us:
            raise ValueError("report remediation history time is inconsistent")
        if self.history[-1].current_status is not self.status:
            raise ValueError("report remediation history status is inconsistent")
        linked_evidence = set(self.evidence_references)
        nested_evidence = {
            reference
            for response in self.provider_responses
            for reference in response.evidence_references
        } | {reference for entry in self.history for reference in entry.evidence_references}
        if not nested_evidence <= linked_evidence:
            raise ValueError("report remediation nested evidence is not linked")


@dataclass(frozen=True, slots=True)
class LocalReportInput:
    profile_label: str | None = field(repr=False)
    comparison: ReportAuditComparison
    findings: tuple[ReportFindingSummary, ...] = field(repr=False)
    remediations: tuple[ReportRemediationSummary, ...] = field(repr=False)
    generated_at_us: int

    def __post_init__(self) -> None:
        if self.profile_label is not None:
            object.__setattr__(
                self,
                "profile_label",
                _normalise_text(self.profile_label, "report profile label", 128),
            )
        if type(self.findings) is not tuple or len(self.findings) > MAX_REPORT_FINDINGS:
            raise ValueError("report findings are outside the allowed bounds")
        if len({item.finding_id for item in self.findings}) != len(self.findings):
            raise ValueError("report finding ids must be unique")
        if type(self.remediations) is not tuple or len(self.remediations) > MAX_REPORT_REMEDIATIONS:
            raise ValueError("report remediations are outside the allowed bounds")
        if len({item.case_id for item in self.remediations}) != len(self.remediations):
            raise ValueError("report remediation case ids must be unique")
        _validate_timestamp(self.generated_at_us, "report generation time")
