"""Strict primitives for authorised Have I Been Pwned v3 self-audits."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from urllib.parse import quote, urlsplit

HIBP_API_HOST = "haveibeenpwned.com"
HIBP_API_BASE_URL = f"https://{HIBP_API_HOST}/api/v3"
HIBP_HOME_URL = "https://haveibeenpwned.com/"
HIBP_API_DOCUMENTATION_URL = "https://haveibeenpwned.com/API/v3"
HIBP_ATTRIBUTION = "Have I Been Pwned"
HIBP_LICENSE = "CC BY 4.0"
HIBP_USER_AGENT = "Codename-Ariadne/0.1 authorised-self-audit"

HARD_MAX_HIBP_RESPONSE_BYTES = 1_048_576
HARD_MAX_HIBP_TIMEOUT_SECONDS = 20.0
HARD_MAX_HIBP_BREACHES = 1_024
HARD_MAX_HIBP_DOMAIN_ACCOUNTS = 2_000
MAX_HIBP_BREACH_NAME_CHARS = 160
MAX_HIBP_ALIAS_CHARS = 160
MAX_HIBP_RETRY_AFTER_SECONDS = 86_400

_API_KEY = re.compile(r"^[0-9A-Fa-f]{32}$", re.ASCII)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.ASCII)


class HibpProvider(StrEnum):
    HAVE_I_BEEN_PWNED_V3 = "HAVE_I_BEEN_PWNED_V3"


class HibpAccountMode(StrEnum):
    K_ANONYMITY = "K_ANONYMITY"
    DIRECT = "DIRECT"


class HibpOperation(StrEnum):
    EMAIL_K_ANONYMITY = "EMAIL_K_ANONYMITY"
    EMAIL_DIRECT = "EMAIL_DIRECT"
    VERIFY_SUBSCRIBED_DOMAIN = "VERIFY_SUBSCRIBED_DOMAIN"
    DOMAIN_ENUMERATION = "DOMAIN_ENUMERATION"


class HibpState(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    SUCCEEDED = "SUCCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    FAILED = "FAILED"


class HibpReason(StrEnum):
    COMPLETE = "COMPLETE"
    NO_RESULTS = "NO_RESULTS"
    PARTIAL_RESULTS = "PARTIAL_RESULTS"
    SELF_AUDIT_AUTHORIZATION_REQUIRED = "SELF_AUDIT_AUTHORIZATION_REQUIRED"
    DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED = "DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED"
    DOMAIN_NOT_PROVIDER_VERIFIED = "DOMAIN_NOT_PROVIDER_VERIFIED"
    INVALID_API_KEY = "INVALID_API_KEY"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    REDIRECT_REFUSED = "REDIRECT_REFUSED"
    UPSTREAM_ACCESS_BLOCKED = "UPSTREAM_ACCESS_BLOCKED"
    TIMEOUT = "TIMEOUT"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class HibpIdentifierDisclosure(StrEnum):
    PARTIAL_SHA1_PREFIX = "PARTIAL_SHA1_PREFIX"
    DIRECT_EMAIL = "DIRECT_EMAIL"
    DIRECT_DOMAIN = "DIRECT_DOMAIN"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class HibpLimits:
    timeout_seconds: float = 10.0
    max_response_bytes: int = HARD_MAX_HIBP_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= HARD_MAX_HIBP_TIMEOUT_SECONDS
        ):
            raise ValueError("HIBP timeout is invalid")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= HARD_MAX_HIBP_RESPONSE_BYTES
        ):
            raise ValueError("HIBP response limit is invalid")


@dataclass(frozen=True, slots=True)
class HibpAccountSearchRequest:
    email: str = field(repr=False)
    api_key: str = field(repr=False)
    mode: HibpAccountMode
    authorized_self_audit: bool
    authorized_direct_identifier_transmission: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalise_hibp_email(self.email))
        object.__setattr__(self, "api_key", validate_hibp_api_key(self.api_key))
        if not isinstance(self.mode, HibpAccountMode):
            raise ValueError("HIBP account mode is invalid")
        if (
            type(self.authorized_self_audit) is not bool
            or type(self.authorized_direct_identifier_transmission) is not bool
        ):
            raise ValueError("HIBP authorization is invalid")


@dataclass(frozen=True, slots=True)
class HibpDomainSearchRequest:
    domain: str = field(repr=False)
    api_key: str = field(repr=False)
    authorized_self_audit: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", normalise_hibp_domain(self.domain))
        object.__setattr__(self, "api_key", validate_hibp_api_key(self.api_key))
        if type(self.authorized_self_audit) is not bool:
            raise ValueError("HIBP authorization is invalid")


@dataclass(frozen=True, slots=True)
class HibpRequestMetadata:
    sequence: int
    operation: HibpOperation
    method: str
    request_url: str
    endpoint_host: str
    identifier_disclosure: HibpIdentifierDisclosure
    request_sha256: str
    http_status: int | None
    response_bytes: int
    observed_at: datetime
    retry_after_seconds: int | None = None
    api_key_sent: bool = True
    redirects_followed: bool = False

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or not 1 <= self.sequence <= 2:
            raise ValueError("HIBP request sequence is invalid")
        if not isinstance(self.operation, HibpOperation):
            raise ValueError("HIBP operation is invalid")
        if self.method != "GET":
            raise ValueError("HIBP request method is invalid")
        _validate_hibp_request_url(self.request_url)
        if self.endpoint_host != HIBP_API_HOST:
            raise ValueError("HIBP endpoint host is invalid")
        if not isinstance(self.identifier_disclosure, HibpIdentifierDisclosure):
            raise ValueError("HIBP disclosure metadata is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", self.request_sha256, re.ASCII):
            raise ValueError("HIBP request reference is invalid")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("HIBP response status is invalid")
        if (
            type(self.response_bytes) is not int
            or not 0 <= self.response_bytes <= HARD_MAX_HIBP_RESPONSE_BYTES
        ):
            raise ValueError("HIBP response size is invalid")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("HIBP observation timestamp is invalid")
        if self.retry_after_seconds is not None and (
            type(self.retry_after_seconds) is not int
            or not 0 <= self.retry_after_seconds <= MAX_HIBP_RETRY_AFTER_SECONDS
        ):
            raise ValueError("HIBP retry metadata is invalid")
        if not self.api_key_sent or self.redirects_followed:
            raise ValueError("HIBP credential or redirect metadata is invalid")


@dataclass(frozen=True, slots=True)
class HibpBreachReference:
    name: str
    source_url: str

    def __post_init__(self) -> None:
        if normalise_hibp_breach_name(self.name) != self.name:
            raise ValueError("HIBP breach reference is invalid")
        expected = f"{HIBP_API_BASE_URL}/breach/{quote(self.name, safe='')}"
        if self.source_url != expected:
            raise ValueError("HIBP breach source is invalid")


@dataclass(frozen=True, slots=True)
class HibpDomainAccount:
    alias: str
    breaches: tuple[HibpBreachReference, ...]

    def __post_init__(self) -> None:
        if normalise_hibp_alias(self.alias) != self.alias:
            raise ValueError("HIBP domain alias is invalid")
        if len(self.breaches) > HARD_MAX_HIBP_BREACHES:
            raise ValueError("HIBP domain breach count is invalid")


@dataclass(frozen=True, slots=True)
class HibpAccountSearchResponse:
    mode: HibpAccountMode
    state: HibpState
    reason: HibpReason
    breaches: tuple[HibpBreachReference, ...] = ()
    requests: tuple[HibpRequestMetadata, ...] = ()
    retry_after_seconds: int | None = None
    external_request_made: bool = False
    authorization_confirmed: bool = False
    direct_transmission_authorized: bool = False
    human_review_required: bool = True
    provider: HibpProvider = HibpProvider.HAVE_I_BEEN_PWNED_V3

    def __post_init__(self) -> None:
        _validate_response_state(
            state=self.state,
            reason=self.reason,
            request_count=len(self.requests),
            retry_after_seconds=self.retry_after_seconds,
            external_request_made=self.external_request_made,
            authorization_confirmed=self.authorization_confirmed,
        )
        if not isinstance(self.mode, HibpAccountMode):
            raise ValueError("HIBP account response mode is invalid")
        if len(self.breaches) > HARD_MAX_HIBP_BREACHES:
            raise ValueError("HIBP account breach count is invalid")
        if self.state is not HibpState.SUCCEEDED and self.breaches:
            raise ValueError("HIBP non-success response cannot contain breaches")
        if self.mode is HibpAccountMode.K_ANONYMITY and self.direct_transmission_authorized:
            raise ValueError("HIBP k-anonymity response cannot claim direct transmission")
        if (
            self.mode is HibpAccountMode.DIRECT
            and self.external_request_made
            and not (self.direct_transmission_authorized)
        ):
            raise ValueError("HIBP direct dispatch requires explicit authorization")
        if type(self.direct_transmission_authorized) is not bool:
            raise ValueError("HIBP direct authorization metadata is invalid")


@dataclass(frozen=True, slots=True)
class HibpDomainSearchResponse:
    state: HibpState
    reason: HibpReason
    accounts: tuple[HibpDomainAccount, ...] = ()
    requests: tuple[HibpRequestMetadata, ...] = ()
    retry_after_seconds: int | None = None
    provider_verified_domain: bool = False
    truncated: bool = False
    external_request_made: bool = False
    authorization_confirmed: bool = False
    human_review_required: bool = True
    provider: HibpProvider = HibpProvider.HAVE_I_BEEN_PWNED_V3

    def __post_init__(self) -> None:
        _validate_response_state(
            state=self.state,
            reason=self.reason,
            request_count=len(self.requests),
            retry_after_seconds=self.retry_after_seconds,
            external_request_made=self.external_request_made,
            authorization_confirmed=self.authorization_confirmed,
        )
        if len(self.requests) > 2 or len(self.accounts) > HARD_MAX_HIBP_DOMAIN_ACCOUNTS:
            raise ValueError("HIBP domain response count is invalid")
        if self.state is not HibpState.SUCCEEDED and self.accounts:
            raise ValueError("HIBP non-success response cannot contain accounts")
        if self.accounts and not self.provider_verified_domain:
            raise ValueError("HIBP domain results require provider verification")
        if self.state is HibpState.SUCCEEDED and not self.provider_verified_domain:
            raise ValueError("HIBP domain success requires provider verification")
        if self.truncated and self.state is not HibpState.SUCCEEDED:
            raise ValueError("HIBP domain truncation state is invalid")
        if any(
            type(value) is not bool for value in (self.provider_verified_domain, self.truncated)
        ):
            raise ValueError("HIBP domain response flag is invalid")


def validate_hibp_api_key(value: str) -> str:
    if not isinstance(value, str) or _API_KEY.fullmatch(value) is None:
        raise ValueError("HIBP API key is invalid")
    return value


def normalise_hibp_email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("HIBP email is invalid")
    normalised = unicodedata.normalize("NFKC", value).strip().casefold()
    if (
        not normalised
        or len(normalised.encode("utf-8")) > 254
        or normalised.count("@") != 1
        or any(character.isspace() or _is_control(character) for character in normalised)
    ):
        raise ValueError("HIBP email is invalid")
    local, domain = normalised.rsplit("@", 1)
    if (
        not local
        or len(local.encode("utf-8")) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
    ):
        raise ValueError("HIBP email is invalid")
    return f"{local}@{normalise_hibp_domain(domain)}"


def normalise_hibp_domain(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("HIBP domain is invalid")
    candidate = unicodedata.normalize("NFKC", value).strip().rstrip(".").casefold()
    if (
        not candidate
        or len(candidate) > 253
        or any(character.isspace() or _is_control(character) for character in candidate)
    ):
        raise ValueError("HIBP domain is invalid")
    try:
        domain = candidate.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("HIBP domain is invalid") from error
    labels = domain.split(".")
    if len(labels) < 2 or any(_HOST_LABEL.fullmatch(label) is None for label in labels):
        raise ValueError("HIBP domain is invalid")
    return domain


def normalise_hibp_breach_name(value: object) -> str:
    return _normalise_provider_text(
        value,
        maximum=MAX_HIBP_BREACH_NAME_CHARS,
        message="HIBP breach name is invalid",
    )


def normalise_hibp_alias(value: object) -> str:
    alias = _normalise_provider_text(
        value,
        maximum=MAX_HIBP_ALIAS_CHARS,
        message="HIBP domain alias is invalid",
    )
    if "@" in alias:
        raise ValueError("HIBP domain alias is invalid")
    return alias


def hibp_breach_reference(name: object) -> HibpBreachReference:
    normalised = normalise_hibp_breach_name(name)
    return HibpBreachReference(
        name=normalised,
        source_url=f"{HIBP_API_BASE_URL}/breach/{quote(normalised, safe='')}",
    )


def _normalise_provider_text(value: object, *, maximum: int, message: str) -> str:
    if not isinstance(value, str):
        raise ValueError(message)
    normalised = unicodedata.normalize("NFKC", value)
    if (
        not normalised
        or len(normalised) > maximum
        or normalised != normalised.strip()
        or any(_is_control(character) for character in normalised)
    ):
        raise ValueError(message)
    return normalised


def _validate_hibp_request_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise ValueError("HIBP request URL is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != HIBP_API_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
        or not parsed.path.startswith("/api/v3/")
        or len(value) > 2_048
    ):
        raise ValueError("HIBP request URL is invalid")


def _validate_response_state(
    *,
    state: HibpState,
    reason: HibpReason,
    request_count: int,
    retry_after_seconds: int | None,
    external_request_made: bool,
    authorization_confirmed: bool,
) -> None:
    allowed = {
        HibpState.NOT_CHECKED: {
            HibpReason.SELF_AUDIT_AUTHORIZATION_REQUIRED,
            HibpReason.DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED,
        },
        HibpState.SUCCEEDED: {
            HibpReason.COMPLETE,
            HibpReason.NO_RESULTS,
            HibpReason.PARTIAL_RESULTS,
        },
        HibpState.RATE_LIMITED: {HibpReason.UPSTREAM_RATE_LIMITED},
        HibpState.ACCESS_BLOCKED: {
            HibpReason.DOMAIN_NOT_PROVIDER_VERIFIED,
            HibpReason.INVALID_API_KEY,
            HibpReason.REDIRECT_REFUSED,
            HibpReason.UPSTREAM_ACCESS_BLOCKED,
        },
        HibpState.FAILED: {
            HibpReason.TIMEOUT,
            HibpReason.RESPONSE_LIMIT,
            HibpReason.NETWORK_UNAVAILABLE,
            HibpReason.UPSTREAM_UNAVAILABLE,
            HibpReason.UPSTREAM_REJECTED,
            HibpReason.INVALID_RESPONSE,
        },
    }
    if not isinstance(state, HibpState) or not isinstance(reason, HibpReason):
        raise ValueError("HIBP response state is invalid")
    if reason not in allowed[state]:
        raise ValueError("HIBP response state reason is invalid")
    if request_count < 0 or request_count > 2:
        raise ValueError("HIBP request metadata count is invalid")
    if external_request_made != (request_count > 0):
        raise ValueError("HIBP dispatch metadata is invalid")
    if external_request_made and not authorization_confirmed:
        raise ValueError("HIBP dispatch requires authorization")
    if retry_after_seconds is not None and (
        state is not HibpState.RATE_LIMITED
        or type(retry_after_seconds) is not int
        or not 0 <= retry_after_seconds <= MAX_HIBP_RETRY_AFTER_SECONDS
    ):
        raise ValueError("HIBP retry state is invalid")
    if type(external_request_made) is not bool or type(authorization_confirmed) is not bool:
        raise ValueError("HIBP response authorization metadata is invalid")


def _is_control(character: str) -> bool:
    return unicodedata.category(character) in {"Cc", "Cs"}
