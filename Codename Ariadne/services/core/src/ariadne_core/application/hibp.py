"""Official HIBP v3 adapter for bounded, authorised defensive self-audits.

Each call is provider-specific, redirect-refusing, response-bounded, and
explicitly authorised; failures become stable states instead of leaked bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from enum import StrEnum
from http.client import HTTPMessage
from typing import IO, Protocol, TypedDict
from urllib.parse import quote, urlsplit

from ariadne_core.domain.hibp import (
    HARD_MAX_HIBP_BREACHES,
    HARD_MAX_HIBP_DOMAIN_ACCOUNTS,
    HARD_MAX_HIBP_RESPONSE_BYTES,
    HIBP_API_BASE_URL,
    HIBP_API_HOST,
    HIBP_USER_AGENT,
    HibpAccountMode,
    HibpAccountSearchRequest,
    HibpAccountSearchResponse,
    HibpBreachReference,
    HibpDomainAccount,
    HibpDomainSearchRequest,
    HibpDomainSearchResponse,
    HibpIdentifierDisclosure,
    HibpLimits,
    HibpOperation,
    HibpReason,
    HibpRequestMetadata,
    HibpState,
    hibp_breach_reference,
    normalise_hibp_alias,
    normalise_hibp_breach_name,
    normalise_hibp_domain,
    validate_hibp_api_key,
)

_MAX_HEADERS = 8
_MAX_HEADER_CHARS = 1_024
_MAX_RANGE_ROWS = 20_000
_MAX_DOMAIN_PROJECTED_RESPONSE_BYTES = 800_000
_SHA1_SUFFIX = re.compile(r"^[0-9A-Fa-f]{34}$", re.ASCII)


class HibpTransportErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"


class HibpTransportError(RuntimeError):
    """Redacted transport failure that cannot contain an identifier or credential."""

    def __init__(self, code: HibpTransportErrorCode) -> None:
        self.code = code
        super().__init__("HIBP transport failed")


@dataclass(frozen=True, slots=True)
class HibpHttpRequest:
    method: str
    url: str = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise ValueError("HIBP HTTP method is invalid")
        _validate_endpoint(self.url)
        if len(self.headers) != 4:
            raise ValueError("HIBP request headers are invalid")
        lowered = {name.casefold(): value for name, value in self.headers}
        if len(lowered) != 4 or set(lowered) != {
            "accept",
            "accept-encoding",
            "hibp-api-key",
            "user-agent",
        }:
            raise ValueError("HIBP request headers are invalid")
        if (
            lowered["accept"] != "application/json"
            or lowered["accept-encoding"] != "identity"
            or lowered["user-agent"] != HIBP_USER_AGENT
        ):
            raise ValueError("HIBP request headers are invalid")
        validate_hibp_api_key(lowered["hibp-api-key"])
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 20.0
        ):
            raise ValueError("HIBP request timeout is invalid")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= HARD_MAX_HIBP_RESPONSE_BYTES
        ):
            raise ValueError("HIBP response limit is invalid")


@dataclass(frozen=True, slots=True)
class HibpHttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("HIBP HTTP status is invalid")
        if len(self.body) > HARD_MAX_HIBP_RESPONSE_BYTES:
            raise ValueError("HIBP HTTP response is invalid")
        if len(self.headers) > _MAX_HEADERS or any(
            not name
            or len(name) > 64
            or len(value) > _MAX_HEADER_CHARS
            or any(ord(character) < 32 for character in name + value)
            for name, value in self.headers
        ):
            raise ValueError("HIBP response headers are invalid")


class HibpHttpTransport(Protocol):
    def send(self, request: HibpHttpRequest) -> HibpHttpResponse: ...


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: IO[bytes],
        code: int,
        message: str,
        headers: HTTPMessage,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class UrllibHibpTransport:
    """Fixed-host HTTPS transport with proxies, cookies, and redirects disabled."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def send(self, request: HibpHttpRequest) -> HibpHttpResponse:
        _validate_endpoint(request.url)
        wire_request = urllib.request.Request(
            request.url,
            headers=dict(request.headers),
            method="GET",
        )
        try:
            response = self._opener.open(wire_request, timeout=request.timeout_seconds)
            try:
                status = int(response.status)
                headers = _selected_headers(response.headers)
                body = response.read(request.max_response_bytes + 1)
            finally:
                response.close()
        except urllib.error.HTTPError as error:
            try:
                status = int(error.code)
                headers = _selected_headers(error.headers)
                body = error.read(request.max_response_bytes + 1)
            finally:
                error.close()
        except TimeoutError as error:
            raise HibpTransportError(HibpTransportErrorCode.TIMEOUT) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise HibpTransportError(HibpTransportErrorCode.TIMEOUT) from error
            raise HibpTransportError(HibpTransportErrorCode.UNAVAILABLE) from error
        except OSError as error:
            raise HibpTransportError(HibpTransportErrorCode.UNAVAILABLE) from error
        if len(body) > request.max_response_bytes:
            raise HibpTransportError(HibpTransportErrorCode.RESPONSE_LIMIT)
        return HibpHttpResponse(status_code=status, headers=headers, body=body)


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: HibpHttpResponse | None
    metadata: HibpRequestMetadata
    failure_reason: HibpReason | None = None


