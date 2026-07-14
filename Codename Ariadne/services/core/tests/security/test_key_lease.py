from __future__ import annotations

import hashlib
import os
import socket
import struct
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import cast
from uuid import UUID, uuid4

import pytest

from ariadne_core.security.key_lease import (
    BINDING_DIGEST_BYTES,
    KEY_BYTES,
    KEY_LEASE_FD,
    LEASE_NONCE_BYTES,
    MANIFEST_DIGEST_BYTES,
    MAX_FRAME_BYTES,
    FrameKind,
    GrantFrame,
    HelloFrame,
    KeyLeaseClient,
    KeyLeaseError,
    KeyLeaseErrorCode,
    LeaseBinding,
    LeaseOperation,
    RequestFrame,
    TransactionFrame,
    binding_digest,
    encode_frame,
    format_key_reference,
    parse_key_reference,
    receive_frame,
    send_frame,
)

STARTUP = UUID("00112233-4455-4677-8899-aabbccddeeff")
TRANSACTION = UUID("10213243-5465-4687-98a9-bacbdcedfe0f")
VAULT = UUID("ffeeddcc-bbaa-4988-8766-554433221100")
REFERENCE_ID = UUID("12345678-1234-4abc-8def-1234567890ab")
REFERENCE = f"kc:v1:{REFERENCE_ID}"


def _manifest_digest() -> bytearray:
    return bytearray(hashlib.sha256(b"synthetic canonical vault manifest").digest())


def _lease_nonce() -> bytearray:
    return bytearray(range(LEASE_NONCE_BYTES))


def _synthetic_key() -> bytearray:
    return bytearray(os.urandom(KEY_BYTES))


def _binding(**overrides: object) -> LeaseBinding:
    values: dict[str, object] = {
        "startup_nonce": STARTUP,
        "lease_nonce": _lease_nonce(),
        "transaction_id": TRANSACTION,
        "vault_id": VAULT,
        "manifest_digest": _manifest_digest(),
        "reference": REFERENCE,
        "key_version": 7,
        "operation": LeaseOperation.DATABASE_UNLOCK_V1,
    }
    values.update(overrides)
    return LeaseBinding(**values)  # type: ignore[arg-type]


def _clone_binding(binding: LeaseBinding, **overrides: object) -> LeaseBinding:
    values: dict[str, object] = {
        "startup_nonce": binding.startup_nonce,
        "lease_nonce": bytearray(binding.lease_nonce),
        "transaction_id": binding.transaction_id,
        "vault_id": binding.vault_id,
        "manifest_digest": bytearray(binding.manifest_digest),
        "reference": binding.reference,
        "key_version": binding.key_version,
        "operation": binding.operation,
    }
    values.update(overrides)
    return LeaseBinding(**values)  # type: ignore[arg-type]


def _zero_frame(frame: object) -> None:
    if isinstance(frame, HelloFrame):
        frame.lease_nonce[:] = b"\x00" * len(frame.lease_nonce)
    elif isinstance(frame, (RequestFrame, GrantFrame, TransactionFrame)):
        frame.zeroize()


def _receive_encoded(encoded: bytearray) -> object:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(encoded)
        sender.shutdown(socket.SHUT_WR)
        return receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


class _BoundarySocket:
    def __init__(self, channel: socket.socket, boundary: int) -> None:
        self.channel = channel
        self.boundary = boundary
        self.received = 0

    def recv_into(self, buffer: memoryview, size: int) -> int:
        allowed = size
        if self.received < self.boundary:
            allowed = min(allowed, self.boundary - self.received)
        count = self.channel.recv_into(buffer, allowed)
        self.received += count
        return count


class _RecordingSocket(socket.socket):
    def __init__(self, *, fileno: int) -> None:
        self.recorded_timeouts: list[float | None] = []
        super().__init__(fileno=fileno)

    def settimeout(self, value: float | None) -> None:
        self.recorded_timeouts.append(value)
        super().settimeout(value)


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
    thread.join(timeout=2)
    assert not thread.is_alive(), "synthetic key-lease peer did not terminate"
    if errors:
        raise errors[0]


def _client_pair(*, timeout: float = 0.5) -> tuple[KeyLeaseClient, socket.socket]:
    client_channel, peer = socket.socketpair()
    peer.settimeout(1)
    return (
        KeyLeaseClient(
            client_channel,
            STARTUP,
            transaction_timeout=timeout,
            grant_timeout=timeout,
        ),
        peer,
    )


