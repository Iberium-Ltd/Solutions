"""Strict contracts for review-only analysis with an explicit local model."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import RFC_4122, UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel
from ariadne_core.local_ai import LocalAIProvider

MAX_WORKSPACE_DOCUMENT_BYTES = 64 * 1024
MAX_WORKSPACE_QUESTION_CHARACTERS = 2_000
MAX_WORKSPACE_SCOPES = 6
MAX_WORKSPACE_SECTIONS = 8
MAX_WORKSPACE_SECTION_ITEMS = 12
MAX_WORKSPACE_FACTS = 20
MAX_WORKSPACE_LIMITATIONS = 12
MAX_WORKSPACE_CONNECTIONS = 16
MAX_WORKSPACE_NEXT_STEPS = 16
MAX_WORKSPACE_SOURCES = 128

_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


def _uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise ValueError(f"{label} is invalid")
    return value


def _safe_text(value: str, *, label: str, allow_newlines: bool = False) -> str:
    if value != value.strip() or any(
        (ord(character) < 32 and (not allow_newlines or character not in "\n\r\t"))
        or ord(character) == 127
        for character in value
    ):
        raise ValueError(f"{label} is invalid")
    return value


class LocalAIWorkspaceTask(StrEnum):
    SUMMARY = "SUMMARY"
    ORGANIZE = "ORGANIZE"
    QUESTION = "QUESTION"
    CONNECTIONS = "CONNECTIONS"
    GAP_ANALYSIS = "GAP_ANALYSIS"


class LocalAIWorkspaceScope(StrEnum):
    ENTITIES = "ENTITIES"
    GRAPH = "GRAPH"
    FINDINGS = "FINDINGS"
    REMEDIATION = "REMEDIATION"
    AUDIT_COVERAGE = "AUDIT_COVERAGE"
    DOCUMENT = "DOCUMENT"


class LocalAIWorkspaceExecution(StrEnum):
    LOCAL_MODEL = "LOCAL_MODEL"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"
    DETERMINISTIC = "DETERMINISTIC"


class LocalAIWorkspaceDocumentKind(StrEnum):
    PASTE = "PASTE"
    FILE = "FILE"


class LocalAIWorkspaceFallbackReason(StrEnum):
    REQUEST_LIMIT = "REQUEST_LIMIT"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"


class LocalAIWorkspaceConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LocalAIWorkspaceDocument(ApiModel):
    kind: LocalAIWorkspaceDocumentKind = Field(strict=False)
    display_name: str = Field(min_length=1, max_length=255, repr=False)
    declared_media_type: str | None = Field(default=None, min_length=3, max_length=64)
    content: str = Field(min_length=1, max_length=MAX_WORKSPACE_DOCUMENT_BYTES, repr=False)
    content_sha256: str = Field(pattern=_SHA256.pattern)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _safe_text(value, label="workspace document name")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > MAX_WORKSPACE_DOCUMENT_BYTES:
            raise ValueError("workspace document exceeds its byte limit")
        if any(
            (ord(character) < 32 and character not in "\n\r\t") or ord(character) == 127
            for character in value
        ):
            raise ValueError("workspace document is invalid")
        return value

    @model_validator(mode="after")
    def validate_kind_binding(self) -> LocalAIWorkspaceDocument:
        if self.kind is LocalAIWorkspaceDocumentKind.PASTE:
            if self.declared_media_type not in {None, "text/plain"}:
                raise ValueError("pasted workspace text must be plain text")
        elif self.declared_media_type is None:
            raise ValueError("workspace file media type is required")
        return self


class LocalAIWorkspaceRequest(ApiModel):
    profile_id: str
    task: LocalAIWorkspaceTask = Field(strict=False)
    question: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_WORKSPACE_QUESTION_CHARACTERS,
        repr=False,
    )
    scopes: tuple[Annotated[LocalAIWorkspaceScope, Field(strict=False)], ...] = Field(
        min_length=1,
        max_length=MAX_WORKSPACE_SCOPES,
        strict=False,
    )
    include_sensitive_entities: bool = False
    execution: LocalAIWorkspaceExecution = Field(strict=False)
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    document: LocalAIWorkspaceDocument | None = None

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="workspace profile id")

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_text(value, label="workspace question", allow_newlines=True)

    @field_validator("model_id")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_text(value, label="workspace model")

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if (
            not secret
            or secret != secret.strip()
            or len(secret.encode("utf-8")) > 512
            or any(ord(character) <= 32 or ord(character) == 127 for character in secret)
        ):
            raise ValueError("OpenAI API key is invalid")
        return value

    @model_validator(mode="after")
    def validate_bindings(self) -> LocalAIWorkspaceRequest:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("workspace scopes must be unique")
        if self.task is LocalAIWorkspaceTask.QUESTION and self.question is None:
            raise ValueError("workspace question task requires a question")
        if self.task is not LocalAIWorkspaceTask.QUESTION and self.question is not None:
            raise ValueError("workspace question is only valid for question tasks")
        if self.execution is LocalAIWorkspaceExecution.LOCAL_MODEL:
            if self.model_id is None:
                raise ValueError("workspace local-model execution requires an explicit model")
            if self.openai_api_key is not None:
                raise ValueError("workspace local-model execution cannot carry an API key")
        elif self.execution is LocalAIWorkspaceExecution.OPENAI_RESPONSES:
            if self.model_id is None or self.openai_api_key is None:
                raise ValueError("OpenAI workspace execution requires a model and API key")
        elif self.model_id is not None or self.openai_api_key is not None:
            raise ValueError("deterministic workspace execution cannot select a model or API key")
        document_selected = LocalAIWorkspaceScope.DOCUMENT in self.scopes
        if document_selected != (self.document is not None):
            raise ValueError("workspace document scope and input must be selected together")
        return self


class LocalAIWorkspaceSectionItem(ApiModel):
    text: str = Field(min_length=1, max_length=600)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="workspace section item", allow_newlines=True)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("workspace section evidence references must be unique")
        if any(not 1 <= len(value) <= 160 or value != value.strip() for value in values):
            raise ValueError("workspace section evidence reference is invalid")
        return values


class LocalAIWorkspaceSection(ApiModel):
    heading: str = Field(min_length=1, max_length=96)
    items: tuple[LocalAIWorkspaceSectionItem, ...] = Field(
        min_length=1,
        max_length=MAX_WORKSPACE_SECTION_ITEMS,
    )

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        return _safe_text(value, label="workspace section heading")

    @field_validator("items")
    @classmethod
    def validate_items(
        cls,
        values: tuple[LocalAIWorkspaceSectionItem, ...],
    ) -> tuple[LocalAIWorkspaceSectionItem, ...]:
        if len({value.text for value in values}) != len(values):
            raise ValueError("workspace section items must be unique")
        return values


class LocalAIWorkspaceFact(ApiModel):
    statement: str = Field(min_length=1, max_length=600)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    confidence: LocalAIWorkspaceConfidence = Field(strict=False)

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _safe_text(value, label="workspace fact", allow_newlines=True)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("workspace evidence references must be unique")
        if any(not 1 <= len(value) <= 160 or value != value.strip() for value in values):
            raise ValueError("workspace evidence reference is invalid")
        return values


class LocalAIWorkspaceConnection(ApiModel):
    from_ref: str = Field(min_length=1, max_length=160)
    to_ref: str = Field(min_length=1, max_length=160)
    relationship: str = Field(min_length=1, max_length=96)
    supporting_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    contradiction_refs: tuple[str, ...] = Field(max_length=8)
    confidence: LocalAIWorkspaceConfidence = Field(strict=False)
    rationale: str = Field(min_length=1, max_length=600)
    verification_suggestion: str = Field(min_length=1, max_length=600)

    @field_validator("relationship", "rationale", "verification_suggestion")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="workspace connection text", allow_newlines=True)

    @field_validator("supporting_refs", "contradiction_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("workspace connection references must be unique")
        if any(not 1 <= len(value) <= 160 or value != value.strip() for value in values):
            raise ValueError("workspace connection reference is invalid")
        return values

    @model_validator(mode="after")
    def validate_endpoints(self) -> LocalAIWorkspaceConnection:
        if self.from_ref == self.to_ref:
            raise ValueError("workspace connection endpoints must differ")
        return self


class LocalAIWorkspaceNextStep(ApiModel):
    priority: int = Field(ge=1, le=5)
    suggestion: str = Field(min_length=1, max_length=600)
    rationale: str = Field(min_length=1, max_length=600)
    supporting_refs: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("suggestion", "rationale")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="workspace next step", allow_newlines=True)

    @field_validator("supporting_refs")
    @classmethod
    def validate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("workspace next-step references must be unique")
        if any(not 1 <= len(value) <= 160 or value != value.strip() for value in values):
            raise ValueError("workspace next-step reference is invalid")
        return values


class LocalAIWorkspaceSource(ApiModel):
    ref: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=240)
    locator: str = Field(min_length=1, max_length=600)
    source_url: str | None = Field(default=None, max_length=2_048)
    content_sha256: str | None = Field(default=None, pattern=_SHA256.pattern)
    provider_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_display_name: str | None = Field(default=None, min_length=1, max_length=255)
    artifact_id: str | None = Field(default=None, min_length=1, max_length=160)
    segment_id: str | None = Field(default=None, min_length=1, max_length=160)
    segment_index: int | None = Field(default=None, ge=0, le=1_000_000)
    segment_locator: str | None = Field(default=None, min_length=1, max_length=600)
    source_span_start: int | None = Field(default=None, ge=0, le=1_000_000_000)
    source_span_end: int | None = Field(default=None, gt=0, le=1_000_000_000)
    extraction_run_id: str | None = Field(default=None, min_length=1, max_length=160)
    extractor_kind: str | None = Field(default=None, min_length=1, max_length=64)
    extractor_name: str | None = Field(default=None, min_length=1, max_length=96)
    extractor_version: str | None = Field(default=None, min_length=1, max_length=48)
    run_id: str | None = Field(default=None, min_length=1, max_length=160)
    origin_kind: str | None = Field(default=None, min_length=1, max_length=64)
    origin_type: str | None = Field(default=None, min_length=1, max_length=64)
    observed_at_us: int | None = Field(default=None, ge=0)
    confidence_micros: int | None = Field(default=None, ge=0, le=1_000_000)
    disposition: str | None = Field(default=None, min_length=1, max_length=32)
    source_url_sha256: str | None = Field(default=None, pattern=_SHA256.pattern)
    capture_method: str | None = Field(default=None, min_length=1, max_length=64)
    http_status: int | None = Field(default=None, ge=100, le=599)
    redirect_count: int | None = Field(default=None, ge=0, le=20)

    @field_validator(
        "ref",
        "kind",
        "label",
        "locator",
        "provider_id",
        "source_id",
        "source_display_name",
        "artifact_id",
        "segment_id",
        "segment_locator",
        "extraction_run_id",
        "extractor_kind",
        "extractor_name",
        "extractor_version",
        "run_id",
        "origin_kind",
        "origin_type",
        "disposition",
        "capture_method",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_text(value, label="workspace source")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _safe_text(value, label="workspace source URL")
        if not value.startswith(("http://", "https://")):
            raise ValueError("workspace source URL is invalid")
        return value

    @model_validator(mode="after")
    def validate_exact_provenance(self) -> LocalAIWorkspaceSource:
        if (self.source_span_start is None) != (self.source_span_end is None):
            raise ValueError("workspace source span must be complete")
        if (
            self.source_span_start is not None
            and self.source_span_end is not None
            and self.source_span_end <= self.source_span_start
        ):
            raise ValueError("workspace source span is invalid")
        if (self.source_url is None) != (self.source_url_sha256 is None):
            raise ValueError("workspace source URL and digest must be bound")
        segment_fields = (self.segment_id, self.segment_index, self.segment_locator)
        if any(item is not None for item in segment_fields) and any(
            item is None for item in segment_fields
        ):
            raise ValueError("workspace segment provenance must be complete")
        if self.kind in {
            "ENTITY_ORIGIN",
            "GRAPH_EDGE_ORIGIN",
            "DOCUMENT_SEGMENT",
        } and (
            self.source_id is None
            or self.source_display_name is None
            or self.content_sha256 is None
            or any(item is None for item in segment_fields)
        ):
            raise ValueError("workspace source provenance is incomplete")
        if self.kind == "ENTITY_ORIGIN" and (
            self.observed_at_us is None
            or self.confidence_micros is None
            or self.origin_kind is None
        ):
            raise ValueError("workspace entity origin provenance is incomplete")
        if self.kind == "GRAPH_EDGE_ORIGIN" and (
            self.extraction_run_id is None
            or self.extractor_kind is None
            or self.extractor_name is None
            or self.extractor_version is None
            or self.observed_at_us is None
            or self.confidence_micros is None
            or self.origin_type is None
            or self.disposition is None
        ):
            raise ValueError("workspace graph origin provenance is incomplete")
        if self.kind == "EVIDENCE_METADATA" and (
            self.artifact_id is None
            or self.content_sha256 is None
            or self.provider_id is None
            or self.run_id is None
            or self.observed_at_us is None
            or self.capture_method is None
        ):
            raise ValueError("workspace evidence provenance is incomplete")
        return self


class LocalAIWorkspaceSourceCounts(ApiModel):
    entities: int = Field(ge=0, le=1_000_000)
    graph_nodes: int = Field(ge=0, le=1_000_000)
    graph_edges: int = Field(ge=0, le=1_000_000)
    findings: int = Field(ge=0, le=1_000_000)
    remediation_cases: int = Field(ge=0, le=1_000_000)
    audit_runs: int = Field(ge=0, le=1_000_000)
    document_segments: int = Field(ge=0, le=1_000_000)


class LocalAIWorkspaceResult(ApiModel):
    profile_id: str
    task: LocalAIWorkspaceTask
    selected_scopes: tuple[LocalAIWorkspaceScope, ...]
    requested_execution: LocalAIWorkspaceExecution
    execution_mode: LocalAIWorkspaceExecution
    fallback_reason: LocalAIWorkspaceFallbackReason | None
    provider: LocalAIProvider | None
    model_id: str | None = Field(default=None, max_length=256)
    engine_version: Literal["1"]
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=2_000)
    sections: tuple[LocalAIWorkspaceSection, ...] = Field(
        max_length=MAX_WORKSPACE_SECTIONS,
    )
    facts: tuple[LocalAIWorkspaceFact, ...] = Field(max_length=MAX_WORKSPACE_FACTS)
    connections: tuple[LocalAIWorkspaceConnection, ...] = Field(
        max_length=MAX_WORKSPACE_CONNECTIONS
    )
    next_steps: tuple[LocalAIWorkspaceNextStep, ...] = Field(max_length=MAX_WORKSPACE_NEXT_STEPS)
    sources: tuple[LocalAIWorkspaceSource, ...] = Field(max_length=MAX_WORKSPACE_SOURCES)
    unanswered: str | None = Field(default=None, max_length=1_000)
    limitations: tuple[str, ...] = Field(max_length=MAX_WORKSPACE_LIMITATIONS)
    included_counts: LocalAIWorkspaceSourceCounts
    available_counts: LocalAIWorkspaceSourceCounts
    projection_truncated: bool
    input_sha256: str = Field(pattern=_SHA256.pattern)
    restricted_values_redacted: int = Field(ge=0, le=10_000)
    local_only: bool
    external_network_used: bool
    raw_evidence_included: Literal[False]
    review_only: Literal[True]
    human_review_required: Literal[True]

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="workspace profile id")

    @model_validator(mode="after")
    def validate_execution_identity(self) -> LocalAIWorkspaceResult:
        complete_identity = self.provider is not None and self.model_id is not None
        if (self.provider is None) != (self.model_id is None):
            raise ValueError("workspace provider identity must be complete")
        if self.execution_mode is LocalAIWorkspaceExecution.LOCAL_MODEL:
            if (
                self.requested_execution is not LocalAIWorkspaceExecution.LOCAL_MODEL
                or not complete_identity
                or self.provider is LocalAIProvider.OPENAI_RESPONSES
                or self.fallback_reason is not None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("local workspace result requires model identity")
        elif self.execution_mode is LocalAIWorkspaceExecution.OPENAI_RESPONSES:
            if (
                self.requested_execution is not LocalAIWorkspaceExecution.OPENAI_RESPONSES
                or self.provider is not LocalAIProvider.OPENAI_RESPONSES
                or not complete_identity
                or self.fallback_reason is not None
                or not self.external_network_used
                or self.local_only
            ):
                raise ValueError("OpenAI workspace result requires external provider identity")
        elif self.requested_execution is LocalAIWorkspaceExecution.DETERMINISTIC:
            if (
                complete_identity
                or self.fallback_reason is not None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("deterministic workspace result cannot be a fallback")
        elif self.requested_execution is LocalAIWorkspaceExecution.LOCAL_MODEL:
            if (
                complete_identity
                or self.fallback_reason is None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("local workspace fallback has invalid provider state")
        elif (
            self.provider is not LocalAIProvider.OPENAI_RESPONSES
            or not complete_identity
            or self.fallback_reason is None
            or not self.external_network_used
            or self.local_only
        ):
            raise ValueError("OpenAI workspace fallback has invalid provider state")
        source_refs = tuple(source.ref for source in self.sources)
        if len(set(source_refs)) != len(source_refs):
            raise ValueError("workspace source references must be unique")
        cited_refs = {reference for fact in self.facts for reference in fact.evidence_refs}
        cited_refs.update(
            reference
            for section in self.sections
            for item in section.items
            for reference in item.evidence_refs
        )
        cited_refs.update(
            reference
            for connection in self.connections
            for reference in (
                connection.from_ref,
                connection.to_ref,
                *connection.supporting_refs,
                *connection.contradiction_refs,
            )
        )
        cited_refs.update(
            reference for step in self.next_steps for reference in step.supporting_refs
        )
        if cited_refs != set(source_refs):
            raise ValueError("workspace citations and source catalog must match exactly")
        return self
