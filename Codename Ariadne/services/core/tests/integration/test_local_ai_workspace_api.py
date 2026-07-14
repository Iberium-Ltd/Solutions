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

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceArtifactOriginal,
    EvidenceCaptureMethod,
)
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.local_ai import LocalAIHttpRequest, LocalAIHttpResponse
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
    def __init__(self) -> None:
        self.responses: list[LocalAIHttpResponse] = []
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected local AI request")
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
            "displayLabel": "Synthetic AI workspace",
            "purpose": "Synthetic local analysis",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


async def _intake(client: httpx.AsyncClient, profile_id: str) -> None:
    response = await client.post(
        "/v1/intake/paste",
        json={
            "idempotencyKey": str(uuid4()),
            "profileId": profile_id,
            "displayName": "Synthetic workspace source",
            "content": (
                "Morgan Vale uses the historical handle @cobalt_orbit.\n"
                "Contact: synthetic.workspace@example.invalid.\n"
                "Morgan Vale worked at Atlas Signal."
            ),
            "consentConfirmed": True,
            "retainRawSource": False,
            "semanticEnrichmentEnabled": True,
        },
        headers=_headers(),
    )
    assert response.status_code == 200


def _request(profile_id: str, **changes: object) -> dict[str, object]:
    request: dict[str, object] = {
        "profileId": profile_id,
        "task": "SUMMARY",
        "question": None,
        "scopes": ["ENTITIES"],
        "includeSensitiveEntities": True,
        "execution": "DETERMINISTIC",
        "modelId": None,
        "document": None,
    }
    request.update(changes)
    return request


@pytest.mark.anyio
async def test_deterministic_workspace_is_repeatable_and_profile_scoped(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic deterministic workspace vault")
    transport = ScriptedTransport()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        await _intake(client, profile_id)
        request = _request(profile_id, scopes=["ENTITIES", "GRAPH"])
        first = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=request,
            headers=_headers(),
        )
        second = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=request,
            headers=_headers(),
        )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = first.json()
    assert result["executionMode"] == "DETERMINISTIC"
    assert result["includedCounts"]["entities"] >= 2
    assert result["localOnly"] is True
    assert result["rawEvidenceIncluded"] is False
    assert result["reviewOnly"] is True
    assert all(fact["evidenceRefs"] for fact in result["facts"])
    cited = {reference for fact in result["facts"] for reference in fact["evidenceRefs"]}
    cited.update(
        reference
        for section in result["sections"]
        for item in section["items"]
        for reference in item["evidenceRefs"]
    )
    assert {source["ref"] for source in result["sources"]} == cited
    assert all(source["label"] and source["locator"] for source in result["sources"])
    entity_origins = [source for source in result["sources"] if source["kind"] == "ENTITY_ORIGIN"]
    assert entity_origins
    assert all(
        source["sourceId"]
        and source["sourceDisplayName"] == "Synthetic workspace source"
        and len(source["contentSha256"]) == 64
        and source["segmentId"]
        and source["segmentIndex"] >= 0
        and source["segmentLocator"]
        and source["extractionRunId"]
        and source["extractorName"] == "bounded-local-rules"
        and source["originKind"]
        and source["observedAtUs"] > 0
        for source in entity_origins
    )
    assert result["includedCounts"]["graphEdges"] >= 1
    graph_origins = [
        source for source in result["sources"] if source["kind"] == "GRAPH_EDGE_ORIGIN"
    ]
    assert graph_origins
    assert all(
        source["sourceId"]
        and source["contentSha256"]
        and source["segmentId"]
        and source["segmentLocator"]
        and source["extractionRunId"]
        and source["extractorKind"] == "DETERMINISTIC"
        and source["originType"] == "DETERMINISTIC"
        and source["disposition"] in {"SUPPORTS", "CONTRADICTS"}
        for source in graph_origins
    )
    assert transport.requests == []
    manager.lock()


@pytest.mark.anyio
async def test_document_is_in_memory_and_restricted_values_are_redacted(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic document workspace vault")
    transport = ScriptedTransport()
    content = "Project: Atlas Signal\nPassword: violet-circuit-4477"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        response = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(
                profile_id,
                scopes=["DOCUMENT"],
                document={
                    "kind": "PASTE",
                    "displayName": "Synthetic pasted notes",
                    "declaredMediaType": "text/plain",
                    "content": content,
                    "contentSha256": hashlib.sha256(content.encode()).hexdigest(),
                },
            ),
            headers=_headers(),
        )

    assert response.status_code == 200
    result = response.json()
    assert result["includedCounts"]["documentSegments"] >= 1
    assert result["restrictedValuesRedacted"] >= 1
    assert "violet-circuit-4477" not in response.text
    document_source = next(
        source for source in result["sources"] if source["kind"] == "DOCUMENT_SEGMENT"
    )
    document_sha256 = hashlib.sha256(content.encode()).hexdigest()
    assert document_source["contentSha256"] == document_sha256
    assert document_sha256 in document_source["ref"]
    assert document_source["sourceId"] == f"document:{document_sha256}"
    assert document_source["segmentId"] == document_source["ref"]
    assert document_source["segmentLocator"]
    assert transport.requests == []
    manager.lock()


