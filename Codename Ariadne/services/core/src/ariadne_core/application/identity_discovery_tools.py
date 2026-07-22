"""Bounded tool registry used by deterministic and local-model audit controllers.

Controllers may select only names in the closed registry and receive typed
results; they never receive sockets, a shell, or a generic URL-fetch primitive.
The larger registered vocabulary is intentionally honest about planned tools:
only ``IMPLEMENTED_TOOLS`` can execute, while every other task stops for review
with a durable not-implemented receipt.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPMessage
from typing import IO, Protocol
from urllib.parse import urljoin, urlsplit

from ariadne_core.application.public_discovery import PublicDiscoveryService
from ariadne_core.domain.identity_compiler import ExtractionLimits, compile_text
from ariadne_core.domain.public_discovery import (
    PublicDiscoveryProvider,
    PublicDiscoveryRequest,
    PublicDiscoveryState,
    normalise_public_result_url,
    normalise_result_text,
)
from ariadne_core.domain.query_policy import Sensitivity
from ariadne_core.infrastructure.db.identity_discovery_repository import (
    ExtractedProposalDraft,
    FetchedPageDraft,
    FrontierTaskRecord,
    SearchResultDraft,
)

MAX_PAGE_BYTES = 1_048_576
MAX_PAGE_TEXT = 131_072
MAX_HTML_EVENTS = 80_000
MAX_LINKS = 100

REGISTERED_TOOLS = frozenset(
    {
        "SEARCH_WEB",
        "SEARCH_PROVIDER",
        "SEARCH_SITE",
        "SEARCH_DOMAIN",
        "SEARCH_USERNAME",
        "FETCH_URL",
        "PARSE_HTML",
        "EXTRACT_LINKS",
        "EXTRACT_IDENTIFIERS",
        "QUERY_ARCHIVE",
        "QUERY_GITHUB",
        "QUERY_REGISTRY",
        "QUERY_DNS",
        "QUERY_CERTIFICATE_TRANSPARENCY",
        "RUN_USERNAME_ENUMERATION",
        "RUN_METADATA_EXTRACTION",
        "RUN_OCR",
        "HASH_IMAGE",
        "COMPARE_IMAGES",
        "CAPTURE_SCREENSHOT",
        "CAPTURE_HTML",
        "CAPTURE_DOCUMENT",
        "GENERATE_QUERY_VARIANTS",
        "ANALYSE_DOCUMENT",
        "COMPARE_SOURCES",
    }
)
IMPLEMENTED_TOOLS = frozenset({"SEARCH_WEB", "QUERY_GITHUB", "FETCH_URL"})


@dataclass(frozen=True, slots=True)
class PageHttpResponse:
    status_code: int
    content_type: str
    body: bytes = field(repr=False)


class PageHttpTransport(Protocol):
    """Narrow injectable port for one bounded public-page GET."""

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> PageHttpResponse: ...


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


class SafePublicPageTransport:
    """Fetch one public page without proxies, cookies, or redirect following.

    A public-DNS preflight rejects currently resolved private and special-use
    addresses. This is a deliberately narrow direct-web adapter, not a browser,
    crawler session, authentication client, or access-control bypass.
    """

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _RejectRedirects(),
        )

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> PageHttpResponse:
        normalised = normalise_public_result_url(url)
        _require_public_dns(normalised)
        request = urllib.request.Request(
            normalised,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                "Accept-Encoding": "identity",
                "User-Agent": "Codename-Ariadne/0.1 authorised-public-audit",
            },
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=timeout_seconds)
            try:
                status = int(response.status)
                content_type = response.headers.get_content_type().casefold()
                body = response.read(max_bytes + 1)
            finally:
                response.close()
        except urllib.error.HTTPError as error:
            try:
                status = int(error.code)
                content_type = error.headers.get_content_type().casefold()
                body = error.read(max_bytes + 1)
            finally:
                error.close()
        if len(body) > max_bytes:
            raise PageFetchError("RESPONSE_LIMIT")
        return PageHttpResponse(status_code=status, content_type=content_type, body=body)


class PageFetchError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("public page fetch failed")


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Transient broker result; the repository decides how it changes durable state."""

    state: str
    reason: str
    search_results: tuple[SearchResultDraft, ...] = ()
    page: FetchedPageDraft | None = None


