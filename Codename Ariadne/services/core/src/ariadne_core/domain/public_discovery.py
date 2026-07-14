"""Bounded domain primitives for explicitly authorised public self-discovery."""

from __future__ import annotations

import ipaddress
import math
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from ariadne_core.domain.query_policy import AccessBasis, Sensitivity

HARD_MAX_DISCOVERY_QUERY_BYTES = 1_024
HARD_MAX_DISCOVERY_RESPONSE_BYTES = 1_048_576
HARD_MAX_DISCOVERY_RESULTS = 25
HARD_MAX_DISCOVERY_TIMEOUT_SECONDS = 20.0
MAX_DISCOVERY_RESULT_URL_CHARS = 2_048
MAX_DISCOVERY_TITLE_CHARS = 240
MAX_DISCOVERY_SNIPPET_CHARS = 600

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.ASCII)


class PublicDiscoveryProvider(StrEnum):
    DUCKDUCKGO_HTML = "DUCKDUCKGO_HTML"
    GITHUB_USERS = "GITHUB_USERS"


class PublicDiscoveryState(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    SUCCEEDED = "SUCCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    FAILED = "FAILED"


class PublicDiscoveryReason(StrEnum):
    COMPLETE = "COMPLETE"
    NO_RESULTS = "NO_RESULTS"
    PARTIAL_RESULTS = "PARTIAL_RESULTS"
    SELF_AUDIT_AUTHORIZATION_REQUIRED = "SELF_AUDIT_AUTHORIZATION_REQUIRED"
    RESTRICTED_VALUE = "RESTRICTED_VALUE"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    CAPTCHA_OR_CHALLENGE = "CAPTCHA_OR_CHALLENGE"
    UPSTREAM_ACCESS_BLOCKED = "UPSTREAM_ACCESS_BLOCKED"
    REDIRECT_REFUSED = "REDIRECT_REFUSED"
    TIMEOUT = "TIMEOUT"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"


@dataclass(frozen=True, slots=True)
class PublicDiscoveryProviderMetadata:
    provider: PublicDiscoveryProvider
    display_name: str
    operator: str
    endpoint_host: str
    access_basis: AccessBasis = AccessBasis.PUBLIC
    external: bool = True
    network_access: bool = True
    sends_query: bool = True
    credentials_required: bool = False
    retention_known: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, PublicDiscoveryProvider)
            or not self.display_name
            or len(self.display_name) > 96
            or not self.operator
            or len(self.operator) > 128
            or not self.endpoint_host
            or len(self.endpoint_host) > 253
        ):
            raise ValueError("public discovery provider metadata is invalid")
        if self.access_basis is not AccessBasis.PUBLIC:
            raise ValueError("public discovery provider requires public access metadata")
        if not self.external or not self.network_access or not self.sends_query:
            raise ValueError("public discovery provider must disclose external query transmission")
        if self.credentials_required or self.retention_known:
            raise ValueError("public discovery credential or retention metadata is invalid")


PUBLIC_DISCOVERY_PROVIDERS = (
    PublicDiscoveryProviderMetadata(
        provider=PublicDiscoveryProvider.DUCKDUCKGO_HTML,
        display_name="DuckDuckGo HTML public web search",
        operator="DuckDuckGo",
        endpoint_host="html.duckduckgo.com",
    ),
    PublicDiscoveryProviderMetadata(
        provider=PublicDiscoveryProvider.GITHUB_USERS,
        display_name="GitHub public user search",
        operator="GitHub",
        endpoint_host="api.github.com",
    ),
)


def public_discovery_provider_metadata(
    provider: PublicDiscoveryProvider,
) -> PublicDiscoveryProviderMetadata:
    try:
        return next(item for item in PUBLIC_DISCOVERY_PROVIDERS if item.provider is provider)
    except StopIteration as error:
        raise LookupError("public discovery provider is unavailable") from error


@dataclass(frozen=True, slots=True)
class PublicDiscoveryLimits:
    timeout_seconds: float = 10.0
    max_response_bytes: int = 512 * 1_024

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= HARD_MAX_DISCOVERY_TIMEOUT_SECONDS
        ):
            raise ValueError("public discovery timeout is invalid")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= HARD_MAX_DISCOVERY_RESPONSE_BYTES
        ):
            raise ValueError("public discovery response limit is invalid")


