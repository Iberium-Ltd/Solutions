from __future__ import annotations

import base64
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.infrastructure.logging import configure_logging
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4876"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(reversed(range(32)))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(*, ttl_seconds: float | None = 900) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=ttl_seconds),
        )
    )


def _headers(**changes: str) -> dict[str, str]:
    values = {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }
    values.update(changes)
    return values


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("changes", "expected_status", "expected_code"),
    [
        ({"Ariadne-Session": ""}, 401, "SESSION_EXPIRED"),
        ({"Ariadne-Session": "A" * 43}, 401, "SESSION_EXPIRED"),
        ({"Ariadne-Contract-Version": "2"}, 409, "SERVICE_UNAVAILABLE"),
        ({"Ariadne-Request-Id": "not-a-uuid"}, 400, "INVALID_REQUEST"),
        ({"Origin": "http://localhost:1420"}, 403, "POLICY_DENIED"),
    ],
)
async def test_boundary_rejects_invalid_metadata(
    changes: dict[str, str], expected_status: int, expected_code: str
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/session", headers=_headers(**changes))

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "input" not in response.text


@pytest.mark.anyio
async def test_rejects_wrong_host_forwarding_replay_and_request_body() -> None:
    app = _app()
    request_id = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        wrong_host = await client.get(
            "/v1/session",
            headers={**_headers(), "Host": "localhost:4876"},
        )
        forwarded = await client.get(
            "/v1/session",
            headers={**_headers(), "X-Forwarded-Host": HOST},
        )
        first = await client.get(
            "/v1/session",
            headers=_headers(**{"Ariadne-Request-Id": request_id}),
        )
        replay = await client.get(
            "/v1/session",
            headers=_headers(**{"Ariadne-Request-Id": request_id}),
        )
        body = await client.request(
            "GET",
            "/v1/session",
            headers=_headers(),
            content="synthetic-boundary-payload",
        )

    assert wrong_host.status_code == 403
    assert forwarded.status_code == 403
    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["message"]["messageCode"] == "request.replayed"
    assert body.status_code == 413


@pytest.mark.anyio
async def test_expired_session_fails_closed() -> None:
    app = _app(ttl_seconds=0.001)
    await __import__("anyio").sleep(0.01)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/session", headers=_headers())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.anyio
async def test_logs_exclude_token_body_unknown_path_and_headers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    unknown_path = "/unmatched/synthetic-sensitive-path"
    body_value = "synthetic-sensitive-request-body"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.request(
            "GET",
            unknown_path,
            headers=_headers(),
            content=body_value,
        )

    assert response.status_code == 413
    logs = capsys.readouterr().err
    assert "local_api_request" in logs
    assert TOKEN not in logs
    assert body_value not in logs
    assert unknown_path not in logs
    assert ORIGIN not in logs
    assert HOST not in logs
    assert "UNMATCHED" in logs


@pytest.mark.anyio
async def test_no_wildcard_cors_is_emitted() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.get("/v1/session", headers=_headers())

    assert response.headers.get("access-control-allow-origin") != "*"
