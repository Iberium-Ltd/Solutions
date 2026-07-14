"""Strict wire contracts for persisted Phase 5 findings and attribution evidence."""

from __future__ import annotations

import base64
import binascii
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel, _canonical_uuid
from ariadne_core.domain.attribution import (
    NegativeAttributionSignal,
    PositiveAttributionSignal,
)
from ariadne_core.domain.evidence_artifacts import (
    MAX_ARTIFACT_BYTES,
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
    validate_safe_url,
    validate_safe_url_reference,
)

MAX_PHASE5_FINDINGS = 100
MAX_PHASE5_ARTIFACTS = 64
MAX_PHASE5_ARTIFACT_COUNT = 1_000
MAX_PHASE5_BASE64_CHARS = 4 * ((MAX_ARTIFACT_BYTES + 2) // 3)
MAX_PHASE5_METADATA_ENTRIES = 32
MAX_PHASE5_METADATA_TOTAL_CHARS = 4_096


class FindingOutcome(StrEnum):
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


class FindingSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingVisibility(StrEnum):
    PUBLICLY_ATTRIBUTABLE = "PUBLICLY_ATTRIBUTABLE"
    PUBLIC_PSEUDONYMOUS = "PUBLIC_PSEUDONYMOUS"
    PRIVATELY_LINKABLE = "PRIVATELY_LINKABLE"
    HISTORICAL_RESIDUE = "HISTORICAL_RESIDUE"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    UNKNOWN = "UNKNOWN"


class AttributionConfidenceBand(StrEnum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class HumanAttributionState(StrEnum):
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    CONFIRMED_NON_MATCH = "CONFIRMED_NON_MATCH"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class EvidenceIntegrityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    FAILED = "FAILED"


class ManualEvidenceArtifactKind(StrEnum):
    SCREENSHOT = "SCREENSHOT"
    HTML = "HTML"
    PDF = "PDF"
    RAW_JSON = "RAW_JSON"


class EvidenceViewport(ApiModel):
    width: int = Field(ge=1, le=16_384)
    height: int = Field(ge=1, le=16_384)
    device_scale_micros: int = Field(ge=100_000, le=8_000_000)


def decode_phase5_content(value: str) -> bytes:
    """Decode one canonical, bounded base64 evidence value without echoing it."""

    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("evidence content encoding is invalid") from None
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("evidence content is outside the allowed bounds")
    if base64.b64encode(content).decode("ascii") != value:
        raise ValueError("evidence content encoding is not canonical")
    return content


class Phase5EvidenceMetadata(ApiModel):
    key: str = Field(
        min_length=1,
        max_length=48,
        pattern=r"^[a-z][a-z0-9_.-]{0,47}$",
    )
    value: str = Field(min_length=1, max_length=256, repr=False)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if value != value.strip() or any(
            unicodedata.category(character).startswith("C") for character in value
        ):
            raise ValueError("evidence metadata value is invalid")
        return value


class Phase5ManualEvidenceImportRequest(ApiModel):
    profile_id: str
    finding_id: str
    kind: ManualEvidenceArtifactKind = Field(strict=False)
    content_base64: str = Field(
        min_length=4,
        max_length=MAX_PHASE5_BASE64_CHARS,
        repr=False,
    )
    viewport: EvidenceViewport | None = None
    metadata: tuple[Phase5EvidenceMetadata, ...] = Field(
        default=(),
        max_length=MAX_PHASE5_METADATA_ENTRIES,
        repr=False,
    )

    @field_validator("profile_id", "finding_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @field_validator("content_base64")
    @classmethod
    def validate_content(cls, value: str) -> str:
        decode_phase5_content(value)
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_import_metadata(self) -> Phase5ManualEvidenceImportRequest:
        if self.kind is ManualEvidenceArtifactKind.SCREENSHOT:
            if self.viewport is None:
                raise ValueError("screenshot evidence requires a viewport")
        elif self.viewport is not None:
            raise ValueError("only screenshot evidence accepts viewport metadata")
        keys = tuple(item.key for item in self.metadata)
        if len(set(keys)) != len(keys):
            raise ValueError("evidence metadata keys are duplicated")
        if sum(len(item.key) + len(item.value) for item in self.metadata) > (
            MAX_PHASE5_METADATA_TOTAL_CHARS
        ):
            raise ValueError("evidence metadata is outside the allowed bounds")
        return self


class Phase5ManualEvidenceImportResult(ApiModel):
    profile_id: str
    finding_id: str
    artifact_id: str
    kind: ManualEvidenceArtifactKind = Field(strict=False)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    capture_method: Literal[EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT]
    encrypted_at_rest: Literal[True]
    local_only: Literal[True]
    deduplicated: bool

    @field_validator("profile_id", "finding_id", "artifact_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))


class Phase5RedactedDerivativeRequest(ApiModel):
    profile_id: str
    original_artifact_id: str
    redacted_content_base64: str = Field(
        min_length=4,
        max_length=MAX_PHASE5_BASE64_CHARS,
        repr=False,
    )
    already_redacted: Literal[True]
    redaction_policy_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    redaction_summary_code: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]{1,63}$",
    )

    @field_validator("profile_id", "original_artifact_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @field_validator("redacted_content_base64")
    @classmethod
    def validate_content(cls, value: str) -> str:
        decode_phase5_content(value)
        return value


class Phase5RedactedDerivativeResult(ApiModel):
    profile_id: str
    original_artifact_id: str
    derivative_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    redaction_policy_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    redaction_summary_code: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]{1,63}$",
    )
    redaction_mode: Literal["CALLER_SUPPLIED"]
    encrypted_at_rest: Literal[True]
    local_only: Literal[True]
    deduplicated: bool

    @field_validator("profile_id", "original_artifact_id", "derivative_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))


class Phase5AttributionDecisionRequest(ApiModel):
    profile_id: str
    finding_id: str
    assessment_id: str
    state: HumanAttributionState = Field(strict=False)
    expected_previous_decision_id: str | None
    expected_previous_revision: int = Field(ge=0, le=2_147_483_647)

    @field_validator(
        "profile_id",
        "finding_id",
        "assessment_id",
        "expected_previous_decision_id",
    )
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_expected_revision(self) -> Phase5AttributionDecisionRequest:
        if (self.expected_previous_decision_id is None) != (self.expected_previous_revision == 0):
            raise ValueError("expected attribution decision revision is inconsistent")
        return self


class Phase5AttributionDecisionResult(ApiModel):
    profile_id: str
    finding_id: str
    assessment_id: str
    decision_id: str
    state: HumanAttributionState = Field(strict=False)
    actor_label: Literal["Local user"]
    decided_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    weight_profile_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    supersedes_decision_id: str | None
    revision: int = Field(ge=1, le=2_147_483_647)

    @field_validator(
        "profile_id",
        "finding_id",
        "assessment_id",
        "decision_id",
        "supersedes_decision_id",
    )
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_revision_chain(self) -> Phase5AttributionDecisionResult:
        if (self.supersedes_decision_id is None) != (self.revision == 1):
            raise ValueError("attribution decision revision chain is inconsistent")
        return self


class Phase5FindingListRequest(ApiModel):
    profile_id: str
    limit: int = Field(default=MAX_PHASE5_FINDINGS, ge=1, le=MAX_PHASE5_FINDINGS)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")


class Phase5FindingDetailRequest(ApiModel):
    profile_id: str
    finding_id: str

    @field_validator("profile_id", "finding_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))


class Phase5ManualFindingCreateRequest(ApiModel):
    profile_id: str
    title: str = Field(min_length=1, max_length=256, repr=False)
    summary: str = Field(min_length=1, max_length=2_048, repr=False)
    outcome: FindingOutcome = Field(strict=False)
    severity: FindingSeverity = Field(strict=False)
    visibility: FindingVisibility = Field(strict=False)
    provider_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    provider_label: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")

    @field_validator("title", "summary", "provider_label")
    @classmethod
    def validate_safe_text(cls, value: str) -> str:
        if value != value.strip() or any(
            unicodedata.category(character).startswith("C") for character in value
        ):
            raise ValueError("manual finding text is invalid")
        return value


class Phase5FindingSummary(ApiModel):
    finding_id: str
    title: str = Field(min_length=1, max_length=256, repr=False)
    summary: str = Field(min_length=1, max_length=2_048, repr=False)
    outcome: FindingOutcome = Field(strict=False)
    severity: FindingSeverity = Field(strict=False)
    visibility: FindingVisibility = Field(strict=False)
    attribution_state: HumanAttributionState | None = Field(strict=False)
    confidence_band: AttributionConfidenceBand = Field(strict=False)
    score: int = Field(ge=-1_000, le=1_000)
    human_review_required: Literal[True]
    provider_label: str = Field(min_length=1, max_length=128)
    artifact_count: int = Field(ge=0, le=MAX_PHASE5_ARTIFACT_COUNT)
    updated_at_us: int = Field(ge=1, le=9_007_199_254_740_991)

    @field_validator("finding_id")
    @classmethod
    def validate_finding_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="finding id")

    @field_validator("title", "summary", "provider_label")
    @classmethod
    def validate_safe_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("finding text is invalid")
        return value


class Phase5FindingListResult(ApiModel):
    profile_id: str
    findings: tuple[Phase5FindingSummary, ...] = Field(max_length=MAX_PHASE5_FINDINGS)
    has_more: bool

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")


class AttributionPositiveContribution(ApiModel):
    signal: PositiveAttributionSignal = Field(strict=False)
    weight: int = Field(ge=0, le=1_000)
    evidence_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("evidence_artifact_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("evidence artifact ids are duplicated")
        return tuple(_canonical_uuid(value, label="evidence artifact id") for value in values)


class AttributionNegativeContribution(ApiModel):
    signal: NegativeAttributionSignal = Field(strict=False)
    penalty: int = Field(ge=0, le=1_000)
    evidence_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("evidence_artifact_ids")
    @classmethod
    def validate_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("evidence artifact ids are duplicated")
        return tuple(_canonical_uuid(value, label="evidence artifact id") for value in values)


class AttributionMissingEvidence(ApiModel):
    signal: PositiveAttributionSignal = Field(strict=False)
    potential_weight: int = Field(ge=0, le=1_000)


class Phase5AttributionAssessment(ApiModel):
    assessment_id: str
    case_id: str
    weight_profile_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    score: int = Field(ge=-1_000, le=1_000)
    confidence_band: AttributionConfidenceBand = Field(strict=False)
    contributing_signals: tuple[AttributionPositiveContribution, ...] = Field(max_length=14)
    contradictions: tuple[AttributionNegativeContribution, ...] = Field(max_length=8)
    missing_evidence: tuple[AttributionMissingEvidence, ...] = Field(max_length=14)
    recommended_next_evidence: tuple[PositiveAttributionSignal, ...] = Field(max_length=5)
    human_review_required: Literal[True]

    @field_validator("recommended_next_evidence", mode="before")
    @classmethod
    def parse_recommended_evidence(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            try:
                return tuple(PositiveAttributionSignal(item) for item in value)
            except (TypeError, ValueError):
                pass
        return value

    @field_validator("assessment_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_signal_partitions(self) -> Phase5AttributionAssessment:
        positive = {item.signal for item in self.contributing_signals}
        missing = {item.signal for item in self.missing_evidence}
        if positive & missing:
            raise ValueError("observed and missing attribution evidence overlap")
        if len(positive) != len(self.contributing_signals):
            raise ValueError("positive attribution signals are duplicated")
        if len({item.signal for item in self.contradictions}) != len(self.contradictions):
            raise ValueError("negative attribution signals are duplicated")
        if len(missing) != len(self.missing_evidence):
            raise ValueError("missing attribution signals are duplicated")
        if len(set(self.recommended_next_evidence)) != len(self.recommended_next_evidence):
            raise ValueError("recommended attribution signals are duplicated")
        if not set(self.recommended_next_evidence) <= missing:
            raise ValueError("recommended evidence must be missing evidence")
        return self


class Phase5EvidenceArtifact(ApiModel):
    artifact_id: str
    kind: EvidenceArtifactKind = Field(strict=False)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    source_url: str | None = Field(default=None, max_length=2_048, repr=False)
    http_status: int | None = Field(default=None, ge=100, le=599)
    redirect_count: int = Field(ge=0, le=10)
    provider_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    run_id: str
    viewport: EvidenceViewport | None
    capture_method: EvidenceCaptureMethod = Field(strict=False)
    encrypted_at_rest: Literal[True]
    integrity_status: EvidenceIntegrityStatus = Field(strict=False)
    derivative_count: int = Field(ge=0, le=2_000)

    @field_validator("artifact_id", "run_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if info.data.get("kind") is EvidenceArtifactKind.URL_REFERENCE:
            return validate_safe_url_reference(value)
        return validate_safe_url(value)

    @model_validator(mode="after")
    def validate_capture_metadata(self) -> Phase5EvidenceArtifact:
        if self.http_status is not None and self.source_url is None:
            raise ValueError("evidence HTTP status requires a source URL")
        if self.redirect_count and self.source_url is None:
            raise ValueError("evidence redirects require a source URL")
        if self.kind is EvidenceArtifactKind.SCREENSHOT and self.viewport is None:
            raise ValueError("screenshot evidence requires a viewport")
        return self


class Phase5HumanDecision(ApiModel):
    decision_id: str
    assessment_id: str
    state: HumanAttributionState = Field(strict=False)
    actor_label: Literal["Local user"]
    decided_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    weight_profile_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    supersedes_decision_id: str | None
    revision: int = Field(ge=1, le=2_147_483_647)

    @field_validator("decision_id", "assessment_id", "supersedes_decision_id")
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_revision_chain(self) -> Phase5HumanDecision:
        if (self.supersedes_decision_id is None) != (self.revision == 1):
            raise ValueError("attribution decision revision chain is inconsistent")
        return self


class Phase5FindingDetailResult(ApiModel):
    profile_id: str
    finding: Phase5FindingSummary
    assessment: Phase5AttributionAssessment
    artifacts: tuple[Phase5EvidenceArtifact, ...] = Field(max_length=MAX_PHASE5_ARTIFACTS)
    human_decision: Phase5HumanDecision | None

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")

    @model_validator(mode="after")
    def validate_detail_consistency(self) -> Phase5FindingDetailResult:
        if self.finding.finding_id != self.assessment.case_id:
            raise ValueError("finding and attribution case do not match")
        if (
            self.finding.score != self.assessment.score
            or self.finding.confidence_band != self.assessment.confidence_band
        ):
            raise ValueError("finding attribution summary does not match")
        if self.finding.artifact_count != len(self.artifacts):
            raise ValueError("finding evidence count does not match")
        if self.finding.attribution_state != (
            None if self.human_decision is None else self.human_decision.state
        ):
            raise ValueError("finding human attribution state does not match")
        if self.human_decision is not None and (
            self.human_decision.assessment_id != self.assessment.assessment_id
            or self.human_decision.weight_profile_version != self.assessment.weight_profile_version
        ):
            raise ValueError("human decision assessment does not match")
        artifact_ids = {artifact.artifact_id for artifact in self.artifacts}
        referenced_ids = {
            artifact_id
            for contribution in self.assessment.contributing_signals
            for artifact_id in contribution.evidence_artifact_ids
        } | {
            artifact_id
            for contribution in self.assessment.contradictions
            for artifact_id in contribution.evidence_artifact_ids
        }
        if not referenced_ids <= artifact_ids:
            raise ValueError("attribution evidence is unavailable in finding detail")
        return self