class _AccountCommon(TypedDict):
    mode: HibpAccountMode
    requests: tuple[HibpRequestMetadata, ...]
    external_request_made: bool
    authorization_confirmed: bool
    direct_transmission_authorized: bool


class _DomainFirstCommon(TypedDict):
    requests: tuple[HibpRequestMetadata, ...]
    external_request_made: bool
    authorization_confirmed: bool


class _DomainCommon(_DomainFirstCommon):
    provider_verified_domain: bool


class HibpService:
    """Stateless HIBP router; API keys and identifiers are never persisted or logged."""

    def __init__(
        self,
        *,
        transport: HibpHttpTransport | None = None,
        limits: HibpLimits | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or UrllibHibpTransport()
        self._limits = limits or HibpLimits()
        self._clock = clock or (lambda: datetime.now(UTC))

    def search_account(self, request: HibpAccountSearchRequest) -> HibpAccountSearchResponse:
        if not request.authorized_self_audit:
            return HibpAccountSearchResponse(
                mode=request.mode,
                state=HibpState.NOT_CHECKED,
                reason=HibpReason.SELF_AUDIT_AUTHORIZATION_REQUIRED,
            )
        if (
            request.mode is HibpAccountMode.DIRECT
            and not request.authorized_direct_identifier_transmission
        ):
            return HibpAccountSearchResponse(
                mode=request.mode,
                state=HibpState.NOT_CHECKED,
                reason=HibpReason.DIRECT_TRANSMISSION_AUTHORIZATION_REQUIRED,
                authorization_confirmed=True,
            )

        digest = (
            hashlib.sha1(request.email.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        )
        if request.mode is HibpAccountMode.K_ANONYMITY:
            prefix, suffix = digest[:6], digest[6:]
            operation = HibpOperation.EMAIL_K_ANONYMITY
            disclosure = HibpIdentifierDisclosure.PARTIAL_SHA1_PREFIX
            url = f"{HIBP_API_BASE_URL}/breachedaccount/range/{prefix}"
        else:
            suffix = ""
            operation = HibpOperation.EMAIL_DIRECT
            disclosure = HibpIdentifierDisclosure.DIRECT_EMAIL
            encoded = quote(request.email, safe="")
            url = (
                f"{HIBP_API_BASE_URL}/breachedAccount/{encoded}"
                "?truncateResponse=true&IncludeUnverified=false"
            )

        attempt = self._attempt(
            sequence=1,
            operation=operation,
            disclosure=disclosure,
            url=url,
            api_key=request.api_key,
        )
        common: _AccountCommon = {
            "mode": request.mode,
            "requests": (attempt.metadata,),
            "external_request_made": True,
            "authorization_confirmed": True,
            "direct_transmission_authorized": (
                request.mode is HibpAccountMode.DIRECT
                and request.authorized_direct_identifier_transmission
            ),
        }
        if attempt.failure_reason is not None:
            return HibpAccountSearchResponse(
                state=_failure_state(attempt.failure_reason),
                reason=attempt.failure_reason,
                retry_after_seconds=attempt.metadata.retry_after_seconds,
                **common,
            )
        response = _required_response(attempt)
        status_reason = _status_reason(
            response.status_code,
            not_found_is_empty=request.mode is HibpAccountMode.DIRECT,
        )
        if status_reason is HibpReason.NO_RESULTS:
            return HibpAccountSearchResponse(
                state=HibpState.SUCCEEDED,
                reason=HibpReason.NO_RESULTS,
                **common,
            )
        if status_reason is not None:
            return HibpAccountSearchResponse(
                state=_failure_state(status_reason),
                reason=status_reason,
                retry_after_seconds=attempt.metadata.retry_after_seconds,
                **common,
            )
        if not _json_content_type(response):
            return HibpAccountSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **common,
            )
        try:
            payload = json.loads(response.body.decode("utf-8", errors="strict"))
            breaches = (
                _parse_range_match(payload, suffix)
                if request.mode is HibpAccountMode.K_ANONYMITY
                else _parse_direct_breaches(payload)
            )
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return HibpAccountSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **common,
            )
        return HibpAccountSearchResponse(
            state=HibpState.SUCCEEDED,
            reason=HibpReason.COMPLETE if breaches else HibpReason.NO_RESULTS,
            breaches=breaches,
            **common,
        )

    def search_domain(self, request: HibpDomainSearchRequest) -> HibpDomainSearchResponse:
        if not request.authorized_self_audit:
            return HibpDomainSearchResponse(
                state=HibpState.NOT_CHECKED,
                reason=HibpReason.SELF_AUDIT_AUTHORIZATION_REQUIRED,
            )

        verification = self._attempt(
            sequence=1,
            operation=HibpOperation.VERIFY_SUBSCRIBED_DOMAIN,
            disclosure=HibpIdentifierDisclosure.NONE,
            url=f"{HIBP_API_BASE_URL}/subscribedDomains",
            api_key=request.api_key,
        )
        first_common: _DomainFirstCommon = {
            "requests": (verification.metadata,),
            "external_request_made": True,
            "authorization_confirmed": True,
        }
        if verification.failure_reason is not None:
            return HibpDomainSearchResponse(
                state=_failure_state(verification.failure_reason),
                reason=verification.failure_reason,
                retry_after_seconds=verification.metadata.retry_after_seconds,
                **first_common,
            )
        verification_response = _required_response(verification)
        status_reason = _status_reason(verification_response.status_code)
        if status_reason is not None:
            return HibpDomainSearchResponse(
                state=_failure_state(status_reason),
                reason=status_reason,
                retry_after_seconds=verification.metadata.retry_after_seconds,
                **first_common,
            )
        if not _json_content_type(verification_response):
            return HibpDomainSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **first_common,
            )
        try:
            payload = json.loads(verification_response.body.decode("utf-8", errors="strict"))
            verified = _provider_verified_domain(payload, request.domain)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return HibpDomainSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **first_common,
            )
        if not verified:
            return HibpDomainSearchResponse(
                state=HibpState.ACCESS_BLOCKED,
                reason=HibpReason.DOMAIN_NOT_PROVIDER_VERIFIED,
                **first_common,
            )

        encoded_domain = quote(request.domain, safe="")
        enumeration = self._attempt(
            sequence=2,
            operation=HibpOperation.DOMAIN_ENUMERATION,
            disclosure=HibpIdentifierDisclosure.DIRECT_DOMAIN,
            url=f"{HIBP_API_BASE_URL}/breachedDomain/{encoded_domain}",
            api_key=request.api_key,
        )
        requests = (verification.metadata, enumeration.metadata)
        common: _DomainCommon = {
            "requests": requests,
            "provider_verified_domain": True,
            "external_request_made": True,
            "authorization_confirmed": True,
        }
        if enumeration.failure_reason is not None:
            return HibpDomainSearchResponse(
                state=_failure_state(enumeration.failure_reason),
                reason=enumeration.failure_reason,
                retry_after_seconds=enumeration.metadata.retry_after_seconds,
                **common,
            )
        domain_response = _required_response(enumeration)
        status_reason = _status_reason(domain_response.status_code, not_found_is_empty=True)
        if status_reason is HibpReason.NO_RESULTS:
            return HibpDomainSearchResponse(
                state=HibpState.SUCCEEDED,
                reason=HibpReason.NO_RESULTS,
                **common,
            )
        if status_reason is not None:
            return HibpDomainSearchResponse(
                state=_failure_state(status_reason),
                reason=status_reason,
                retry_after_seconds=enumeration.metadata.retry_after_seconds,
                **common,
            )
        if not _json_content_type(domain_response):
            return HibpDomainSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **common,
            )
        try:
            payload = json.loads(domain_response.body.decode("utf-8", errors="strict"))
            accounts, truncated = _parse_domain_accounts(payload)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return HibpDomainSearchResponse(
                state=HibpState.FAILED,
                reason=HibpReason.INVALID_RESPONSE,
                **common,
            )
        return HibpDomainSearchResponse(
            state=HibpState.SUCCEEDED,
            reason=(
                HibpReason.PARTIAL_RESULTS
                if truncated
                else HibpReason.COMPLETE
                if accounts
                else HibpReason.NO_RESULTS
            ),
            accounts=accounts,
            truncated=truncated,
            **common,
        )

    def _attempt(
        self,
        *,
        sequence: int,
        operation: HibpOperation,
        disclosure: HibpIdentifierDisclosure,
        url: str,
        api_key: str,
    ) -> _Attempt:
        wire = HibpHttpRequest(
            method="GET",
            url=url,
            headers=(
                ("Accept", "application/json"),
                ("Accept-Encoding", "identity"),
                ("User-Agent", HIBP_USER_AGENT),
                ("hibp-api-key", api_key),
            ),
            timeout_seconds=self._limits.timeout_seconds,
            max_response_bytes=self._limits.max_response_bytes,
        )
        response: HibpHttpResponse | None = None
        failure: HibpReason | None = None
        try:
            response = self._transport.send(wire)
        except HibpTransportError as error:
            failure = {
                HibpTransportErrorCode.TIMEOUT: HibpReason.TIMEOUT,
                HibpTransportErrorCode.RESPONSE_LIMIT: HibpReason.RESPONSE_LIMIT,
                HibpTransportErrorCode.UNAVAILABLE: HibpReason.NETWORK_UNAVAILABLE,
            }[error.code]
        except Exception:
            failure = HibpReason.NETWORK_UNAVAILABLE
        retry_after = None if response is None else _retry_after(response)
        metadata = HibpRequestMetadata(
            sequence=sequence,
            operation=operation,
            method="GET",
            request_url=url,
            endpoint_host=HIBP_API_HOST,
            identifier_disclosure=disclosure,
            request_sha256=hashlib.sha256(f"GET\n{url}".encode()).hexdigest(),
            http_status=None if response is None else response.status_code,
            response_bytes=0 if response is None else len(response.body),
            observed_at=self._clock(),
            retry_after_seconds=retry_after if response and response.status_code == 429 else None,
        )
        return _Attempt(response=response, metadata=metadata, failure_reason=failure)


