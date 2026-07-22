from __future__ import annotations

import base64
from collections.abc import Iterable
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs
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
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
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


def _app(manager: VaultManager, transport: ScriptedTransport) -> FastAPI:
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
            b'href="https://profiles.example.com/synthetic-orbit">Synthetic profile</a>'
            b'<div class="result__snippet">Synthetic public profile result.</div></div>'
        ),
    )


@pytest.mark.anyio
async def test_person_workspace_and_audit_survive_navigation(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic identity discovery vault")
    transport = ScriptedTransport([_search_response()])
    app = _app(manager, transport)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
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
        assert intake_response.status_code == 200
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
                "maxDepth": 1,
                "requestBudget": 8,
                "timeBudgetSeconds": 60,
                "costBudgetMicros": 0,
                "useLocalAi": False,
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
        assert executed["results"][0]["url"].endswith("/synthetic-orbit")
        assert executed["tasks"][0]["state"] == "SUCCEEDED_RESULTS"
        request_body = transport.requests[0].body
        assert request_body is not None
        assert parse_qs(request_body.decode())["q"] == ["synthetic_orbit_742"]

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
        assert workspace["audits"][0]["auditId"] == audit_id
        assert workspace["audits"][0]["taskStates"]

    manager.lock()
