from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.hibp import HibpHttpRequest, HibpHttpResponse
from ariadne_core.infrastructure.logging import configure_logging
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4891"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(reversed(range(32)))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()
API_KEY = "b" * 32
EMAIL = "morgan.api@ariadne-example.invalid"
DOMAIN = "ariadne-example.invalid"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ScriptedHibpTransport:
    def __init__(self, responses: Iterable[HibpHttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[HibpHttpRequest] = []

    def send(self, request: HibpHttpRequest) -> HibpHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected HIBP request")
        return self.responses.pop(0)


def _json_response(payload: object, *, status: int = 200, retry_after: int | None = None):
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),)
    if retry_after is not None:
        headers += (("Retry-After", str(retry_after)),)
    return HibpHttpResponse(
        status_code=status,
        headers=headers,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )


def _app(transport: ScriptedHibpTransport) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            hibp_transport=transport,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


@pytest.mark.anyio
async def test_hibp_k_anonymity_api_is_authenticated_exact_and_secret_safe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    digest = hashlib.sha1(EMAIL.encode(), usedforsecurity=False).hexdigest().upper()
    transport = ScriptedHibpTransport(
        [
            _json_response(
                [
                    {
                        "hashSuffix": digest[6:],
                        "websites": ["SyntheticApiBreach"],
                    }
                ]
            )
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/hibp/account",
            json={
                "email": EMAIL,
                "apiKey": API_KEY,
                "mode": "K_ANONYMITY",
                "authorizedSelfAudit": True,
                "authorizedDirectIdentifierTransmission": False,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "HAVE_I_BEEN_PWNED_V3"
    assert payload["attribution"] == "Have I Been Pwned"
    assert payload["state"] == "SUCCEEDED"
    assert payload["breaches"] == [
        {
            "name": "SyntheticApiBreach",
            "sourceUrl": ("https://haveibeenpwned.com/api/v3/breach/SyntheticApiBreach"),
        }
    ]
    metadata = payload["requests"][0]
    assert metadata["requestUrl"].endswith(f"/breachedaccount/range/{digest[:6]}")
    assert metadata["identifierDisclosure"] == "PARTIAL_SHA1_PREFIX"
    assert metadata["apiKeySent"] is True
    assert metadata["redirectsFollowed"] is False
    assert EMAIL not in response.text
    assert API_KEY not in response.text
    assert EMAIL not in repr(transport.requests[0])
    assert API_KEY not in repr(transport.requests[0])
    logs = capsys.readouterr().err
    assert EMAIL not in logs
    assert API_KEY not in logs
    assert "/v1/discovery/hibp/account" in logs


@pytest.mark.anyio
async def test_hibp_domain_api_verifies_subscription_before_returning_aliases() -> None:
    transport = ScriptedHibpTransport(
        [
            _json_response([{"DomainName": DOMAIN, "PwnCount": 1}]),
            _json_response({"synthetic.api": ["SyntheticDomainBreach"]}),
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/hibp/domain",
            json={
                "domain": DOMAIN,
                "apiKey": API_KEY,
                "authorizedSelfAudit": True,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["providerVerifiedDomain"] is True
    assert payload["accounts"] == [
        {
            "alias": "synthetic.api",
            "breaches": [
                {
                    "name": "SyntheticDomainBreach",
                    "sourceUrl": ("https://haveibeenpwned.com/api/v3/breach/SyntheticDomainBreach"),
                }
            ],
        }
    ]
    assert [item["operation"] for item in payload["requests"]] == [
        "VERIFY_SUBSCRIBED_DOMAIN",
        "DOMAIN_ENUMERATION",
    ]
    assert transport.requests[0].url.endswith("/subscribedDomains")
    assert transport.requests[1].url.endswith(f"/breachedDomain/{DOMAIN}")
    assert API_KEY not in response.text


@pytest.mark.anyio
async def test_unverified_domain_never_dispatches_enumeration() -> None:
    transport = ScriptedHibpTransport([_json_response([{"DomainName": "other-synthetic.invalid"}])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/hibp/domain",
            json={
                "domain": DOMAIN,
                "apiKey": API_KEY,
                "authorizedSelfAudit": True,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["reason"] == "DOMAIN_NOT_PROVIDER_VERIFIED"
    assert len(transport.requests) == 1


@pytest.mark.anyio
async def test_hibp_api_honors_retry_after_without_hidden_retry() -> None:
    transport = ScriptedHibpTransport(
        [_json_response({"message": "synthetic rate limit"}, status=429, retry_after=9)]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/hibp/account",
            json={
                "email": EMAIL,
                "apiKey": API_KEY,
                "mode": "K_ANONYMITY",
                "authorizedSelfAudit": True,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["state"] == "RATE_LIMITED"
    assert response.json()["retryAfterSeconds"] == 9
    assert len(transport.requests) == 1


@pytest.mark.anyio
async def test_investigation_plan_api_composes_without_dispatch_or_value_echo() -> None:
    transport = ScriptedHibpTransport([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/investigation/plan",
            json={
                "identifiers": [
                    {
                        "identifierRef": "email-primary",
                        "kind": "EMAIL",
                        "value": EMAIL,
                    },
                    {
                        "identifierRef": "username-primary",
                        "kind": "USERNAME",
                        "value": "synthetic_api_handle",
                    },
                ],
                "enabledProviders": [
                    "DUCKDUCKGO_HTML",
                    "GITHUB_USERS",
                    "HAVE_I_BEEN_PWNED_V3",
                ],
                "authorizedSelfAudit": True,
                "hibpApiKeyAvailable": True,
                "hibpKAnonymityAvailable": True,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deterministic"] is True
    assert payload["executed"] is False
    assert [item["operation"] for item in payload["steps"]] == [
        "PUBLIC_WEB_SEARCH",
        "HIBP_EMAIL_K_ANONYMITY",
        "PUBLIC_WEB_SEARCH",
        "GITHUB_USER_SEARCH",
    ]
    assert all(item["executesDuringCompilation"] is False for item in payload["steps"])
    assert EMAIL not in response.text
    assert "synthetic_api_handle" not in response.text
    assert transport.requests == []


@pytest.mark.anyio
async def test_invalid_api_key_is_rejected_without_echo_or_dispatch() -> None:
    invalid = "synthetic-invalid-key"
    transport = ScriptedHibpTransport([])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/discovery/hibp/account",
            json={
                "email": EMAIL,
                "apiKey": invalid,
                "mode": "K_ANONYMITY",
                "authorizedSelfAudit": True,
            },
            headers=_headers(),
        )

    assert response.status_code == 400
    assert invalid not in response.text
    assert transport.requests == []
