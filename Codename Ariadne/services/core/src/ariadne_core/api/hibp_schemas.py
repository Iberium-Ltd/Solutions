"""Strict wire schemas for ephemeral, authorised HIBP v3 self-audits."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from ariadne_core.api.schemas import ApiModel
from ariadne_core.domain.hibp import (
    HARD_MAX_HIBP_BREACHES,
    HARD_MAX_HIBP_DOMAIN_ACCOUNTS,
    MAX_HIBP_ALIAS_CHARS,
    MAX_HIBP_BREACH_NAME_CHARS,
    MAX_HIBP_RETRY_AFTER_SECONDS,
    HibpAccountMode,
    HibpAccountSearchRequest,
    HibpAccountSearchResponse,
    HibpDomainSearchRequest,
    HibpDomainSearchResponse,
    HibpIdentifierDisclosure,
    HibpOperation,
    HibpProvider,
    HibpReason,
    HibpState,
    normalise_hibp_domain,
    normalise_hibp_email,
    validate_hibp_api_key,
)


class HibpAccountRequest(ApiModel):
    email: str = Field(min_length=3, max_length=254, repr=False)
    api_key: SecretStr = Field(min_length=32, max_length=32, repr=False)
    mode: HibpAccountMode = Field(default=HibpAccountMode.K_ANONYMITY, strict=False)
    authorized_self_audit: bool
    authorized_direct_identifier_transmission: bool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalise_hibp_email(value)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        validate_hibp_api_key(value.get_secret_value())
        return value

    def to_domain(self) -> HibpAccountSearchRequest:
        return HibpAccountSearchRequest(
            email=self.email,
            api_key=self.api_key.get_secret_value(),
            mode=self.mode,
            authorized_self_audit=self.authorized_self_audit,
            authorized_direct_identifier_transmission=(
                self.authorized_direct_identifier_transmission
            ),
        )


class HibpDomainRequest(ApiModel):
    domain: str = Field(min_length=3, max_length=253, repr=False)
    api_key: SecretStr = Field(min_length=32, max_length=32, repr=False)
    authorized_self_audit: bool

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalise_hibp_domain(value)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        validate_hibp_api_key(value.get_secret_value())
        return value

    def to_domain(self) -> HibpDomainSearchRequest:
        return HibpDomainSearchRequest(
            domain=self.domain,
            api_key=self.api_key.get_secret_value(),
            authorized_self_audit=self.authorized_self_audit,
        )


class HibpRequestMetadataItem(ApiModel):
    sequence: int = Field(ge=1, le=2)
    operation: HibpOperation = Field(strict=False)
    method: Literal["GET"]
    request_url: str = Field(min_length=1, max_length=2_048)
    endpoint_host: Literal["haveibeenpwned.com"]
    identifier_disclosure: HibpIdentifierDisclosure = Field(strict=False)
    request_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    http_status: int | None = Field(default=None, ge=100, le=599)
    response_bytes: int = Field(ge=0, le=1_048_576)
    observed_at: datetime
    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
        le=MAX_HIBP_RETRY_AFTER_SECONDS,
    )
    api_key_sent: Literal[True]
    redirects_followed: Literal[False]


class HibpBreachReferenceItem(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_HIBP_BREACH_NAME_CHARS)
    source_url: str = Field(
        min_length=1,
        max_length=2_048,
        description="Canonical HIBP v3 breach endpoint for this exact stable breach name.",
    )


class HibpDomainAccountItem(ApiModel):
    alias: str = Field(min_length=1, max_length=MAX_HIBP_ALIAS_CHARS)
    breaches: tuple[HibpBreachReferenceItem, ...] = Field(max_length=HARD_MAX_HIBP_BREACHES)


class _HibpResultBase(ApiModel):
    provider: HibpProvider = Field(strict=False)
    provider_home_url: Literal["https://haveibeenpwned.com/"]
    api_documentation_url: Literal["https://haveibeenpwned.com/API/v3"]
    attribution: Literal["Have I Been Pwned"]
    license: Literal["CC BY 4.0"]
    state: HibpState = Field(strict=False)
    reason: HibpReason = Field(strict=False)
    requests: tuple[HibpRequestMetadataItem, ...] = Field(max_length=2)
    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
        le=MAX_HIBP_RETRY_AFTER_SECONDS,
    )
    external_request_made: bool
    authorization_confirmed: bool
    human_review_required: Literal[True]


class HibpAccountResult(_HibpResultBase):
    mode: HibpAccountMode = Field(strict=False)
    breaches: tuple[HibpBreachReferenceItem, ...] = Field(max_length=HARD_MAX_HIBP_BREACHES)
    direct_transmission_authorized: bool

    @classmethod
    def from_domain(cls, response: HibpAccountSearchResponse) -> HibpAccountResult:
        return cls(
            provider=response.provider,
            provider_home_url="https://haveibeenpwned.com/",
            api_documentation_url="https://haveibeenpwned.com/API/v3",
            attribution="Have I Been Pwned",
            license="CC BY 4.0",
            mode=response.mode,
            state=response.state,
            reason=response.reason,
            breaches=tuple(
                HibpBreachReferenceItem(name=item.name, source_url=item.source_url)
                for item in response.breaches
            ),
            requests=tuple(_request_metadata(item) for item in response.requests),
            retry_after_seconds=response.retry_after_seconds,
            external_request_made=response.external_request_made,
            authorization_confirmed=response.authorization_confirmed,
            direct_transmission_authorized=response.direct_transmission_authorized,
            human_review_required=True,
        )


class HibpDomainResult(_HibpResultBase):
    accounts: tuple[HibpDomainAccountItem, ...] = Field(max_length=HARD_MAX_HIBP_DOMAIN_ACCOUNTS)
    provider_verified_domain: bool
    truncated: bool

    @classmethod
    def from_domain(cls, response: HibpDomainSearchResponse) -> HibpDomainResult:
        return cls(
            provider=response.provider,
            provider_home_url="https://haveibeenpwned.com/",
            api_documentation_url="https://haveibeenpwned.com/API/v3",
            attribution="Have I Been Pwned",
            license="CC BY 4.0",
            state=response.state,
            reason=response.reason,
            accounts=tuple(
                HibpDomainAccountItem(
                    alias=account.alias,
                    breaches=tuple(
                        HibpBreachReferenceItem(name=item.name, source_url=item.source_url)
                        for item in account.breaches
                    ),
                )
                for account in response.accounts
            ),
            requests=tuple(_request_metadata(item) for item in response.requests),
            retry_after_seconds=response.retry_after_seconds,
            provider_verified_domain=response.provider_verified_domain,
            truncated=response.truncated,
            external_request_made=response.external_request_made,
            authorization_confirmed=response.authorization_confirmed,
            human_review_required=True,
        )


def _request_metadata(item: object) -> HibpRequestMetadataItem:
    from ariadne_core.domain.hibp import HibpRequestMetadata

    if not isinstance(item, HibpRequestMetadata):
        raise ValueError("HIBP request metadata is invalid")
    return HibpRequestMetadataItem(
        sequence=item.sequence,
        operation=item.operation,
        method="GET",
        request_url=item.request_url,
        endpoint_host="haveibeenpwned.com",
        identifier_disclosure=item.identifier_disclosure,
        request_sha256=item.request_sha256,
        http_status=item.http_status,
        response_bytes=item.response_bytes,
        observed_at=item.observed_at,
        retry_after_seconds=item.retry_after_seconds,
        api_key_sent=True,
        redirects_followed=False,
    )