def _required_response(attempt: _Attempt) -> HibpHttpResponse:
    if attempt.response is None:
        raise RuntimeError("HIBP response is unavailable")
    return attempt.response


def _status_reason(status: int, *, not_found_is_empty: bool = False) -> HibpReason | None:
    if status == 200:
        return None
    if status == 404 and not_found_is_empty:
        return HibpReason.NO_RESULTS
    if status == 401:
        return HibpReason.INVALID_API_KEY
    if status == 429:
        return HibpReason.UPSTREAM_RATE_LIMITED
    if 300 <= status < 400:
        return HibpReason.REDIRECT_REFUSED
    if status in {403, 451}:
        return HibpReason.UPSTREAM_ACCESS_BLOCKED
    if status >= 500:
        return HibpReason.UPSTREAM_UNAVAILABLE
    return HibpReason.UPSTREAM_REJECTED


def _failure_state(reason: HibpReason) -> HibpState:
    if reason is HibpReason.UPSTREAM_RATE_LIMITED:
        return HibpState.RATE_LIMITED
    if reason in {
        HibpReason.DOMAIN_NOT_PROVIDER_VERIFIED,
        HibpReason.INVALID_API_KEY,
        HibpReason.REDIRECT_REFUSED,
        HibpReason.UPSTREAM_ACCESS_BLOCKED,
    }:
        return HibpState.ACCESS_BLOCKED
    return HibpState.FAILED


