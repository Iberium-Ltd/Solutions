"""Strict contracts for retaining one reviewed public-discovery result."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel, _canonical_uuid
from ariadne_core.domain.evidence_artifacts import MAX_TIMESTAMP_US
from ariadne_core.domain.public_discovery import (
    HARD_MAX_DISCOVERY_QUERY_BYTES,
    HARD_MAX_DISCOVERY_RESULTS,
    MAX_DISCOVERY_RESULT_URL_CHARS,
    MAX_DISCOVERY_SNIPPET_CHARS,
    MAX_DISCOVERY_TITLE_CHARS,
    PublicDiscoveryProvider,
    PublicDiscoveryResult,
    normalise_discovery_query,
    normalise_public_result_url,
    normalise_result_text,
)


class PublicDiscoveryCaptureRequest(ApiModel):
    """One exact provider result explicitly reviewed for local retention."""

    profile_id: str
    provider: PublicDiscoveryProvider = Field(strict=False)
    query: str = Field(min_length=1, max_length=HARD_MAX_DISCOVERY_QUERY_BYTES, repr=False)
    rank: int = Field(ge=1, le=HARD_MAX_DISCOVERY_RESULTS)
    title: str = Field(min_length=1, max_length=MAX_DISCOVERY_TITLE_CHARS, repr=False)
    url: str = Field(min_length=1, max_length=MAX_DISCOVERY_RESULT_URL_CHARS, repr=False)
    snippet: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DISCOVERY_SNIPPET_CHARS,
        repr=False,
    )
    source_id: str | None = Field(default=None, min_length=1, max_length=160, repr=False)
    captured_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    authorized_self_audit: Literal[True]

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return normalise_discovery_query(value)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalised = normalise_result_text(
            value,
            maximum=MAX_DISCOVERY_TITLE_CHARS,
            required=True,
        )
        if normalised is None:
            raise ValueError("public discovery title is invalid")
        return normalised

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise ValueError("public discovery result URL is invalid") from error
        if parsed.fragment:
            raise ValueError("public discovery result URL fragments are forbidden")
        return normalise_public_result_url(value)

    @field_validator("snippet")
    @classmethod
    def validate_snippet(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalise_result_text(
            value,
            maximum=MAX_DISCOVERY_SNIPPET_CHARS,
            required=True,
        )

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalise_result_text(value, maximum=160, required=True)

    @model_validator(mode="after")
    def validate_result_binding(self) -> PublicDiscoveryCaptureRequest:
        PublicDiscoveryResult(
            provider=self.provider,
            rank=self.rank,
            title=self.title,
            url=self.url,
            snippet=self.snippet,
            source_id=self.source_id,
        )
        return self


class PublicDiscoveryCaptureResult(ApiModel):
    profile_id: str
    finding_id: str
    artifact_id: str
    provider: PublicDiscoveryProvider = Field(strict=False)
    rank: int = Field(ge=1, le=HARD_MAX_DISCOVERY_RESULTS)
    source_id: str | None = Field(default=None, min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=MAX_DISCOVERY_RESULT_URL_CHARS)
    url_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_reference: str = Field(pattern=r"^mq_[0-9a-f]{64}$", repr=False)
    captured_at_us: int = Field(ge=1, le=MAX_TIMESTAMP_US)
    evidence_kind: Literal["URL_REFERENCE"]
    encrypted_at_rest: Literal[True]
    local_only: Literal[True]
    deduplicated: bool

    @field_validator("profile_id", "finding_id", "artifact_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if urlsplit(value).fragment:
            raise ValueError("captured public discovery URL contains a fragment")
        if normalise_public_result_url(value) != value:
            raise ValueError("captured public discovery URL is not normalized")
        return value