class InvestigationToolBroker:
    """Execute only closed, typed tools; a model never receives a shell primitive.

    Authorization is established when the durable audit is created. The broker
    still validates the task type and maps provider/network outcomes to explicit
    frontier states without persisting anything itself.
    """

    def __init__(
        self,
        *,
        public_discovery: PublicDiscoveryService,
        page_transport: PageHttpTransport | None = None,
    ) -> None:
        self._public_discovery = public_discovery
        self._page_transport = page_transport or SafePublicPageTransport()

    @property
    def registered_tools(self) -> frozenset[str]:
        return REGISTERED_TOOLS

    @property
    def implemented_tools(self) -> frozenset[str]:
        return IMPLEMENTED_TOOLS

    def execute(self, task: FrontierTaskRecord) -> ToolExecution:
        """Dispatch one already-claimed task or return a truthful non-execution state."""

        if task.task_type not in REGISTERED_TOOLS:
            return ToolExecution(state="FAILED_TERMINAL", reason="TOOL_NOT_REGISTERED")
        if task.task_type not in IMPLEMENTED_TOOLS:
            return ToolExecution(state="REVIEW_REQUIRED", reason="TOOL_NOT_IMPLEMENTED")
        if task.task_type in {"SEARCH_WEB", "QUERY_GITHUB"}:
            return self._search(task)
        return self._fetch(task)

    def _search(self, task: FrontierTaskRecord) -> ToolExecution:
        """Translate one frontier task into an existing bounded provider adapter call."""

        provider = (
            PublicDiscoveryProvider.GITHUB_USERS
            if task.task_type == "QUERY_GITHUB"
            else PublicDiscoveryProvider.DUCKDUCKGO_HTML
        )
        sensitivity = Sensitivity.SENSITIVE if "@" in task.payload else Sensitivity.PUBLIC
        try:
            response = self._public_discovery.search(
                PublicDiscoveryRequest(
                    provider=provider,
                    query=task.payload,
                    sensitivity=sensitivity,
                    authorized_self_audit=True,
                    max_results=10,
                )
            )
        except (LookupError, ValueError):
            return ToolExecution(state="FAILED_TERMINAL", reason="INVALID_PROVIDER_REQUEST")
        state = {
            PublicDiscoveryState.SUCCEEDED: (
                "SUCCEEDED_RESULTS" if response.results else "SUCCEEDED_EMPTY"
            ),
            PublicDiscoveryState.RATE_LIMITED: "RATE_LIMITED",
            PublicDiscoveryState.ACCESS_BLOCKED: "BLOCKED",
            PublicDiscoveryState.NOT_CHECKED: "BLOCKED",
            PublicDiscoveryState.FAILED: "FAILED_RETRYABLE",
        }[response.state]
        results = tuple(
            SearchResultDraft(
                provider_id=result.provider.value,
                rank=result.rank,
                category=classify_url(result.url),
                url=result.url,
                title=result.title,
                snippet=result.snippet or "No provider snippet was returned.",
            )
            for result in response.results
        )
        return ToolExecution(state=state, reason=response.reason.value, search_results=results)

    def _fetch(self, task: FrontierTaskRecord) -> ToolExecution:
        """Fetch and parse one public page while preserving blocked/error distinctions."""

        try:
            url = normalise_public_result_url(task.payload)
            response = self._page_transport.fetch(
                url, timeout_seconds=10.0, max_bytes=MAX_PAGE_BYTES
            )
        except PageFetchError as error:
            return ToolExecution(
                state="FAILED_RETRYABLE"
                if error.code in {"TIMEOUT", "NETWORK_UNAVAILABLE"}
                else "BLOCKED",
                reason=error.code,
            )
        except (OSError, TimeoutError, urllib.error.URLError):
            return ToolExecution(state="FAILED_RETRYABLE", reason="NETWORK_UNAVAILABLE")
        except ValueError:
            return ToolExecution(state="BLOCKED", reason="UNSAFE_OR_INVALID_URL")
        if 300 <= response.status_code <= 399:
            return ToolExecution(state="BLOCKED", reason="REDIRECT_REFUSED")
        if response.status_code in {401, 403}:
            return ToolExecution(state="AUTH_REQUIRED", reason="AUTH_REQUIRED")
        if response.status_code == 429:
            return ToolExecution(state="RATE_LIMITED", reason="UPSTREAM_RATE_LIMITED")
        if response.status_code < 200 or response.status_code >= 300:
            return ToolExecution(state="FAILED_RETRYABLE", reason="UPSTREAM_REJECTED")
        if response.content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            return ToolExecution(state="REVIEW_REQUIRED", reason="UNSUPPORTED_CONTENT_TYPE")
        try:
            text = response.body.decode("utf-8", errors="strict")
        except UnicodeError:
            return ToolExecution(state="FAILED_TERMINAL", reason="INVALID_ENCODING")
        page = parse_public_page(url, text, response.status_code)
        return ToolExecution(state="SUCCEEDED_RESULTS", reason="COMPLETE", page=page)