def _transaction(client: KeyLeaseClient, **overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "transaction_id": TRANSACTION,
        "vault_id": VAULT,
        "manifest_digest": _manifest_digest(),
        "reference": REFERENCE,
        "key_version": 7,
        "operation": LeaseOperation.DATABASE_UNLOCK_V1,
    }
    values.update(overrides)
    return client.transaction(**values)  # type: ignore[arg-type]


def _receive_hello_and_request(peer: socket.socket) -> RequestFrame:
    hello = receive_frame(peer)
    assert isinstance(hello, HelloFrame)
    assert hello.startup_nonce == STARTUP
    assert len(hello.lease_nonce) == LEASE_NONCE_BYTES
    request = receive_frame(peer)
    assert isinstance(request, RequestFrame)
    assert request.binding.startup_nonce == STARTUP
    assert request.binding.lease_nonce == hello.lease_nonce
    _zero_frame(hello)
    return request


def _successful_peer(
    peer: socket.socket,
    key: bytearray,
    events: list[str] | None = None,
) -> None:
    request = _receive_hello_and_request(peer)
    grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
    try:
        send_frame(peer, grant)
    finally:
        grant.zeroize()
    prepared = receive_frame(peer)
    assert isinstance(prepared, TransactionFrame)
    assert prepared.kind is FrameKind.PREPARED
    expected_digest = binding_digest(request.binding)
    assert prepared.startup_nonce == request.binding.startup_nonce
    assert prepared.lease_nonce == request.binding.lease_nonce
    assert prepared.transaction_id == request.binding.transaction_id
    assert prepared.binding_digest == expected_digest
    expected_digest[:] = b"\x00" * len(expected_digest)
    if events is not None:
        events.append("prepared")
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
    if events is not None:
        events.append("commit")
    committed = receive_frame(peer)
    assert isinstance(committed, TransactionFrame)
    assert committed.kind is FrameKind.COMMITTED
    if events is not None:
        events.append("committed")
    committed.zeroize()
    request.zeroize()


def test_wire_layout_is_canonical_and_has_no_outer_prefix() -> None:
    binding = _binding()
    request = encode_frame(RequestFrame(binding))
    try:
        assert len(request) == 16 + 160
        assert request[:4] == b"AKL1"
        assert struct.unpack(">4sBBHII", request[:16]) == (b"AKL1", 1, 2, 0, 160, 1)
        assert request[16:32] == STARTUP.bytes
        assert request[32:64] == binding.lease_nonce
        assert request[64:80] == TRANSACTION.bytes
        assert request[80:96] == VAULT.bytes
        assert request[96:128] == binding.manifest_digest
        assert request[128:170] == REFERENCE.encode("ascii")
        assert request[170:176] == struct.pack(">IH", 7, 2)

        digest = binding_digest(binding)
        try:
            assert digest == hashlib.sha256(request[16:]).digest()
        finally:
            digest[:] = b"\x00" * len(digest)
    finally:
        request[:] = b"\x00" * len(request)
        binding.zeroize()


def test_all_six_frame_kinds_round_trip_with_exact_lengths_and_sequences() -> None:
    binding = _binding()
    digest = binding_digest(binding)
    key = _synthetic_key()
    frames = [
        HelloFrame(STARTUP, bytearray(binding.lease_nonce)),
        RequestFrame(_clone_binding(binding)),
        GrantFrame(_clone_binding(binding), bytearray(key)),
        TransactionFrame(
            FrameKind.PREPARED,
            STARTUP,
            _lease_nonce(),
            TRANSACTION,
            bytearray(digest),
        ),
        TransactionFrame(FrameKind.COMMIT, STARTUP, _lease_nonce(), TRANSACTION, bytearray(digest)),
        TransactionFrame(
            FrameKind.COMMITTED,
            STARTUP,
            _lease_nonce(),
            TRANSACTION,
            bytearray(digest),
        ),
    ]
    expected = {
        FrameKind.HELLO: (48, 0),
        FrameKind.REQUEST: (160, 1),
        FrameKind.GRANT: (192, 2),
        FrameKind.PREPARED: (96, 3),
        FrameKind.COMMIT: (96, 4),
        FrameKind.COMMITTED: (96, 5),
    }
    try:
        for frame in frames:
            encoded = encode_frame(frame)
            try:
                _, _, kind_value, flags, payload_size, sequence = struct.unpack(
                    ">4sBBHII", encoded[:16]
                )
                assert flags == 0
                assert (payload_size, sequence) == expected[FrameKind(kind_value)]
                decoded = _receive_encoded(encoded)
                reencoded = encode_frame(cast(object, decoded))  # type: ignore[arg-type]
                try:
                    assert reencoded == encoded
                finally:
                    reencoded[:] = b"\x00" * len(reencoded)
                    _zero_frame(decoded)
            finally:
                encoded[:] = b"\x00" * len(encoded)
    finally:
        for frame in frames:
            _zero_frame(frame)
        binding.zeroize()
        digest[:] = b"\x00" * len(digest)
        key[:] = b"\x00" * len(key)


