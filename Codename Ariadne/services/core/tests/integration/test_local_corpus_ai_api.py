from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app, create_contract_app
from ariadne_core.api.local_corpus_schemas import (
    MAX_LOCAL_CORPUS_API_REQUEST_BYTES,
    MAX_LOCAL_CORPUS_API_RESPONSE_BYTES,
)
from ariadne_core.api.middleware import ROUTE_POLICIES
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.local_ai import LocalAIHttpRequest, LocalAIHttpResponse
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4596"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class NoModelTransport:
    def __init__(self) -> None:
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        raise AssertionError("deterministic corpus analysis must not call a local model")


class ScriptedTransport(NoModelTransport):
    def __init__(self, responses: list[LocalAIHttpResponse]) -> None:
        super().__init__()
        self.responses = responses

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected model request")
        return self.responses.pop(0)


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


def _app(manager: VaultManager, transport: NoModelTransport) -> FastAPI:
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
            "displayLabel": "Synthetic corpus API profile",
            "purpose": "Synthetic cited multi-document API analysis",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


def _document(name: str, content: bytes) -> dict[str, object]:
    return {
        "displayName": name,
        "declaredMediaType": "application/json",
        "contentBase64": base64.b64encode(content).decode("ascii"),
        "expectedSizeBytes": len(content),
        "expectedSha256": hashlib.sha256(content).hexdigest(),
    }


def _request(profile_id: str) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "documents": [
            _document(
                "synthetic-current.json",
                (
                    b'{"email":"shared.api@example.invalid","location":"Sample City",'
                    b'"project":"Atlas Signal"}'
                ),
            ),
            _document(
                "synthetic-history.json",
                (
                    b'{"email":"shared.api@example.invalid","location":"Other City",'
                    b'"project":"Atlas Signal"}'
                ),
            ),
        ],
        "semanticEnrichmentEnabled": False,
        "task": "CONNECTIONS",
        "question": None,
        "execution": "DETERMINISTIC",
        "modelId": None,
        "maxSegments": 200,
    }


@pytest.mark.anyio
async def test_deterministic_corpus_route_is_repeatable_cited_and_response_bounded(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic corpus API vault")
    transport = NoModelTransport()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        first = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=_request(profile_id),
            headers=_headers(),
        )
        second = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=_request(profile_id),
            headers=_headers(),
        )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.content) <= MAX_LOCAL_CORPUS_API_RESPONSE_BYTES
    assert first.headers["cache-control"] == "no-store"
    result = first.json()
    assert result["profileId"] == profile_id
    assert result["executionMode"] == "DETERMINISTIC"
    assert result["externalNetworkUsed"] is False
    assert result["persisted"] is False
    assert result["connections"]
    catalog = {entry["referenceId"]: entry for entry in result["sourceCatalog"]}
    cited = {
        reference
        for connection in result["connections"]
        for reference in (
            connection["fromRef"],
            connection["toRef"],
            *connection["sharedEntityRefs"],
            *connection["supportingRefs"],
            *connection["contradictionRefs"],
        )
    }
    assert cited.issubset(catalog)
    for reference in cited:
        for source in catalog[reference]["sources"]:
            assert source["documentId"]
            assert source["documentName"].startswith("synthetic-")
            assert source["segmentId"]
            assert source["segmentIndex"] >= 0
            assert source["locator"]
    assert transport.requests == []
    manager.lock()


