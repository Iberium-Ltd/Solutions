from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
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
from ariadne_core.infrastructure.db.models import (
    audit_events,
    entities,
    entity_decisions,
    entity_origins,
    intake_segments,
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


def _app(manager: VaultManager) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            vault_manager=manager,
            # Phase 3 never accesses the lease client, but production exposes these
            # routes only when the complete lease-backed foundation is available.
            key_lease_client=cast(KeyLeaseClient, object()),
            cipher_runtime=_cipher_runtime(),
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


def _idempotency_key() -> str:
    return str(uuid4())


async def _create_profile(client: httpx.AsyncClient, label: str) -> dict[str, object]:
    response = await client.post(
        "/v1/profiles",
        json={
            "idempotencyKey": _idempotency_key(),
            "displayLabel": label,
            "purpose": "Synthetic authorised local review",
        },
        headers=_headers(),
    )
    assert response.status_code == 200
    return cast(dict[str, object], response.json())


@pytest.mark.anyio
async def test_profiles_can_be_listed_for_explicit_native_resume(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic profile resume vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        first = await _create_profile(client, "Synthetic first profile")
        second = await _create_profile(client, "Synthetic second profile")

        response = await client.get("/v1/profiles", headers=_headers())

        assert response.status_code == 200
        assert response.json() == {
            "profiles": [second, first],
            "hasMore": False,
        }

        manager.lock()
        locked = await client.get("/v1/profiles", headers=_headers())
        assert locked.status_code == 409


@pytest.mark.anyio
async def test_paste_review_decision_and_graph_are_profile_scoped_and_idempotent(
    tmp_path: Path,
) -> None:
    secret = "synthetic-intake-secret"
    raw_only_marker = "synthetic raw provenance phrase remains local"
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic Phase 3 API vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        capabilities = await client.get("/v1/system/capabilities", headers=_headers())
        available = {
            item["key"] for item in capabilities.json()["features"] if item["status"] == "AVAILABLE"
        }
        assert {
            "intake",
            "identity_compiler",
            "entity_review",
            "identity_graph",
        } <= available

        profile = await _create_profile(client, "Synthetic primary profile")
        profile_id = str(profile["profileId"])
        intake_key = _idempotency_key()
        content = (
            "Morgan Vale uses the historical handle @night_orbit.\n"
            "Contact: person@example.invalid.\n"
            "Recovery contact: person@example.invalid.\n"
            "Morgan Vale worked at Northbridge Systems.\n"
            f"{raw_only_marker}.\n"
            f"Password: {secret}"
        )
        request = {
            "idempotencyKey": intake_key,
            "profileId": profile_id,
            "displayName": "Synthetic pasted source",
            "content": content,
            "consentConfirmed": True,
            "retainRawSource": False,
            "semanticEnrichmentEnabled": True,
        }
        ingested = await client.post(
            "/v1/intake/paste",
            json=request,
            headers=_headers(),
        )
        replayed = await client.post(
            "/v1/intake/paste",
            json=request,
            headers=_headers(),
        )
        assert ingested.status_code == replayed.status_code == 200
        receipt = ingested.json()
        assert replayed.json()["sourceId"] == receipt["sourceId"]
        assert replayed.json()["duplicateCount"] == receipt["duplicateCount"]
        assert receipt["candidateCount"] >= 3
        assert receipt["quarantineCount"] >= 1
        assert receipt["localAiStatus"] == "DISABLED"
        assert receipt["localAiProvider"] is None
        assert receipt["localAiSuggestionCount"] == 0
        assert secret not in ingested.text

        conflicting = await client.post(
            "/v1/intake/paste",
            json={**request, "content": "Different synthetic source"},
            headers=_headers(),
        )
        assert conflicting.status_code == 409
        assert secret not in conflicting.text

        review = await client.post(
            "/v1/intake/review",
            json={
                "profileId": profile_id,
                "sourceId": receipt["sourceId"],
                "limit": 100,
            },
            headers=_headers(),
        )
        assert review.status_code == 200
        review_body = review.json()
        assert review_body["entities"]
        assert review_body["quarantineCount"] >= 1
        assert secret not in review.text
        assert raw_only_marker not in review.text
        source_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        for reviewed_entity in review_body["entities"]:
            assert reviewed_entity["origins"]
            assert reviewed_entity["originsTruncated"] is False
            for origin in reviewed_entity["origins"]:
                assert origin["sourceId"] == receipt["sourceId"]
                assert origin["sourceDisplayName"] == request["displayName"]
                assert origin["sourceSha256"] == source_sha256
                assert origin["segmentId"]
                assert origin["segmentIndex"] >= 0
                assert origin["segmentLocator"]
                assert origin["extractionRunId"]
                assert origin["extractorKind"] == "DETERMINISTIC"
                assert origin["extractorName"] == "bounded-local-rules"
                assert origin["extractorVersion"] == "1"
                assert origin["originKind"] in {"DETERMINISTIC", "LOCAL_MODEL"}
                assert origin["observedAtUs"] > 0
                assert 0 <= origin["confidenceMicros"] <= 1_000_000
                assert origin["explanation"]
                assert "content" not in "".join(origin).casefold()
        with manager.engine.connect() as connection:
            persisted_origins = connection.execute(
                select(
                    entity_origins.c.entity_id,
                    entity_origins.c.confidence_micros,
                    entity_origins.c.explanation,
                )
            ).all()
        origins_by_entity: dict[str, list[tuple[int, str]]] = {}
        for entity_id, confidence, explanation in persisted_origins:
            origins_by_entity.setdefault(str(entity_id), []).append(
                (int(confidence), str(explanation))
            )
        assert any(
            confidence != 1_000_000
            for origins in origins_by_entity.values()
            for confidence, _explanation in origins
        )
        for reviewed_entity in review_body["entities"]:
            persisted = origins_by_entity[reviewed_entity["entityId"]]
            maximum = max(confidence for confidence, _explanation in persisted)
            assert reviewed_entity["confidenceMicros"] == maximum
            assert reviewed_entity["provenanceLabel"] in {
                explanation for confidence, explanation in persisted if confidence == maximum
            }

        origin_candidate = max(review_body["entities"], key=lambda item: len(item["origins"]))
        assert len(origin_candidate["origins"]) >= 2
        first_origin_page = await client.post(
            "/v1/entities/origins",
            json={
                "profileId": profile_id,
                "entityId": origin_candidate["entityId"],
                "offset": 0,
                "limit": 1,
            },
            headers=_headers(),
        )
        assert first_origin_page.status_code == 200
        first_page_body = first_origin_page.json()
        assert first_page_body == {
            "profileId": profile_id,
            "entityId": origin_candidate["entityId"],
            "offset": 0,
            "limit": 1,
            "origins": origin_candidate["origins"][:1],
            "total": len(origin_candidate["origins"]),
            "hasMore": True,
        }
        remaining_origin_page = await client.post(
            "/v1/entities/origins",
            json={
                "profileId": profile_id,
                "entityId": origin_candidate["entityId"],
                "offset": 1,
                "limit": 12,
            },
            headers=_headers(),
        )
        assert remaining_origin_page.status_code == 200
        remaining_page_body = remaining_origin_page.json()
        assert remaining_page_body["origins"] == origin_candidate["origins"][1:]
        assert remaining_page_body["total"] == len(origin_candidate["origins"])
        assert remaining_page_body["hasMore"] is False
        assert secret not in first_origin_page.text + remaining_origin_page.text
        assert raw_only_marker not in first_origin_page.text + remaining_origin_page.text

        candidate = next(
            entity
            for entity in review_body["entities"]
            if entity["transmissionPolicy"] == "LOCAL_ONLY"
        )
        decision_key = _idempotency_key()
        decision_request = {
            "idempotencyKey": decision_key,
            "profileId": profile_id,
            "entityId": candidate["entityId"],
            "expectedRevision": candidate["revision"],
            "decisionType": "CONFIRM",
            "reviewState": "CONFIRMED",
            "sensitivity": candidate["sensitivity"],
            "temporalState": candidate["temporalState"],
            "searchPolicy": candidate["searchPolicy"],
            "transmissionPolicy": candidate["transmissionPolicy"],
            "reason": "Synthetic confirmation",
        }
        decided = await client.post(
            "/v1/entities/decision",
            json=decision_request,
            headers=_headers(),
        )
        decision_replay = await client.post(
            "/v1/entities/decision",
            json=decision_request,
            headers=_headers(),
        )
        assert decided.status_code == decision_replay.status_code == 200
        assert decided.json()["reviewState"] == "CONFIRMED"
        assert decided.json()["transmissionPolicy"] == "LOCAL_ONLY"
        assert decision_replay.json()["revision"] == decided.json()["revision"]

        graph = await client.post(
            "/v1/graph/snapshot",
            json={
                "profileId": profile_id,
                "maxNodes": 200,
                "includeSensitive": True,
            },
            headers=_headers(),
        )
        assert graph.status_code == 200
        graph_body = graph.json()
        assert graph_body["nodes"]
        assert graph_body["edges"]
        assert all(edge["originType"] == "DETERMINISTIC" for edge in graph_body["edges"])
        assert all(edge["supportCount"] >= 1 for edge in graph_body["edges"])
        assert all(edge["evidence"] for edge in graph_body["edges"])
        assert all(
            evidence["sourceId"] == receipt["sourceId"]
            and evidence["disposition"] == "SUPPORTS"
            and evidence["sourceSpanEnd"] > evidence["sourceSpanStart"]
            for edge in graph_body["edges"]
            for evidence in edge["evidence"]
        )
        assert all(
            edge["explanation"] != "Local relationship candidate" for edge in graph_body["edges"]
        )
        assert secret not in graph.text

        rejected_node_id = graph_body["edges"][0]["fromNodeId"]
        rejected_entity_id = next(
            node["entityId"] for node in graph_body["nodes"] if node["nodeId"] == rejected_node_id
        )
        rejected_entity = next(
            entity for entity in review_body["entities"] if entity["entityId"] == rejected_entity_id
        )
        if rejected_entity_id == candidate["entityId"]:
            rejected_entity = decided.json()
        rejected = await client.post(
            "/v1/entities/decision",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile_id,
                "entityId": rejected_entity_id,
                "expectedRevision": rejected_entity["revision"],
                "decisionType": "REJECT",
                "reviewState": "FALSE_POSITIVE",
                "sensitivity": rejected_entity["sensitivity"],
                "temporalState": rejected_entity["temporalState"],
                "searchPolicy": "DENY",
                "transmissionPolicy": "NEVER",
                "reason": "Synthetic false-positive rejection",
            },
            headers=_headers(),
        )
        assert rejected.status_code == 200
        suppressed_graph = await client.post(
            "/v1/graph/snapshot",
            json={
                "profileId": profile_id,
                "maxNodes": 200,
                "includeSensitive": True,
            },
            headers=_headers(),
        )
        assert suppressed_graph.status_code == 200
        suppressed_body = suppressed_graph.json()
        assert rejected_node_id not in {node["nodeId"] for node in suppressed_body["nodes"]}
        assert all(
            rejected_node_id not in {edge["fromNodeId"], edge["toNodeId"]}
            for edge in suppressed_body["edges"]
        )

        other_profile = await _create_profile(client, "Synthetic isolated profile")
        cross_profile = await client.post(
            "/v1/intake/review",
            json={
                "profileId": other_profile["profileId"],
                "sourceId": receipt["sourceId"],
                "limit": 100,
            },
            headers=_headers(),
        )
        assert cross_profile.status_code == 404
        cross_profile_origins = await client.post(
            "/v1/entities/origins",
            json={
                "profileId": other_profile["profileId"],
                "entityId": origin_candidate["entityId"],
                "offset": 0,
                "limit": 12,
            },
            headers=_headers(),
        )
        assert cross_profile_origins.status_code == 404

        manager.lock()
        locked = await client.post(
            "/v1/intake/review",
            json={"profileId": profile_id, "limit": 100},
            headers=_headers(),
        )
        assert locked.status_code == 409
        locked_origins = await client.post(
            "/v1/entities/origins",
            json={
                "profileId": profile_id,
                "entityId": origin_candidate["entityId"],
                "offset": 0,
                "limit": 12,
            },
            headers=_headers(),
        )
        assert locked_origins.status_code == 409

    manager.unlock()
    with manager.engine.connect() as connection:
        stored_values = connection.execute(select(entities.c.canonical_value)).scalars().all()
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
        event_metadata = connection.execute(select(audit_events.c.metadata_json)).scalars().all()
        decision_reason_codes = (
            connection.execute(select(entity_decisions.c.reason_code)).scalars().all()
        )
        email_origin_count = connection.execute(
            select(func.count())
            .select_from(entity_origins.join(entities))
            .where(
                entities.c.entity_type == "EMAIL",
                entities.c.canonical_value == "person@example.invalid",
            )
        ).scalar_one()
    assert secret not in " ".join(str(value) for value in stored_values)
    assert secret not in " ".join(str(value) for value in segment_values)
    assert all(value is None for value in segment_values)
    assert secret not in " ".join(str(value) for value in event_metadata)
    assert len(decision_reason_codes) == 2
    assert all(
        code is not None and str(code).startswith("USER_REASON_") for code in decision_reason_codes
    )
    assert (
        "USER_REASON_" + hashlib.sha256(b"Synthetic confirmation").hexdigest()[:16]
        not in decision_reason_codes
    )
    assert email_origin_count == 2
    assert all(json.loads(value) is not None for value in event_metadata)
    manager.lock()


@pytest.mark.anyio
async def test_multiline_repeated_candidate_retains_each_span_and_reports_duplicate(
    tmp_path: Path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic repeated-origin vault")
    app = _app(manager)
    canonical = "Repeat.Case@example.invalid"
    content = f"Contact: {canonical}.\nAgain:\t{canonical}.\n"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic repeated-origin profile")
        response = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile["profileId"],
                "displayName": "Synthetic multiline paste",
                "content": content,
                "consentConfirmed": True,
                "retainRawSource": False,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )

    assert response.status_code == 200
    assert response.json()["candidateCount"] >= 1
    assert response.json()["duplicateCount"] >= 1
    assert response.json()["localAiStatus"] == "NOT_REQUESTED"
    with manager.engine.connect() as connection:
        entity_id = connection.execute(
            select(entities.c.id).where(
                entities.c.canonical_value == canonical,
                entities.c.entity_type == "EMAIL",
            )
        ).scalar_one()
        spans = connection.execute(
            select(entity_origins.c.source_span_start, entity_origins.c.source_span_end).where(
                entity_origins.c.entity_id == entity_id
            )
        ).all()
    assert len(spans) == 2
    assert len(set(spans)) == 2
    manager.lock()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("display_name", "media_type", "content_factory"),
    (
        (
            "synthetic.json",
            "application/json",
            lambda secret: (
                b'{"pass\\u0077ord":"'
                + secret.encode()
                + b'","email":"file.person@example.invalid"}'
            ),
        ),
        (
            "synthetic.csv",
            "text/csv",
            lambda secret: (
                "password,email\n" + secret + ",file.person@example.invalid\n"
            ).encode(),
        ),
    ),
)
async def test_selected_file_binding_is_verified_and_structured_secrets_are_suppressed(
    tmp_path: Path,
    display_name: str,
    media_type: str,
    content_factory: Callable[[str], bytes],
) -> None:
    secret = "synthetic-file-secret"
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic selected-file vault")
    app = _app(manager)
    content = content_factory(secret)
    encoded = base64.b64encode(content).decode()
    digest = hashlib.sha256(content).hexdigest()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic file profile")
        body = {
            "idempotencyKey": _idempotency_key(),
            "profileId": profile["profileId"],
            "contentBase64": encoded,
            "displayName": display_name,
            "declaredMediaType": media_type,
            "expectedSizeBytes": len(content),
            "expectedSha256": digest,
            "consentConfirmed": True,
            "retainRawSource": False,
            "semanticEnrichmentEnabled": False,
        }
        accepted = await client.post(
            "/v1/intake/file",
            json=body,
            headers=_headers(),
        )
        mismatched = await client.post(
            "/v1/intake/file",
            json={
                **body,
                "idempotencyKey": _idempotency_key(),
                "expectedSha256": "0" * 64,
            },
            headers=_headers(),
        )

    assert accepted.status_code == 200
    assert accepted.json()["quarantineCount"] >= 1
    assert mismatched.status_code == 400
    assert secret not in accepted.text
    assert secret not in mismatched.text
    with manager.engine.connect() as connection:
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
    assert secret not in " ".join(str(value) for value in segment_values)
    assert all(value is None for value in segment_values)
    manager.lock()