@pytest.mark.anyio
async def test_explicit_model_output_is_cited_and_invalid_output_falls_back(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic model workspace vault")
    transport = ScriptedTransport()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        await _intake(client, profile_id)
        enabled = await client.post(
            "/v1/local-ai/settings",
            json={
                "enabled": True,
                "provider": "OLLAMA",
                "endpoint": "http://127.0.0.1:11434",
                "selectedModel": "qwen3:30b",
                "expectedRevision": 1,
            },
            headers=_headers(),
        )
        assert enabled.status_code == 200
        profile_ref = f"profile:{profile_id}"
        model_output = {
            "title": "Synthetic workspace overview",
            "summary": "The selected profile is available for local review.",
            "sections": [
                {
                    "heading": "Profile",
                    "items": [{"text": "One selected profile.", "evidence_refs": [profile_ref]}],
                }
            ],
            "facts": [
                {
                    "statement": "The profile is configured for synthetic local analysis.",
                    "evidence_refs": [profile_ref],
                    "confidence": "HIGH",
                }
            ],
            "connections": [],
            "next_steps": [],
            "unanswered": None,
            "limitations": ["Human review remains required."],
        }
        transport.responses.append(
            LocalAIHttpResponse(
                200,
                json.dumps(
                    {
                        "model": "qwen3:30b",
                        "message": {"content": json.dumps(model_output)},
                    }
                ).encode(),
            )
        )
        local = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(
                profile_id,
                execution="LOCAL_MODEL",
                modelId="qwen3:30b",
            ),
            headers=_headers(),
        )

        model_output["facts"][0]["evidence_refs"] = ["finding:unknown"]  # type: ignore[index]
        transport.responses.append(
            LocalAIHttpResponse(
                200,
                json.dumps(
                    {
                        "model": "qwen3:30b",
                        "message": {"content": json.dumps(model_output)},
                    }
                ).encode(),
            )
        )
        fallback = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(
                profile_id,
                execution="LOCAL_MODEL",
                modelId="qwen3:30b",
            ),
            headers=_headers(),
        )

    assert local.status_code == fallback.status_code == 200
    assert local.json()["executionMode"] == "LOCAL_MODEL"
    assert local.json()["modelId"] == "qwen3:30b"
    assert local.json()["facts"][0]["evidenceRefs"] == [profile_ref]
    profile_source = local.json()["sources"][0]
    assert profile_source["ref"] == profile_ref
    assert profile_source["kind"] == "PROFILE"
    assert profile_source["label"] == "Synthetic AI workspace"
    assert profile_source["sourceUrl"] is None
    assert profile_source["sourceUrlSha256"] is None
    assert fallback.json()["executionMode"] == "DETERMINISTIC"
    assert fallback.json()["fallbackReason"] == "INVALID_RESPONSE"
    assert fallback.json()["provider"] is None
    assert len(transport.requests) == 2
    manager.lock()