class _PageParser(HTMLParser):
    """Non-rendering, event-bounded text/link extractor for untrusted public HTML."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._in_title = False
        self._ignored_depth = 0
        self._events = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tick()
        lowered = tag.casefold()
        if lowered in {"script", "style", "noscript", "svg", "canvas"}:
            self._ignored_depth += 1
            return
        if lowered == "title":
            self._in_title = True
        if lowered == "a" and self._ignored_depth == 0 and len(self.links) < MAX_LINKS * 4:
            href = next((value for name, value in attrs if name.casefold() == "href"), None)
            if href:
                with suppress(ValueError):
                    self.links.append(normalise_public_result_url(urljoin(self.base_url, href)))

    def handle_endtag(self, tag: str) -> None:
        self._tick()
        lowered = tag.casefold()
        if lowered == "title":
            self._in_title = False
        if lowered in {"script", "style", "noscript", "svg", "canvas"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        self._tick()
        if self._ignored_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        if sum(len(part) for part in self.text_parts) < MAX_PAGE_TEXT:
            self.text_parts.append(cleaned)

    def _tick(self) -> None:
        self._events += 1
        if self._events > MAX_HTML_EVENTS:
            raise PageFetchError("HTML_EVENT_LIMIT")


def parse_public_page(url: str, html: str, status_code: int) -> FetchedPageDraft:
    """Produce bounded evidence and review proposals; never promote extracted facts."""

    parser = _PageParser(url)
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, PageFetchError):
        raise PageFetchError("INVALID_HTML") from None
    title = normalise_result_text(" ".join(parser.title_parts), maximum=240, required=False)
    text = " ".join(parser.text_parts)
    excerpt = normalise_result_text(text, maximum=600, required=False) or "No text extracted."
    category = classify_url(url, page_text=text[:10_000])
    links = _rank_links(url, parser.links)
    proposals: list[ExtractedProposalDraft] = []
    bounded_text = text[:MAX_PAGE_TEXT]
    try:
        compilation = compile_text(
            bounded_text,
            limits=ExtractionLimits(
                max_text_bytes=MAX_PAGE_TEXT * 4,
                max_restricted_items=64,
                max_candidate_occurrences=512,
                max_candidates=128,
                max_value_chars=2048,
            ),
        )
    except ValueError:
        compilation = None
    if compilation is not None:
        for candidate in compilation.candidates[:64]:
            if candidate.entity_type.value not in {
                "EMAIL",
                "USERNAME",
                "DOMAIN",
                "URL",
                "TELEPHONE",
            }:
                continue
            first_span = candidate.spans[0]
            proposals.append(
                ExtractedProposalDraft(
                    entity_type=candidate.entity_type.value,
                    canonical_value=candidate.canonical_value,
                    display_value=candidate.display_mask,
                    source_url=url,
                    source_span_start=first_span.start,
                    source_span_end=first_span.end,
                    confidence_micros=min(candidate.confidence_micros, 850_000),
                    supporting_signals=("EXACT_PAGE_SPAN", category),
                )
            )
    return FetchedPageDraft(
        url=url,
        title=title or urlsplit(url).hostname or "Public page",
        text_excerpt=excerpt,
        content_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        http_status=status_code,
        category=category,
        links=links,
        proposals=tuple(proposals),
    )


def classify_url(url: str, *, page_text: str = "") -> str:
    """Apply explainable category hints used for prioritization, not attribution."""

    lowered = f"{url} {page_text[:4000]}".casefold()
    if any(
        token in lowered
        for token in ("forum", "thread", "member.php", "viewtopic", "discourse", "xenforo", "phpbb")
    ):
        return "FORUM"
    if any(token in lowered for token in ("github.com", "gitlab.com", "gist.github")):
        return "CODE"
    if any(token in lowered for token in ("web.archive.org", "archive.today", "archive.is")):
        return "ARCHIVE"
    if any(token in lowered for token in (".pdf", "/document", "/docs/")):
        return "DOCUMENT"
    if any(
        token in lowered
        for token in (
            "instagram.com",
            "facebook.com",
            "linkedin.com",
            "tiktok.com",
            "twitter.com",
            "x.com/",
            "mastodon",
        )
    ):
        return "SOCIAL"
    if any(
        token in lowered for token in ("registry", "gazette", "government", ".gov.", ".europa.eu")
    ):
        return "PUBLIC_RECORD"
    if any(token in lowered for token in ("youtube.com", "vimeo.com", "flickr.com")):
        return "MEDIA"
    return "WEBSITE"


def _rank_links(base_url: str, links: list[str]) -> tuple[str, ...]:
    """Favor bounded same-site/profile paths and exclude obvious state-changing links."""

    base_host = urlsplit(base_url).hostname
    blocked_tokens = (
        "logout",
        "login",
        "signin",
        "register",
        "reply",
        "delete",
        "admin",
        "session=",
    )
    preferred_tokens = (
        "profile",
        "member",
        "user",
        "author",
        "thread",
        "post",
        "archive",
        "rss",
        "feed",
        "about",
        "contact",
    )
    unique = tuple(
        dict.fromkeys(
            link for link in links if not any(token in link.casefold() for token in blocked_tokens)
        )
    )

    def score(link: str) -> tuple[int, int, str]:
        lowered = link.casefold()
        same_host = int(urlsplit(link).hostname == base_host)
        preferred = sum(token in lowered for token in preferred_tokens)
        return (-same_host, -preferred, link)

    return tuple(sorted(unique, key=score)[:MAX_LINKS])


def _require_public_dns(url: str) -> None:
    """Reject a URL unless its current DNS answers are globally routable addresses."""

    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ValueError("public page host is invalid")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                host, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        }
    except (OSError, ValueError) as error:
        raise PageFetchError("NETWORK_UNAVAILABLE") from error
    if not addresses or any(
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        for address in addresses
    ):
        raise ValueError("public page resolved to a non-public address")
