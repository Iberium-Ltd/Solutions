from __future__ import annotations

import base64
import json
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from uuid6 import uuid7

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager, VaultManifest
from ariadne_core.domain.settings import VaultSettingsPatch
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.infrastructure.db.repositories import SettingsRepository
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import (
    FrameKind,
    GrantFrame,
    HelloFrame,
    KeyLeaseClient,
    KeyLeaseError,
    KeyLeaseErrorCode,
    LeaseBinding,
    RequestFrame,
    TransactionFrame,
    binding_digest,
    receive_frame,
    send_frame,
)
from ariadne_core.security.sessions import LaunchSession

HOST = "127.0.0.1:4581"
ORIGIN = "http://127.0.0.1:1420"
RAW_TOKEN = bytes(range(32))
TOKEN = base64.urlsafe_b64encode(RAW_TOKEN).rstrip(b"=").decode()
STARTUP_NONCE = UUID("00112233-4455-4677-8899-aabbccddeeff")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _reference() -> str:
    return f"kc:v1:{uuid4()}"


def _manifest() -> VaultManifest:
    return VaultManifest(
        vault_id=str(uuid7()),
        format_version=1,
        database_key_ref=_reference(),
        backup_key_ref=_reference(),
        database_key_version=1,
    )


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


def _app(
    *,
    manager: VaultManager | None = None,
    lease_client: KeyLeaseClient | None = None,
    foundation_available: bool = False,
) -> FastAPI:
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host=HOST,
            allowed_origins=frozenset({ORIGIN}),
            session=LaunchSession.from_token_bytes(RAW_TOKEN, ttl_seconds=900),
            vault_manager=manager,
            key_lease_client=lease_client,
            cipher_runtime=_cipher_runtime() if foundation_available else None,
        )
    )


def _headers() -> dict[str, str]:
    return {
        "Ariadne-Session": TOKEN,
        "Ariadne-Contract-Version": "1",
        "Ariadne-Request-Id": str(uuid4()),
        "Origin": ORIGIN,
    }


def _create_body(manifest: VaultManifest, *, marker: str = "Synthetic vault") -> dict[str, object]:
    return {
        "displayName": marker,
        "transactionId": str(uuid4()),
        "vaultId": manifest.vault_id,
        "manifestDigest": manifest.digest().hex(),
        "databaseKeyRef": manifest.database_key_ref,
        "backupKeyRef": manifest.backup_key_ref,
        "formatVersion": manifest.format_version,
        "databaseKeyVersion": manifest.database_key_version,
    }


def _unlock_body(manifest: VaultManifest, transaction_id: UUID) -> dict[str, object]:
    return {
        "transactionId": str(transaction_id),
        "vaultId": manifest.vault_id,
        "manifestDigest": manifest.digest().hex(),
        "databaseKeyRef": manifest.database_key_ref,
        "databaseKeyVersion": manifest.database_key_version,
    }


def _clone_binding(binding: LeaseBinding) -> LeaseBinding:
    return LeaseBinding(
        startup_nonce=binding.startup_nonce,
        lease_nonce=bytearray(binding.lease_nonce),
        transaction_id=binding.transaction_id,
        vault_id=binding.vault_id,
        manifest_digest=bytearray(binding.manifest_digest),
        reference=binding.reference,
        key_version=binding.key_version,
        operation=binding.operation,
    )


def _start_peer(
    peer: socket.socket,
    handler: Callable[[socket.socket], None],
) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            handler(peer)
        except BaseException as error:
            errors.append(error)
        finally:
            peer.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def _join_peer(thread: threading.Thread, errors: list[BaseException]) -> None:
    thread.join(timeout=5)
    assert not thread.is_alive(), "synthetic Rust peer did not terminate"
    if errors:
        raise errors[0]


def _write_manifest(root: Path, manifest: VaultManifest) -> VaultManager:
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    manifest_path = root / "vault.json"
    manifest_path.write_bytes(manifest.to_json())
    manifest_path.chmod(0o600)
    return VaultManager(root)


@pytest.mark.anyio
async def test_foundation_unavailable_post_returns_only_safe_503() -> None:
    manifest = _manifest()
    marker = "Synthetic unavailable foundation marker"
    headers = _headers()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/vaults",
            json=_create_body(manifest, marker=marker),
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": {"messageCode": "vault.foundation_unavailable", "args": []},
            "requestId": headers["Ariadne-Request-Id"],
            "retryable": True,
        }
    }
    assert marker not in response.text
    assert manifest.database_key_ref not in response.text