def test_fragmentation_at_every_byte_boundary_is_accepted() -> None:
    key = _synthetic_key()
    frame = GrantFrame(_binding(), key)
    encoded = encode_frame(frame)
    try:
        assert len(encoded) == 208
        for boundary in range(1, len(encoded)):
            sender, receiver = socket.socketpair()
            try:
                sender.sendall(encoded)
                fragmented = _BoundarySocket(receiver, boundary)
                decoded = receive_frame(cast(socket.socket, fragmented))
                assert isinstance(decoded, GrantFrame)
                assert decoded.key == key
                decoded.zeroize()
            finally:
                sender.close()
                receiver.close()
    finally:
        encoded[:] = b"\x00" * len(encoded)
        frame.zeroize()


@pytest.mark.parametrize(
    ("offset", "replacement", "code"),
    [
        (0, b"B", KeyLeaseErrorCode.FRAME_MAGIC),
        (4, b"\x02", KeyLeaseErrorCode.FRAME_VERSION),
        (5, b"\xff", KeyLeaseErrorCode.FRAME_KIND),
        (6, b"\x00\x01", KeyLeaseErrorCode.FRAME_FLAGS),
        (12, b"\x00\x00\x00\x05", KeyLeaseErrorCode.FRAME_SEQUENCE),
    ],
)
def test_malformed_headers_fail_with_only_stable_codes(
    offset: int,
    replacement: bytes,
    code: KeyLeaseErrorCode,
) -> None:
    encoded = encode_frame(HelloFrame(STARTUP, _lease_nonce()))
    encoded[offset : offset + len(replacement)] = replacement
    with pytest.raises(KeyLeaseError) as raised:
        _receive_encoded(encoded)
    assert raised.value.code is code
    assert str(raised.value) == code.value


@pytest.mark.parametrize(
    ("total_bytes", "code"),
    [
        (MAX_FRAME_BYTES - 1, KeyLeaseErrorCode.FRAME_LENGTH),
        (MAX_FRAME_BYTES, KeyLeaseErrorCode.FRAME_LENGTH),
        (MAX_FRAME_BYTES + 1, KeyLeaseErrorCode.FRAME_TOO_LARGE),
    ],
)
def test_frame_bound_is_checked_at_255_256_and_257(
    total_bytes: int,
    code: KeyLeaseErrorCode,
) -> None:
    payload_bytes = total_bytes - 16
    header = bytearray(struct.pack(">4sBBHII", b"AKL1", 1, 1, 0, payload_bytes, 0))
    try:
        with pytest.raises(KeyLeaseError) as raised:
            _receive_encoded(header)
        assert raised.value.code is code
    finally:
        header[:] = b"\x00" * len(header)


@pytest.mark.parametrize(
    ("absolute_offset", "replacement", "code"),
    [
        (16 + 8, b"\x00", KeyLeaseErrorCode.UUID_INVALID),
        (16 + 112, b"x", KeyLeaseErrorCode.REFERENCE_INVALID),
        (16 + 158, b"\x00\xff", KeyLeaseErrorCode.OPERATION_INVALID),
    ],
)
def test_malformed_binding_fields_are_rejected(
    absolute_offset: int,
    replacement: bytes,
    code: KeyLeaseErrorCode,
) -> None:
    frame = RequestFrame(_binding())
    encoded = encode_frame(frame)
    encoded[absolute_offset : absolute_offset + len(replacement)] = replacement
    try:
        with pytest.raises(KeyLeaseError) as raised:
            _receive_encoded(encoded)
        assert raised.value.code is code
    finally:
        encoded[:] = b"\x00" * len(encoded)
        frame.zeroize()


def test_truncated_header_and_payload_fail_closed() -> None:
    encoded = encode_frame(GrantFrame(_binding(), _synthetic_key()))
    try:
        for cut in (0, 1, 15, 16, 17, len(encoded) - 1):
            with pytest.raises(KeyLeaseError) as raised:
                _receive_encoded(encoded[:cut])
            assert raised.value.code is KeyLeaseErrorCode.EOF
    finally:
        encoded[:] = b"\x00" * len(encoded)