def _parse_direct_breaches(payload: object) -> tuple[HibpBreachReference, ...]:
    if not isinstance(payload, list) or len(payload) > HARD_MAX_HIBP_BREACHES:
        raise ValueError("HIBP direct response is invalid")
    names: list[str] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"Name"}:
            raise ValueError("HIBP direct response is invalid")
        names.append(normalise_hibp_breach_name(item["Name"]))
    return _breach_references(names)


def _parse_range_match(payload: object, expected_suffix: str) -> tuple[HibpBreachReference, ...]:
    if not isinstance(payload, list) or len(payload) > _MAX_RANGE_ROWS:
        raise ValueError("HIBP range response is invalid")
    for item in payload:
        if not isinstance(item, dict):
            continue
        suffix = item.get("hashSuffix")
        if not isinstance(suffix, str) or _SHA1_SUFFIX.fullmatch(suffix) is None:
            continue
        if suffix.upper() != expected_suffix:
            continue
        websites = item.get("websites")
        if not isinstance(websites, list) or len(websites) > HARD_MAX_HIBP_BREACHES:
            raise ValueError("HIBP range match is invalid")
        return _breach_references([normalise_hibp_breach_name(name) for name in websites])
    return ()


def _provider_verified_domain(payload: object, expected_domain: str) -> bool:
    if not isinstance(payload, list) or len(payload) > 10_000:
        raise ValueError("HIBP subscribed-domain response is invalid")
    for item in payload:
        if not isinstance(item, dict) or "DomainName" not in item:
            raise ValueError("HIBP subscribed-domain response is invalid")
        try:
            domain = normalise_hibp_domain(item["DomainName"])
        except ValueError:
            continue
        if domain == expected_domain:
            return True
    return False


