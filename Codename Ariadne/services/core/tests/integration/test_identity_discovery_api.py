from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import MetaData, Table, insert, select

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.public_discovery import (
    PublicDiscoveryHttpRequest,
    PublicDiscoveryHttpResponse,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.local_ai import LocalAIHttpRequest, LocalAIHttpResponse
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4947"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(31, -1, -1))
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


class CitedLocalAITransport:
    def __init__(self) -> None:
        self.requests: list[LocalAIHttpRequest] = []

    def send(self, request: LocalAIHttpRequest) -> LocalAIHttpResponse:
        self.requests.append(request)
        body = request.body.decode() if request.body is not None else ""
        match = re.search(r"result:[0-9a-f-]{36}", body)
        if match is None:
            raise AssertionError("identity AI projection omitted its result reference")
        reference = match.group(0)
        output = {
            "title": "Synthetic identity connections",
            "summary": "One exact public source is ready for human review.",
            "sections": [
                {
                    "heading": "Sources",
                    "items": [{"text": "One public result.", "evidence_refs": [reference]}],
                }
            ],
            "facts": [
                {
                    "statement": "A public profile result was returned.",
                    "evidence_refs": [reference],
                    "confidence": "HIGH",
                }
            ],
            "connections": [],
            "next_steps": [
                {
                    "priority": 1,
                    "suggestion": "Review the exact profile source.",
                    "rationale": "Ownership still requires human confirmation.",
                    "supporting_refs": [reference],
                }
            ],
            "unanswered": None,
            "limitations": ["Synthetic model output requires human review."],
        }
        return LocalAIHttpResponse(
            200,
            json.dumps(
                {"model": "qwen-local:7b", "message": {"content": json.dumps(output)}}
            ).encode(),
        )


def _app(
    manager: VaultManager,
    transport: ScriptedTransport,
    local_ai_transport: CitedLocalAITransport | None = None,
) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            vault_manager=manager,
            key_lease_client=cast(KeyLeaseClient, object()),
            cipher_runtime=CipherRuntime(
                sqlite_version="3.53.3",
                cipher_version="4.17.0 community",
                foreign_keys=True,
                journal_mode="delete",
                temp_store=2,
                fts5=True,
                json=True,
            ),
            public_discovery_transport=transport,
            local_ai_transport=local_ai_transport,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


def _search_response() -> PublicDiscoveryHttpResponse:
    return PublicDiscoveryHttpResponse(
        status_code=200,
        headers=(("Content-Type", "text/html; charset=UTF-8"),),
        body=(
            b'<div class="result"><a class="result__a" '
            b'href="https://profiles.example.com/synthetic_orbit_742">Synthetic profile</a>'
            b'<div class="result__snippet">Synthetic public profile result.</div></div>'
        ),
    )


@pytest.mark.anyio
async def test_person_workspace_and_audit_survive_navigation(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic identity discovery vault")
    transport = ScriptedTransport([_search_response()])
    local_ai_transport = CitedLocalAITransport()
    app = _app(manager, transport, local_ai_transport)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        settings_response = await client.post(
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
        assert settings_response.status_code == 200
        profile_response = await client.post(
            "/v1/profiles",
            json={
                "idempotencyKey": str(uuid4()),
                "displayLabel": "Synthetic person",
                "purpose": "Authorised synthetic self-audit",
            },
            headers=_headers(),
        )
        assert profile_response.status_code == 200
        profile_id = profile_response.json()["profileId"]

        intake_response = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": str(uuid4()),
                "profileId": profile_id,
                "displayName": "Synthetic identity seed",
                "content": "Public handle: @synthetic_orbit_742",
                "consentConfirmed": True,
                "retainRawSource": False,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )
        assert intake_response.status_code == 200, intake_response.text
        review_response = await client.post(
            "/v1/intake/review",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert review_response.status_code == 200
        username = next(
            item for item in review_response.json()["entities"] if item["entityType"] == "USERNAME"
        )
        decision_response = await client.post(
            "/v1/entities/decision",
            json={
                "idempotencyKey": str(uuid4()),
                "profileId": profile_id,
                "entityId": username["entityId"],
                "expectedRevision": username["revision"],
                "decisionType": "CONFIRM",
                "reviewState": "CONFIRMED",
                "sensitivity": "PUBLIC",
                "temporalState": "CURRENT",
                "searchPolicy": "ALLOW",
                "transmissionPolicy": "POLICY_CONTROLLED",
                "reason": "Synthetic public self-audit seed",
            },
            headers=_headers(),
        )
        assert decision_response.status_code == 200

        update_response = await client.post(
            "/v1/identity/person",
            json={
                "profileId": profile_id,
                "expectedProfileRevision": 1,
                "expectedDetailsRevision": 0,
                "displayName": "Synthetic person workspace",
                "purpose": "Persistent synthetic identity audit",
                "notes": "Synthetic notes retained locally.",
                "tags": ["synthetic", "test"],
            },
            headers=_headers(),
        )
        assert update_response.status_code == 200, update_response.text

        audit_response = await client.post(
            "/v1/identity/audits",
            json={
                "profileId": profile_id,
                "name": "Synthetic full audit",
                "mode": "FULL_RESCAN",
                "providerIds": ["DUCKDUCKGO_HTML"],
                "maxDepth": 0,
                "requestBudget": 8,
                "timeBudgetSeconds": 60,
                "costBudgetMicros": 0,
                "useLocalAi": True,
                "authorizedSelfAudit": True,
            },
            headers=_headers(),
        )
        assert audit_response.status_code == 200, audit_response.text
        audit_id = audit_response.json()["audit"]["auditId"]

        execute_response = await client.post(
            "/v1/identity/audits/execute",
            json={"profileId": profile_id, "auditId": audit_id, "maximumTasks": 1},
            headers=_headers(),
        )
        assert execute_response.status_code == 200
        executed = execute_response.json()
        assert executed["audit"]["resultCount"] == 1, (
            executed["tasks"][0]["state"],
            executed["tasks"][0]["stopReason"],
            executed["receipts"][0]["resultCode"],
        )
        assert executed["results"][0]["url"].endswith("/synthetic_orbit_742")
        assert executed["tasks"][0]["state"] == "SUCCEEDED_RESULTS"
        assert executed["aiAnalysis"] is None

        analysis_response = await client.post(
            "/v1/identity/audits/execute",
            json={"profileId": profile_id, "auditId": audit_id, "maximumTasks": 1},
            headers=_headers(),
        )
        assert analysis_response.status_code == 200
        executed = analysis_response.json()
        assert executed["aiAnalysis"]["status"] == "SUCCEEDED"
        assert executed["aiAnalysis"]["provider"] == "OLLAMA"
        assert executed["aiAnalysis"]["modelId"] == "qwen-local:7b"
        assert executed["aiAnalysis"]["citations"][0]["url"].endswith("/synthetic_orbit_742")
        assert executed["aiAnalysis"]["insights"][0]["evidenceRefs"] == [
            executed["aiAnalysis"]["citations"][0]["referenceId"]
        ]
        request_body = transport.requests[0].body
        assert request_body is not None
        assert parse_qs(request_body.decode())["q"] == ["synthetic_orbit_742"]

        metadata = MetaData()
        proposals = Table("identity_proposals", metadata, autoload_with=manager.engine)
        proposal_origins = Table("identity_entity_origins", metadata, autoload_with=manager.engine)
        proposal_id = str(uuid4())
        source_url = executed["results"][0]["url"]
        with manager.engine.begin() as connection:
            connection.execute(
                insert(proposals).values(
                    id=proposal_id,
                    vault_id=manager.manifest.vault_id,
                    profile_id=profile_id,
                    audit_id=audit_id,
                    lead_id=executed["leads"][0]["leadId"],
                    entity_type="USERNAME",
                    canonical_value="synthetic_new_alias_901",
                    display_value="s•••1",
                    value_hmac="a" * 64,
                    source_url=source_url,
                    source_span_start=None,
                    source_span_end=None,
                    supporting_signals_json='["SYNTHETIC_TEST_SOURCE"]',
                    contradictions_json="[]",
                    confidence_micros=700_000,
                    temporal_state="UNKNOWN",
                    review_state="UNREVIEWED",
                    recommended_actions_json='["CONFIRM","REJECT"]',
                    model_provider=None,
                    model_id=None,
                    created_at_us=executed["audit"]["updatedAtUs"] + 1,
                    reviewed_at_us=None,
                    revision=1,
                )
            )
        decision = await client.post(
            "/v1/identity/proposals/decision",
            json={
                "profileId": profile_id,
                "auditId": audit_id,
                "proposalId": proposal_id,
                "expectedRevision": 1,
                "decision": "CONFIRM",
            },
            headers=_headers(),
        )
        assert decision.status_code == 200, decision.text
        assert (
            next(
                item for item in decision.json()["proposals"] if item["proposalId"] == proposal_id
            )["reviewState"]
            == "CONFIRMED"
        )
        with manager.engine.connect() as connection:
            origin_url = connection.execute(
                select(proposal_origins.c.source_url).where(
                    proposal_origins.c.proposal_id == proposal_id
                )
            ).scalar_one()
        assert origin_url == source_url

        reopened_response = await client.post(
            "/v1/identity/audits/detail",
            json={"profileId": profile_id, "auditId": audit_id},
            headers=_headers(),
        )
        assert reopened_response.status_code == 200
        assert reopened_response.json()["results"] == executed["results"]

        workspace_response = await client.post(
            "/v1/identity/workspace",
            json={"profileId": profile_id},
            headers=_headers(),
        )
        assert workspace_response.status_code == 200
        workspace = workspace_response.json()
        assert workspace["person"]["displayName"] == "Synthetic person workspace"
        assert workspace["person"]["tags"] == ["synthetic", "test"]
        assert workspace["person"]["identityCount"] == 2
        assert workspace["audits"][0]["auditId"] == audit_id
        assert workspace["audits"][0]["taskStates"]

        # Completed recursive runs retain nullable parent-task links. Profile
        # deletion must break those self references and erase the whole durable
        # workspace in one transaction.
        tasks = Table("identity_frontier_tasks", metadata, autoload_with=manager.engine)
        with manager.engine.begin() as connection:
            parent = (
                connection.execute(select(tasks).where(tasks.c.audit_id == audit_id))
                .mappings()
                .one()
            )
            child = dict(parent)
            child.update(
                id=str(uuid4()),
                parent_task_id=str(parent["id"]),
                payload_text="synthetic-child-query",
                payload_hmac="b" * 64,
                masked_payload="synthetic-child-query",
                state="BLOCKED",
                stop_reason="SYNTHETIC_TEST_TERMINAL",
                revision=1,
            )
            connection.execute(insert(tasks).values(**child))

        profiles_response = await client.get("/v1/profiles", headers=_headers())
        assert profiles_response.status_code == 200
        profile = profiles_response.json()["profiles"][0]
        deleted = await client.post(
            "/v1/profiles/delete",
            json={
                "profileId": profile_id,
                "expectedRevision": profile["revision"],
                "confirmationLabel": profile["displayLabel"],
            },
            headers=_headers(),
        )
        assert deleted.status_code == 200, deleted.text
        assert (await client.get("/v1/profiles", headers=_headers())).json()["profiles"] == []

    assert len(local_ai_transport.requests) == 1

    manager.lock()
