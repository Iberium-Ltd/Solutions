from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterable
from typing import cast
from urllib.parse import parse_qs

import pytest
from pydantic import ValidationError

from ariadne_core.api.public_discovery_schemas import (
    PublicDiscoverySearchRequest,
    PublicDiscoverySearchResult,
)
from ariadne_core.application.public_discovery import (
    DuckDuckGoHtmlAdapter,
    GitHubPublicUserAdapter,
    PublicDiscoveryHttpRequest,
    PublicDiscoveryHttpResponse,
    PublicDiscoveryService,
    PublicDiscoveryTransportError,
    PublicDiscoveryTransportErrorCode,
    UrllibPublicDiscoveryTransport,
)
from ariadne_core.domain.public_discovery import (
    PublicDiscoveryLimits,
    PublicDiscoveryProvider,
    PublicDiscoveryReason,
    PublicDiscoveryRequest,
    PublicDiscoveryState,
    normalise_public_result_url,
)
from ariadne_core.domain.query_policy import Sensitivity


class RecordingTransport:
    def __init__(
        self,
        responses: Iterable[PublicDiscoveryHttpResponse | Exception],
    ) -> None:
        self.responses = list(responses)
        self.requests: list[PublicDiscoveryHttpRequest] = []

    def send(self, request: PublicDiscoveryHttpRequest) -> PublicDiscoveryHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected public-discovery request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _request(
    provider: PublicDiscoveryProvider,
    *,
    query: str = "ariadne-synthetic-000",
    sensitivity: Sensitivity = Sensitivity.PUBLIC,
    authorized: bool = True,
    maximum: int = 10,
) -> PublicDiscoveryRequest:
    return PublicDiscoveryRequest(
        provider=provider,
        query=query,
        sensitivity=sensitivity,
        authorized_self_audit=authorized,
        max_results=maximum,
    )


def _html_response(body: str, *, status: int = 200) -> PublicDiscoveryHttpResponse:
    return PublicDiscoveryHttpResponse(
        status_code=status,
        headers=(("Content-Type", "text/html; charset=UTF-8"),),
        body=body.encode(),
    )