@pytest.mark.anyio
async def test_session_tracks_no_vault_unlocked_and_locked_states(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    app = _app(manager=manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        no_vault = await client.get("/v1/session", headers=_headers())
        manifest = manager.create(display_name="Synthetic dynamic session vault")
        unlocked = await client.get("/v1/session", headers=_headers())
        manager.lock()
        locked = await client.get("/v1/session", headers=_headers())

    assert no_vault.status_code == unlocked.status_code == locked.status_code == 200
    assert (no_vault.json()["lockState"], no_vault.json()["vaultState"]) == (
        "LOCKED",
        "NO_VAULT",
    )
    assert (unlocked.json()["lockState"], unlocked.json()["vaultState"]) == (
        "UNLOCKED",
        "UNLOCKED",
    )
    assert (locked.json()["lockState"], locked.json()["vaultState"]) == (
        "LOCKED",
        "LOCKED",
    )
    assert manifest.vault_id not in no_vault.text
    assert manifest.database_key_ref not in unlocked.text


@pytest.mark.anyio
async def test_event_replay_is_authenticated_bounded_and_unlocked_only(tmp_path: Path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic API event vault")
    SettingsRepository(manager.engine).update(
        manifest.vault_id,
        VaultSettingsPatch(auto_lock_seconds=600),
        expected_revision=1,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(manager=manager, foundation_available=True)),
        base_url=f"http://{HOST}",
    ) as client:
        replay = await client.post(
            "/v1/events/replay",
            json={"cursor": None, "maxEvents": 8},
            headers=_headers(),
        )
        manager.lock()
        locked = await client.post(
            "/v1/events/replay",
            json={"cursor": replay.json()["nextCursor"], "maxEvents": 8},
            headers=_headers(),
        )

    assert replay.status_code == 200
    assert set(replay.json()) == {"disposition", "events", "nextCursor", "hasMore"}
    assert len(replay.json()["events"]) == 1
    assert set(replay.json()["events"][0]) == {
        "eventId",
        "sequence",
        "eventType",
        "resourceType",
        "resourceId",
        "resourceRevision",
    }
    assert "payload" not in replay.text.lower()
    assert locked.status_code == 409


@pytest.mark.anyio
async def test_post_bodies_are_strictly_typed_and_bounded() -> None:
    manifest = _manifest()
    valid = _create_body(manifest)
    with_extra = {**valid, "unexpected": "Synthetic rejected field value"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url=f"http://{HOST}",
    ) as client:
        lock_body = await client.post(
            "/v1/vaults/current/lock",
            content=b"{}",
            headers={**_headers(), "Content-Type": "application/json"},
        )
        oversized = await client.post(
            "/v1/vaults",
            content=b"x" * 1025,
            headers={**_headers(), "Content-Type": "application/json"},
        )
        wrong_content_type = await client.post(
            "/v1/vaults",
            content=json.dumps(valid).encode(),
            headers={**_headers(), "Content-Type": "text/plain"},
        )
        extra_field = await client.post(
            "/v1/vaults",
            json=with_extra,
            headers=_headers(),
        )

    assert lock_body.status_code == oversized.status_code == 413
    assert lock_body.json()["error"]["code"] == "LIMIT_EXCEEDED"
    assert oversized.json()["error"]["code"] == "LIMIT_EXCEEDED"
    assert wrong_content_type.status_code == 400
    assert wrong_content_type.json()["error"]["code"] == "INVALID_REQUEST"
    assert extra_field.status_code == 400
    assert extra_field.json()["error"]["code"] == "INVALID_REQUEST"
    assert "Synthetic rejected field value" not in extra_field.text


@pytest.mark.anyio
async def test_unlock_uses_real_lease_and_publishes_only_after_commit(tmp_path: Path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manifest = manager.create(display_name="Synthetic API lease vault")
    manager.lock()
    with custodian.borrow(manifest.database_key_ref) as borrowed:
        key = bytearray(borrowed)

    client_channel, peer_channel = socket.socketpair()
    peer_channel.settimeout(5)
    lease_client = KeyLeaseClient(
        client_channel,
        STARTUP_NONCE,
        transaction_timeout=2,
        grant_timeout=2,
    )
    transaction_id = uuid4()
    observed_states: list[tuple[str, bool]] = []

    def rust_peer(peer: socket.socket) -> None:
        hello = receive_frame(peer)
        assert isinstance(hello, HelloFrame)
        assert hello.startup_nonce == STARTUP_NONCE
        request = receive_frame(peer)
        assert isinstance(request, RequestFrame)
        assert request.binding.transaction_id == transaction_id
        assert str(request.binding.vault_id) == manifest.vault_id
        assert request.binding.manifest_digest == manifest.digest()
        assert request.binding.reference == manifest.database_key_ref
        assert request.binding.key_version == manifest.database_key_version

        grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
        try:
            send_frame(peer, grant)
        finally:
            grant.zeroize()

        prepared = receive_frame(peer)
        assert isinstance(prepared, TransactionFrame)
        assert prepared.kind is FrameKind.PREPARED
        expected_digest = binding_digest(request.binding)
        try:
            assert prepared.binding_digest == expected_digest
        finally:
            expected_digest[:] = b"\x00" * len(expected_digest)
        observed_states.append(("prepared", manager.is_unlocked))

        commit = TransactionFrame(
            kind=FrameKind.COMMIT,
            startup_nonce=prepared.startup_nonce,
            lease_nonce=bytearray(prepared.lease_nonce),
            transaction_id=prepared.transaction_id,
            binding_digest=bytearray(prepared.binding_digest),
        )
        prepared.zeroize()
        try:
            send_frame(peer, commit)
        finally:
            commit.zeroize()

        committed = receive_frame(peer)
        assert isinstance(committed, TransactionFrame)
        assert committed.kind is FrameKind.COMMITTED
        observed_states.append(("committed", manager.is_unlocked))
        committed.zeroize()
        request.zeroize()
        hello.lease_nonce[:] = b"\x00" * len(hello.lease_nonce)

    peer_thread, peer_errors = _start_peer(peer_channel, rust_peer)
    lease_client.handshake()
    app = _app(
        manager=manager,
        lease_client=lease_client,
        foundation_available=True,
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=f"http://{HOST}",
        ) as client:
            response = await client.post(
                "/v1/vaults/current/unlock",
                json=_unlock_body(manifest, transaction_id),
                headers=_headers(),
            )
        _join_peer(peer_thread, peer_errors)

        assert response.status_code == 200
        assert response.json() == {
            "vaultId": manifest.vault_id,
            "lockState": "UNLOCKED",
            "vaultState": "UNLOCKED",
        }
        assert observed_states == [("prepared", False), ("committed", True)]
        assert manager.is_unlocked is True
    finally:
        if peer_thread.is_alive():
            lease_client.close()
            _join_peer(peer_thread, peer_errors)
        manager.lock()
        key[:] = b"\x00" * len(key)


@pytest.mark.anyio
async def test_http_context_mismatch_sends_no_request_and_closes_lease(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    manager = _write_manifest(tmp_path / "vault", manifest)
    client_channel, peer_channel = socket.socketpair()
    peer_channel.settimeout(5)
    lease_client = KeyLeaseClient(
        client_channel,
        STARTUP_NONCE,
        transaction_timeout=2,
        grant_timeout=2,
    )
    saw_request: list[bool] = []

    def rust_peer(peer: socket.socket) -> None:
        hello = receive_frame(peer)
        assert isinstance(hello, HelloFrame)
        hello.lease_nonce[:] = b"\x00" * len(hello.lease_nonce)
        assert peer.recv(1) == b""
        saw_request.append(False)

    peer_thread, peer_errors = _start_peer(peer_channel, rust_peer)
    lease_client.handshake()
    app = _app(
        manager=manager,
        lease_client=lease_client,
        foundation_available=True,
    )
    mismatched = _unlock_body(manifest, uuid4())
    mismatched["manifestDigest"] = "00" * 32

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=f"http://{HOST}",
    ) as client:
        response = await client.post(
            "/v1/vaults/current/unlock",
            json=mismatched,
            headers=_headers(),
        )

    _join_peer(peer_thread, peer_errors)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STATE_CONFLICT"
    assert saw_request == [False]
    with pytest.raises(KeyLeaseError) as raised:
        lease_client.handshake()
    assert raised.value.code is KeyLeaseErrorCode.CLOSED
