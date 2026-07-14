"""Strict contracts for ephemeral, cited reasoning over a local document corpus."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Literal, Self
from uuid import RFC_4122, UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from ariadne_core.api.local_corpus_schemas import LocalCorpusDocumentsRequest
from ariadne_core.api.schemas import ApiModel
from ariadne_core.local_ai import LocalAIError, LocalAIProvider, validate_model_id

MAX_LOCAL_CORPUS_AI_QUESTION_CHARACTERS = 2_000
MAX_LOCAL_CORPUS_AI_SECTIONS = 8
MAX_LOCAL_CORPUS_AI_SECTION_ITEMS = 12
MAX_LOCAL_CORPUS_AI_FACTS = 20
MAX_LOCAL_CORPUS_AI_CONNECTIONS = 16
MAX_LOCAL_CORPUS_AI_NEXT_STEPS = 16
MAX_LOCAL_CORPUS_AI_UNCERTAINTIES = 12
MAX_LOCAL_CORPUS_AI_SOURCE_CATALOG = 512

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CORPUS_ID_PATTERN = r"^corpus:[0-9a-f]{64}$"
_DOCUMENT_ID_PATTERN = r"^corpus-document:[0-9]{4}:[0-9a-f]{64}$"
_SEGMENT_ID_PATTERN = r"^corpus-document:[0-9]{4}:[0-9a-f]{64}:segment:[0-9]{1,5}$"
_ENTITY_ID_PATTERN = r"^corpus-entity:[0-9a-f]{64}$"
_CITABLE_REFERENCE = re.compile(
    rf"(?:{_SEGMENT_ID_PATTERN[1:-1]})|(?:{_ENTITY_ID_PATTERN[1:-1]})",
    re.ASCII,
)


def _safe_text(value: str, *, label: str, allow_newlines: bool = False) -> str:
    if value != value.strip() or any(
        (ord(character) < 32 and (not allow_newlines or character not in "\n\r\t"))
        or ord(character) == 127
        or unicodedata.category(character) in {"Cs"}
        for character in value
    ):
        raise ValueError(f"{label} is invalid")
    return value


def _uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise ValueError(f"{label} is invalid")
    return value


def _validate_references(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values) or any(
        _CITABLE_REFERENCE.fullmatch(value) is None for value in values
    ):
        raise ValueError(f"{label} references are invalid")
    return values


class LocalCorpusAITask(StrEnum):
    SUMMARY = "SUMMARY"
    ORGANIZE = "ORGANIZE"
    QUESTION = "QUESTION"
    CONNECTIONS = "CONNECTIONS"
    GAP_ANALYSIS = "GAP_ANALYSIS"


class LocalCorpusAIExecution(StrEnum):
    LOCAL_MODEL = "LOCAL_MODEL"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"
    DETERMINISTIC = "DETERMINISTIC"


class LocalCorpusAIFallbackReason(StrEnum):
    REQUEST_LIMIT = "REQUEST_LIMIT"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CONFIGURATION = "CONFIGURATION"


class LocalCorpusAIConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LocalCorpusAITextLabel(StrEnum):
    ORGANIZATION = "ORGANIZATION"
    CITED_SUMMARY = "CITED_SUMMARY"
    HYPOTHESIS = "HYPOTHESIS"
    LIMITATION = "LIMITATION"


class LocalCorpusAIReferenceKind(StrEnum):
    SEGMENT = "SEGMENT"
    ENTITY = "ENTITY"


class LocalCorpusAIContentOrigin(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    LOCAL_MODEL = "LOCAL_MODEL"
    OPENAI_RESPONSES = "OPENAI_RESPONSES"


class LocalCorpusAIRequest(LocalCorpusDocumentsRequest):
    profile_id: str
    task: LocalCorpusAITask = Field(strict=False)
    question: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_LOCAL_CORPUS_AI_QUESTION_CHARACTERS,
        repr=False,
    )
    execution: LocalCorpusAIExecution = Field(
        default=LocalCorpusAIExecution.DETERMINISTIC,
        strict=False,
    )
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    max_segments: int = Field(default=200, ge=1, le=200)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="local corpus AI profile id")

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _safe_text(value, label="local corpus AI question", allow_newlines=True)
        if len(value.encode("utf-8")) > 2_048:
            raise ValueError("local corpus AI question exceeds its byte limit")
        return value

    @field_validator("model_id")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_model_id(value)
        except LocalAIError:
            raise ValueError("local corpus AI model is invalid") from None

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
    def validate_bindings(self) -> Self:
        if self.task is LocalCorpusAITask.QUESTION and self.question is None:
            raise ValueError("local corpus AI question task requires a question")
        if self.task is not LocalCorpusAITask.QUESTION and self.question is not None:
            raise ValueError("local corpus AI question is only valid for question tasks")
        if self.execution is LocalCorpusAIExecution.LOCAL_MODEL:
            if self.model_id is None:
                raise ValueError("local corpus AI model execution requires an explicit model")
            if self.openai_api_key is not None:
                raise ValueError("local corpus AI model execution cannot carry an API key")
        elif self.execution is LocalCorpusAIExecution.OPENAI_RESPONSES:
            if self.model_id is None or self.openai_api_key is None:
                raise ValueError("OpenAI corpus execution requires a model and API key")
        elif self.model_id is not None or self.openai_api_key is not None:
            raise ValueError("deterministic local corpus AI cannot select a model or API key")
        return self


class LocalCorpusAISourcePointer(ApiModel):
    document_id: str = Field(pattern=_DOCUMENT_ID_PATTERN)
    document_name: str = Field(min_length=1, max_length=255, repr=False)
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    segment_index: int = Field(ge=0, le=99_999)
    locator: str = Field(min_length=1, max_length=4_096, repr=False)

    @field_validator("document_name", "locator")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI source", allow_newlines=True)

    @model_validator(mode="after")
    def validate_segment_document_binding(self) -> Self:
        if not self.segment_id.startswith(f"{self.document_id}:segment:"):
            raise ValueError("local corpus AI source binding is invalid")
        if not self.segment_id.endswith(f":{self.segment_index}"):
            raise ValueError("local corpus AI segment index binding is invalid")
        return self


class LocalCorpusAISourceCatalogEntry(ApiModel):
    reference_id: str = Field(min_length=1, max_length=160)
    reference_kind: LocalCorpusAIReferenceKind = Field(strict=False)
    sources: tuple[LocalCorpusAISourcePointer, ...] = Field(min_length=1, max_length=32)

    @field_validator("reference_id")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if _CITABLE_REFERENCE.fullmatch(value) is None:
            raise ValueError("local corpus AI catalog reference is invalid")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(
        cls,
        values: tuple[LocalCorpusAISourcePointer, ...],
    ) -> tuple[LocalCorpusAISourcePointer, ...]:
        if len({item.segment_id for item in values}) != len(values):
            raise ValueError("local corpus AI catalog sources must be unique")
        return values

    @model_validator(mode="after")
    def validate_reference_binding(self) -> Self:
        is_segment = self.reference_kind is LocalCorpusAIReferenceKind.SEGMENT
        if is_segment != self.reference_id.startswith("corpus-document:"):
            raise ValueError("local corpus AI catalog kind is invalid")
        if is_segment and (
            len(self.sources) != 1 or self.sources[0].segment_id != self.reference_id
        ):
            raise ValueError("local corpus AI segment catalog binding is invalid")
        return self


class LocalCorpusAIReviewNote(ApiModel):
    text: str = Field(min_length=1, max_length=600, repr=False)
    label: LocalCorpusAITextLabel = Field(strict=False)
    origin: LocalCorpusAIContentOrigin = Field(strict=False)
    evidence_refs: tuple[str, ...] = Field(max_length=8)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI review note", allow_newlines=True)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_references(values, label="local corpus AI review note")

    @model_validator(mode="after")
    def validate_label_citations(self) -> Self:
        cited = self.label in {
            LocalCorpusAITextLabel.ORGANIZATION,
            LocalCorpusAITextLabel.CITED_SUMMARY,
        }
        if cited and not self.evidence_refs:
            raise ValueError("cited local corpus AI notes require evidence")
        return self


class LocalCorpusAISection(ApiModel):
    heading: str = Field(min_length=1, max_length=96)
    items: tuple[LocalCorpusAIReviewNote, ...] = Field(
        min_length=1,
        max_length=MAX_LOCAL_CORPUS_AI_SECTION_ITEMS,
    )

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI section heading")


class LocalCorpusAIFact(ApiModel):
    statement: str = Field(min_length=1, max_length=600, repr=False)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    confidence: LocalCorpusAIConfidence = Field(strict=False)
    origin: LocalCorpusAIContentOrigin = Field(strict=False)

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI fact", allow_newlines=True)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_references(values, label="local corpus AI fact")


class LocalCorpusAIConnection(ApiModel):
    from_ref: str = Field(min_length=1, max_length=160)
    to_ref: str = Field(min_length=1, max_length=160)
    shared_entity_refs: tuple[str, ...] = Field(min_length=1, max_length=4)
    relationship: str = Field(min_length=1, max_length=96)
    supporting_refs: tuple[str, ...] = Field(min_length=3, max_length=8)
    contradiction_refs: tuple[str, ...] = Field(max_length=8)
    confidence: LocalCorpusAIConfidence = Field(strict=False)
    origin: LocalCorpusAIContentOrigin = Field(strict=False)
    rationale: str = Field(min_length=1, max_length=600, repr=False)
    verification_suggestion: str = Field(min_length=1, max_length=600, repr=False)

    @field_validator("from_ref", "to_ref")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if re.fullmatch(_SEGMENT_ID_PATTERN, value) is None:
            raise ValueError("local corpus AI connection endpoint is invalid")
        return value

    @field_validator("shared_entity_refs")
    @classmethod
    def validate_shared_entities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            re.fullmatch(_ENTITY_ID_PATTERN, value) is None for value in values
        ):
            raise ValueError("local corpus AI shared entities are invalid")
        return values

    @field_validator("supporting_refs", "contradiction_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_references(values, label="local corpus AI connection")

    @field_validator("relationship", "rationale", "verification_suggestion")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI connection", allow_newlines=True)

    @model_validator(mode="after")
    def validate_connection_binding(self) -> Self:
        if self.from_ref == self.to_ref:
            raise ValueError("local corpus AI connection endpoints must differ")
        required = {self.from_ref, self.to_ref, *self.shared_entity_refs}
        if not required.issubset(self.supporting_refs):
            raise ValueError("local corpus AI connection support is incomplete")
        return self


class LocalCorpusAINextStep(ApiModel):
    priority: int = Field(ge=1, le=5)
    suggestion: str = Field(min_length=1, max_length=600, repr=False)
    rationale: str = Field(min_length=1, max_length=600, repr=False)
    supporting_refs: tuple[str, ...] = Field(min_length=1, max_length=8)
    origin: LocalCorpusAIContentOrigin = Field(strict=False)

    @field_validator("suggestion", "rationale")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI next step", allow_newlines=True)

    @field_validator("supporting_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_references(values, label="local corpus AI next step")


class LocalCorpusAICounts(ApiModel):
    documents: int = Field(ge=1, le=20)
    segments: int = Field(ge=1, le=5_000)
    entities: int = Field(ge=0, le=4_096)
    shared_entities: int = Field(ge=0, le=4_096)


class LocalCorpusAIResult(ApiModel):
    profile_id: str
    corpus_id: str = Field(pattern=_CORPUS_ID_PATTERN)
    input_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    input_sha256: str = Field(pattern=_SHA256_PATTERN)
    task: LocalCorpusAITask = Field(strict=False)
    requested_execution: LocalCorpusAIExecution = Field(strict=False)
    execution_mode: LocalCorpusAIExecution = Field(strict=False)
    fallback_reason: LocalCorpusAIFallbackReason | None
    provider: LocalAIProvider | None
    model_id: str | None = Field(default=None, max_length=256)
    engine_version: Literal["1"]
    title: str = Field(min_length=1, max_length=120)
    draft_summary: str = Field(min_length=1, max_length=2_000, repr=False)
    narrative_label: Literal["DRAFT_SUMMARY_NOT_A_FACT"]
    sections: tuple[LocalCorpusAISection, ...] = Field(max_length=MAX_LOCAL_CORPUS_AI_SECTIONS)
    facts: tuple[LocalCorpusAIFact, ...] = Field(max_length=MAX_LOCAL_CORPUS_AI_FACTS)
    connections: tuple[LocalCorpusAIConnection, ...] = Field(
        max_length=MAX_LOCAL_CORPUS_AI_CONNECTIONS
    )
    next_steps: tuple[LocalCorpusAINextStep, ...] = Field(max_length=MAX_LOCAL_CORPUS_AI_NEXT_STEPS)
    unanswered: str | None = Field(default=None, max_length=1_000, repr=False)
    uncertainties: tuple[LocalCorpusAIReviewNote, ...] = Field(
        max_length=MAX_LOCAL_CORPUS_AI_UNCERTAINTIES
    )
    source_catalog: tuple[LocalCorpusAISourceCatalogEntry, ...] = Field(
        max_length=MAX_LOCAL_CORPUS_AI_SOURCE_CATALOG,
        repr=False,
    )
    included_counts: LocalCorpusAICounts
    available_counts: LocalCorpusAICounts
    projection_truncated: bool
    restricted_values_redacted: int = Field(ge=0, le=20_000)
    local_only: bool
    external_network_used: bool
    raw_sources_retained: Literal[False]
    persisted: Literal[False]
    review_only: Literal[True]
    human_review_required: Literal[True]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _safe_text(value, label="local corpus AI title")

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _uuid(value, label="local corpus AI profile id")

    @field_validator("draft_summary", "unanswered")
    @classmethod
    def validate_narrative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_text(value, label="local corpus AI narrative", allow_newlines=True)

    @model_validator(mode="after")
    def validate_result_bindings(self) -> Self:
        complete_identity = self.provider is not None and self.model_id is not None
        if (self.provider is None) != (self.model_id is None):
            raise ValueError("corpus AI provider identity must be complete")
        if self.execution_mode is LocalCorpusAIExecution.LOCAL_MODEL:
            if (
                self.requested_execution is not LocalCorpusAIExecution.LOCAL_MODEL
                or not complete_identity
                or self.provider is LocalAIProvider.OPENAI_RESPONSES
                or self.fallback_reason is not None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("local corpus AI model result requires model identity")
        elif self.execution_mode is LocalCorpusAIExecution.OPENAI_RESPONSES:
            if (
                self.requested_execution is not LocalCorpusAIExecution.OPENAI_RESPONSES
                or self.provider is not LocalAIProvider.OPENAI_RESPONSES
                or not complete_identity
                or self.fallback_reason is not None
                or not self.external_network_used
                or self.local_only
            ):
                raise ValueError("OpenAI corpus result requires external provider identity")
        elif self.requested_execution is LocalCorpusAIExecution.DETERMINISTIC:
            if (
                complete_identity
                or self.fallback_reason is not None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("deterministic local corpus AI cannot be a fallback")
        elif self.requested_execution is LocalCorpusAIExecution.LOCAL_MODEL:
            if (
                complete_identity
                or self.fallback_reason is None
                or self.external_network_used
                or not self.local_only
            ):
                raise ValueError("local corpus AI fallback has invalid provider state")
        elif (
            self.provider is not LocalAIProvider.OPENAI_RESPONSES
            or not complete_identity
            or self.fallback_reason is None
            or not self.external_network_used
            or self.local_only
        ):
            raise ValueError("OpenAI corpus fallback has invalid provider state")

        catalog = {entry.reference_id for entry in self.source_catalog}
        if len(catalog) != len(self.source_catalog):
            raise ValueError("local corpus AI source catalog references must be unique")
        cited: set[str] = set()
        for section in self.sections:
            for item in section.items:
                cited.update(item.evidence_refs)
        for fact in self.facts:
            cited.update(fact.evidence_refs)
        for connection in self.connections:
            cited.update((connection.from_ref, connection.to_ref))
            cited.update(connection.shared_entity_refs)
            cited.update(connection.supporting_refs)
            cited.update(connection.contradiction_refs)
        for step in self.next_steps:
            cited.update(step.supporting_refs)
        for uncertainty in self.uncertainties:
            cited.update(uncertainty.evidence_refs)
        if not cited.issubset(catalog):
            raise ValueError("local corpus AI citation is missing source provenance")
        return self