def _github_response(
    payload: object,
    *,
    status: int = 200,
    remaining: int | None = 59,
) -> PublicDiscoveryHttpResponse:
    headers: tuple[tuple[str, str], ...] = (
        ("Content-Type", "application/vnd.github+json; charset=utf-8"),
    )
    if remaining is not None:
        headers += (("X-RateLimit-Remaining", str(remaining)),)
    return PublicDiscoveryHttpResponse(
        status_code=status,
        headers=headers,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


@pytest.mark.parametrize("provider", list(PublicDiscoveryProvider))
def test_authorization_and_restricted_values_block_before_dispatch(
    provider: PublicDiscoveryProvider,
) -> None:
    transport = RecordingTransport([])
    service = PublicDiscoveryService(transport=transport)

    unauthorized = service.search(_request(provider, authorized=False))
    restricted = service.search(_request(provider, sensitivity=Sensitivity.RESTRICTED))

    assert unauthorized.state is PublicDiscoveryState.NOT_CHECKED
    assert unauthorized.reason is PublicDiscoveryReason.SELF_AUDIT_AUTHORIZATION_REQUIRED
    assert unauthorized.external_request_made is False
    assert restricted.state is PublicDiscoveryState.ACCESS_BLOCKED
    assert restricted.reason is PublicDiscoveryReason.RESTRICTED_VALUE
    assert restricted.external_request_made is False
    assert transport.requests == []


def test_provider_catalog_discloses_public_external_query_transmission() -> None:
    metadata = PublicDiscoveryService(transport=RecordingTransport([])).provider_metadata

    assert {item.provider for item in metadata} == set(PublicDiscoveryProvider)
    assert all(item.access_basis.value == "PUBLIC" for item in metadata)
    assert all(item.external and item.network_access and item.sends_query for item in metadata)
    assert all(not item.credentials_required and not item.retention_known for item in metadata)


def test_queries_are_normalised_and_hidden_from_routine_representations() -> None:
    secret = "ariadne-synthetic-query-000"
    request = _request(
        PublicDiscoveryProvider.DUCKDUCKGO_HTML,
        query=f"  {secret}\n value  ",
    )
    transport = RecordingTransport([_html_response("<html><body>No results.</body></html>")])

    result = DuckDuckGoHtmlAdapter(transport=transport).search(request)

    assert request.query == f"{secret} value"
    assert secret not in repr(request)
    assert secret not in repr(transport.requests[0])
    assert secret not in repr(result)
    assert result.reason is PublicDiscoveryReason.NO_RESULTS


def test_duckduckgo_html_results_are_unwrapped_sanitised_deduplicated_and_bounded() -> None:
    html = (
        '<html><body><div class="result"><a class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpublic.example.com%2Fprofile%23bio">'
        'Synthetic <b>Profile</b></a><a class="result__snippet">'
        "A synthetic &amp; bounded\n snippet.</a></div>"
        '<div class="result"><a class="result__a" '
        'href="https://PUBLIC.EXAMPLE.ORG:443/second">Second result</a>'
        '<div class="result__snippet">Second snippet</div></div>'
        '<div class="result"><a class="result__a" '
        'href="https://public.example.com/profile">Duplicate</a></div></body></html>'
    )
    transport = RecordingTransport([_html_response(html)])

    result = DuckDuckGoHtmlAdapter(transport=transport).search(
        _request(PublicDiscoveryProvider.DUCKDUCKGO_HTML, maximum=2)
    )

    assert result.state is PublicDiscoveryState.SUCCEEDED
    assert result.reason is PublicDiscoveryReason.PARTIAL_RESULTS
    assert result.truncated is True
    assert [(item.rank, item.title, item.url, item.snippet) for item in result.results] == [
        (
            1,
            "Synthetic Profile",
            "https://public.example.com/profile",
            "A synthetic & bounded snippet.",
        ),
        (
            2,
            "Second result",
            "https://public.example.org/second",
            "Second snippet",
        ),
    ]
    wire = transport.requests[0]
    assert wire.method == "POST"
    assert wire.url == "https://html.duckduckgo.com/html/"
    assert wire.bound_host == "html.duckduckgo.com"
    assert parse_qs((wire.body or b"").decode()) == {"q": ["ariadne-synthetic-000"]}
    assert all(name.casefold() not in {"authorization", "cookie"} for name, _ in wire.headers)


def test_duckduckgo_reports_challenge_without_retry_or_bypass() -> None:
    transport = RecordingTransport(
        [_html_response('<form id="challenge-form"><input name="captcha"></form>')]
    )

    result = DuckDuckGoHtmlAdapter(transport=transport).search(
        _request(PublicDiscoveryProvider.DUCKDUCKGO_HTML)
    )

    assert result.state is PublicDiscoveryState.ACCESS_BLOCKED
    assert result.reason is PublicDiscoveryReason.CAPTCHA_OR_CHALLENGE
    assert result.results == ()
    assert len(transport.requests) == 1


def test_duckduckgo_preserves_status_precedence_and_recognises_202_challenge() -> None:
    challenge = '<form id="challenge-form"><input name="captcha"></form>'
    rate_limited = DuckDuckGoHtmlAdapter(
        transport=RecordingTransport([_html_response(challenge, status=429)])
    ).search(_request(PublicDiscoveryProvider.DUCKDUCKGO_HTML))
    challenged = DuckDuckGoHtmlAdapter(
        transport=RecordingTransport([_html_response(challenge, status=202)])
    ).search(_request(PublicDiscoveryProvider.DUCKDUCKGO_HTML))

    assert rate_limited.state is PublicDiscoveryState.RATE_LIMITED
    assert rate_limited.reason is PublicDiscoveryReason.UPSTREAM_RATE_LIMITED
    assert challenged.state is PublicDiscoveryState.ACCESS_BLOCKED
    assert challenged.reason is PublicDiscoveryReason.CAPTCHA_OR_CHALLENGE


@pytest.mark.parametrize(
    ("status", "state", "reason"),
    [
        (302, PublicDiscoveryState.ACCESS_BLOCKED, PublicDiscoveryReason.REDIRECT_REFUSED),
        (
            403,
            PublicDiscoveryState.ACCESS_BLOCKED,
            PublicDiscoveryReason.UPSTREAM_ACCESS_BLOCKED,
        ),
        (429, PublicDiscoveryState.RATE_LIMITED, PublicDiscoveryReason.UPSTREAM_RATE_LIMITED),
        (503, PublicDiscoveryState.FAILED, PublicDiscoveryReason.UPSTREAM_UNAVAILABLE),
        (422, PublicDiscoveryState.FAILED, PublicDiscoveryReason.UPSTREAM_REJECTED),
    ],
)
def test_duckduckgo_statuses_are_reported_honestly(
    status: int,
    state: PublicDiscoveryState,
    reason: PublicDiscoveryReason,
) -> None:
    adapter = DuckDuckGoHtmlAdapter(
        transport=RecordingTransport([_html_response("", status=status)])
    )

    result = adapter.search(_request(PublicDiscoveryProvider.DUCKDUCKGO_HTML))

    assert result.state is state
    assert result.reason is reason
    assert result.external_request_made is True


def test_response_limit_and_redacted_transport_errors_fail_closed() -> None:
    limited_transport = RecordingTransport(
        [
            PublicDiscoveryHttpResponse(
                status_code=200,
                headers=(("Content-Type", "text/html"),),
                body=b"x" * 33,
            )
        ]
    )
    limited = DuckDuckGoHtmlAdapter(
        transport=limited_transport,
        limits=PublicDiscoveryLimits(max_response_bytes=32),
    ).search(_request(PublicDiscoveryProvider.DUCKDUCKGO_HTML))
    secret_error = "synthetic-upstream-secret"
    failing_transport = RecordingTransport([RuntimeError(secret_error)])
    failed = DuckDuckGoHtmlAdapter(transport=failing_transport).search(
        _request(PublicDiscoveryProvider.DUCKDUCKGO_HTML)
    )

    assert limited.reason is PublicDiscoveryReason.RESPONSE_LIMIT
    assert failed.reason is PublicDiscoveryReason.NETWORK_UNAVAILABLE
    assert secret_error not in repr(failed)


def test_typed_timeout_is_mapped_without_leaking_transport_details() -> None:
    transport = RecordingTransport(
        [PublicDiscoveryTransportError(PublicDiscoveryTransportErrorCode.TIMEOUT)]
    )

    result = GitHubPublicUserAdapter(transport=transport).search(
        _request(PublicDiscoveryProvider.GITHUB_USERS)
    )

    assert result.state is PublicDiscoveryState.FAILED
    assert result.reason is PublicDiscoveryReason.TIMEOUT


def test_github_official_api_results_are_bound_normalised_and_rate_aware() -> None:
    payload = {
        "total_count": 2,
        "incomplete_results": False,
        "items": [
            {
                "login": "ariadne-synthetic-000",
                "html_url": "https://GITHUB.COM/ariadne-synthetic-000#readme",
                "type": "User",
            },
            {
                "login": "ariadne-synthetic-org",
                "html_url": "https://github.com/ariadne-synthetic-org",
                "type": "Organization",
            },
        ],
    }
    transport = RecordingTransport([_github_response(payload, remaining=41)])

    result = GitHubPublicUserAdapter(transport=transport).search(
        _request(PublicDiscoveryProvider.GITHUB_USERS, maximum=2)
    )

    assert result.state is PublicDiscoveryState.SUCCEEDED
    assert result.reason is PublicDiscoveryReason.COMPLETE
    assert result.rate_limit_remaining == 41
    assert result.total_estimate == 2
    assert [item.source_id for item in result.results] == [
        "ariadne-synthetic-000",
        "ariadne-synthetic-org",
    ]
    assert result.results[0].url == "https://github.com/ariadne-synthetic-000"
    wire = transport.requests[0]
    assert wire.method == "GET"
    assert wire.bound_host == "api.github.com"
    assert wire.url.startswith("https://api.github.com/search/users?")
    query = parse_qs(wire.url.split("?", maxsplit=1)[1])
    assert query == {
        "page": ["1"],
        "per_page": ["2"],
        "q": ["ariadne-synthetic-000"],
    }
    assert all(name.casefold() != "authorization" for name, _ in wire.headers)


def test_github_drops_untrusted_items_and_marks_partial_results() -> None:
    payload = {
        "total_count": 2,
        "incomplete_results": True,
        "items": [
            {
                "login": "ariadne-synthetic-000",
                "html_url": "https://github.com/ariadne-synthetic-000",
                "type": "User",
            },
            {
                "login": "off-host-synthetic",
                "html_url": "https://public.example.com/off-host-synthetic",
                "type": "User",
            },
        ],
    }
    result = GitHubPublicUserAdapter(
        transport=RecordingTransport([_github_response(payload)])
    ).search(_request(PublicDiscoveryProvider.GITHUB_USERS))

    assert result.state is PublicDiscoveryState.SUCCEEDED
    assert result.reason is PublicDiscoveryReason.PARTIAL_RESULTS
    assert result.truncated is True
    assert len(result.results) == 1


def test_github_distinguishes_rate_limit_access_block_and_invalid_response() -> None:
    rate_limited = GitHubPublicUserAdapter(
        transport=RecordingTransport([_github_response({}, status=403, remaining=0)])
    ).search(_request(PublicDiscoveryProvider.GITHUB_USERS))
    access_blocked = GitHubPublicUserAdapter(
        transport=RecordingTransport([_github_response({}, status=403, remaining=12)])
    ).search(_request(PublicDiscoveryProvider.GITHUB_USERS))
    invalid = GitHubPublicUserAdapter(
        transport=RecordingTransport([_github_response({"unexpected": True})])
    ).search(_request(PublicDiscoveryProvider.GITHUB_USERS))

    assert rate_limited.state is PublicDiscoveryState.RATE_LIMITED
    assert rate_limited.rate_limit_remaining == 0
    assert access_blocked.state is PublicDiscoveryState.ACCESS_BLOCKED
    assert invalid.state is PublicDiscoveryState.FAILED
    assert invalid.reason is PublicDiscoveryReason.INVALID_RESPONSE


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/result",
        "https://localhost/result",
        "https://user:secret" + "@public.example.com/result",
        "file:///tmp/result",
        "https://public.example.com/result\nsecond",
    ],
)
def test_result_url_normalisation_rejects_non_public_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        normalise_public_result_url(url)


