"""Strict wire contracts for ephemeral multi-document local corpus operations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel

MAX_LOCAL_CORPUS_DOCUMENTS = 20
MAX_LOCAL_CORPUS_DOCUMENT_BYTES = 1_048_576
MAX_LOCAL_CORPUS_TOTAL_BYTES = 4 * 1024 * 1024
MAX_LOCAL_CORPUS_FILE_BASE64_CHARACTERS = ((MAX_LOCAL_CORPUS_DOCUMENT_BYTES + 2) // 3) * 4
MAX_LOCAL_CORPUS_QUERY_CHARACTERS = 512
MAX_LOCAL_CORPUS_SEARCH_RESULTS = 100
MAX_LOCAL_CORPUS_API_REQUEST_BYTES = 5_750_000
MAX_LOCAL_CORPUS_API_RESPONSE_BYTES = 256_000

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CORPUS_ID_PATTERN = r"^corpus:[0-9a-f]{64}$"
_DOCUMENT_ID_PATTERN = r"^corpus-document:[0-9]{4}:[0-9a-f]{64}$"
_SEGMENT_ID_PATTERN = r"^corpus-document:[0-9]{4}:[0-9a-f]{64}:segment:[0-9]{1,5}$"


class LocalCorpusMediaType(StrEnum):
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"
    X_MARKDOWN = "text/x-markdown"
    CSV = "text/csv"
    JSON = "application/json"
    VCARD = "text/vcard"
    X_VCARD = "text/x-vcard"


_MEDIA_BY_SUFFIX: dict[str, frozenset[LocalCorpusMediaType]] = {
    ".txt": frozenset({LocalCorpusMediaType.TEXT}),
    ".md": frozenset({LocalCorpusMediaType.MARKDOWN, LocalCorpusMediaType.X_MARKDOWN}),
    ".csv": frozenset({LocalCorpusMediaType.CSV}),
    ".json": frozenset({LocalCorpusMediaType.JSON}),
    ".vcf": frozenset({LocalCorpusMediaType.VCARD, LocalCorpusMediaType.X_VCARD}),
}


class LocalCorpusDocumentRequest(ApiModel):
    display_name: str = Field(min_length=1, max_length=255, repr=False)
    declared_media_type: LocalCorpusMediaType = Field(strict=False)
    content_base64: str = Field(
        min_length=4,
        max_length=MAX_LOCAL_CORPUS_FILE_BASE64_CHARACTERS,
        repr=False,
    )
    expected_size_bytes: int = Field(ge=1, le=MAX_LOCAL_CORPUS_DOCUMENT_BYTES)
    expected_sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        if (
            value != value.strip()
            or value != Path(value).name
            or "/" in value
            or "\\" in value
            or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)
        ):
            raise ValueError("local corpus document name is invalid")
        return value

    @model_validator(mode="after")
    def validate_document_binding(self) -> Self:
        accepted_media = _MEDIA_BY_SUFFIX.get(Path(self.display_name).suffix.casefold())
        if accepted_media is None or self.declared_media_type not in accepted_media:
            raise ValueError("local corpus document type binding is invalid")
        content = _decode_canonical_base64(self.content_base64)
        if len(content) != self.expected_size_bytes or not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(),
            self.expected_sha256,
        ):
            raise ValueError("local corpus document content binding is invalid")
        return self

    def decoded_content(self) -> bytes:
        """Decode already-validated content without retaining a second representation."""

        return _decode_canonical_base64(self.content_base64)


class LocalCorpusDocumentsRequest(ApiModel):
    documents: tuple[LocalCorpusDocumentRequest, ...] = Field(
        min_length=1,
        max_length=MAX_LOCAL_CORPUS_DOCUMENTS,
        repr=False,
        strict=False,
    )
    semantic_enrichment_enabled: bool = True

    @model_validator(mode="after")
    def validate_batch_bounds(self) -> Self:
        if sum(item.expected_size_bytes for item in self.documents) > (
            MAX_LOCAL_CORPUS_TOTAL_BYTES
        ):
            raise ValueError("local corpus aggregate byte limit exceeded")
        return self

    @property
    def input_manifest_sha256(self) -> str:
        manifest = [
            {
                "displayName": item.display_name,
                "mediaType": item.declared_media_type.value,
                "sha256": item.expected_sha256,
                "sizeBytes": item.expected_size_bytes,
            }
            for item in self.documents
        ]
        canonical = json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class LocalCorpusSearchRequest(LocalCorpusDocumentsRequest):
    query: str = Field(
        min_length=1,
        max_length=MAX_LOCAL_CORPUS_QUERY_CHARACTERS,
        repr=False,
    )
    limit: int = Field(default=50, ge=1, le=MAX_LOCAL_CORPUS_SEARCH_RESULTS)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if value != value.strip() or any(
            unicodedata.category(character) in {"Cc", "Cs"} for character in value
        ):
            raise ValueError("local corpus query is invalid")
        try:
            encoded = value.encode()
        except UnicodeEncodeError:
            raise ValueError("local corpus query is invalid") from None
        if len(encoded) > 2_048:
            raise ValueError("local corpus query is invalid")
        return value


class LocalCorpusProjectionRequest(LocalCorpusDocumentsRequest):
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_LOCAL_CORPUS_QUERY_CHARACTERS,
        repr=False,
    )
    max_segments: int = Field(default=200, ge=1, le=500)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return LocalCorpusSearchRequest.validate_query(value)


class LocalCorpusSummaryResult(ApiModel):
    corpus_id: str = Field(pattern=_CORPUS_ID_PATTERN)
    input_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    document_count: int = Field(ge=1, le=MAX_LOCAL_CORPUS_DOCUMENTS)
    segment_count: int = Field(ge=1, le=5_000)
    entity_count: int = Field(ge=0, le=4_096)
    restricted_values_redacted: int = Field(ge=0, le=20_000)
    local_only: Literal[True]
    raw_sources_retained: Literal[False]


class LocalCorpusSearchHitResult(ApiModel):
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    document_id: str = Field(pattern=_DOCUMENT_ID_PATTERN)
    document_name: str = Field(min_length=1, max_length=255, repr=False)
    segment_index: int = Field(ge=0, le=99_999)
    locator: str = Field(min_length=1, max_length=4_096, repr=False)
    score: int = Field(ge=1, le=2_300_000)
    matched_terms: tuple[str, ...] = Field(min_length=1, max_length=128, repr=False)
    excerpt: str = Field(min_length=1, max_length=322, repr=False)

    @field_validator("matched_terms")
    @classmethod
    def validate_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            not value or len(value) > 512 or value != value.strip() for value in values
        ):
            raise ValueError("local corpus matched terms are invalid")
        return values


class LocalCorpusSearchResult(LocalCorpusSummaryResult):
    query: str = Field(min_length=1, max_length=MAX_LOCAL_CORPUS_QUERY_CHARACTERS, repr=False)
    hits: tuple[LocalCorpusSearchHitResult, ...] = Field(
        max_length=MAX_LOCAL_CORPUS_SEARCH_RESULTS,
        repr=False,
    )


class LocalCorpusProjectionResult(LocalCorpusSummaryResult):
    input_sha256: str = Field(pattern=_SHA256_PATTERN)
    references: tuple[str, ...] = Field(min_length=1, max_length=720)
    included_document_count: int = Field(ge=0, le=MAX_LOCAL_CORPUS_DOCUMENTS)
    included_segment_count: int = Field(ge=0, le=500)
    included_entity_count: int = Field(ge=0, le=4_096)
    truncated: bool

    @field_validator("references")
    @classmethod
    def validate_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            not value
            or len(value) > 160
            or value != value.strip()
            or any(ord(character) < 33 or ord(character) == 127 for character in value)
            for value in values
        ):
            raise ValueError("local corpus projection references are invalid")
        return values


def _decode_canonical_base64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("local corpus document encoding is invalid") from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("local corpus document encoding is invalid")
    return decoded