@pytest.mark.parametrize(
    "value",
    [
        "kc:v1:not-a-uuid",
        "kc:v1:1234567812344abc8def1234567890ab",
        "kc:v1:12345678-1234-1abc-8def-1234567890ab",
        "kc:v1:12345678-1234-4ABC-8def-1234567890ab",
        "vault:v1:12345678-1234-4abc-8def-1234567890ab",
    ],
)
def test_only_canonical_uuid4_key_references_are_accepted(value: str) -> None:
    with pytest.raises(KeyLeaseError) as raised:
        parse_key_reference(value)
    assert raised.value.code is KeyLeaseErrorCode.REFERENCE_INVALID
    assert format_key_reference(REFERENCE_ID) == REFERENCE


def test_socket_validation_clears_inheritance_and_rejects_named_channels() -> None:
    client_channel, peer = socket.socketpair()
    os.set_inheritable(client_channel.fileno(), True)
    client = KeyLeaseClient(client_channel, STARTUP)
    try:
        assert not os.get_inheritable(client_channel.fileno())
    finally:
        client.close()
        peer.close()

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "named.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connector = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(1)
        connector.connect(path)
        accepted, _ = listener.accept()
        try:
            with pytest.raises(KeyLeaseError) as raised:
                KeyLeaseClient(accepted, STARTUP)
            assert raised.value.code is KeyLeaseErrorCode.SOCKET_INVALID
        finally:
            accepted.close()
            connector.close()
            listener.close()


def test_fixed_inherited_descriptor_198_is_owned_and_made_non_inheritable() -> None:
    backup: int | None = None
    original_inheritable = False
    try:
        try:
            original_inheritable = os.get_inheritable(KEY_LEASE_FD)
            backup = os.dup(KEY_LEASE_FD)
        except OSError:
            backup = None
        source, peer = socket.socketpair()
        try:
            os.dup2(source.fileno(), KEY_LEASE_FD, inheritable=True)
            client = KeyLeaseClient.from_inherited_fd(STARTUP)
            try:
                assert not os.get_inheritable(KEY_LEASE_FD)
                client.handshake()
                hello = receive_frame(peer)
                assert isinstance(hello, HelloFrame)
                _zero_frame(hello)
            finally:
                client.close()
        finally:
            source.close()
            peer.close()
    finally:
        if backup is None:
            with suppress(OSError):
                os.close(KEY_LEASE_FD)
        else:
            os.dup2(backup, KEY_LEASE_FD, inheritable=original_inheritable)
            os.close(backup)


def test_handshake_is_one_way_and_success_commits_only_after_publication() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()
    events: list[str] = []
    thread, errors = _start_peer(peer, lambda channel: _successful_peer(channel, key, events))
    client.handshake()
    transaction = _transaction(client)
    leased_alias: bytearray | None = None

    with transaction as lease:
        leased_alias = lease.key
        assert leased_alias == key

        def publish() -> None:
            assert leased_alias == bytearray(KEY_BYTES)
            events.append("published")

        lease.commit(publish)

    assert leased_alias == bytearray(KEY_BYTES)
    _join_peer(thread, errors)
    assert events == ["prepared", "commit", "published", "committed"]
    assert "CONSUMED" in repr(client)
    key[:] = b"\x00" * len(key)


def test_grant_wait_uses_125_second_default_then_restores_transaction_timeout() -> None:
    raw_client, peer = socket.socketpair()
    recording_channel = _RecordingSocket(fileno=raw_client.detach())
    client = KeyLeaseClient(recording_channel, STARTUP)
    key = _synthetic_key()
    thread, errors = _start_peer(peer, lambda channel: _successful_peer(channel, key))
    client.handshake()
    with _transaction(client) as lease:
        lease.commit(lambda: None)
    _join_peer(thread, errors)
    assert recording_channel.recorded_timeouts == [5.0, 125.0, 5.0]
    key[:] = b"\x00" * len(key)