def test_http_request_enforces_https_exact_host_and_no_credentials() -> None:
    common = {
        "method": "GET",
        "bound_host": "api.github.com",
        "headers": (("Accept", "application/json"),),
        "body": None,
        "timeout_seconds": 1.0,
        "max_response_bytes": 100,
    }
    with pytest.raises(ValueError, match="binding"):
        PublicDiscoveryHttpRequest(
            url="https://api.github.com.attacker.example/search/users",
            **common,
        )
    with pytest.raises(ValueError, match="headers"):
        PublicDiscoveryHttpRequest(
            url="https://api.github.com/search/users",
            **{**common, "headers": (("Authorization", "synthetic"),)},
        )


def test_production_transport_installs_empty_proxy_and_redirect_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: tuple[object, ...] = ()

    class SyntheticOpener:
        pass

    def capture(*items: object) -> SyntheticOpener:
        nonlocal handlers
        handlers = items
        return SyntheticOpener()

    monkeypatch.setattr(urllib.request, "build_opener", capture)

    transport = UrllibPublicDiscoveryTransport()

    assert transport is not None
    proxy = next(item for item in handlers if isinstance(item, urllib.request.ProxyHandler))
    redirect = next(
        item for item in handlers if isinstance(item, urllib.request.HTTPRedirectHandler)
    )
    assert cast(urllib.request.ProxyHandler, proxy).proxies == {}
    assert type(redirect) is not urllib.request.HTTPRedirectHandler


