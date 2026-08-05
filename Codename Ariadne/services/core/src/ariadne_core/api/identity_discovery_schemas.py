"""Strict contracts for persistent people and restart-safe recursive discovery.

Closed enums make task and audit lifecycle states explicit. Requests always
carry a profile scope, mutations carry optimistic revisions where applicable,
and aggregate responses are capped so a large frontier cannot cross the local
API boundary without pagination indicators.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import RFC_4122, UUID

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel

MAX_SOURCES = 200
MAX_AUDITS = 64
MAX_TASKS = 500
MAX_RESULTS = 500
MAX_LEADS = 500
MAX_PROPOSALS = 250
MAX_RECEIPTS = 500
MAX_AI_INSIGHTS = 100
MAX_AI_CITATIONS = 200


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise ValueError(f"{label} is invalid")
    return value


def _safe_text(value: str, label: str) -> str:
    if value != value.strip() or any(
        (ord(character) < 32 and character not in "\n\t") or ord(character) == 127
        for character in value
    ):
        raise ValueError(f"{label} is invalid")
    return value


class AuditMode(StrEnum):
    """Stable seed-selection policy captured on each audit run."""

    FULL_RESCAN = "FULL_RESCAN"
    INCREMENTAL = "INCREMENTAL"
    NEW_IDENTIFIERS_ONLY = "NEW_IDENTIFIERS_ONLY"
    FAILED_AND_BLOCKED_RETRY = "FAILED_AND_BLOCKED_RETRY"
    SELECTED_IDENTITIES = "SELECTED_IDENTITIES"
    SELECTED_PROVIDERS = "SELECTED_PROVIDERS"
    CHANGE_MONITORING = "CHANGE_MONITORING"
    MAXIMUM_COVERAGE = "MAXIMUM_COVERAGE"


class AuditState(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AuditStage(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    PLANNING = "PLANNING"
    SEARCHING = "SEARCHING"
    EXTRACTING = "EXTRACTING"
    CORRELATING = "CORRELATING"
    AI_ANALYSIS = "AI_ANALYSIS"
    REVIEW = "REVIEW"
    CHECKPOINT = "CHECKPOINT"
    COMPLETE = "COMPLETE"


class AuditControlAction(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


class FrontierTaskState(StrEnum):
    """Durable outcomes distinguish empty, blocked, retryable, and reviewed work."""

    PLANNED = "PLANNED"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED_EMPTY = "SUCCEEDED_EMPTY"
    SUCCEEDED_RESULTS = "SUCCEEDED_RESULTS"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWED = "REVIEWED"
    SAVED = "SAVED"


class FrontierTaskType(StrEnum):
    """Closed broker vocabulary; membership does not imply an adapter is implemented."""

    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_PROVIDER = "SEARCH_PROVIDER"
    SEARCH_SITE = "SEARCH_SITE"
    SEARCH_DOMAIN = "SEARCH_DOMAIN"
    SEARCH_USERNAME = "SEARCH_USERNAME"
    FETCH_URL = "FETCH_URL"
    PARSE_HTML = "PARSE_HTML"
    EXTRACT_LINKS = "EXTRACT_LINKS"
    EXTRACT_IDENTIFIERS = "EXTRACT_IDENTIFIERS"
    QUERY_ARCHIVE = "QUERY_ARCHIVE"
    QUERY_GITHUB = "QUERY_GITHUB"
    QUERY_REGISTRY = "QUERY_REGISTRY"
    QUERY_DNS = "QUERY_DNS"
    QUERY_CERTIFICATE_TRANSPARENCY = "QUERY_CERTIFICATE_TRANSPARENCY"
    RUN_USERNAME_ENUMERATION = "RUN_USERNAME_ENUMERATION"
    RUN_METADATA_EXTRACTION = "RUN_METADATA_EXTRACTION"
    RUN_OCR = "RUN_OCR"
    HASH_IMAGE = "HASH_IMAGE"
    COMPARE_IMAGES = "COMPARE_IMAGES"
    CAPTURE_SCREENSHOT = "CAPTURE_SCREENSHOT"
    CAPTURE_HTML = "CAPTURE_HTML"
    CAPTURE_DOCUMENT = "CAPTURE_DOCUMENT"
    GENERATE_QUERY_VARIANTS = "GENERATE_QUERY_VARIANTS"
    ANALYSE_DOCUMENT = "ANALYSE_DOCUMENT"
    COMPARE_SOURCES = "COMPARE_SOURCES"


class SourceType(StrEnum):
    WEBSITE = "WEBSITE"
    SUBPAGE = "SUBPAGE"
    SOCIAL_PROFILE = "SOCIAL_PROFILE"
    FORUM_PROFILE = "FORUM_PROFILE"
    FORUM_THREAD = "FORUM_THREAD"
    COMMENT = "COMMENT"
    MEMBER_PAGE = "MEMBER_PAGE"
    GIT_REPOSITORY = "GIT_REPOSITORY"
    PACKAGE_REGISTRY = "PACKAGE_REGISTRY"
    DOCUMENT = "DOCUMENT"
    PDF = "PDF"
    PUBLIC_RECORD = "PUBLIC_RECORD"
    ARCHIVE = "ARCHIVE"
    SEARCH_RESULT = "SEARCH_RESULT"
    MEDIA = "MEDIA"
    MANUAL_URL = "MANUAL_URL"
    OTHER = "OTHER"


class ProposalDecision(StrEnum):
    CONFIRM = "CONFIRM"
    CONFIRM_HISTORICAL = "CONFIRM_HISTORICAL"
    PROBABLE = "PROBABLE"
    SEARCH_DEEPER = "SEARCH_DEEPER"
    REJECT = "REJECT"
    UNRELATED = "UNRELATED"
    MERGE = "MERGE"


class AIAnalysisStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"
    EMPTY = "EMPTY"


class AIInsightKind(StrEnum):
    FACT = "FACT"
    CONNECTION = "CONNECTION"
    NEXT_STEP = "NEXT_STEP"


class PersonWorkspaceRequest(ApiModel):
    """Base scope shared by every person and audit operation."""

    profile_id: str

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, "profile id")


class PersonUpdateRequest(PersonWorkspaceRequest):
    """Compare-and-swap update spanning profile and identity-workspace metadata."""

    expected_profile_revision: int = Field(ge=1)
    expected_details_revision: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=240)
    notes: str = Field(default="", max_length=20_000)
    tags: tuple[str, ...] = Field(default=(), max_length=32, strict=False)

    @field_validator("display_name", "purpose", "notes")
    @classmethod
    def validate_text(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _safe_text(value, info.field_name)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_safe_text(value, "tag") for value in values)
        if any(not value or len(value) > 48 for value in cleaned) or len(set(cleaned)) != len(
            cleaned
        ):
            raise ValueError("tags are invalid")
        return cleaned


class PersonDetails(ApiModel):
    profile_id: str
    display_name: str
    purpose: str
    status: str
    notes: str
    tags: tuple[str, ...]
    profile_revision: int = Field(ge=1)
    details_revision: int = Field(ge=0)
    identity_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    audit_count: int = Field(ge=0)
    unresolved_proposal_count: int = Field(ge=0)


class PersonSourceCreateRequest(PersonWorkspaceRequest):
    url: str = Field(min_length=8, max_length=2048, repr=False)
    source_type: SourceType = Field(default=SourceType.MANUAL_URL, strict=False)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    notes: str = Field(default="", max_length=4000)
    authorized_self_audit: bool

    @field_validator("url", "notes")
    @classmethod
    def validate_text(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _safe_text(value, info.field_name)


class PersonSource(ApiModel):
    source_id: str
    source_type: SourceType
    url: str
    title: str | None
    notes: str
    relationship_state: str
    parent_source_id: str | None
    first_seen_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    last_checked_at_us: int | None = Field(default=None, ge=1, le=9_007_199_254_740_991)
    http_status: int | None = Field(default=None, ge=100, le=599)
    revision: int = Field(ge=1)


class AuditCreateRequest(PersonWorkspaceRequest):
    """Explicit authorization plus immutable provider, depth, time, and request budgets."""

    name: str = Field(min_length=1, max_length=120)
    mode: AuditMode = Field(default=AuditMode.INCREMENTAL, strict=False)
    provider_ids: tuple[str, ...] = Field(
        default=(
            "DUCKDUCKGO_HTML",
            "GITHUB_USERS",
            "GITLAB_USERS",
            "NPM_REGISTRY",
            "RDAP_DOMAIN",
            "WAYBACK_CDX",
            "CERTIFICATE_TRANSPARENCY",
        ),
        min_length=1,
        max_length=8,
        strict=False,
    )
    max_depth: int = Field(default=3, ge=0, le=8)
    request_budget: int = Field(default=120, ge=1, le=2000)
    time_budget_seconds: int = Field(default=1800, ge=10, le=86_400)
    cost_budget_micros: int = Field(default=0, ge=0, le=1_000_000_000_000)
    use_local_ai: bool = True
    authorized_self_audit: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _safe_text(value, "audit name")

    @field_validator("provider_ids")
    @classmethod
    def validate_providers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {
            "DUCKDUCKGO_HTML",
            "GITHUB_USERS",
            "GITLAB_USERS",
            "NPM_REGISTRY",
            "RDAP_DOMAIN",
            "WAYBACK_CDX",
            "CERTIFICATE_TRANSPARENCY",
            "HAVE_I_BEEN_PWNED_V3",
            "MANUAL_BROWSER_HANDOFFS",
        }
        if len(set(values)) != len(values) or not set(values) <= allowed:
            raise ValueError("audit providers are invalid")
        return values


class AuditControlRequest(PersonWorkspaceRequest):
    audit_id: str
    expected_revision: int = Field(ge=1)
    action: AuditControlAction = Field(strict=False)

    @field_validator("audit_id")
    @classmethod
    def validate_audit_id(cls, value: str) -> str:
        return _uuid(value, "audit id")


class AuditExecuteRequest(PersonWorkspaceRequest):
    audit_id: str
    maximum_tasks: int = Field(default=4, ge=1, le=8)

    @field_validator("audit_id")
    @classmethod
    def validate_audit_id(cls, value: str) -> str:
        return _uuid(value, "audit id")


class TaskStateCount(ApiModel):
    state: FrontierTaskState
    count: int = Field(ge=0)


class AuditSummary(ApiModel):
    """Materialized progress derived from durable frontier state, never a timer animation."""

    audit_id: str
    name: str
    mode: AuditMode
    state: AuditState
    stage: AuditStage
    provider_ids: tuple[str, ...]
    use_local_ai: bool
    selected_model: str | None
    max_depth: int = Field(ge=0, le=8)
    request_budget: int = Field(ge=1, le=2000)
    total_tasks: int = Field(ge=0)
    terminal_tasks: int = Field(ge=0)
    result_count: int = Field(ge=0)
    lead_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    progress_micros: int = Field(ge=0, le=1_000_000)
    stop_reason: str | None
    task_states: tuple[TaskStateCount, ...]
    started_at_us: int | None = Field(default=None, ge=1, le=9_007_199_254_740_991)
    finished_at_us: int | None = Field(default=None, ge=1, le=9_007_199_254_740_991)
    created_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    updated_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_progress(self) -> AuditSummary:
        if self.terminal_tasks > self.total_tasks:
            raise ValueError("audit progress is invalid")
        return self


class FrontierTaskSummary(ApiModel):
    task_id: str
    lead_id: str | None
    parent_task_id: str | None
    task_type: FrontierTaskType
    provider_id: str
    masked_payload: str
    priority: int = Field(ge=0, le=100)
    information_gain_micros: int = Field(ge=0, le=1_000_000)
    depth: int = Field(ge=0, le=8)
    state: FrontierTaskState
    attempt_count: int = Field(ge=0)
    retry_limit: int = Field(ge=0, le=10)
    result_count: int = Field(ge=0)
    stop_reason: str | None
    revision: int = Field(ge=1)


class DiscoveryResult(ApiModel):
    result_id: str
    task_id: str
    provider_id: str
    rank: int = Field(ge=1)
    category: str
    url: str
    title: str
    snippet: str
    observed_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    review_state: str


class DiscoveryLead(ApiModel):
    lead_id: str
    parent_lead_id: str | None
    source_id: str | None
    lead_type: str
    display_value: str
    source_url: str | None
    provider_id: str
    depth: int = Field(ge=0, le=8)
    supporting_signals: tuple[str, ...]
    contradictions: tuple[str, ...]
    confidence_micros: int = Field(ge=0, le=1_000_000)
    ownership_state: str
    temporal_state: str
    review_state: str
    expansion_state: str


class KnowledgeProposal(ApiModel):
    """Source-backed candidate knowledge that remains non-canonical until human review."""

    proposal_id: str
    lead_id: str
    entity_type: str
    display_value: str
    source_url: str
    source_span_start: int | None
    source_span_end: int | None
    supporting_signals: tuple[str, ...]
    contradictions: tuple[str, ...]
    confidence_micros: int = Field(ge=0, le=1_000_000)
    temporal_state: str
    review_state: str
    recommended_actions: tuple[str, ...]
    model_provider: str | None
    model_id: str | None
    revision: int = Field(ge=1)


class ToolReceipt(ApiModel):
    receipt_id: str
    task_id: str | None
    tool_name: FrontierTaskType
    authorization_state: str
    execution_state: str
    result_code: str
    result_count: int = Field(ge=0)
    model_provider: str | None
    model_id: str | None
    started_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    finished_at_us: int = Field(ge=1, le=9_007_199_254_740_991)


class AIAnalysisCitation(ApiModel):
    reference_id: str = Field(min_length=3, max_length=183)
    result_id: str
    url: str = Field(min_length=8, max_length=2_048)
    title: str = Field(max_length=500)


class AIAnalysisInsight(ApiModel):
    kind: AIInsightKind
    statement: str = Field(min_length=1, max_length=2_000)
    rationale: str = Field(max_length=2_000)
    confidence: str | None = Field(default=None, max_length=16)
    evidence_refs: tuple[str, ...] = Field(max_length=32)


class AuditAIAnalysis(ApiModel):
    """Persisted model or deterministic result with exact public-result citations."""

    analysis_id: str
    status: AIAnalysisStatus
    result_code: str
    provider: str | None
    model_id: str | None
    engine_version: str | None
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=4_000)
    insights: tuple[AIAnalysisInsight, ...] = Field(max_length=MAX_AI_INSIGHTS)
    citations: tuple[AIAnalysisCitation, ...] = Field(max_length=MAX_AI_CITATIONS)
    limitations: tuple[str, ...] = Field(max_length=32)
    created_at_us: int = Field(ge=1, le=9_007_199_254_740_991)


class PersonWorkspace(ApiModel):
    person: PersonDetails
    sources: tuple[PersonSource, ...] = Field(max_length=MAX_SOURCES)
    audits: tuple[AuditSummary, ...] = Field(max_length=MAX_AUDITS)
    has_more_sources: bool
    has_more_audits: bool


class AuditDetail(ApiModel):
    """Bounded audit projection with truncation flags for every growing collection."""

    profile_id: str
    audit: AuditSummary
    tasks: tuple[FrontierTaskSummary, ...] = Field(max_length=MAX_TASKS)
    results: tuple[DiscoveryResult, ...] = Field(max_length=MAX_RESULTS)
    leads: tuple[DiscoveryLead, ...] = Field(max_length=MAX_LEADS)
    proposals: tuple[KnowledgeProposal, ...] = Field(max_length=MAX_PROPOSALS)
    receipts: tuple[ToolReceipt, ...] = Field(max_length=MAX_RECEIPTS)
    ai_analysis: AuditAIAnalysis | None
    has_more_tasks: bool
    has_more_results: bool
    has_more_leads: bool
    has_more_proposals: bool
    has_more_receipts: bool


class ProposalDecisionRequest(PersonWorkspaceRequest):
    audit_id: str
    proposal_id: str
    expected_revision: int = Field(ge=1)
    decision: ProposalDecision = Field(strict=False)

    @field_validator("audit_id", "proposal_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _uuid(value, info.field_name)
