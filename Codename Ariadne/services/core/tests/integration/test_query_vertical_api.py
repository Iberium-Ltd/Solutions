from __future__ import annotations

import base64
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.query_policy_repository import QueryPolicyRepository
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4594"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(manager: VaultManager) -> FastAPI:
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
async def test_confirmed_entities_compile_to_masked_local_preflight_and_real_dry_run(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic query vertical vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_response = await client.post(
            "/v1/profiles",
            json={
                "idempotencyKey": str(uuid4()),
                "displayLabel": "Synthetic query vertical profile",
                "purpose": "Synthetic network-free query planning",
            },
            headers=_headers(),
        )
        assert profile_response.status_code == 200
        profile_id = str(profile_response.json()["profileId"])
        raw_value = "vertical.person@example.invalid"
        intake = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": str(uuid4()),
                "profileId": profile_id,
                "displayName": "Synthetic query source",
                "content": f"Contact: {raw_value}",
                "consentConfirmed": True,
                "retainRawSource": False,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )
        assert intake.status_code == 200
        review = await client.post(
            "/v1/intake/review",
            json={"profileId": profile_id, "sourceId": intake.json()["sourceId"], "limit": 100},
            headers=_headers(),
        )
        candidate = next(
            entity for entity in review.json()["entities"] if entity["entityType"] == "EMAIL"
        )
        confirmed = await client.post(
            "/v1/entities/decision",
            json={
                "idempotencyKey": str(uuid4()),
                "profileId": profile_id,
                "entityId": candidate["entityId"],
                "expectedRevision": candidate["revision"],
                "decisionType": "CONFIRM",
                "reviewState": "CONFIRMED",
                "sensitivity": candidate["sensitivity"],
                "temporalState": candidate["temporalState"],
                "searchPolicy": candidate["searchPolicy"],
                "transmissionPolicy": candidate["transmissionPolicy"],
                "reason": "Synthetic local query approval",
            },
            headers=_headers(),
        )
        assert confirmed.status_code == 200

        catalog = await client.post(
            "/v1/query/providers",
            json={"profileId": profile_id},
            headers=_headers(),
        )
        assert catalog.status_code == 200
        assert catalog.json()["externalProviderCount"] == 0
        assert all(
            not provider["networkAccess"] and not provider["sendsIdentifiers"]
            for provider in catalog.json()["providers"]
        )

        plan_request = {
            "profileId": profile_id,
            "purposeCode": "SYNTHETIC_LOCAL_PREFLIGHT",
            "providerIds": ["local-dry-run", "manual-import"],
            "policyMode": "LOCAL_ONLY",
            "allowedProviderIds": [],
            "allowedRegions": [],
            "maximumChecks": 2,
            "maximumChecksPerProvider": 1,
        }
        assert raw_value not in str(plan_request)
        plan = await client.post("/v1/query/plans", json=plan_request, headers=_headers())
        assert plan.status_code == 200
        plan_body = plan.json()
        assert plan_body["approvalRequiredCount"] == 1
        assert plan_body["notCheckedCount"] == 1
        assert {cell["state"] for cell in plan_body["cells"]} == {
            "APPROVAL_REQUIRED",
            "NOT_CHECKED",
        }
        assert raw_value not in plan.text
        dry_cell = next(
            cell for cell in plan_body["cells"] if cell["providerId"] == "local-dry-run"
        )
        approved = await client.post(
            "/v1/query/dry-run",
            json={
                "profileId": profile_id,
                "runId": plan_body["runId"],
                "checkId": dry_cell["checkId"],
                "expectedRevision": dry_cell["revision"],
                "approveOnce": True,
            },
            headers=_headers(),
        )
        assert approved.status_code == 200
        assert approved.json()["state"] == "SUCCEEDED"
        assert approved.json()["reasonCode"] == "DRY_RUN_COMPLETE"
        assert raw_value not in approved.text

    repository = QueryPolicyRepository(manager.engine, policy_hmac_key=b"q" * 32)
    with manager.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(repository.ledger)).scalar_one()
            == 1
        )
        ledger = connection.execute(select(repository.ledger)).mappings().one()
        approval = connection.execute(select(repository.approvals)).mappings().one()
    assert raw_value not in str(ledger)
    assert approval["consumed_at_us"] is not None
    repository.close()
    manager.lock()


@pytest.mark.anyio
async def test_query_vertical_requires_authentication_scope_and_unlocked_vault(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic query scope vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        unauthenticated = await client.post(
            "/v1/query/providers",
            json={"profileId": str(uuid4())},
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert unauthenticated.status_code == 401
        absent_profile = await client.post(
            "/v1/query/providers",
            json={"profileId": str(uuid4())},
            headers=_headers(),
        )
        assert absent_profile.status_code == 404
        manager.lock()
        locked = await client.post(
            "/v1/query/providers",
            json={"profileId": str(uuid4())},
            headers=_headers(),
        )
        assert locked.status_code == 409