def test_normal_exit_without_explicit_commit_zeroizes_and_poison_closes() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()
    peer_saw_eof = threading.Event()

    def handler(channel: socket.socket) -> None:
        request = _receive_hello_and_request(channel)
        grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
        send_frame(channel, grant)
        grant.zeroize()
        request.zeroize()
        with pytest.raises(KeyLeaseError) as raised:
            receive_frame(channel)
        assert raised.value.code is KeyLeaseErrorCode.EOF
        peer_saw_eof.set()

    thread, errors = _start_peer(peer, handler)
    client.handshake()
    alias: bytearray | None = None
    with pytest.raises(KeyLeaseError) as raised, _transaction(client) as lease:
        alias = lease.key
    assert raised.value.code is KeyLeaseErrorCode.COMMIT_REQUIRED
    assert alias == bytearray(KEY_BYTES)
    _join_peer(thread, errors)
    assert peer_saw_eof.is_set()
    key[:] = b"\x00" * len(key)


def test_body_exception_zeroizes_key_and_sends_no_prepared() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()

    def handler(channel: socket.socket) -> None:
        request = _receive_hello_and_request(channel)
        grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
        send_frame(channel, grant)
        grant.zeroize()
        request.zeroize()
        with pytest.raises(KeyLeaseError) as raised:
            receive_frame(channel)
        assert raised.value.code is KeyLeaseErrorCode.EOF

    thread, errors = _start_peer(peer, handler)
    client.handshake()
    alias: bytearray | None = None
    with (
        pytest.raises(RuntimeError, match="synthetic staging failure"),
        _transaction(client) as lease,
    ):
        alias = lease.key
        raise RuntimeError("synthetic staging failure")
    assert alias == bytearray(KEY_BYTES)
    _join_peer(thread, errors)
    key[:] = b"\x00" * len(key)


def test_mismatched_grant_and_out_of_order_frame_poison_the_channel() -> None:
    for mismatch in (True, False):
        client, peer = _client_pair()
        key = _synthetic_key()

        def handler(
            channel: socket.socket,
            *,
            mismatch: bool = mismatch,
            synthetic_key: bytearray = key,
        ) -> None:
            request = _receive_hello_and_request(channel)
            if mismatch:
                wrong = _clone_binding(request.binding, vault_id=uuid4())
                frame: object = GrantFrame(wrong, bytearray(synthetic_key))
            else:
                digest = binding_digest(request.binding)
                frame = TransactionFrame(
                    FrameKind.COMMIT,
                    request.binding.startup_nonce,
                    bytearray(request.binding.lease_nonce),
                    request.binding.transaction_id,
                    digest,
                )
            send_frame(channel, cast(object, frame))  # type: ignore[arg-type]
            _zero_frame(frame)
            request.zeroize()

        thread, errors = _start_peer(peer, handler)
        client.handshake()
        with pytest.raises(KeyLeaseError) as raised, _transaction(client):
            pass
        expected = (
            KeyLeaseErrorCode.RESPONSE_MISMATCH if mismatch else KeyLeaseErrorCode.RESPONSE_ORDER
        )
        assert raised.value.code is expected
        assert "POISONED" in repr(client)
        _join_peer(thread, errors)
        key[:] = b"\x00" * len(key)


def test_timeout_waiting_for_grant_poison_closes_without_retry() -> None:
    client, peer = _client_pair(timeout=0.03)
    release = threading.Event()

    def handler(channel: socket.socket) -> None:
        request = _receive_hello_and_request(channel)
        request.zeroize()
        release.wait(timeout=1)

    thread, errors = _start_peer(peer, handler)
    client.handshake()
    with pytest.raises(KeyLeaseError) as raised, _transaction(client):
        pass
    assert raised.value.code is KeyLeaseErrorCode.TIMEOUT
    release.set()
    _join_peer(thread, errors)


def test_commit_context_mismatch_zeroizes_key_and_never_publishes() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()
    published = threading.Event()

    def handler(channel: socket.socket) -> None:
        request = _receive_hello_and_request(channel)
        grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
        send_frame(channel, grant)
        grant.zeroize()
        prepared = receive_frame(channel)
        assert isinstance(prepared, TransactionFrame)
        wrong_digest = bytearray(prepared.binding_digest)
        wrong_digest[0] ^= 0xFF
        commit = TransactionFrame(
            FrameKind.COMMIT,
            prepared.startup_nonce,
            bytearray(prepared.lease_nonce),
            prepared.transaction_id,
            wrong_digest,
        )
        send_frame(channel, commit)
        commit.zeroize()
        prepared.zeroize()
        request.zeroize()

    thread, errors = _start_peer(peer, handler)
    client.handshake()
    alias: bytearray | None = None
    with pytest.raises(KeyLeaseError) as raised, _transaction(client) as lease:
        alias = lease.key
        lease.commit(published.set)
    assert raised.value.code is KeyLeaseErrorCode.RESPONSE_MISMATCH
    assert alias == bytearray(KEY_BYTES)
    assert not published.is_set()
    _join_peer(thread, errors)
    key[:] = b"\x00" * len(key)