@dataclass(frozen=True, slots=True)
class PublicDiscoveryRequest:
    provider: PublicDiscoveryProvider
    query: str = field(repr=False)
    sensitivity: Sensitivity
    authorized_self_audit: bool
    max_results: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.provider, PublicDiscoveryProvider):
            raise ValueError("public discovery provider is invalid")
        if not isinstance(self.sensitivity, Sensitivity):
            raise ValueError("public discovery sensitivity is invalid")
        if type(self.authorized_self_audit) is not bool:
            raise ValueError("self-audit authorization flag is invalid")
        if type(self.max_results) is not int or not 1 <= self.max_results <= (
            HARD_MAX_DISCOVERY_RESULTS
        ):
            raise ValueError("public discovery result limit is invalid")
        query = normalise_discovery_query(self.query)
        object.__setattr__(self, "query", query)


@dataclass(frozen=True, slots=True)
class PublicDiscoveryResult:
    provider: PublicDiscoveryProvider
    rank: int
    title: str
    url: str
    snippet: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, PublicDiscoveryProvider):
            raise ValueError("public discovery result provider is invalid")
        if type(self.rank) is not int or not 1 <= self.rank <= HARD_MAX_DISCOVERY_RESULTS:
            raise ValueError("public discovery result rank is invalid")
        if (
            not self.title
            or len(self.title) > MAX_DISCOVERY_TITLE_CHARS
            or normalise_result_text(
                self.title,
                maximum=MAX_DISCOVERY_TITLE_CHARS,
                required=True,
            )
            != self.title
        ):
            raise ValueError("public discovery result title is invalid")
        if (
            not self.url
            or len(self.url) > MAX_DISCOVERY_RESULT_URL_CHARS
            or normalise_public_result_url(self.url) != self.url
        ):
            raise ValueError("public discovery result URL is invalid")
        if self.snippet is not None and (
            not self.snippet or len(self.snippet) > MAX_DISCOVERY_SNIPPET_CHARS
        ):
            raise ValueError("public discovery result snippet is invalid")
        if (
            self.snippet is not None
            and normalise_result_text(
                self.snippet,
                maximum=MAX_DISCOVERY_SNIPPET_CHARS,
                required=True,
            )
            != self.snippet
        ):
            raise ValueError("public discovery result snippet is invalid")
        if self.source_id is not None and (
            not self.source_id
            or len(self.source_id) > 160
            or normalise_result_text(self.source_id, maximum=160, required=True) != self.source_id
        ):
            raise ValueError("public discovery source id is invalid")


@dataclass(frozen=True, slots=True)
class PublicDiscoveryResponse:
    provider: PublicDiscoveryProvider
    state: PublicDiscoveryState
    reason: PublicDiscoveryReason
    results: tuple[PublicDiscoveryResult, ...] = ()
    total_estimate: int | None = None
    rate_limit_remaining: int | None = None
    truncated: bool = False
    external_request_made: bool = False
    authorization_confirmed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        if len(self.results) > HARD_MAX_DISCOVERY_RESULTS:
            raise ValueError("public discovery result count is invalid")
        if any(result.provider is not self.provider for result in self.results):
            raise ValueError("public discovery result provider binding is invalid")
        if self.state is not PublicDiscoveryState.SUCCEEDED and self.results:
            raise ValueError("non-successful public discovery cannot contain results")
        allowed_reasons = {
            PublicDiscoveryState.NOT_CHECKED: {
                PublicDiscoveryReason.SELF_AUDIT_AUTHORIZATION_REQUIRED
            },
            PublicDiscoveryState.SUCCEEDED: {
                PublicDiscoveryReason.COMPLETE,
                PublicDiscoveryReason.NO_RESULTS,
                PublicDiscoveryReason.PARTIAL_RESULTS,
            },
            PublicDiscoveryState.RATE_LIMITED: {PublicDiscoveryReason.UPSTREAM_RATE_LIMITED},
            PublicDiscoveryState.ACCESS_BLOCKED: {
                PublicDiscoveryReason.RESTRICTED_VALUE,
                PublicDiscoveryReason.CAPTCHA_OR_CHALLENGE,
                PublicDiscoveryReason.UPSTREAM_ACCESS_BLOCKED,
                PublicDiscoveryReason.REDIRECT_REFUSED,
            },
            PublicDiscoveryState.FAILED: {
                PublicDiscoveryReason.TIMEOUT,
                PublicDiscoveryReason.RESPONSE_LIMIT,
                PublicDiscoveryReason.NETWORK_UNAVAILABLE,
                PublicDiscoveryReason.UPSTREAM_UNAVAILABLE,
                PublicDiscoveryReason.UPSTREAM_REJECTED,
                PublicDiscoveryReason.INVALID_RESPONSE,
            },
        }
        if self.reason not in allowed_reasons[self.state]:
            raise ValueError("public discovery state reason is invalid")
        if self.external_request_made and not self.authorization_confirmed:
            raise ValueError("public discovery dispatch requires authorization")
        if (
            self.state
            in {
                PublicDiscoveryState.SUCCEEDED,
                PublicDiscoveryState.RATE_LIMITED,
                PublicDiscoveryState.FAILED,
            }
            and not self.external_request_made
        ):
            raise ValueError("public discovery dispatch state is invalid")
        if self.truncated and self.state is not PublicDiscoveryState.SUCCEEDED:
            raise ValueError("public discovery truncation state is invalid")
        if self.total_estimate is not None and (
            type(self.total_estimate) is not int or self.total_estimate < 0
        ):
            raise ValueError("public discovery total estimate is invalid")
        if self.rate_limit_remaining is not None and (
            type(self.rate_limit_remaining) is not int or self.rate_limit_remaining < 0
        ):
            raise ValueError("public discovery rate limit is invalid")
        if any(
            type(value) is not bool
            for value in (
                self.truncated,
                self.external_request_made,
                self.authorization_confirmed,
                self.human_review_required,
            )
        ):
            raise ValueError("public discovery response flag is invalid")
        if not self.human_review_required:
            raise ValueError("public discovery always requires human review")


