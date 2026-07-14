from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.public_discovery import (
    PublicDiscoveryHttpRequest,
    PublicDiscoveryHttpResponse,
)
from ariadne_core.infrastructure.logging import configure_logging
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4891"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(reversed(range(32)))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ScriptedTransport:
    def __init__(self, responses: Iterable[PublicDiscoveryHttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[PublicDiscoveryHttpRequest] = []

    def send(self, request: PublicDiscoveryHttpRequest) -> PublicDiscoveryHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected public discovery request")
        return self.responses.pop(0)


def _app(transport: ScriptedTransport) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            public_discovery_transport=transport,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


def _html_response() -> PublicDiscoveryHttpResponse:
    return PublicDiscoveryHttpResponse(
        status_code=200,
        headers=(("Content-Type", "text/html; charset=UTF-8"),),
        body=(
            b'<div class="result"><a class="result__a" '
            b'href="https://public.example.com/synthetic-profile">Synthetic profile</a>'
            b'<div class="result__snippet">Bounded public result.</div></div>'
        ),
    )


def _github_response() -> PublicDiscoveryHttpResponse:
    return PublicDiscoveryHttpResponse(
        status_code=200,
        headers=(
            ("Content-Type", "application/vnd.github+json"),
            ("X-RateLimit-Remaining", "42"),
        ),
        body=json.dumps(
            {
                "total_count": 1,
                "incomplete_results": False,
                "items": [
                    {
                        "login": "ariadne-synthetic-api-404",
                        "html_url": "https://github.com/ariadne-synthetic-api-404",
                        "type": "User",
                    }
                ],
            },
            separators=(",", ":"),
        ).encode(),
    )


@pytest.mark.anyio
async def test_public_search_is_authenticated_bounded_and_query_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    query = "ariadne-sensitive-synthetic-query-401"
    transport = ScriptedTransport([_html_response()])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/public/search",
            json={
                "provider": "DUCKDUCKGO_HTML",
                "query": query,
                "authorizedSelfAudit": True,
                "maxResults": 2,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "DUCKDUCKGO_HTML",
        "state": "SUCCEEDED",
        "reason": "COMPLETE",
        "results": [
            {
                "provider": "DUCKDUCKGO_HTML",
                "rank": 1,
                "title": "Synthetic profile",
                "url": "https://public.example.com/synthetic-profile",
                "snippet": "Bounded public result.",
                "sourceId": None,
            }
        ],
        "totalEstimate": 1,
        "rateLimitRemaining": None,
        "truncated": False,
        "externalRequestMade": True,
        "authorizationConfirmed": True,
        "humanReviewRequired": True,
    }
    assert len(transport.requests) == 1
    assert query.encode() in (transport.requests[0].body or b"")
    assert query not in repr(transport.requests[0])
    assert query not in response.text
    logs = capsys.readouterr().err
    assert "discovery.public.search" not in logs
    assert query not in logs
    assert "/v1/discovery/public/search" in logs


@pytest.mark.anyio
async def test_public_search_requires_explicit_self_audit_without_dispatch() -> None:
    transport = ScriptedTransport([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/public/search",
            json={
                "provider": "GITHUB_USERS",
                "query": "ariadne-synthetic-no-dispatch-402",
                "authorizedSelfAudit": False,
                "maxResults": 5,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["state"] == "NOT_CHECKED"
    assert response.json()["reason"] == "SELF_AUDIT_AUTHORIZATION_REQUIRED"
    assert response.json()["externalRequestMade"] is False
    assert transport.requests == []


@pytest.mark.anyio
async def test_public_search_preserves_structured_github_provenance() -> None:
    transport = ScriptedTransport([_github_response()])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/public/search",
            json={
                "provider": "GITHUB_USERS",
                "query": "ariadne-synthetic-api-404",
                "authorizedSelfAudit": True,
                "maxResults": 1,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["provider"] == "GITHUB_USERS"
    assert item["url"] == "https://github.com/ariadne-synthetic-api-404"
    assert item["sourceId"] == "ariadne-synthetic-api-404"


@pytest.mark.anyio
async def test_public_search_rejects_client_sensitivity_without_echoing_query() -> None:
    query = "ariadne-synthetic-rejected-403"
    transport = ScriptedTransport([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/public/search",
            json={
                "provider": "DUCKDUCKGO_HTML",
                "query": query,
                "sensitivity": "PUBLIC",
                "authorizedSelfAudit": True,
                "maxResults": 5,
            },
            headers=_headers(),
        )

    assert response.status_code == 400
    assert query not in response.text
    assert transport.requests == []


@pytest.mark.anyio
async def test_public_discovery_capability_is_available_without_a_vault() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(ScriptedTransport([]))),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/system/capabilities", headers=_headers())

    assert response.status_code == 200
    statuses = {item["key"]: item["status"] for item in response.json()["features"]}
    assert statuses["public_discovery"] == "AVAILABLE"
