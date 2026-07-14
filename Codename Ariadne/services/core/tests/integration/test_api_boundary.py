from __future__ import annotations

import base64
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4567"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app() -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
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
async def test_capabilities_are_truthful_and_have_no_host_inventory() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/system/capabilities", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["versions"] == {
        "contract": 1,
        "schema": "ariadne-v1",
        "events": 1,
        "core": "0.1.0",
    }
    assert body["transport"] == "DEV_LOOPBACK"
    assert body["cipher"] == {
        "required": "SQLCIPHER",
        "available": False,
        "sqliteVersion": None,
        "cipherVersion": None,
    }
    feature_status = {item["key"]: item["status"] for item in body["features"]}
    assert feature_status["authenticated_local_api"] == "AVAILABLE"
    assert feature_status["public_discovery"] == "AVAILABLE"
    assert all(
        status == "NOT_IMPLEMENTED"
        for key, status in feature_status.items()
        if key not in {"authenticated_local_api", "public_discovery"}
    )
    assert HOST not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_session_is_authenticated_locked_and_has_no_vault() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/session", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["lockState"] == "LOCKED"
    assert body["vaultState"] == "NO_VAULT"
    assert body["compatibility"] == "COMPATIBLE"
    assert body["authenticatedTransport"] is True
    assert body["sessionExpiresAt"] is not None
    assert body["activeRevealCapabilities"] == 0


@pytest.mark.anyio
async def test_runtime_documentation_endpoints_do_not_exist() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = await client.get(path, headers=_headers())
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "NOT_FOUND"
