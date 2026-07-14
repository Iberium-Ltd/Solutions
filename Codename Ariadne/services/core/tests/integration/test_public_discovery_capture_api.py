from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.phase5_repository import (
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4595"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()
EXACT_URL = "https://example.org/profiles/synthetic-capture-9037?view=full&lang=en%2Dus"
RAW_QUERY = "SYNTHETIC_CAPTURE_QUERY_9037"
CAPTURED_AT_US = 1_765_000_000_000_000


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


async def _profile(client: httpx.AsyncClient, label: str) -> str:
    response = await client.post(
        "/v1/profiles",
        json={
            "idempotencyKey": str(uuid4()),
            "displayLabel": label,
            "purpose": "Synthetic exact-source public discovery review",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return str(response.json()["profileId"])


def _payload(profile_id: str, *, url: str = EXACT_URL) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "provider": "GITHUB_USERS",
        "query": RAW_QUERY,
        "rank": 2,
        "title": "Synthetic capture fixture 9037",
        "url": url,
        "snippet": "Synthetic provider excerpt retained for local review.",
        "sourceId": "synthetic-capture-9037",
        "capturedAtUs": CAPTURED_AT_US,
        "authorizedSelfAudit": True,
    }


@pytest.mark.anyio
async def test_capture_is_authenticated_and_retains_exact_query_url_without_raw_query(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic discovery capture vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic discovery capture profile")
        payload = _payload(profile_id)
        missing_session = await client.post(
            "/v1/discovery/public/capture",
            json=payload,
            headers={key: value for key, value in _headers().items() if key != "Ariadne-Session"},
        )
        assert missing_session.status_code == 401
        unauthorized = await client.post(
            "/v1/discovery/public/capture",
            json={**payload, "authorizedSelfAudit": False},
            headers=_headers(),
        )
        assert unauthorized.status_code == 400

        response = await client.post(
            "/v1/discovery/public/capture",
            json=payload,
            headers=_headers(),
        )
        assert response.status_code == 200
        result = response.json()
        assert UUID(result["findingId"]).version == 4
        assert UUID(result["artifactId"]).version == 4
        assert result["url"] == EXACT_URL
        assert result["urlSha256"] == hashlib.sha256(EXACT_URL.encode()).hexdigest()
        assert result["provider"] == "GITHUB_USERS"
        assert result["rank"] == 2
        assert result["sourceId"] == "synthetic-capture-9037"
        assert result["evidenceKind"] == "URL_REFERENCE"
        assert result["deduplicated"] is False
        assert result["queryReference"].startswith("mq_")
        assert RAW_QUERY not in result["queryReference"]

        scope = {"vault_id": manager.manifest.vault_id, "profile_id": profile_id}
        finding_repository = Phase5AttributionRepository(manager.engine, **scope)
        evidence_repository = Phase5EvidenceRepository(manager.engine, **scope)
        finding = finding_repository.get_finding(result["findingId"])
        artifact = evidence_repository.get_original(result["artifactId"])
        assessment = finding_repository.latest_assessment(result["findingId"])
        assert assessment is not None
        assert evidence_repository.count_originals_for_finding(result["findingId"]) == 1
        assert artifact.source_url == EXACT_URL
        assert artifact.content == b""
        assert artifact.content_sha256 == result["urlSha256"]
        assert artifact.masked_query_reference == result["queryReference"]
        assert artifact.finding_id == finding.finding_id
        metadata = {item.key: item.value for item in artifact.metadata}
        assert metadata["discovery.authorized_self_audit"] == "true"
        assert metadata["discovery.rank"] == "2"
        assert metadata["discovery.source_id"] == "synthetic-capture-9037"
        assert RAW_QUERY not in finding.title
        assert RAW_QUERY not in finding.summary
        assert all(RAW_QUERY not in value for value in metadata.values())

        detail = await client.post(
            "/v1/phase5/findings/detail",
            json={"profileId": profile_id, "findingId": result["findingId"]},
            headers=_headers(),
        )
        assert detail.status_code == 200
        assert detail.json()["artifacts"][0]["sourceUrl"] == EXACT_URL
    manager.lock()


@pytest.mark.anyio
async def test_capture_is_profile_scoped_and_same_profile_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic scoped discovery capture vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        first_profile = await _profile(client, "Synthetic discovery profile one")
        second_profile = await _profile(client, "Synthetic discovery profile two")
        first = await client.post(
            "/v1/discovery/public/capture",
            json=_payload(first_profile),
            headers=_headers(),
        )
        duplicate = await client.post(
            "/v1/discovery/public/capture",
            json=_payload(first_profile),
            headers=_headers(),
        )
        second = await client.post(
            "/v1/discovery/public/capture",
            json=_payload(second_profile),
            headers=_headers(),
        )
        assert first.status_code == duplicate.status_code == second.status_code == 200
        assert duplicate.json()["deduplicated"] is True
        assert duplicate.json()["findingId"] == first.json()["findingId"]
        assert duplicate.json()["artifactId"] == first.json()["artifactId"]
        assert second.json()["findingId"] != first.json()["findingId"]
        assert second.json()["artifactId"] != first.json()["artifactId"]

        cross_scope = await client.post(
            "/v1/phase5/findings/detail",
            json={
                "profileId": second_profile,
                "findingId": first.json()["findingId"],
            },
            headers=_headers(),
        )
        assert cross_scope.status_code == 404

        incompatible_retry = await client.post(
            "/v1/discovery/public/capture",
            json={**_payload(first_profile), "capturedAtUs": CAPTURED_AT_US + 1},
            headers=_headers(),
        )
        assert incompatible_retry.status_code == 409
    manager.lock()


@pytest.mark.anyio
async def test_capture_rejects_unsafe_or_ambiguous_urls(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic unsafe discovery capture vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic unsafe discovery profile")
        for unsafe_url in (
            "http://127.0.0.1/private?record=synthetic",
            "https://localhost/private?record=synthetic",
            "https://user:secret@credentials-fixture.invalid/public?record=synthetic",
            "https://example.org/public?record=synthetic#ambiguous",
            "file:///tmp/synthetic",
        ):
            response = await client.post(
                "/v1/discovery/public/capture",
                json=_payload(profile_id, url=unsafe_url),
                headers=_headers(),
            )
            assert response.status_code == 400
        repository = Phase5AttributionRepository(
            manager.engine,
            vault_id=manager.manifest.vault_id,
            profile_id=profile_id,
        )
        assert repository.count_findings() == 0
    manager.lock()


@pytest.mark.anyio
async def test_capture_rolls_back_finding_and_assessment_when_evidence_insert_fails(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic discovery rollback vault")
    app = _app(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile_id = await _profile(client, "Synthetic discovery rollback profile")
        with manager.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER test_reject_public_discovery_artifact "
                "BEFORE INSERT ON phase5_evidence_originals BEGIN "
                "SELECT RAISE(ABORT, 'synthetic evidence failure'); END"
            )

        response = await client.post(
            "/v1/discovery/public/capture",
            json=_payload(profile_id),
            headers=_headers(),
        )
        assert response.status_code == 409
        assert RAW_QUERY not in response.text
        with manager.engine.connect() as connection:
            counts = tuple(
                int(
                    connection.exec_driver_sql(
                        f"SELECT COUNT(*) FROM {table} WHERE vault_id = ? AND profile_id = ?",
                        (manager.manifest.vault_id, profile_id),
                    ).scalar_one()
                )
                for table in (
                    "phase5_findings",
                    "phase5_attribution_assessments",
                    "phase5_attribution_missing_evidence",
                    "phase5_evidence_originals",
                    "phase5_finding_evidence",
                )
            )
        assert counts == (0, 0, 0, 0, 0)

        with manager.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER test_reject_public_discovery_artifact")
            connection.exec_driver_sql(
                "CREATE TRIGGER test_reject_public_discovery_finding "
                "BEFORE INSERT ON phase5_findings BEGIN "
                "SELECT RAISE(ABORT, 'synthetic finding failure'); END"
            )
        finding_failure = await client.post(
            "/v1/discovery/public/capture",
            json=_payload(
                profile_id,
                url="https://example.org/profiles/synthetic-secondary?view=full",
            ),
            headers=_headers(),
        )
        assert finding_failure.status_code == 409
        with manager.engine.connect() as connection:
            assert all(
                int(
                    connection.exec_driver_sql(
                        f"SELECT COUNT(*) FROM {table} WHERE vault_id = ? AND profile_id = ?",
                        (manager.manifest.vault_id, profile_id),
                    ).scalar_one()
                )
                == 0
                for table in (
                    "phase5_findings",
                    "phase5_attribution_assessments",
                    "phase5_evidence_originals",
                    "phase5_finding_evidence",
                )
            )
    manager.lock()