@pytest.mark.anyio
async def test_ephemeral_openai_workspace_is_cited_and_falls_back_safely(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic OpenAI workspace vault")
    transport = ScriptedTransport()
    ephemeral_key = "synthetic_ephemeral_openai_key"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        await _intake(client, profile_id)
        profile_ref = f"profile:{profile_id}"
        alias = f"source_alias:{hashlib.sha256(profile_ref.encode()).hexdigest()[:32]}"
        model_output = {
            "title": "Synthetic external workspace overview",
            "summary": "One selected profile is available for review.",
            "sections": [],
            "facts": [
                {
                    "statement": "The selected synthetic profile is present.",
                    "evidence_refs": [alias],
                    "confidence": "HIGH",
                }
            ],
            "connections": [],
            "next_steps": [],
            "unanswered": None,
            "limitations": ["Human review remains required."],
        }
        transport.responses.append(
            LocalAIHttpResponse(
                200,
                json.dumps(
                    {
                        "model": "synthetic-openai-model",
                        "output": [
                            {"type": "reasoning"},
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
                            },
                        ],
                        "status": "completed",
                    }
                ).encode(),
            )
        )
        external = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(
                profile_id,
                execution="OPENAI_RESPONSES",
                modelId="synthetic-openai-model",
                openaiApiKey=ephemeral_key,
            ),
            headers=_headers(),
        )

        transport.responses.append(LocalAIHttpResponse(401, b'{"error":"synthetic"}'))
        fallback = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(
                profile_id,
                execution="OPENAI_RESPONSES",
                modelId="synthetic-openai-model",
                openaiApiKey=ephemeral_key,
            ),
            headers=_headers(),
        )

    assert external.status_code == fallback.status_code == 200
    result = external.json()
    assert result["executionMode"] == "OPENAI_RESPONSES"
    assert result["provider"] == "OPENAI_RESPONSES"
    assert result["modelId"] == "synthetic-openai-model"
    assert result["externalNetworkUsed"] is True
    assert result["localOnly"] is False
    assert result["facts"][0]["evidenceRefs"] == [profile_ref]
    assert ephemeral_key not in external.text
    first_request = transport.requests[0]
    assert first_request.url == "https://api.openai.com/v1/responses"
    assert dict(first_request.headers)["Authorization"] == f"Bearer {ephemeral_key}"
    assert ephemeral_key not in repr(first_request)

    fallback_result = fallback.json()
    assert fallback_result["executionMode"] == "DETERMINISTIC"
    assert fallback_result["fallbackReason"] == "UPSTREAM_REJECTED"
    assert fallback_result["provider"] == "OPENAI_RESPONSES"
    assert fallback_result["modelId"] == "synthetic-openai-model"
    assert fallback_result["externalNetworkUsed"] is True
    assert fallback_result["localOnly"] is False
    assert ephemeral_key not in fallback.text
    manager.lock()


@pytest.mark.anyio
async def test_evidence_source_exposes_exact_url_without_loading_content_into_result(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic cited evidence workspace vault")
    transport = ScriptedTransport()
    exact_url = "https://synthetic-evidence.example.invalid/profile/atlas"
    private_evidence_bytes = b"synthetic private evidence body that must not enter AI output"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager, transport)),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client)
        scope = {
            "vault_id": manager.manifest.vault_id,
            "profile_id": profile_id,
        }
        finding_id = "finding-synthetic-exact-source"
        Phase5AttributionRepository(manager.engine, **scope).persist_finding(
            FindingDraft(
                finding_id=finding_id,
                title="Synthetic exact-source finding",
                summary="Synthetic finding for exact source visibility verification.",
                outcome=FindingOutcome.FOUND,
                severity=FindingSeverity.MEDIUM,
                visibility=FindingVisibility.PUBLICLY_ATTRIBUTABLE,
                provider_id="provider-synthetic-local",
                provider_label="Synthetic source provider",
                observed_at_us=1_783_900_000_000_000,
            )
        )
        artifact_id = "artifact-synthetic-exact-source"
        Phase5EvidenceRepository(manager.engine, **scope).insert_original(
            EvidenceArtifactOriginal(
                artifact_id=artifact_id,
                kind=EvidenceArtifactKind.HTML,
                content=private_evidence_bytes,
                content_sha256=hashlib.sha256(private_evidence_bytes).hexdigest(),
                captured_at_us=1_783_900_000_000_001,
                source_url=exact_url,
                http_status=200,
                redirect_chain=(),
                masked_query_reference=None,
                provider_id="provider-synthetic-local",
                run_id="run-synthetic-exact-source",
                finding_id=finding_id,
                viewport=None,
                capture_method=EvidenceCaptureMethod.HTTP_FETCH,
                metadata=(),
            )
        )
        response = await client.post(
            "/v1/local-ai/workspace/analyze",
            json=_request(profile_id, scopes=["FINDINGS"]),
            headers=_headers(),
        )

    assert response.status_code == 200
    sources = {source["ref"]: source for source in response.json()["sources"]}
    evidence_source = sources[f"evidence:{artifact_id}"]
    assert evidence_source["sourceUrl"] == exact_url
    assert evidence_source["sourceUrlSha256"] == hashlib.sha256(exact_url.encode()).hexdigest()
    assert evidence_source["artifactId"] == artifact_id
    assert evidence_source["runId"] == "run-synthetic-exact-source"
    assert evidence_source["providerId"] == "provider-synthetic-local"
    assert evidence_source["captureMethod"] == "HTTP_FETCH"
    assert artifact_id in evidence_source["locator"]
    assert hashlib.sha256(private_evidence_bytes).hexdigest() in evidence_source["locator"]
    assert private_evidence_bytes.decode() not in response.text
    assert transport.requests == []
    manager.lock()
