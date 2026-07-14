"""Credential-free public-search adapters with a strict outbound HTTP boundary."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from enum import StrEnum
from html.parser import HTMLParser
from http.client import HTTPMessage
from typing import IO, Protocol
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from ariadne_core.domain.public_discovery import (
    HARD_MAX_DISCOVERY_RESPONSE_BYTES,
    HARD_MAX_DISCOVERY_TIMEOUT_SECONDS,
    MAX_DISCOVERY_SNIPPET_CHARS,
    MAX_DISCOVERY_TITLE_CHARS,
    PublicDiscoveryLimits,
    PublicDiscoveryProvider,
    PublicDiscoveryProviderMetadata,
    PublicDiscoveryReason,
    PublicDiscoveryRequest,
    PublicDiscoveryResponse,
    PublicDiscoveryResult,
    PublicDiscoveryState,
    normalise_public_result_url,
    normalise_result_text,
    public_discovery_provider_metadata,
    validate_bound_https_url,
)
from ariadne_core.domain.query_policy import Sensitivity

_DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
_DUCKDUCKGO_HOST = "html.duckduckgo.com"
_GITHUB_SEARCH_URL = "https://api.github.com/search/users"
_GITHUB_API_HOST = "api.github.com"
_ALLOWED_ENDPOINT_HOSTS = frozenset({_DUCKDUCKGO_HOST, _GITHUB_API_HOST})
_MAX_REQUEST_BODY_BYTES = 4_096
_MAX_RESPONSE_HEADERS = 16
_MAX_HEADER_CHARS = 1_024
_MAX_HTML_EVENTS = 50_000
_MAX_CAPTURE_CHARS = 4_096
_GITHUB_LOGIN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$",
    re.ASCII,
)


class PublicDiscoveryTransportErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    RESPONSE_LIMIT = "RESPONSE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"


class PublicDiscoveryTransportError(RuntimeError):
    """Redacted transport failure which never includes a query or upstream body."""

    def __init__(self, code: PublicDiscoveryTransportErrorCode) -> None:
        self.code = code
        super().__init__("public discovery transport failed")


@dataclass(frozen=True, slots=True)
class PublicDiscoveryHttpRequest:
    method: str
    url: str = field(repr=False)
    bound_host: str
    headers: tuple[tuple[str, str], ...]
    body: bytes | None = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("public discovery HTTP method is invalid")
        if self.bound_host not in _ALLOWED_ENDPOINT_HOSTS:
            raise ValueError("public discovery endpoint host is invalid")
        validate_bound_https_url(self.url, expected_host=self.bound_host)
        if len(self.headers) > _MAX_RESPONSE_HEADERS:
            raise ValueError("public discovery request headers are invalid")
        blocked_headers = {"authorization", "cookie", "proxy-authorization"}
        for name, value in self.headers:
            if (
                not name
                or name.casefold() in blocked_headers
                or len(name) > 64
                or len(value) > _MAX_HEADER_CHARS
                or any(ord(character) < 32 for character in name + value)
            ):
                raise ValueError("public discovery request headers are invalid")
        if self.body is not None and len(self.body) > _MAX_REQUEST_BODY_BYTES:
            raise ValueError("public discovery request body is invalid")
        if self.method == "GET" and self.body is not None:
            raise ValueError("public discovery GET request cannot contain a body")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= HARD_MAX_DISCOVERY_TIMEOUT_SECONDS
        ):
            raise ValueError("public discovery request timeout is invalid")
        if (
            type(self.max_response_bytes) is not int
            or not 1 <= self.max_response_bytes <= HARD_MAX_DISCOVERY_RESPONSE_BYTES
        ):
            raise ValueError("public discovery response limit is invalid")


@dataclass(frozen=True, slots=True)
class PublicDiscoveryHttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("public discovery HTTP status is invalid")
        if len(self.body) > HARD_MAX_DISCOVERY_RESPONSE_BYTES:
            raise ValueError("public discovery HTTP response is invalid")
        if len(self.headers) > _MAX_RESPONSE_HEADERS or any(
            not name
            or len(name) > 64
            or len(value) > _MAX_HEADER_CHARS
            or any(ord(character) < 32 for character in name + value)
            for name, value in self.headers
        ):
            raise ValueError("public discovery response headers are invalid")


class PublicDiscoveryHttpTransport(Protocol):
    """Injectable single-request transport for deterministic synthetic tests."""

    def send(self, request: PublicDiscoveryHttpRequest) -> PublicDiscoveryHttpResponse: ...


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


class UrllibPublicDiscoveryTransport:
    """HTTPS transport with environment proxies, cookies, and redirects disabled."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def send(self, request: PublicDiscoveryHttpRequest) -> PublicDiscoveryHttpResponse:
        validate_bound_https_url(request.url, expected_host=request.bound_host)
        wire_request = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            response = self._opener.open(wire_request, timeout=request.timeout_seconds)
            try:
                status = int(response.status)
                headers = _selected_response_headers(response.headers)
                body = response.read(request.max_response_bytes + 1)
            finally:
                response.close()
        except urllib.error.HTTPError as error:
            try:
                status = int(error.code)
                headers = _selected_response_headers(error.headers)
                body = error.read(request.max_response_bytes + 1)
            finally:
                error.close()
        except TimeoutError as error:
            raise PublicDiscoveryTransportError(
                PublicDiscoveryTransportErrorCode.TIMEOUT
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise PublicDiscoveryTransportError(
                    PublicDiscoveryTransportErrorCode.TIMEOUT
                ) from error
            raise PublicDiscoveryTransportError(
                PublicDiscoveryTransportErrorCode.UNAVAILABLE
            ) from error
        except OSError as error:
            raise PublicDiscoveryTransportError(
                PublicDiscoveryTransportErrorCode.UNAVAILABLE
            ) from error
        if len(body) > request.max_response_bytes:
            raise PublicDiscoveryTransportError(PublicDiscoveryTransportErrorCode.RESPONSE_LIMIT)
        return PublicDiscoveryHttpResponse(status_code=status, headers=headers, body=body)


class PublicDiscoveryAdapter(Protocol):
    provider: PublicDiscoveryProvider

    def search(self, request: PublicDiscoveryRequest) -> PublicDiscoveryResponse: ...


class DuckDuckGoHtmlAdapter:
    """One-page DuckDuckGo HTML search; challenges are reported, never bypassed."""

    provider = PublicDiscoveryProvider.DUCKDUCKGO_HTML

    def __init__(
        self,
        *,
        transport: PublicDiscoveryHttpTransport | None = None,
        limits: PublicDiscoveryLimits | None = None,
    ) -> None:
        self._transport = transport or UrllibPublicDiscoveryTransport()
        self._limits = limits or PublicDiscoveryLimits()

    def search(self, request: PublicDiscoveryRequest) -> PublicDiscoveryResponse:
        blocked = _preflight(request, self.provider)
        if blocked is not None:
            return blocked
        body = urlencode({"q": request.query}, encoding="utf-8").encode("ascii")
        wire_request = PublicDiscoveryHttpRequest(
            method="POST",
            url=_DUCKDUCKGO_URL,
            bound_host=_DUCKDUCKGO_HOST,
            headers=(
                ("Accept", "text/html,application/xhtml+xml"),
                ("Accept-Encoding", "identity"),
                ("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"),
                ("User-Agent", "Codename-Ariadne/0.1 public-self-audit"),
            ),
            body=body,
            timeout_seconds=self._limits.timeout_seconds,
            max_response_bytes=self._limits.max_response_bytes,
        )
        response = _send(self._transport, wire_request, request)
        if isinstance(response, PublicDiscoveryResponse):
            return response
        if len(response.body) > self._limits.max_response_bytes:
            return _failure(request, PublicDiscoveryReason.RESPONSE_LIMIT)
        if response.status_code == 202 and _has_challenge(response.body):
            return _failure(
                request,
                PublicDiscoveryReason.CAPTCHA_OR_CHALLENGE,
                state=PublicDiscoveryState.ACCESS_BLOCKED,
            )
        status_failure = _status_failure(request, response, github=False)
        if status_failure is not None:
            return status_failure
        if _has_challenge(response.body):
            return _failure(
                request,
                PublicDiscoveryReason.CAPTCHA_OR_CHALLENGE,
                state=PublicDiscoveryState.ACCESS_BLOCKED,
            )
        if not _content_type_is(response, ("text/html", "application/xhtml+xml")):
            return _failure(request, PublicDiscoveryReason.INVALID_RESPONSE)
        try:
            text = response.body.decode("utf-8", errors="strict")
            parser = _DuckDuckGoParser(max_candidates=request.max_results * 4)
            parser.feed(text)
            parser.close()
            results, invalid_count = _normalise_duckduckgo_results(
                parser.candidates,
                request.max_results,
            )
        except (UnicodeError, ValueError):
            return _failure(request, PublicDiscoveryReason.INVALID_RESPONSE)
        if parser.candidate_count > 0 and not results:
            return _failure(request, PublicDiscoveryReason.INVALID_RESPONSE)
        truncated = parser.candidate_count > len(results) or invalid_count > 0
        reason = (
            PublicDiscoveryReason.NO_RESULTS
            if not results
            else PublicDiscoveryReason.PARTIAL_RESULTS
            if truncated
            else PublicDiscoveryReason.COMPLETE
        )
        return PublicDiscoveryResponse(
            provider=request.provider,
            state=PublicDiscoveryState.SUCCEEDED,
            reason=reason,
            results=results,
            total_estimate=parser.candidate_count,
            truncated=truncated,
            external_request_made=True,
            authorization_confirmed=True,
        )


class GitHubPublicUserAdapter:
    """Official unauthenticated GitHub public-user search API adapter."""

    provider = PublicDiscoveryProvider.GITHUB_USERS

    def __init__(
        self,
        *,
        transport: PublicDiscoveryHttpTransport | None = None,
        limits: PublicDiscoveryLimits | None = None,
    ) -> None:
        self._transport = transport or UrllibPublicDiscoveryTransport()
        self._limits = limits or PublicDiscoveryLimits()

    def search(self, request: PublicDiscoveryRequest) -> PublicDiscoveryResponse:
        blocked = _preflight(request, self.provider)
        if blocked is not None:
            return blocked
        query = urlencode(
            {"q": request.query, "per_page": request.max_results, "page": 1},
            encoding="utf-8",
        )
        wire_request = PublicDiscoveryHttpRequest(
            method="GET",
            url=f"{_GITHUB_SEARCH_URL}?{query}",
            bound_host=_GITHUB_API_HOST,
            headers=(
                ("Accept", "application/vnd.github+json"),
                ("Accept-Encoding", "identity"),
                ("User-Agent", "Codename-Ariadne/0.1 public-self-audit"),
                ("X-GitHub-Api-Version", "2022-11-28"),
            ),
            body=None,
            timeout_seconds=self._limits.timeout_seconds,
            max_response_bytes=self._limits.max_response_bytes,
        )
        response = _send(self._transport, wire_request, request)
        if isinstance(response, PublicDiscoveryResponse):
            return response
        if len(response.body) > self._limits.max_response_bytes:
            return _failure(request, PublicDiscoveryReason.RESPONSE_LIMIT)
        status_failure = _status_failure(request, response, github=True)
        if status_failure is not None:
            return status_failure
        if not _content_type_is(
            response,
            ("application/json", "application/vnd.github+json"),
        ):
            return _failure(request, PublicDiscoveryReason.INVALID_RESPONSE)
        try:
            payload = json.loads(response.body.decode("utf-8", errors="strict"))
            results, total_estimate, truncated = _normalise_github_results(
                payload,
                request.max_results,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return _failure(request, PublicDiscoveryReason.INVALID_RESPONSE)
        reason = (
            PublicDiscoveryReason.NO_RESULTS
            if not results
            else PublicDiscoveryReason.PARTIAL_RESULTS
            if truncated
            else PublicDiscoveryReason.COMPLETE
        )
        return PublicDiscoveryResponse(
            provider=request.provider,
            state=PublicDiscoveryState.SUCCEEDED,
            reason=reason,
            results=results,
            total_estimate=total_estimate,
            rate_limit_remaining=_rate_limit_remaining(response),
            truncated=truncated,
            external_request_made=True,
            authorization_confirmed=True,
        )


class PublicDiscoveryService:
    """Stateless provider router; deliberately performs no persistence or logging."""

    def __init__(
        self,
        *,
        transport: PublicDiscoveryHttpTransport | None = None,
        limits: PublicDiscoveryLimits | None = None,
    ) -> None:
        shared_transport = transport or UrllibPublicDiscoveryTransport()
        shared_limits = limits or PublicDiscoveryLimits()
        adapters: tuple[PublicDiscoveryAdapter, ...] = (
            DuckDuckGoHtmlAdapter(transport=shared_transport, limits=shared_limits),
            GitHubPublicUserAdapter(transport=shared_transport, limits=shared_limits),
        )
        self._adapters = {adapter.provider: adapter for adapter in adapters}

    @property
    def providers(self) -> tuple[PublicDiscoveryProvider, ...]:
        return tuple(sorted(self._adapters, key=lambda item: item.value))

    @property
    def provider_metadata(self) -> tuple[PublicDiscoveryProviderMetadata, ...]:
        return tuple(public_discovery_provider_metadata(provider) for provider in self.providers)

    def search(self, request: PublicDiscoveryRequest) -> PublicDiscoveryResponse:
        return self._adapters[request.provider].search(request)


@dataclass(slots=True)
class _DuckDuckGoCandidate:
    raw_url: str
    raw_title: str
    raw_snippet: str | None = None


class _DuckDuckGoParser(HTMLParser):
    def __init__(self, *, max_candidates: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_candidates = max_candidates
        self.candidates: list[_DuckDuckGoCandidate] = []
        self.candidate_count = 0
        self._event_count = 0
        self._capture: str | None = None
        self._capture_depth = 0
        self._capture_url = ""
        self._capture_parts: list[str] = []
        self._capture_chars = 0
        self._snippet_candidate_index: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._event()
        if self._capture is not None:
            self._capture_depth += 1
            return
        attributes = {name.casefold(): value or "" for name, value in attrs}
        classes = frozenset(attributes.get("class", "").split())
        if tag.casefold() == "a" and "result__a" in classes:
            self._snippet_candidate_index = None
            self.candidate_count += 1
            if len(self.candidates) < self.max_candidates:
                self._begin_capture("title", attributes.get("href", ""))
        elif "result__snippet" in classes and self._snippet_candidate_index is not None:
            self._begin_capture("snippet", "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs
        self._event()
        if self._capture is not None:
            self._capture_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        del tag
        self._event()
        if self._capture is None:
            return
        self._capture_depth -= 1
        if self._capture_depth == 0:
            self._finish_capture()

    def handle_data(self, data: str) -> None:
        self._event()
        if self._capture is None:
            return
        self._capture_chars += len(data)
        if self._capture_chars > _MAX_CAPTURE_CHARS:
            raise ValueError("public discovery HTML capture limit exceeded")
        self._capture_parts.append(data)

    def _event(self) -> None:
        self._event_count += 1
        if self._event_count > _MAX_HTML_EVENTS:
            raise ValueError("public discovery HTML event limit exceeded")

    def _begin_capture(self, kind: str, url: str) -> None:
        self._capture = kind
        self._capture_depth = 1
        self._capture_url = url
        self._capture_parts = []
        self._capture_chars = 0

    def _finish_capture(self) -> None:
        captured = "".join(self._capture_parts)
        if self._capture == "title":
            self.candidates.append(
                _DuckDuckGoCandidate(raw_url=self._capture_url, raw_title=captured)
            )
            self._snippet_candidate_index = len(self.candidates) - 1
        elif self._capture == "snippet" and self._snippet_candidate_index is not None:
            self.candidates[self._snippet_candidate_index].raw_snippet = captured
            self._snippet_candidate_index = None
        self._capture = None
        self._capture_url = ""
        self._capture_parts = []
        self._capture_chars = 0


def _preflight(
    request: PublicDiscoveryRequest,
    provider: PublicDiscoveryProvider,
) -> PublicDiscoveryResponse | None:
    if request.provider is not provider:
        raise ValueError("public discovery provider binding is invalid")
    if not request.authorized_self_audit:
        return PublicDiscoveryResponse(
            provider=provider,
            state=PublicDiscoveryState.NOT_CHECKED,
            reason=PublicDiscoveryReason.SELF_AUDIT_AUTHORIZATION_REQUIRED,
            authorization_confirmed=False,
        )
    if request.sensitivity is Sensitivity.RESTRICTED:
        return PublicDiscoveryResponse(
            provider=provider,
            state=PublicDiscoveryState.ACCESS_BLOCKED,
            reason=PublicDiscoveryReason.RESTRICTED_VALUE,
            authorization_confirmed=True,
        )
    return None


def _send(
    transport: PublicDiscoveryHttpTransport,
    wire_request: PublicDiscoveryHttpRequest,
    request: PublicDiscoveryRequest,
) -> PublicDiscoveryHttpResponse | PublicDiscoveryResponse:
    try:
        return transport.send(wire_request)
    except PublicDiscoveryTransportError as error:
        reason = {
            PublicDiscoveryTransportErrorCode.TIMEOUT: PublicDiscoveryReason.TIMEOUT,
            PublicDiscoveryTransportErrorCode.RESPONSE_LIMIT: PublicDiscoveryReason.RESPONSE_LIMIT,
            PublicDiscoveryTransportErrorCode.UNAVAILABLE: (
                PublicDiscoveryReason.NETWORK_UNAVAILABLE
            ),
        }[error.code]
        return _failure(request, reason)
    except Exception:
        return _failure(request, PublicDiscoveryReason.NETWORK_UNAVAILABLE)


def _failure(
    request: PublicDiscoveryRequest,
    reason: PublicDiscoveryReason,
    *,
    state: PublicDiscoveryState = PublicDiscoveryState.FAILED,
    rate_limit_remaining: int | None = None,
) -> PublicDiscoveryResponse:
    return PublicDiscoveryResponse(
        provider=request.provider,
        state=state,
        reason=reason,
        rate_limit_remaining=rate_limit_remaining,
        external_request_made=True,
        authorization_confirmed=True,
    )


def _status_failure(
    request: PublicDiscoveryRequest,
    response: PublicDiscoveryHttpResponse,
    *,
    github: bool,
) -> PublicDiscoveryResponse | None:
    remaining = _rate_limit_remaining(response)
    if response.status_code == 429 or (github and response.status_code == 403 and remaining == 0):
        return _failure(
            request,
            PublicDiscoveryReason.UPSTREAM_RATE_LIMITED,
            state=PublicDiscoveryState.RATE_LIMITED,
            rate_limit_remaining=remaining,
        )
    if 300 <= response.status_code < 400:
        return _failure(
            request,
            PublicDiscoveryReason.REDIRECT_REFUSED,
            state=PublicDiscoveryState.ACCESS_BLOCKED,
        )
    if response.status_code in {401, 403, 451}:
        return _failure(
            request,
            PublicDiscoveryReason.UPSTREAM_ACCESS_BLOCKED,
            state=PublicDiscoveryState.ACCESS_BLOCKED,
            rate_limit_remaining=remaining,
        )
    if response.status_code >= 500:
        return _failure(request, PublicDiscoveryReason.UPSTREAM_UNAVAILABLE)
    if response.status_code != 200:
        return _failure(request, PublicDiscoveryReason.UPSTREAM_REJECTED)
    return None


def _content_type_is(
    response: PublicDiscoveryHttpResponse,
    allowed: tuple[str, ...],
) -> bool:
    value = _header(response, "content-type")
    if value is None:
        return False
    media_type = value.partition(";")[0].strip().casefold()
    return media_type in allowed


def _has_challenge(body: bytes) -> bool:
    sample = body[: 64 * 1_024].lower()
    return any(
        marker in sample
        for marker in (
            b'id="anomaly-modal"',
            b'class="anomaly-modal',
            b'name="captcha"',
            b'id="challenge-form"',
            b"automated requests are not permitted",
        )
    )


def _normalise_duckduckgo_results(
    candidates: list[_DuckDuckGoCandidate],
    maximum: int,
) -> tuple[tuple[PublicDiscoveryResult, ...], int]:
    results: list[PublicDiscoveryResult] = []
    seen: set[str] = set()
    invalid_count = 0
    for candidate in candidates:
        if len(results) >= maximum:
            break
        try:
            url = _duckduckgo_target(candidate.raw_url)
            title = _required_result_text(
                candidate.raw_title,
                maximum=MAX_DISCOVERY_TITLE_CHARS,
            )
            snippet = normalise_result_text(
                candidate.raw_snippet,
                maximum=MAX_DISCOVERY_SNIPPET_CHARS,
                required=False,
            )
        except ValueError:
            invalid_count += 1
            continue
        if url in seen:
            invalid_count += 1
            continue
        seen.add(url)
        results.append(
            PublicDiscoveryResult(
                provider=PublicDiscoveryProvider.DUCKDUCKGO_HTML,
                rank=len(results) + 1,
                title=title,
                url=url,
                snippet=snippet,
            )
        )
    return tuple(results), invalid_count


def _duckduckgo_target(raw_url: str) -> str:
    joined = urljoin(_DUCKDUCKGO_URL, raw_url)
    parsed = urlsplit(joined)
    target = joined
    if parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com", _DUCKDUCKGO_HOST}:
        if parsed.path.rstrip("/") != "/l":
            raise ValueError("DuckDuckGo result URL is invalid")
        parameters = parse_qs(parsed.query, max_num_fields=16)
        targets = parameters.get("uddg", [])
        if len(targets) != 1:
            raise ValueError("DuckDuckGo result URL is invalid")
        target = targets[0]
    return normalise_public_result_url(target)


def _normalise_github_results(
    payload: object,
    maximum: int,
) -> tuple[tuple[PublicDiscoveryResult, ...], int, bool]:
    if not isinstance(payload, dict):
        raise ValueError("GitHub result envelope is invalid")
    total = payload.get("total_count")
    items = payload.get("items")
    incomplete = payload.get("incomplete_results")
    if (
        type(total) is not int
        or not 0 <= total <= 1_000_000_000
        or not isinstance(items, list)
        or len(items) > 100
        or type(incomplete) is not bool
    ):
        raise ValueError("GitHub result envelope is invalid")
    results: list[PublicDiscoveryResult] = []
    seen: set[str] = set()
    invalid = False
    for item in items:
        if len(results) >= maximum:
            break
        if not isinstance(item, dict):
            invalid = True
            continue
        login = item.get("login")
        if not isinstance(login, str) or _GITHUB_LOGIN.fullmatch(login) is None:
            invalid = True
            continue
        try:
            url = normalise_public_result_url(
                item.get("html_url"),
                allowed_hosts=frozenset({"github.com"}),
            )
        except ValueError:
            invalid = True
            continue
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.query
            or parsed.path.strip("/").casefold() != (login.casefold())
        ):
            invalid = True
            continue
        if url in seen:
            invalid = True
            continue
        seen.add(url)
        account_type = item.get("type")
        suffix = (
            f" {account_type.casefold()} account"
            if isinstance(account_type, str) and account_type in {"User", "Organization"}
            else " account"
        )
        results.append(
            PublicDiscoveryResult(
                provider=PublicDiscoveryProvider.GITHUB_USERS,
                rank=len(results) + 1,
                title=login,
                url=url,
                snippet=f"GitHub public{suffix}",
                source_id=login,
            )
        )
    if items and not results:
        raise ValueError("GitHub result items are invalid")
    truncated = bool(incomplete or invalid or total > len(results) or len(items) > maximum)
    return tuple(results), total, truncated


def _required_result_text(value: object, *, maximum: int) -> str:
    result = normalise_result_text(value, maximum=maximum, required=True)
    if result is None:
        raise ValueError("public discovery result text is invalid")
    return result


def _header(response: PublicDiscoveryHttpResponse, name: str) -> str | None:
    expected = name.casefold()
    return next(
        (value for header_name, value in response.headers if header_name.casefold() == expected),
        None,
    )


def _rate_limit_remaining(response: PublicDiscoveryHttpResponse) -> int | None:
    raw = _header(response, "x-ratelimit-remaining")
    if raw is None or not raw.isascii() or not raw.isdigit():
        return None
    value = int(raw)
    return value if value <= 1_000_000_000 else None


def _selected_response_headers(headers: Message[str, str]) -> tuple[tuple[str, str], ...]:
    selected: list[tuple[str, str]] = []
    for name in (
        "Content-Type",
        "Content-Encoding",
        "Retry-After",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ):
        value = headers.get(name)
        if (
            value is not None
            and len(value) <= _MAX_HEADER_CHARS
            and all(ord(character) >= 32 for character in value)
        ):
            selected.append((name, value))
    return tuple(selected)
