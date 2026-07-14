"""Strict wire schemas for bounded, explicitly authorised public discovery."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from ariadne_core.api.schemas import ApiModel
from ariadne_core.domain.public_discovery import (
    HARD_MAX_DISCOVERY_QUERY_BYTES,
    HARD_MAX_DISCOVERY_RESULTS,
    MAX_DISCOVERY_RESULT_URL_CHARS,
    MAX_DISCOVERY_SNIPPET_CHARS,
    MAX_DISCOVERY_TITLE_CHARS,
    PublicDiscoveryProvider,
    PublicDiscoveryReason,
    PublicDiscoveryRequest,
    PublicDiscoveryResponse,
    PublicDiscoveryState,
    normalise_discovery_query,
)
from ariadne_core.domain.query_policy import Sensitivity


class PublicDiscoverySearchRequest(ApiModel):
    provider: PublicDiscoveryProvider = Field(strict=False)
    query: str = Field(min_length=1, max_length=HARD_MAX_DISCOVERY_QUERY_BYTES, repr=False)
    authorized_self_audit: bool
    max_results: int = Field(default=10, ge=1, le=HARD_MAX_DISCOVERY_RESULTS)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return normalise_discovery_query(value)

    def to_domain(self, *, sensitivity: Sensitivity) -> PublicDiscoveryRequest:
        """Bind server-derived sensitivity; never trust a client sensitivity assertion."""

        return PublicDiscoveryRequest(
            provider=self.provider,
            query=self.query,
            sensitivity=sensitivity,
            authorized_self_audit=self.authorized_self_audit,
            max_results=self.max_results,
        )


class PublicDiscoveryResultItem(ApiModel):
    provider: PublicDiscoveryProvider = Field(
        strict=False,
        description="Exact provider that returned this normalized public result.",
    )
    rank: int = Field(ge=1, le=HARD_MAX_DISCOVERY_RESULTS)
    title: str = Field(min_length=1, max_length=MAX_DISCOVERY_TITLE_CHARS)
    url: str = Field(
        min_length=1,
        max_length=MAX_DISCOVERY_RESULT_URL_CHARS,
        description="Normalized public result URL preserved for structured provenance.",
    )
    snippet: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DISCOVERY_SNIPPET_CHARS,
    )
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        description="Provider source identifier when one is supplied.",
    )


class PublicDiscoverySearchResult(ApiModel):
    provider: PublicDiscoveryProvider = Field(strict=False)
    state: PublicDiscoveryState = Field(strict=False)
    reason: PublicDiscoveryReason = Field(strict=False)
    results: tuple[PublicDiscoveryResultItem, ...] = Field(max_length=HARD_MAX_DISCOVERY_RESULTS)
    total_estimate: int | None = Field(default=None, ge=0, le=1_000_000_000)
    rate_limit_remaining: int | None = Field(default=None, ge=0, le=1_000_000_000)
    truncated: bool
    external_request_made: bool
    authorization_confirmed: bool
    human_review_required: Literal[True]

    @classmethod
    def from_domain(cls, response: PublicDiscoveryResponse) -> PublicDiscoverySearchResult:
        return cls(
            provider=response.provider,
            state=response.state,
            reason=response.reason,
            results=tuple(
                PublicDiscoveryResultItem(
                    provider=item.provider,
                    rank=item.rank,
                    title=item.title,
                    url=item.url,
                    snippet=item.snippet,
                    source_id=item.source_id,
                )
                for item in response.results
            ),
            total_estimate=response.total_estimate,
            rate_limit_remaining=response.rate_limit_remaining,
            truncated=response.truncated,
            external_request_made=response.external_request_made,
            authorization_confirmed=response.authorization_confirmed,
            human_review_required=True,
        )