def test_publish_failure_sends_no_committed_and_returns_redacted_code() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()

    def handler(channel: socket.socket) -> None:
        request = _receive_hello_and_request(channel)
        grant = GrantFrame(_clone_binding(request.binding), bytearray(key))
        send_frame(channel, grant)
        grant.zeroize()
        prepared = receive_frame(channel)
        assert isinstance(prepared, TransactionFrame)
        commit = TransactionFrame(
            FrameKind.COMMIT,
            prepared.startup_nonce,
            bytearray(prepared.lease_nonce),
            prepared.transaction_id,
            bytearray(prepared.binding_digest),
        )
        send_frame(channel, commit)
        commit.zeroize()
        prepared.zeroize()
        request.zeroize()
        with pytest.raises(KeyLeaseError) as raised:
            receive_frame(channel)
        assert raised.value.code is KeyLeaseErrorCode.EOF

    thread, errors = _start_peer(peer, handler)
    client.handshake()

    def fail_publish() -> None:
        raise RuntimeError("detail that must not cross the lease boundary")

    with pytest.raises(KeyLeaseError) as raised, _transaction(client) as lease:
        lease.commit(fail_publish)
    assert raised.value.code is KeyLeaseErrorCode.PUBLISH_FAILED
    assert "detail" not in str(raised.value)
    _join_peer(thread, errors)
    key[:] = b"\x00" * len(key)


def test_transaction_replay_and_post_consumption_request_are_rejected() -> None:
    client, peer = _client_pair()
    key = _synthetic_key()
    thread, errors = _start_peer(peer, lambda channel: _successful_peer(channel, key))
    client.handshake()
    transaction = _transaction(client)
    with transaction as lease:
        lease.commit(lambda: None)
    _join_peer(thread, errors)

    with pytest.raises(KeyLeaseError) as replayed:
        transaction.__enter__()
    assert replayed.value.code is KeyLeaseErrorCode.TRANSACTION_REPLAY

    second = _transaction(client, transaction_id=uuid4())
    with pytest.raises(KeyLeaseError) as consumed:
        second.__enter__()
    assert consumed.value.code is KeyLeaseErrorCode.CONSUMED
    key[:] = b"\x00" * len(key)


def test_key_canary_never_appears_in_repr_or_protocol_errors() -> None:
    key = _synthetic_key()
    frame = GrantFrame(_binding(), bytearray(key))
    client, peer = _client_pair()
    transaction = _transaction(client)
    error = KeyLeaseError(KeyLeaseErrorCode.RESPONSE_MISMATCH)
    key_hex = key.hex()
    key_repr = repr(key)
    surfaces = [repr(frame), repr(client), repr(transaction), repr(error), str(error)]
    try:
        assert all(key_hex not in surface for surface in surfaces)
        assert all(key_repr not in surface for surface in surfaces)
        assert all("REDACTED" in repr(value) for value in (frame, transaction))
    finally:
        frame.zeroize()
        transaction.binding.zeroize()
        transaction._binding_digest[:] = b"\x00" * BINDING_DIGEST_BYTES
        client.close()
        peer.close()
        key[:] = b"\x00" * len(key)


@pytest.mark.parametrize("key_version", [-1, 0x1_0000_0000, True])
def test_invalid_key_versions_are_rejected_before_any_frame(key_version: int) -> None:
    client, peer = _client_pair()
    try:
        with pytest.raises(KeyLeaseError) as raised:
            _transaction(client, key_version=key_version)
        assert raised.value.code is KeyLeaseErrorCode.KEY_VERSION_INVALID
    finally:
        client.close()
        peer.close()


def test_manifest_digest_and_operation_are_closed_exact_types() -> None:
    client, peer = _client_pair()
    try:
        with pytest.raises(KeyLeaseError) as digest_error:
            _transaction(client, manifest_digest=bytearray(MANIFEST_DIGEST_BYTES - 1))
        assert digest_error.value.code is KeyLeaseErrorCode.MANIFEST_DIGEST_INVALID

        with pytest.raises(KeyLeaseError) as operation_error:
            _transaction(client, operation=cast(LeaseOperation, 2))
        assert operation_error.value.code is KeyLeaseErrorCode.OPERATION_INVALID
    finally:
        client.close()
        peer.close()
