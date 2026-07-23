"""Strict Phase 3 intake, review, and graph API contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import RFC_4122, UUID

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel
from ariadne_core.local_ai import LocalAIProvider

MAX_PASTED_TEXT_CHARACTERS = 262_144
MAX_PHASE3_FILE_BYTES = 1_048_576
MAX_PHASE3_FILE_BASE64_CHARACTERS = ((MAX_PHASE3_FILE_BYTES + 2) // 3) * 4
MAX_REVIEW_ENTITIES = 100
MAX_ENTITY_ORIGINS = 32
MAX_ENTITY_ORIGIN_PAGE_SIZE = 12
MAX_ENTITY_ORIGIN_OFFSET = 100_000_000
MAX_GRAPH_NODES = 500
MAX_PROFILE_SUMMARIES = 100


def _uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise ValueError(f"{label} is invalid")
    return value


def _safe_label(value: str, *, label: str) -> str:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} is invalid")
    return value


class Sensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    SENSITIVE = "SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"


class ReviewState(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    EXCLUDED = "EXCLUDED"


class TemporalState(StrEnum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    UNKNOWN = "UNKNOWN"


class SearchPolicy(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    STORE_ONLY = "STORE_ONLY"
    DENY = "DENY"


class TransmissionPolicy(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    POLICY_CONTROLLED = "POLICY_CONTROLLED"
    REQUIRE_EACH_APPROVAL = "REQUIRE_EACH_APPROVAL"
    NEVER = "NEVER"


class LocalAIIntakeStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    DISABLED = "DISABLED"
    SUCCEEDED = "SUCCEEDED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class EntityDecisionType(StrEnum):
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    EXCLUDE = "EXCLUDE"
    CLASSIFY = "CLASSIFY"
    POLICY_CHANGE = "POLICY_CHANGE"


class GraphEvidenceDisposition(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class GraphVisibility(StrEnum):
    PUBLICLY_ATTRIBUTABLE = "PUBLICLY_ATTRIBUTABLE"
    PUBLIC_PSEUDONYMOUS = "PUBLIC_PSEUDONYMOUS"
    PRIVATELY_LINKABLE = "PRIVATELY_LINKABLE"
    HISTORICAL_RESIDUE = "HISTORICAL_RESIDUE"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    UNKNOWN = "UNKNOWN"


class ProfileCreateRequest(ApiModel):
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        repr=False,
    )
    display_label: str = Field(min_length=1, max_length=80, repr=False)
    purpose: str = Field(min_length=1, max_length=240, repr=False)

    @field_validator("display_label", "purpose")
    @classmethod
    def validate_labels(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _safe_label(value, label=info.field_name.replace("_", " "))


class ProfileSummary(ApiModel):
    profile_id: str
    display_label: str = Field(repr=False)
    purpose: str = Field(repr=False)
    status: str
    revision: int = Field(ge=1)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")


class ProfileListResult(ApiModel):
    profiles: tuple[ProfileSummary, ...] = Field(max_length=MAX_PROFILE_SUMMARIES)
    has_more: bool


class ProfileDeleteRequest(ApiModel):
    profile_id: str
    expected_revision: int = Field(ge=1)
    confirmation_label: str = Field(min_length=1, max_length=80, repr=False)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")

    @field_validator("confirmation_label")
    @classmethod
    def validate_confirmation_label(cls, value: str) -> str:
        return _safe_label(value, label="confirmation label")


class ProfileDeleteResult(ApiModel):
    profile_id: str
    deleted_rows: int = Field(ge=1)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")


class PasteIntakeRequest(ApiModel):
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        repr=False,
    )
    profile_id: str
    display_name: str = Field(min_length=1, max_length=128, repr=False)
    content: str = Field(min_length=1, max_length=MAX_PASTED_TEXT_CHARACTERS, repr=False)
    consent_confirmed: bool
    retain_raw_source: bool = False
    semantic_enrichment_enabled: bool = True

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _safe_label(value, label="intake display name")

    @field_validator("consent_confirmed")
    @classmethod
    def validate_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit intake consent is required")
        return value


class FileIntakeRequest(ApiModel):
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        repr=False,
    )
    profile_id: str
    content_base64: str = Field(
        min_length=4,
        max_length=MAX_PHASE3_FILE_BASE64_CHARACTERS,
        pattern=r"^[A-Za-z0-9+/]*={0,2}$",
        repr=False,
    )
    display_name: str = Field(min_length=1, max_length=255, repr=False)
    declared_media_type: str = Field(min_length=3, max_length=64)
    expected_size_bytes: int = Field(ge=1, le=MAX_PHASE3_FILE_BYTES)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent_confirmed: bool
    retain_raw_source: bool = False
    semantic_enrichment_enabled: bool = True

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _safe_label(value, label="file display name")

    @field_validator("consent_confirmed")
    @classmethod
    def validate_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit intake consent is required")
        return value


class IntakeReceipt(ApiModel):
    source_id: str
    profile_id: str
    state: str
    source_kind: str
    segment_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    quarantine_count: int = Field(ge=0)
    revision: int = Field(ge=1)
    local_ai_status: LocalAIIntakeStatus = Field(strict=False)
    local_ai_provider: LocalAIProvider | None = Field(strict=False)
    local_ai_model: str | None = Field(max_length=256)
    local_ai_engine_version: str | None = Field(max_length=48)
    local_ai_suggestion_count: int = Field(ge=0, le=64)

    @field_validator("source_id", "profile_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, label=info.field_name.replace("_", " "))


class EntityReviewRequest(ApiModel):
    profile_id: str
    source_id: str | None = None
    limit: int = Field(default=MAX_REVIEW_ENTITIES, ge=1, le=MAX_REVIEW_ENTITIES)

    @field_validator("profile_id", "source_id")
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is not None:
            return _uuid(value, label=info.field_name.replace("_", " "))
        return None


class EntityOrigin(ApiModel):
    source_id: str
    source_display_name: str = Field(min_length=1, max_length=255, repr=False)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_id: str
    segment_index: int = Field(ge=0, le=1_000_000)
    segment_locator: str = Field(min_length=1, max_length=16_384, repr=False)
    source_span_start: int | None = Field(default=None, ge=0, le=1_048_576)
    source_span_end: int | None = Field(default=None, ge=1, le=1_048_576)
    extraction_run_id: str | None = None
    extractor_kind: str | None = Field(default=None, min_length=1, max_length=24)
    extractor_name: str | None = Field(default=None, min_length=1, max_length=96)
    extractor_version: str | None = Field(default=None, min_length=1, max_length=48)
    origin_kind: str = Field(min_length=1, max_length=24)
    observed_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    confidence_micros: int = Field(ge=0, le=1_000_000)
    explanation: str = Field(min_length=1, max_length=2_048, repr=False)

    @field_validator("source_id", "segment_id", "extraction_run_id")
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is not None:
            return _uuid(value, label=info.field_name.replace("_", " "))
        return None

    @model_validator(mode="after")
    def validate_source_span_and_extractor(self) -> EntityOrigin:
        if (self.source_span_start is None) != (self.source_span_end is None):
            raise ValueError("entity origin source span is incomplete")
        if (
            self.source_span_start is not None
            and self.source_span_end is not None
            and self.source_span_end <= self.source_span_start
        ):
            raise ValueError("entity origin source span is invalid")
        extraction_fields = (
            self.extraction_run_id,
            self.extractor_kind,
            self.extractor_name,
            self.extractor_version,
        )
        if any(item is not None for item in extraction_fields) and not all(
            item is not None for item in extraction_fields
        ):
            raise ValueError("entity origin extractor metadata is incomplete")
        return self


class EntityOriginPageRequest(ApiModel):
    profile_id: str
    entity_id: str
    offset: int = Field(default=0, ge=0, le=MAX_ENTITY_ORIGIN_OFFSET)
    limit: int = Field(default=MAX_ENTITY_ORIGIN_PAGE_SIZE, ge=1, le=MAX_ENTITY_ORIGIN_PAGE_SIZE)

    @field_validator("profile_id", "entity_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, label=info.field_name.replace("_", " "))


class EntityOriginPageResult(ApiModel):
    profile_id: str
    entity_id: str
    offset: int = Field(ge=0, le=MAX_ENTITY_ORIGIN_OFFSET)
    limit: int = Field(ge=1, le=MAX_ENTITY_ORIGIN_PAGE_SIZE)
    origins: tuple[EntityOrigin, ...] = Field(max_length=MAX_ENTITY_ORIGIN_PAGE_SIZE, repr=False)
    total: int = Field(ge=0)
    has_more: bool

    @field_validator("profile_id", "entity_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_page(self) -> EntityOriginPageResult:
        if len(self.origins) > self.limit:
            raise ValueError("entity origin page exceeds its requested limit")
        if self.offset < self.total and not self.origins:
            raise ValueError("entity origin page is unexpectedly empty")
        if self.origins and self.offset + len(self.origins) > self.total:
            raise ValueError("entity origin page exceeds the stored total")
        if self.has_more != (self.offset + len(self.origins) < self.total):
            raise ValueError("entity origin pagination state is inconsistent")
        return self


class EntitySummary(ApiModel):
    entity_id: str
    entity_type: str
    display_value: str = Field(min_length=1, max_length=512, repr=False)
    sensitivity: Sensitivity = Field(strict=False)
    review_state: ReviewState = Field(strict=False)
    temporal_state: TemporalState = Field(strict=False)
    search_policy: SearchPolicy = Field(strict=False)
    transmission_policy: TransmissionPolicy = Field(strict=False)
    confidence_micros: int = Field(ge=0, le=1_000_000)
    provenance_label: str = Field(min_length=1, max_length=160, repr=False)
    origins: tuple[EntityOrigin, ...] = Field(
        min_length=1,
        max_length=MAX_ENTITY_ORIGINS,
        repr=False,
    )
    origins_truncated: bool
    revision: int = Field(ge=1)

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        return _uuid(value, label="entity id")

    @model_validator(mode="after")
    def validate_origin_truncation(self) -> EntitySummary:
        if self.origins_truncated and len(self.origins) != MAX_ENTITY_ORIGINS:
            raise ValueError("truncated entity origins must fill the response bound")
        return self


class EntityReviewResult(ApiModel):
    profile_id: str
    entities: tuple[EntitySummary, ...] = Field(max_length=MAX_REVIEW_ENTITIES)
    quarantine_count: int = Field(ge=0)
    has_more: bool

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")


class EntityDecisionRequest(ApiModel):
    idempotency_key: str = Field(
        min_length=16,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
        repr=False,
    )
    profile_id: str
    entity_id: str
    expected_revision: int = Field(ge=1)
    decision_type: EntityDecisionType = Field(strict=False)
    review_state: ReviewState = Field(strict=False)
    sensitivity: Sensitivity = Field(strict=False)
    temporal_state: TemporalState = Field(strict=False)
    search_policy: SearchPolicy = Field(strict=False)
    transmission_policy: TransmissionPolicy = Field(strict=False)
    reason: str | None = Field(default=None, max_length=240, repr=False)

    @field_validator("profile_id", "entity_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, label=info.field_name.replace("_", " "))

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is not None:
            return _safe_label(value, label="decision reason")
        return None

    @model_validator(mode="after")
    def validate_restricted_policies(self) -> EntityDecisionRequest:
        required_state = {
            EntityDecisionType.CONFIRM: ReviewState.CONFIRMED,
            EntityDecisionType.REJECT: ReviewState.FALSE_POSITIVE,
            EntityDecisionType.EXCLUDE: ReviewState.EXCLUDED,
        }.get(self.decision_type)
        if required_state is not None and self.review_state is not required_state:
            raise ValueError("decision type and review state are inconsistent")
        if self.decision_type is EntityDecisionType.CLASSIFY and self.review_state not in {
            ReviewState.PROBABLE,
            ReviewState.POSSIBLE,
        }:
            raise ValueError("classification decision has an invalid review state")
        if self.sensitivity is Sensitivity.HIGHLY_SENSITIVE:
            if self.search_policy is SearchPolicy.ALLOW:
                raise ValueError("highly sensitive entities require explicit search approval")
            if self.transmission_policy is TransmissionPolicy.POLICY_CONTROLLED:
                raise ValueError("highly sensitive entities require per-disclosure approval")
        if self.review_state in {ReviewState.FALSE_POSITIVE, ReviewState.EXCLUDED}:
            if self.search_policy is not SearchPolicy.DENY:
                raise ValueError("excluded entities cannot be search permitted")
            if self.transmission_policy is not TransmissionPolicy.NEVER:
                raise ValueError("excluded entities cannot be transmitted")
        return self


class GraphSnapshotRequest(ApiModel):
    profile_id: str
    max_nodes: int = Field(default=200, ge=1, le=MAX_GRAPH_NODES)
    include_sensitive: bool = False

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")


class GraphNode(ApiModel):
    node_id: str
    node_type: str
    display_label: str = Field(min_length=1, max_length=512, repr=False)
    sensitivity: Sensitivity = Field(strict=False)
    entity_id: str | None

    @field_validator("node_id", "entity_id")
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is not None:
            return _uuid(value, label=info.field_name.replace("_", " "))
        return None


class GraphEdge(ApiModel):
    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_type: str
    confidence_micros: int = Field(ge=0, le=1_000_000)
    origin_type: str
    explanation: str = Field(min_length=1, max_length=2_048, repr=False)
    support_count: int = Field(ge=0, le=100_000)
    contradiction_count: int = Field(ge=0, le=100_000)
    evidence: tuple[GraphEdgeEvidence, ...] = Field(max_length=8, repr=False)
    evidence_truncated: bool

    @field_validator("edge_id", "from_node_id", "to_node_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_evidence_counts(self) -> GraphEdge:
        included_support = sum(
            item.disposition is GraphEvidenceDisposition.SUPPORTS for item in self.evidence
        )
        included_contradictions = len(self.evidence) - included_support
        total = self.support_count + self.contradiction_count
        if total < 1 or not self.evidence:
            raise ValueError("graph edge evidence is required")
        if self.support_count < included_support:
            raise ValueError("graph support evidence count is inconsistent")
        if self.contradiction_count < included_contradictions:
            raise ValueError("graph contradiction evidence count is inconsistent")
        if self.evidence_truncated is not (len(self.evidence) < total):
            raise ValueError("graph evidence truncation state is inconsistent")
        return self


class GraphEdgeEvidence(ApiModel):
    source_id: str
    segment_ordinal: int = Field(ge=0, le=1_000_000)
    disposition: GraphEvidenceDisposition = Field(strict=False)
    confidence_micros: int = Field(ge=0, le=1_000_000)
    visibility: GraphVisibility = Field(strict=False)
    source_span_start: int | None = Field(default=None, ge=0, le=1_048_576)
    source_span_end: int | None = Field(default=None, ge=1, le=1_048_576)
    observed_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    origin_type: str = Field(min_length=1, max_length=64)
    explanation: str = Field(min_length=1, max_length=160, repr=False)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _uuid(value, label="source id")

    @model_validator(mode="after")
    def validate_source_span(self) -> GraphEdgeEvidence:
        if (self.source_span_start is None) != (self.source_span_end is None):
            raise ValueError("graph evidence source span is incomplete")
        if (
            self.source_span_start is not None
            and self.source_span_end is not None
            and self.source_span_end <= self.source_span_start
        ):
            raise ValueError("graph evidence source span is invalid")
        return self


class GraphSnapshot(ApiModel):
    profile_id: str
    nodes: tuple[GraphNode, ...] = Field(max_length=MAX_GRAPH_NODES)
    edges: tuple[GraphEdge, ...] = Field(max_length=250)
    truncated: bool

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="profile id")