def normalise_discovery_query(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("public discovery query is invalid")
    query = " ".join(unicodedata.normalize("NFKC", value).split())
    if (
        not query
        or len(query.encode("utf-8")) > HARD_MAX_DISCOVERY_QUERY_BYTES
        or any(unicodedata.category(character) in {"Cc", "Cs"} for character in query)
    ):
        raise ValueError("public discovery query is invalid")
    return query


def normalise_result_text(value: object, *, maximum: int, required: bool) -> str | None:
    if not isinstance(value, str):
        if required:
            raise ValueError("public discovery result text is invalid")
        return None
    normalised = unicodedata.normalize("NFKC", value)
    characters: list[str] = []
    for character in normalised:
        if character.isspace():
            characters.append(" ")
        elif unicodedata.category(character) not in {"Cc", "Cs"}:
            characters.append(character)
    cleaned = "".join(characters)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        if required:
            raise ValueError("public discovery result text is invalid")
        return None
    if len(cleaned) > maximum:
        cleaned = cleaned[: maximum - 1].rstrip() + "…"
    return cleaned


def normalise_public_result_url(
    value: object,
    *,
    allowed_hosts: frozenset[str] | None = None,
) -> str:
    """Return a display-safe public HTTP(S) URL without credentials or fragments."""

    if not isinstance(value, str) or not value or len(value) > 4_096:
        raise ValueError("public discovery result URL is invalid")
    if any(
        character.isspace() or unicodedata.category(character) in {"Cc", "Cs"}
        for character in value
    ):
        raise ValueError("public discovery result URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("public discovery result URL is invalid") from error
    scheme = parsed.scheme.casefold()
    if (
        scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("public discovery result URL is invalid")
    if parsed.hostname is None:
        raise ValueError("public discovery result URL is invalid")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise ValueError("public discovery result URL is invalid") from error
    if not _is_public_host(host):
        raise ValueError("public discovery result URL is invalid")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError("public discovery result URL host is invalid")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("public discovery result URL is invalid")
    display_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    netloc = display_host if port in {None, default_port} else f"{display_host}:{port}"
    path = parsed.path or "/"
    normalised = urlunsplit((scheme, netloc, path, parsed.query, ""))
    if len(normalised) > MAX_DISCOVERY_RESULT_URL_CHARS:
        raise ValueError("public discovery result URL is invalid")
    return normalised


def validate_bound_https_url(value: str, *, expected_host: str) -> None:
    """Validate fixed dispatch endpoints without DNS, redirects, or alternate ports."""

    if not value or len(value) > 4_096:
        raise ValueError("public discovery endpoint binding is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("public discovery endpoint binding is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("public discovery endpoint binding is invalid")


def _is_public_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        return (
            len(labels) >= 2
            and all(_HOST_LABEL.fullmatch(label) is not None for label in labels)
            and not host.endswith((".local", ".localhost", ".internal", ".invalid"))
        )
    return address.is_global