def _parse_domain_accounts(payload: object) -> tuple[tuple[HibpDomainAccount, ...], bool]:
    if not isinstance(payload, dict):
        raise ValueError("HIBP domain response is invalid")
    accounts: list[HibpDomainAccount] = []
    truncated = len(payload) > HARD_MAX_HIBP_DOMAIN_ACCOUNTS
    projected_bytes = 16_384
    ordered_items = sorted(payload.items(), key=lambda item: str(item[0]).casefold())
    for raw_alias, raw_breaches in ordered_items:
        if len(accounts) >= HARD_MAX_HIBP_DOMAIN_ACCOUNTS:
            break
        alias = normalise_hibp_alias(raw_alias)
        if not isinstance(raw_breaches, list) or len(raw_breaches) > HARD_MAX_HIBP_BREACHES:
            raise ValueError("HIBP domain account is invalid")
        account = HibpDomainAccount(
            alias=alias,
            breaches=_breach_references(
                [normalise_hibp_breach_name(name) for name in raw_breaches]
            ),
        )
        projected_item = json.dumps(
            {
                "alias": account.alias,
                "breaches": [
                    {"name": item.name, "sourceUrl": item.source_url} for item in account.breaches
                ],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        if projected_bytes + len(projected_item) > _MAX_DOMAIN_PROJECTED_RESPONSE_BYTES:
            truncated = True
            break
        projected_bytes += len(projected_item)
        accounts.append(account)
    return tuple(accounts), truncated


def _breach_references(names: list[str]) -> tuple[HibpBreachReference, ...]:
    unique: dict[str, str] = {}
    for name in names:
        unique.setdefault(name.casefold(), name)
    return tuple(hibp_breach_reference(name) for name in sorted(unique.values(), key=str.casefold))


def _retry_after(response: HibpHttpResponse) -> int | None:
    raw = _header(response, "retry-after")
    if raw is None or not raw.isascii() or not raw.isdigit():
        return None
    seconds = int(raw)
    return seconds if 0 <= seconds <= 86_400 else None


def _json_content_type(response: HibpHttpResponse) -> bool:
    raw = _header(response, "content-type")
    if raw is None:
        return False
    return raw.partition(";")[0].strip().casefold() == "application/json"


def _header(response: HibpHttpResponse, name: str) -> str | None:
    expected = name.casefold()
    return next(
        (value for key, value in response.headers if key.casefold() == expected),
        None,
    )


def _selected_headers(headers: Message[str, str]) -> tuple[tuple[str, str], ...]:
    selected: list[tuple[str, str]] = []
    for name in ("Content-Type", "Retry-After"):
        value = headers.get(name)
        if (
            value is not None
            and len(value) <= _MAX_HEADER_CHARS
            and all(ord(character) >= 32 for character in value)
        ):
            selected.append((name, value))
    return tuple(selected)


def _validate_endpoint(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise ValueError("HIBP endpoint is invalid") from error
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
        raise ValueError("HIBP endpoint is invalid")