@pytest.mark.anyio
async def test_retained_source_redacts_complete_password_phrase_before_persistence(
    tmp_path: Path,
) -> None:
    phrase = "alpha bravo charlie"
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic retained-source vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic retained-source profile")
        accepted = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile["profileId"],
                "displayName": "Synthetic retained paste",
                "content": (f"Password: {phrase}\nContact: retained.safe@example.invalid"),
                "consentConfirmed": True,
                "retainRawSource": True,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )

    assert accepted.status_code == 200
    with manager.engine.connect() as connection:
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
    persisted = " ".join(value for value in segment_values if value is not None)
    assert phrase not in persisted
    assert "bravo charlie" not in persisted
    assert "retained.safe@example.invalid" in persisted
    manager.lock()


@pytest.mark.anyio
async def test_retained_paste_redacts_password_with_escaped_quote_without_suffix_leak(
    tmp_path: Path,
) -> None:
    suffix = "bravo-charlie"
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic escaped-password vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic escaped-password profile")
        accepted = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile["profileId"],
                "displayName": "Synthetic escaped-password paste",
                "content": (f'Password: "alpha\\"{suffix}"\nContact: escaped.safe@example.invalid'),
                "consentConfirmed": True,
                "retainRawSource": True,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )

    assert accepted.status_code == 200
    with manager.engine.connect() as connection:
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
    persisted = "\n".join(value for value in segment_values if value is not None)
    assert suffix not in persisted
    assert "escaped.safe@example.invalid" in persisted
    manager.lock()