@pytest.mark.anyio
async def test_openai_corpus_route_is_ephemeral_aliased_and_exactly_cited(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic OpenAI corpus API vault")
    model_reference = "segment:s0001"
    alias = f"source_alias:{hashlib.sha256(model_reference.encode()).hexdigest()[:32]}"
    model_output = {
        "title": "Synthetic external corpus summary",
        "summary": "One bounded source segment is available for review.",
        "sections": [],
        "facts": [
            {
                "statement": "The selected corpus contains a cited synthetic segment.",
                "evidence_refs": [alias],
                "confidence": "HIGH",
            }
        ],
        "connections": [],
        "next_steps": [],
        "unanswered": None,
        "limitations": ["Human review remains required."],
    }
    transport = ScriptedTransport(
        [
            LocalAIHttpResponse(
                200,
                json.dumps(
                    {
                        "model": "synthetic-openai-model",
                        "output": [
                            {
                                "content": [
                                    {
                                        "text": json.dumps(model_output),
                                        "type": "output_text",
                                    }
                                ],
                                "role": "assistant",
                                "status": "completed",
                                "type": "message",
                            }
                        ],
                        "status": "completed",
                    }
                ).encode(),
            )
        ]
    )
    ephemeral_key = "synthetic_ephemeral_openai_key"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        request = _request(profile_id)
        request.update(
            {
                "execution": "OPENAI_RESPONSES",
                "modelId": "synthetic-openai-model",
                "openaiApiKey": ephemeral_key,
                "task": "SUMMARY",
            }
        )
        response = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=request,
            headers=_headers(),
        )

    assert response.status_code == 200
    result = response.json()
    assert result["executionMode"] == "OPENAI_RESPONSES"
    assert result["provider"] == "OPENAI_RESPONSES"
    assert result["modelId"] == "synthetic-openai-model"
    assert result["externalNetworkUsed"] is True
    assert result["localOnly"] is False
    assert result["facts"][0]["origin"] == "OPENAI_RESPONSES"
    exact_reference = result["facts"][0]["evidenceRefs"][0]
    assert exact_reference.startswith("corpus-document:")
    assert exact_reference in {entry["referenceId"] for entry in result["sourceCatalog"]}
    assert ephemeral_key not in response.text
    wire_request = transport.requests[0]
    wire_payload = json.loads(wire_request.body or b"")
    prompt = json.dumps(wire_payload["input"])
    assert alias in prompt
    assert model_reference not in prompt
    assert ephemeral_key not in repr(wire_request)
    manager.lock()


@pytest.mark.anyio
async def test_corpus_route_requires_authentication_unlocked_vault_and_existing_profile(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic corpus scope vault")
    transport = NoModelTransport()
    app = _app(manager, transport)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        unauthenticated_headers = _headers()
        unauthenticated_headers.pop("Ariadne-Session")
        unauthenticated = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=_request(profile_id),
            headers=unauthenticated_headers,
        )
        missing = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=_request("22222222-2222-4222-8222-222222222222"),
            headers=_headers(),
        )
        manager.lock()
        locked = await client.post(
            "/v1/local-ai/corpus/analyze",
            json=_request(profile_id),
            headers=_headers(),
        )

    assert unauthenticated.status_code == 401
    assert missing.status_code == 404
    assert locked.status_code == 409
    assert transport.requests == []


@pytest.mark.anyio
async def test_corpus_route_rejects_payload_over_exact_middleware_limit(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic corpus limit vault")
    transport = NoModelTransport()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/local-ai/corpus/analyze",
            content=b"x" * (MAX_LOCAL_CORPUS_API_REQUEST_BYTES + 1),
            headers={**_headers(), "Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "LIMIT_EXCEEDED"
    assert transport.requests == []
    manager.lock()


def test_corpus_route_declares_exact_capability_and_middleware_metadata() -> None:
    document = create_contract_app().openapi()
    operation = document["paths"]["/v1/local-ai/corpus/analyze"]["post"]

    assert operation["operationId"] == "analyzeLocalAICorpus"
    assert operation["x-ariadne-capability"] == {
        "routeId": "local_ai.corpus.analyze",
        "maxRequestBytes": MAX_LOCAL_CORPUS_API_REQUEST_BYTES,
        "maxResponseBytes": MAX_LOCAL_CORPUS_API_RESPONSE_BYTES,
        "requiredLockState": "UNLOCKED",
        "scopeClass": "PROFILE",
        "revealClass": "NONE",
        "authorizationClass": "USER_GESTURE",
    }
    assert (
        ROUTE_POLICIES[("POST", "/v1/local-ai/corpus/analyze")].maximum_body_bytes
        == MAX_LOCAL_CORPUS_API_REQUEST_BYTES
    )