def test_strict_wire_schemas_normalise_input_and_never_echo_query() -> None:
    body = PublicDiscoverySearchRequest.model_validate(
        {
            "provider": "GITHUB_USERS",
            "query": "  ariadne-synthetic-000  ",
            "authorizedSelfAudit": True,
            "maxResults": 3,
        }
    )
    transport = RecordingTransport(
        [_github_response({"total_count": 0, "incomplete_results": False, "items": []})]
    )
    domain_result = PublicDiscoveryService(transport=transport).search(
        body.to_domain(sensitivity=Sensitivity.SENSITIVE)
    )
    wire_result = PublicDiscoverySearchResult.from_domain(domain_result)

    assert body.query == "ariadne-synthetic-000"
    assert "ariadne-synthetic-000" not in repr(body)
    assert wire_result.model_dump(by_alias=True) == {
        "provider": "GITHUB_USERS",
        "state": "SUCCEEDED",
        "reason": "NO_RESULTS",
        "results": (),
        "totalEstimate": 0,
        "rateLimitRemaining": 59,
        "truncated": False,
        "externalRequestMade": True,
        "authorizationConfirmed": True,
        "humanReviewRequired": True,
    }
    with pytest.raises(ValidationError):
        PublicDiscoverySearchRequest.model_validate(
            {
                "provider": "GITHUB_USERS",
                "query": "synthetic",
                "authorizedSelfAudit": True,
                "sensitivity": "PUBLIC",
            }
        )