@pytest.mark.anyio
async def test_retained_paste_unions_overlapping_restricted_spans_without_suffix_leak(
    tmp_path: Path,
) -> None:
    suffix = "trailing-secret"
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic overlap-redaction vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic overlap-redaction profile")
        accepted = await client.post(
            "/v1/intake/paste",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile["profileId"],
                "displayName": "Synthetic overlap-redaction paste",
                "content": (
                    "Password: https://login.example.invalid/reset?token=synthetic-token "
                    f"{suffix}\nContact: overlap.safe@example.invalid"
                ),
                "consentConfirmed": True,
                "retainRawSource": True,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )

    assert accepted.status_code == 200
    with manager.engine.connect() as connection:
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
    persisted = "\n".join(value for value in segment_values if value is not None)
    assert suffix not in persisted
    assert "synthetic-token" not in persisted
    assert "overlap.safe@example.invalid" in persisted
    manager.lock()


@pytest.mark.anyio
async def test_retained_structured_source_redacts_short_password_cell_before_persistence(
    tmp_path: Path,
) -> None:
    secret = "x"
    content = f"password,email\n{secret},structured.safe@example.invalid\n".encode()
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic retained-CSV vault")
    app = _app(manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        profile = await _create_profile(client, "Synthetic retained-CSV profile")
        accepted = await client.post(
            "/v1/intake/file",
            json={
                "idempotencyKey": _idempotency_key(),
                "profileId": profile["profileId"],
                "contentBase64": base64.b64encode(content).decode(),
                "displayName": "synthetic.csv",
                "declaredMediaType": "text/csv",
                "expectedSizeBytes": len(content),
                "expectedSha256": hashlib.sha256(content).hexdigest(),
                "consentConfirmed": True,
                "retainRawSource": True,
                "semanticEnrichmentEnabled": False,
            },
            headers=_headers(),
        )

    assert accepted.status_code == 200
    assert accepted.json()["quarantineCount"] >= 1
    with manager.engine.connect() as connection:
        segment_values = connection.execute(select(intake_segments.c.content_text)).scalars().all()
    persisted = "\n".join(value for value in segment_values if value is not None)
    assert f"\n{secret}\n" not in f"\n{persisted}\n"
    assert "structured.safe@example.invalid" in persisted
    manager.lock()
