from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.models import audit_events, entities, entity_origins
from ariadne_core.local_ai import (
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpRequest,
    LocalAIHttpResponse,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4593"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ScriptedTransport:
    def __init__(self, responses: list[LocalAIHttpResponse | LocalAIError]) -> None:
        self.responses = responses
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, LocalAIError):
            raise response
        return response


def _json_response(payload: object) -> LocalAIHttpResponse:
    return LocalAIHttpResponse(200, json.dumps(payload).encode())


def _cipher_runtime() -> CipherRuntime:
    return CipherRuntime(
        sqlite_version="3.53.3",
        cipher_version="4.17.0 community",
        foreign_keys=True,
        journal_mode="delete",
        temp_store=2,
        fts5=True,
        json=True,
    )


def _app(manager: VaultManager, transport: ScriptedTransport) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            vault_manager=manager,
            key_lease_client=cast(KeyLeaseClient, object()),
            cipher_runtime=_cipher_runtime(),
            local_ai_transport=transport,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


async def _profile(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/profiles",
        json={
            "idempotencyKey": str(uuid4()),
            "displayLabel": "Synthetic local AI intake profile",
            "purpose": "Synthetic authorised local review",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


async def _enable_local_ai(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/local-ai/settings",
        json={
            "enabled": True,
            "provider": "OLLAMA",
            "endpoint": "http://127.0.0.1:11434",
            "selectedModel": "qwen-local:7b",
            "expectedRevision": 1,
        },
        headers=_headers(),
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_local_ai_settings_discovery_test_and_revisioned_selection(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic local AI settings vault")
    transport = ScriptedTransport(
        [
            _json_response({"models": [{"model": "qwen-local:7b"}]}),
            _json_response({"models": [{"model": "qwen-local:7b"}]}),
            _json_response({"model": "qwen-local:7b", "done": True}),
            _json_response({"model": "qwen-local:7b", "done": True}),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        capabilities = await client.get("/v1/system/capabilities", headers=_headers())
        assert {
            item["key"] for item in capabilities.json()["features"] if item["status"] == "AVAILABLE"
        } >= {"local_ai"}

        initial = await client.get("/v1/local-ai/settings", headers=_headers())
        assert initial.status_code == 200
        assert initial.json() == {
            "enabled": False,
            "provider": "OLLAMA",
            "endpoint": "http://127.0.0.1:11434",
            "selectedModel": None,
            "revision": 1,
        }

        discovery = await client.post(
            "/v1/local-ai/models",
            json={
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": None,
            },
            headers=_headers(),
        )
        assert discovery.status_code == 200
        assert discovery.json() == {"models": [{"provider": "OLLAMA", "modelId": "qwen-local:7b"}]}

        tested = await client.post(
            "/v1/local-ai/test",
            json={
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": "qwen-local:7b",
            },
            headers=_headers(),
        )
        assert tested.status_code == 200
        assert tested.json() == {
            "status": "AVAILABLE",
            "reachable": True,
            "modelCount": 1,
            "selectedModelAvailable": True,
        }
        assert transport.requests[2].url.endswith("/api/generate")
        assert json.loads(transport.requests[2].body or b"")["prompt"] == ""

        unloaded = await client.post(
            "/v1/local-ai/unload",
            json={
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": "qwen-local:7b",
            },
            headers=_headers(),
        )
        assert unloaded.status_code == 200
        assert unloaded.json() == {
            "provider": "OLLAMA",
            "modelId": "qwen-local:7b",
            "status": "UNLOADED",
        }
        assert json.loads(transport.requests[3].body or b"")["keep_alive"] == 0

        saved = await client.post(
            "/v1/local-ai/settings",
            json={
                "enabled": True,
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": "qwen-local:7b",
                "expectedRevision": 1,
            },
            headers=_headers(),
        )
        assert saved.status_code == 200
        assert saved.json()["selectedModel"] == "qwen-local:7b"
        assert saved.json()["enabled"] is True
        assert saved.json()["revision"] == 2

        stale = await client.post(
            "/v1/local-ai/settings",
            json={
                "enabled": False,
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": None,
                "expectedRevision": 1,
            },
            headers=_headers(),
        )
        assert stale.status_code == 409

        cleared = await client.post(
            "/v1/local-ai/settings",
            json={
                "enabled": False,
                "provider": "OPENAI_COMPATIBLE",
                "endpoint": "http://127.0.0.1:1234",
                "selectedModel": None,
                "expectedRevision": 2,
            },
            headers=_headers(),
        )
        assert cleared.status_code == 200
        assert cleared.json()["selectedModel"] is None
        assert cleared.json()["provider"] == "OPENAI_COMPATIBLE"

        assert [request.url for request in transport.requests] == [
            "http://127.0.0.1:11434/api/tags",
            "http://127.0.0.1:11434/api/tags",
            "http://127.0.0.1:11434/api/generate",
            "http://127.0.0.1:11434/api/generate",
        ]
    assert all(
        all(name.casefold() != "authorization" for name, _value in request.headers)
        for request in transport.requests
    )
    manager.lock()


@pytest.mark.anyio
async def test_local_ai_endpoints_reject_cloud_and_report_safe_connection_failure(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic local AI failure vault")
    transport = ScriptedTransport([LocalAIError(LocalAIErrorCode.TIMEOUT)])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        cloud = await client.post(
            "/v1/local-ai/models",
            json={
                "provider": "OPENAI_COMPATIBLE",
                "endpoint": "https://api.example.invalid/v1",
                "selectedModel": None,
            },
            headers=_headers(),
        )
        assert cloud.status_code == 400
        assert "api.example.invalid" not in cloud.text

        persisted_external = await client.post(
            "/v1/local-ai/settings",
            json={
                "enabled": True,
                "provider": "OPENAI_RESPONSES",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": "synthetic-openai-model",
                "expectedRevision": 1,
            },
            headers=_headers(),
        )
        assert persisted_external.status_code == 400

        failed = await client.post(
            "/v1/local-ai/test",
            json={
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": None,
            },
            headers=_headers(),
        )
        assert failed.status_code == 200
        assert failed.json() == {
            "status": "TIMEOUT",
            "reachable": False,
            "modelCount": 0,
            "selectedModelAvailable": None,
        }

    manager.lock()


@pytest.mark.anyio
async def test_selected_local_model_enriches_only_redacted_intake_and_requires_review(
    tmp_path: Path,
) -> None:
    secret = "synthetic-restricted-marker"
    surface = "Aurora Collective"
    content = (
        "Contact: synthetic.person@example.invalid.\n"
        f"Password: {secret}\n"
        f"Reference label: {surface}."
    )
    start = content.index(surface)
    model_output = {
        "entities": [
            {
                "entity_type": "ORGANISATION",
                "surface": surface,
                "start": start,
                "end": start + len(surface),
                "confidence_micros": 930_000,
                "explanation_code": "model.organisation.explicit",
            }
        ],
        "relationships": [],
    }
    transport = ScriptedTransport(
        [
            _json_response(
                {
                    "model": "qwen-local:7b",
                    "message": {"content": json.dumps(model_output)},
                }
            )
        ]
    )
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic selected-model intake vault")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        await _enable_local_ai(client)
        profile_id = await _profile(client)
        request = {
            "idempotencyKey": str(uuid4()),
            "profileId": profile_id,
            "displayName": "Synthetic AI-assisted paste",
            "content": content,
            "consentConfirmed": True,
            "retainRawSource": False,
            "semanticEnrichmentEnabled": True,
        }
        response = await client.post("/v1/intake/paste", json=request, headers=_headers())
        replay = await client.post("/v1/intake/paste", json=request, headers=_headers())
        assert response.status_code == replay.status_code == 200, response.text
        receipt = response.json()
        assert replay.json() == receipt
        assert receipt["localAiStatus"] == "SUCCEEDED"
        assert receipt["localAiProvider"] == "OLLAMA"
        assert receipt["localAiModel"] == "qwen-local:7b"
        assert receipt["localAiEngineVersion"] == "1"
        assert receipt["localAiSuggestionCount"] == 1

        review = await client.post(
            "/v1/intake/review",
            json={"profileId": profile_id, "sourceId": receipt["sourceId"], "limit": 100},
            headers=_headers(),
        )
        assert review.status_code == 200
        suggestion = next(
            item
            for item in review.json()["entities"]
            if item["provenanceLabel"].startswith("local-ai:")
        )
        assert suggestion["entityType"] == "ORGANISATION"
        assert suggestion["reviewState"] == "UNREVIEWED"
        assert suggestion["sensitivity"] == "PUBLIC"
        assert suggestion["temporalState"] == "CURRENT"
        assert suggestion["searchPolicy"] == "ALLOW"
        assert suggestion["transmissionPolicy"] == "POLICY_CONTROLLED"
        assert suggestion["confidenceMicros"] == 850_000

    assert len(transport.requests) == 1
    wire_body = (transport.requests[0].body or b"").decode()
    assert secret not in wire_body
    assert surface in wire_body
    assert json.loads(wire_body)["model"] == "qwen-local:7b"
    with manager.engine.connect() as connection:
        canonical_values = connection.execute(select(entities.c.canonical_value)).scalars().all()
        local_origin = (
            connection.execute(
                select(entity_origins).where(entity_origins.c.origin_kind == "LOCAL_MODEL")
            )
            .mappings()
            .one()
        )
        metadata_json = connection.execute(
            select(audit_events.c.metadata_json).where(
                audit_events.c.event_type == "INTAKE_COMPILATION_PERSISTED"
            )
        ).scalar_one()
    assert secret not in " ".join(str(value) for value in canonical_values)
    assert local_origin["source_span_start"] == start
    assert local_origin["source_span_end"] == start + len(surface)
    assert local_origin["explanation"].startswith("local-ai:v1:probable:review-required:")
    metadata = json.loads(metadata_json)
    assert metadata["localAIStatus"] == "SUCCEEDED"
    assert metadata["localAIProvider"] == "OLLAMA"
    assert metadata["localAIModel"] == "qwen-local:7b"
    assert metadata["localAISuggestionCount"] == 1
    manager.lock()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    (
        (LocalAIErrorCode.TIMEOUT, "TIMEOUT"),
        (LocalAIErrorCode.UNAVAILABLE, "UNAVAILABLE"),
        (LocalAIErrorCode.INVALID_RESPONSE, "INVALID_RESPONSE"),
    ),
)
async def test_local_ai_failure_keeps_deterministic_intake_ready(
    tmp_path: Path,
    error_code: LocalAIErrorCode,
    expected_status: str,
) -> None:
    manager = VaultManager(tmp_path / error_code.value, MemoryKeyCustodian())
    manager.create(display_name="Synthetic local AI fallback vault")
    transport = ScriptedTransport([LocalAIError(error_code)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        await _enable_local_ai(client)
        profile_id = await _profile(client)
        response = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": str(uuid4()),
                "profileId": profile_id,
                "displayName": "Synthetic deterministic fallback paste",
                "content": "Contact: fallback.person@example.invalid.",
                "consentConfirmed": True,
                "retainRawSource": False,
                "semanticEnrichmentEnabled": True,
            },
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["state"] == "READY_FOR_REVIEW"
        assert receipt["candidateCount"] >= 1
        assert receipt["localAiStatus"] == expected_status
        assert receipt["localAiSuggestionCount"] == 0
        assert receipt["localAiProvider"] == "OLLAMA"
        assert receipt["localAiModel"] == "qwen-local:7b"
    assert len(transport.requests) == 1
    manager.lock()
