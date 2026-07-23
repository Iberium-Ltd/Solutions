"""Anonymous, one-operation vault-key lease protocol for the packaged sidecar.

The inherited socket, peer/process binding, strict frame sequence, transcript
authentication, and commit handshake constrain a grant to one database action.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import secrets
import socket
import stat
import struct
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import TracebackType
from typing import Literal
from uuid import RFC_4122, UUID

KEY_LEASE_FD = 198
MAX_FRAME_BYTES = 256
KEY_BYTES = 32
LEASE_NONCE_BYTES = 32
MANIFEST_DIGEST_BYTES = 32
BINDING_DIGEST_BYTES = 32
REFERENCE_PREFIX = "kc:v1:"
REFERENCE_BYTES = 42

_HEADER = struct.Struct(">4sBBHII")
_MAGIC = b"AKL1"
_VERSION = 1
_BINDING_BYTES = 160
_FINAL_CONTEXT_BYTES = 96


class FrameKind(IntEnum):
    HELLO = 1
    REQUEST = 2
    GRANT = 3
    PREPARED = 4
    COMMIT = 5
    COMMITTED = 6


class LeaseOperation(IntEnum):
    DATABASE_CREATE_V1 = 1
    DATABASE_UNLOCK_V1 = 2


_SEQUENCE_BY_KIND = {
    FrameKind.HELLO: 0,
    FrameKind.REQUEST: 1,
    FrameKind.GRANT: 2,
    FrameKind.PREPARED: 3,
    FrameKind.COMMIT: 4,
    FrameKind.COMMITTED: 5,
}

_PAYLOAD_BYTES_BY_KIND = {
    FrameKind.HELLO: 16 + LEASE_NONCE_BYTES,
    FrameKind.REQUEST: _BINDING_BYTES,
    FrameKind.GRANT: _BINDING_BYTES + KEY_BYTES,
    FrameKind.PREPARED: _FINAL_CONTEXT_BYTES,
    FrameKind.COMMIT: _FINAL_CONTEXT_BYTES,
    FrameKind.COMMITTED: _FINAL_CONTEXT_BYTES,
}


class KeyLeaseErrorCode(StrEnum):
    FD_INVALID = "KEY_LEASE_FD_INVALID"
    SOCKET_INVALID = "KEY_LEASE_SOCKET_INVALID"
    PEER_INVALID = "KEY_LEASE_PEER_INVALID"
    NOT_CONNECTED = "KEY_LEASE_NOT_CONNECTED"
    TIMEOUT = "KEY_LEASE_TIMEOUT"
    EOF = "KEY_LEASE_EOF"
    IO = "KEY_LEASE_IO"
    FRAME_TOO_SMALL = "KEY_LEASE_FRAME_TOO_SMALL"
    FRAME_TOO_LARGE = "KEY_LEASE_FRAME_TOO_LARGE"
    FRAME_MAGIC = "KEY_LEASE_FRAME_MAGIC"
    FRAME_VERSION = "KEY_LEASE_FRAME_VERSION"
    FRAME_KIND = "KEY_LEASE_FRAME_KIND"
    FRAME_FLAGS = "KEY_LEASE_FRAME_FLAGS"
    FRAME_LENGTH = "KEY_LEASE_FRAME_LENGTH"
    FRAME_SEQUENCE = "KEY_LEASE_FRAME_SEQUENCE"
    FRAME_LAYOUT = "KEY_LEASE_FRAME_LAYOUT"
    UUID_INVALID = "KEY_LEASE_UUID_INVALID"
    LEASE_NONCE_INVALID = "KEY_LEASE_NONCE_INVALID"
    MANIFEST_DIGEST_INVALID = "KEY_LEASE_MANIFEST_DIGEST_INVALID"
    BINDING_DIGEST_INVALID = "KEY_LEASE_BINDING_DIGEST_INVALID"
    REFERENCE_INVALID = "KEY_LEASE_REFERENCE_INVALID"
    KEY_VERSION_INVALID = "KEY_LEASE_KEY_VERSION_INVALID"
    OPERATION_INVALID = "KEY_LEASE_OPERATION_INVALID"
    HANDSHAKE_REQUIRED = "KEY_LEASE_HANDSHAKE_REQUIRED"
    TRANSACTION_ACTIVE = "KEY_LEASE_TRANSACTION_ACTIVE"
    TRANSACTION_REPLAY = "KEY_LEASE_TRANSACTION_REPLAY"
    RESPONSE_MISMATCH = "KEY_LEASE_RESPONSE_MISMATCH"
    RESPONSE_ORDER = "KEY_LEASE_RESPONSE_ORDER"
    KEY_UNAVAILABLE = "KEY_LEASE_KEY_UNAVAILABLE"
    COMMIT_REQUIRED = "KEY_LEASE_COMMIT_REQUIRED"
    PUBLISH_FAILED = "KEY_LEASE_PUBLISH_FAILED"
    CLOSED = "KEY_LEASE_CLOSED"
    CONSUMED = "KEY_LEASE_CONSUMED"


class KeyLeaseError(RuntimeError):
    """A redacted protocol failure represented by one stable debug code."""

    __slots__ = ("code",)

    def __init__(self, code: KeyLeaseErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __repr__(self) -> str:
        return f"KeyLeaseError(code={self.code.value})"


def _fail(code: KeyLeaseErrorCode) -> KeyLeaseError:
    return KeyLeaseError(code)


def _zero(buffer: bytearray | None) -> None:
    if buffer is not None:
        buffer[:] = b"\x00" * len(buffer)


def _uuid_rfc(value: UUID) -> UUID:
    if not isinstance(value, UUID) or value.variant != RFC_4122 or value.version is None:
        raise _fail(KeyLeaseErrorCode.UUID_INVALID)
    return value


def parse_key_reference(value: str) -> UUID:
    """Validate an opaque key reference received across the native lease channel."""

    if not isinstance(value, str) or not value.startswith(REFERENCE_PREFIX):
        raise _fail(KeyLeaseErrorCode.REFERENCE_INVALID)
    encoded = value[len(REFERENCE_PREFIX) :]
    try:
        reference = UUID(encoded)
    except (ValueError, AttributeError, TypeError):
        raise _fail(KeyLeaseErrorCode.REFERENCE_INVALID) from None
    if (
        len(value.encode("ascii", errors="ignore")) != REFERENCE_BYTES
        or str(reference) != encoded
        or reference.version != 4
        or reference.variant != RFC_4122
    ):
        raise _fail(KeyLeaseErrorCode.REFERENCE_INVALID)
    return reference


def format_key_reference(value: UUID) -> str:
    """Encode a key reference in the only wire representation accepted by the lease protocol."""

    value = _uuid_rfc(value)
    if value.version != 4:
        raise _fail(KeyLeaseErrorCode.REFERENCE_INVALID)
    return f"{REFERENCE_PREFIX}{value}"


def _copy_exact(
    value: bytes | bytearray | memoryview,
    size: int,
    code: KeyLeaseErrorCode,
) -> bytearray:
    try:
        view = memoryview(value).cast("B")
    except (TypeError, ValueError):
        raise _fail(code) from None
    try:
        if len(view) != size:
            raise _fail(code)
        return bytearray(view)
    finally:
        view.release()


def _operation(value: LeaseOperation) -> LeaseOperation:
    if not isinstance(value, LeaseOperation):
        raise _fail(KeyLeaseErrorCode.OPERATION_INVALID)
    return value


def _key_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF_FFFF:
        raise _fail(KeyLeaseErrorCode.KEY_VERSION_INVALID)
    return value


@dataclass(slots=True)
class LeaseBinding:
    startup_nonce: UUID
    lease_nonce: bytearray = field(repr=False)
    transaction_id: UUID
    vault_id: UUID
    manifest_digest: bytearray = field(repr=False)
    reference: str = field(repr=False)
    key_version: int
    operation: LeaseOperation

    def zeroize(self) -> None:
        _zero(self.lease_nonce)
        _zero(self.manifest_digest)

    def __repr__(self) -> str:
        return (
            "LeaseBinding(startup_nonce=[UUID], lease_nonce=[REDACTED], "
            "transaction_id=[UUID], vault_id=[UUID], manifest_digest=[DIGEST], "
            f"reference=[OPAQUE], key_version={self.key_version}, "
            f"operation={self.operation.name})"
        )


@dataclass(frozen=True, slots=True)
class HelloFrame:
    startup_nonce: UUID
    lease_nonce: bytearray = field(repr=False, compare=True)
    kind: FrameKind = field(default=FrameKind.HELLO, init=False)

    def __repr__(self) -> str:
        return "HelloFrame(startup_nonce=[UUID], lease_nonce=[REDACTED])"


@dataclass(slots=True)
class RequestFrame:
    binding: LeaseBinding = field(repr=False)
    kind: FrameKind = field(default=FrameKind.REQUEST, init=False)

    def zeroize(self) -> None:
        self.binding.zeroize()

    def __repr__(self) -> str:
        return "RequestFrame(binding=[OPAQUE])"


@dataclass(slots=True)
class GrantFrame:
    binding: LeaseBinding = field(repr=False)
    key: bytearray = field(repr=False)
    kind: FrameKind = field(default=FrameKind.GRANT, init=False)

    def zeroize(self) -> None:
        self.binding.zeroize()
        _zero(self.key)

    def __repr__(self) -> str:
        return "GrantFrame(binding=[OPAQUE], key=[REDACTED])"


@dataclass(slots=True)
class TransactionFrame:
    kind: FrameKind
    startup_nonce: UUID
    lease_nonce: bytearray = field(repr=False)
    transaction_id: UUID
    binding_digest: bytearray = field(repr=False)

    def __post_init__(self) -> None:
        if self.kind not in {FrameKind.PREPARED, FrameKind.COMMIT, FrameKind.COMMITTED}:
            raise _fail(KeyLeaseErrorCode.FRAME_KIND)

    def zeroize(self) -> None:
        _zero(self.lease_nonce)
        _zero(self.binding_digest)

    def __repr__(self) -> str:
        return f"TransactionFrame(kind={self.kind.name}, context=[OPAQUE])"


KeyLeaseFrame = HelloFrame | RequestFrame | GrantFrame | TransactionFrame


def _encode_binding(binding: LeaseBinding) -> bytearray:
    startup_nonce = _uuid_rfc(binding.startup_nonce)
    transaction_id = _uuid_rfc(binding.transaction_id)
    vault_id = _uuid_rfc(binding.vault_id)
    lease_nonce = _copy_exact(
        binding.lease_nonce,
        LEASE_NONCE_BYTES,
        KeyLeaseErrorCode.LEASE_NONCE_INVALID,
    )
    manifest_digest = _copy_exact(
        binding.manifest_digest,
        MANIFEST_DIGEST_BYTES,
        KeyLeaseErrorCode.MANIFEST_DIGEST_INVALID,
    )
    reference_id = parse_key_reference(binding.reference)
    reference = format_key_reference(reference_id).encode("ascii")
    key_version = _key_version(binding.key_version)
    operation = _operation(binding.operation)
    encoded = bytearray()
    try:
        encoded.extend(startup_nonce.bytes)
        encoded.extend(lease_nonce)
        encoded.extend(transaction_id.bytes)
        encoded.extend(vault_id.bytes)
        encoded.extend(manifest_digest)
        encoded.extend(reference)
        encoded.extend(struct.pack(">IH", key_version, int(operation)))
        if len(encoded) != _BINDING_BYTES:
            raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
        return encoded
    except BaseException:
        _zero(encoded)
        raise
    finally:
        _zero(lease_nonce)
        _zero(manifest_digest)


def binding_digest(binding: LeaseBinding) -> bytearray:
    """Bind lease frames to their process and session context to prevent cross-session reuse."""

    encoded = _encode_binding(binding)
    try:
        return bytearray(hashlib.sha256(encoded).digest())
    finally:
        _zero(encoded)


def _encode_final_context(frame: TransactionFrame) -> bytearray:
    startup_nonce = _uuid_rfc(frame.startup_nonce)
    transaction_id = _uuid_rfc(frame.transaction_id)
    lease_nonce = _copy_exact(
        frame.lease_nonce,
        LEASE_NONCE_BYTES,
        KeyLeaseErrorCode.LEASE_NONCE_INVALID,
    )
    digest = _copy_exact(
        frame.binding_digest,
        BINDING_DIGEST_BYTES,
        KeyLeaseErrorCode.BINDING_DIGEST_INVALID,
    )
    encoded = bytearray()
    try:
        encoded.extend(startup_nonce.bytes)
        encoded.extend(lease_nonce)
        encoded.extend(transaction_id.bytes)
        encoded.extend(digest)
        if len(encoded) != _FINAL_CONTEXT_BYTES:
            raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
        return encoded
    except BaseException:
        _zero(encoded)
        raise
    finally:
        _zero(lease_nonce)
        _zero(digest)


def _encode_payload(frame: KeyLeaseFrame) -> bytearray:
    if isinstance(frame, HelloFrame):
        lease_nonce = _copy_exact(
            frame.lease_nonce,
            LEASE_NONCE_BYTES,
            KeyLeaseErrorCode.LEASE_NONCE_INVALID,
        )
        try:
            payload = bytearray(_uuid_rfc(frame.startup_nonce).bytes)
            payload.extend(lease_nonce)
            return payload
        finally:
            _zero(lease_nonce)
    if isinstance(frame, RequestFrame):
        return _encode_binding(frame.binding)
    if isinstance(frame, GrantFrame):
        if not isinstance(frame.key, bytearray) or len(frame.key) != KEY_BYTES:
            raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
        payload = _encode_binding(frame.binding)
        payload.extend(frame.key)
        return payload
    if isinstance(frame, TransactionFrame):
        return _encode_final_context(frame)
    raise _fail(KeyLeaseErrorCode.FRAME_KIND)


def encode_frame(frame: KeyLeaseFrame) -> bytearray:
    """Serialize a bounded authenticated lease frame without exposing key material in logs."""

    payload = _encode_payload(frame)
    try:
        expected_payload = _PAYLOAD_BYTES_BY_KIND[frame.kind]
        if len(payload) != expected_payload:
            raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
        total_bytes = _HEADER.size + len(payload)
        if total_bytes > MAX_FRAME_BYTES:
            raise _fail(KeyLeaseErrorCode.FRAME_TOO_LARGE)
        encoded = bytearray(
            _HEADER.pack(
                _MAGIC,
                _VERSION,
                int(frame.kind),
                0,
                len(payload),
                _SEQUENCE_BY_KIND[frame.kind],
            )
        )
        encoded.extend(payload)
        return encoded
    except (KeyError, ValueError):
        raise _fail(KeyLeaseErrorCode.FRAME_KIND) from None
    finally:
        _zero(payload)


def _decode_header(header: bytearray) -> tuple[FrameKind, int]:
    if len(header) != _HEADER.size:
        raise _fail(KeyLeaseErrorCode.FRAME_TOO_SMALL)
    magic, version, kind_value, flags, payload_bytes, sequence = _HEADER.unpack(header)
    if magic != _MAGIC:
        raise _fail(KeyLeaseErrorCode.FRAME_MAGIC)
    if version != _VERSION:
        raise _fail(KeyLeaseErrorCode.FRAME_VERSION)
    try:
        kind = FrameKind(kind_value)
    except ValueError:
        raise _fail(KeyLeaseErrorCode.FRAME_KIND) from None
    if flags != 0:
        raise _fail(KeyLeaseErrorCode.FRAME_FLAGS)
    if _HEADER.size + payload_bytes > MAX_FRAME_BYTES:
        raise _fail(KeyLeaseErrorCode.FRAME_TOO_LARGE)
    if payload_bytes != _PAYLOAD_BYTES_BY_KIND[kind]:
        raise _fail(KeyLeaseErrorCode.FRAME_LENGTH)
    if sequence != _SEQUENCE_BY_KIND[kind]:
        raise _fail(KeyLeaseErrorCode.FRAME_SEQUENCE)
    return kind, payload_bytes


def _decode_uuid(payload: bytearray, offset: int) -> UUID:
    return _uuid_rfc(UUID(bytes=bytes(memoryview(payload)[offset : offset + 16])))


def _decode_binding(payload: bytearray) -> LeaseBinding:
    if len(payload) < _BINDING_BYTES:
        raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
    lease_nonce: bytearray | None = None
    manifest_digest: bytearray | None = None
    try:
        startup_nonce = _decode_uuid(payload, 0)
        lease_nonce = bytearray(memoryview(payload)[16:48])
        transaction_id = _decode_uuid(payload, 48)
        vault_id = _decode_uuid(payload, 64)
        manifest_digest = bytearray(memoryview(payload)[80:112])
        reference = bytes(memoryview(payload)[112:154]).decode("ascii")
        key_version, operation_value = struct.unpack_from(">IH", payload, 154)
        parse_key_reference(reference)
        operation = LeaseOperation(operation_value)
        return LeaseBinding(
            startup_nonce=startup_nonce,
            lease_nonce=lease_nonce,
            transaction_id=transaction_id,
            vault_id=vault_id,
            manifest_digest=manifest_digest,
            reference=reference,
            key_version=key_version,
            operation=operation,
        )
    except UnicodeDecodeError:
        _zero(lease_nonce)
        _zero(manifest_digest)
        raise _fail(KeyLeaseErrorCode.REFERENCE_INVALID) from None
    except ValueError:
        _zero(lease_nonce)
        _zero(manifest_digest)
        raise _fail(KeyLeaseErrorCode.OPERATION_INVALID) from None
    except BaseException:
        _zero(lease_nonce)
        _zero(manifest_digest)
        raise


def _decode_final_context(kind: FrameKind, payload: bytearray) -> TransactionFrame:
    return TransactionFrame(
        kind=kind,
        startup_nonce=_decode_uuid(payload, 0),
        lease_nonce=bytearray(memoryview(payload)[16:48]),
        transaction_id=_decode_uuid(payload, 48),
        binding_digest=bytearray(memoryview(payload)[64:96]),
    )


def _decode_payload(kind: FrameKind, payload: bytearray) -> KeyLeaseFrame:
    if len(payload) != _PAYLOAD_BYTES_BY_KIND[kind]:
        raise _fail(KeyLeaseErrorCode.FRAME_LAYOUT)
    if kind is FrameKind.HELLO:
        return HelloFrame(
            startup_nonce=_decode_uuid(payload, 0),
            lease_nonce=bytearray(memoryview(payload)[16:48]),
        )
    if kind is FrameKind.REQUEST:
        return RequestFrame(_decode_binding(payload))
    if kind is FrameKind.GRANT:
        binding = _decode_binding(payload)
        return GrantFrame(binding, bytearray(memoryview(payload)[_BINDING_BYTES:]))
    return _decode_final_context(kind, payload)


def _recv_exact(channel: socket.socket, size: int) -> bytearray:
    buffer = bytearray(size)
    view = memoryview(buffer)
    received = 0
    try:
        while received < size:
            try:
                count = channel.recv_into(view[received:], size - received)
            except TimeoutError:
                raise _fail(KeyLeaseErrorCode.TIMEOUT) from None
            except OSError:
                raise _fail(KeyLeaseErrorCode.IO) from None
            if count == 0:
                raise _fail(KeyLeaseErrorCode.EOF)
            received += count
        return buffer
    except BaseException:
        _zero(buffer)
        raise
    finally:
        view.release()


def receive_frame(channel: socket.socket) -> KeyLeaseFrame:
    """Read exactly one bounded lease frame and reject truncation or trailing ambiguity."""

    header = _recv_exact(channel, _HEADER.size)
    try:
        kind, payload_bytes = _decode_header(header)
    finally:
        _zero(header)
    payload = _recv_exact(channel, payload_bytes)
    try:
        return _decode_payload(kind, payload)
    finally:
        _zero(payload)


def send_frame(channel: socket.socket, frame: KeyLeaseFrame) -> None:
    """Write one complete lease frame so partial transport writes cannot alter protocol meaning."""

    encoded = encode_frame(frame)
    try:
        try:
            channel.sendall(encoded)
        except TimeoutError:
            raise _fail(KeyLeaseErrorCode.TIMEOUT) from None
        except OSError:
            raise _fail(KeyLeaseErrorCode.IO) from None
    finally:
        _zero(encoded)


def _peer_effective_uid(channel: socket.socket) -> int:
    if hasattr(socket, "SO_PEERCRED"):
        try:
            credentials = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack("3i", credentials)
            return int(uid)
        except (OSError, struct.error):
            raise _fail(KeyLeaseErrorCode.PEER_INVALID) from None
    if sys.platform == "darwin":
        effective_uid = ctypes.c_uint()
        effective_gid = ctypes.c_uint()
        libc = ctypes.CDLL(None, use_errno=True)
        getpeereid = libc.getpeereid
        getpeereid.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        getpeereid.restype = ctypes.c_int
        if getpeereid(channel.fileno(), effective_uid, effective_gid) != 0:
            raise _fail(KeyLeaseErrorCode.PEER_INVALID)
        return int(effective_uid.value)
    raise _fail(KeyLeaseErrorCode.PEER_INVALID)


def _validate_socket(channel: socket.socket) -> None:
    try:
        descriptor = channel.fileno()
        if descriptor < 0:
            raise _fail(KeyLeaseErrorCode.FD_INVALID)
        os.set_inheritable(descriptor, False)
        metadata = os.fstat(descriptor)
        if descriptor in {0, 1, 2} or not stat.S_ISSOCK(metadata.st_mode):
            raise _fail(KeyLeaseErrorCode.FD_INVALID)
        if channel.family != socket.AF_UNIX:
            raise _fail(KeyLeaseErrorCode.SOCKET_INVALID)
        if channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise _fail(KeyLeaseErrorCode.SOCKET_INVALID)
        if channel.getsockname() not in ("", b""):
            raise _fail(KeyLeaseErrorCode.SOCKET_INVALID)
        if channel.getpeername() not in ("", b""):
            raise _fail(KeyLeaseErrorCode.SOCKET_INVALID)
        if _peer_effective_uid(channel) != os.geteuid():
            raise _fail(KeyLeaseErrorCode.PEER_INVALID)
        if os.get_inheritable(descriptor):
            raise _fail(KeyLeaseErrorCode.FD_INVALID)
    except KeyLeaseError:
        raise
    except OSError:
        raise _fail(KeyLeaseErrorCode.NOT_CONNECTED) from None


class _ClientState(StrEnum):
    NEW = "NEW"
    READY = "READY"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    POISONED = "POISONED"
    CLOSED = "CLOSED"


class KeyLeaseClient:
    """Single-use client for the inherited, shell-owned key channel."""

    __slots__ = (
        "_channel",
        "_grant_timeout",
        "_lease_nonce",
        "_lock",
        "_startup_nonce",
        "_state",
        "_transaction_timeout",
    )

    def __init__(
        self,
        channel: socket.socket,
        startup_nonce: UUID,
        *,
        transaction_timeout: float = 5.0,
        grant_timeout: float = 125.0,
    ) -> None:
        _validate_socket(channel)
        _uuid_rfc(startup_nonce)
        if transaction_timeout <= 0 or grant_timeout <= 0:
            raise _fail(KeyLeaseErrorCode.TIMEOUT)
        channel.settimeout(transaction_timeout)
        self._channel = channel
        self._startup_nonce = startup_nonce
        self._lease_nonce = bytearray(secrets.token_bytes(LEASE_NONCE_BYTES))
        self._transaction_timeout = transaction_timeout
        self._grant_timeout = grant_timeout
        self._lock = threading.Lock()
        self._state = _ClientState.NEW

    @classmethod
    def from_inherited_fd(
        cls,
        startup_nonce: UUID,
        *,
        transaction_timeout: float = 5.0,
        grant_timeout: float = 125.0,
    ) -> KeyLeaseClient:
        try:
            os.set_inheritable(KEY_LEASE_FD, False)
            channel = socket.socket(fileno=KEY_LEASE_FD)
        except OSError:
            raise _fail(KeyLeaseErrorCode.FD_INVALID) from None
        try:
            return cls(
                channel,
                startup_nonce,
                transaction_timeout=transaction_timeout,
                grant_timeout=grant_timeout,
            )
        except BaseException:
            channel.close()
            raise

    def __repr__(self) -> str:
        return f"KeyLeaseClient(state={self._state.value}, channel=[ANONYMOUS])"

    def close(self) -> None:
        with self._lock:
            if self._state not in {_ClientState.CONSUMED, _ClientState.POISONED}:
                self._state = _ClientState.CLOSED
            self._close_channel()

    def _close_channel(self) -> None:
        _zero(self._lease_nonce)
        with suppress(OSError):
            self._channel.close()

    def _poison(self) -> None:
        self._state = _ClientState.POISONED
        self._close_channel()

    def _set_timeout(self, value: float) -> None:
        try:
            self._channel.settimeout(value)
        except OSError:
            raise _fail(KeyLeaseErrorCode.IO) from None

    def handshake(self) -> None:
        with self._lock:
            if self._state is _ClientState.READY:
                return
            if self._state is not _ClientState.NEW:
                raise self._state_error()
            try:
                send_frame(
                    self._channel,
                    HelloFrame(self._startup_nonce, self._lease_nonce),
                )
            except BaseException:
                self._poison()
                raise
            self._state = _ClientState.READY

    def transaction(
        self,
        *,
        transaction_id: UUID,
        vault_id: UUID,
        manifest_digest: bytes | bytearray | memoryview,
        reference: str,
        key_version: int,
        operation: LeaseOperation,
    ) -> KeyLeaseTransaction:
        startup_nonce = _uuid_rfc(self._startup_nonce)
        transaction_id = _uuid_rfc(transaction_id)
        vault_id = _uuid_rfc(vault_id)
        reference = format_key_reference(parse_key_reference(reference))
        key_version = _key_version(key_version)
        operation = _operation(operation)
        lease_nonce = _copy_exact(
            self._lease_nonce,
            LEASE_NONCE_BYTES,
            KeyLeaseErrorCode.LEASE_NONCE_INVALID,
        )
        manifest_digest_copy: bytearray | None = None
        binding: LeaseBinding | None = None
        digest: bytearray | None = None
        try:
            manifest_digest_copy = _copy_exact(
                manifest_digest,
                MANIFEST_DIGEST_BYTES,
                KeyLeaseErrorCode.MANIFEST_DIGEST_INVALID,
            )
            binding = LeaseBinding(
                startup_nonce=startup_nonce,
                lease_nonce=lease_nonce,
                transaction_id=transaction_id,
                vault_id=vault_id,
                manifest_digest=manifest_digest_copy,
                reference=reference,
                key_version=key_version,
                operation=operation,
            )
            digest = binding_digest(binding)
            return KeyLeaseTransaction(client=self, binding=binding, _binding_digest=digest)
        except BaseException:
            if binding is not None:
                binding.zeroize()
            else:
                _zero(lease_nonce)
                _zero(manifest_digest_copy)
            _zero(digest)
            raise

    def _state_error(self) -> KeyLeaseError:
        if self._state is _ClientState.NEW:
            return _fail(KeyLeaseErrorCode.HANDSHAKE_REQUIRED)
        if self._state is _ClientState.ACTIVE:
            return _fail(KeyLeaseErrorCode.TRANSACTION_ACTIVE)
        if self._state is _ClientState.CONSUMED:
            return _fail(KeyLeaseErrorCode.CONSUMED)
        return _fail(KeyLeaseErrorCode.CLOSED)

    def _begin(self, transaction: KeyLeaseTransaction) -> bytearray:
        if not self._lock.acquire(blocking=False):
            raise _fail(KeyLeaseErrorCode.TRANSACTION_ACTIVE)
        response: KeyLeaseFrame | None = None
        try:
            if self._state is not _ClientState.READY:
                raise self._state_error()
            self._state = _ClientState.ACTIVE
            send_frame(self._channel, RequestFrame(transaction.binding))
            self._set_timeout(self._grant_timeout)
            try:
                response = receive_frame(self._channel)
            finally:
                self._set_timeout(self._transaction_timeout)
            if not isinstance(response, GrantFrame):
                raise _fail(KeyLeaseErrorCode.RESPONSE_ORDER)
            if not _bindings_equal(response.binding, transaction.binding):
                raise _fail(KeyLeaseErrorCode.RESPONSE_MISMATCH)
            if len(response.key) != KEY_BYTES:
                raise _fail(KeyLeaseErrorCode.KEY_UNAVAILABLE)
            key = response.key
            response.key = bytearray()
            return key
        except BaseException:
            self._poison()
            self._lock.release()
            raise
        finally:
            if response is not None:
                _zero_frame(response)

    def _commit(
        self,
        transaction: KeyLeaseTransaction,
        publish: Callable[[], None],
    ) -> None:
        try:
            prepared = transaction._context_frame(FrameKind.PREPARED)
            try:
                send_frame(self._channel, prepared)
            finally:
                prepared.zeroize()
            response = receive_frame(self._channel)
            try:
                if not isinstance(response, TransactionFrame):
                    raise _fail(KeyLeaseErrorCode.RESPONSE_ORDER)
                if response.kind is not FrameKind.COMMIT:
                    raise _fail(KeyLeaseErrorCode.RESPONSE_ORDER)
                if not transaction._matches_context(response):
                    raise _fail(KeyLeaseErrorCode.RESPONSE_MISMATCH)
            finally:
                _zero_frame(response)
            try:
                publish()
            except Exception:
                raise _fail(KeyLeaseErrorCode.PUBLISH_FAILED) from None
            committed = transaction._context_frame(FrameKind.COMMITTED)
            try:
                send_frame(self._channel, committed)
            finally:
                committed.zeroize()
            self._state = _ClientState.CONSUMED
            self._close_channel()
        except BaseException:
            self._poison()
            raise
        finally:
            self._lock.release()

    def _abort(self) -> None:
        try:
            self._poison()
        finally:
            self._lock.release()


@dataclass(slots=True)
class KeyLeaseTransaction:
    client: KeyLeaseClient = field(repr=False)
    binding: LeaseBinding = field(repr=False)
    _binding_digest: bytearray = field(repr=False)
    _key: bytearray | None = field(default=None, init=False, repr=False)
    _entered: bool = field(default=False, init=False, repr=False)
    _finished: bool = field(default=False, init=False, repr=False)
    _committed: bool = field(default=False, init=False, repr=False)

    @property
    def key(self) -> bytearray:
        if self._key is None:
            raise _fail(KeyLeaseErrorCode.KEY_UNAVAILABLE)
        return self._key

    def __repr__(self) -> str:
        return (
            "KeyLeaseTransaction(transaction_id=[UUID], vault_id=[UUID], "
            f"operation={self.binding.operation.name}, binding=[OPAQUE], key=[REDACTED])"
        )

    def __enter__(self) -> KeyLeaseTransaction:
        if self._entered:
            raise _fail(KeyLeaseErrorCode.TRANSACTION_REPLAY)
        self._entered = True
        try:
            self._key = self.client._begin(self)
        except BaseException:
            self._zero_context()
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exception, traceback
        _zero(self._key)
        self._key = None
        try:
            if not self._finished:
                self.client._abort()
            if exception_type is None and not self._committed:
                raise _fail(KeyLeaseErrorCode.COMMIT_REQUIRED)
        finally:
            self._zero_context()
        return False

    def commit(self, publish: Callable[[], None]) -> None:
        if not self._entered or self._key is None:
            raise _fail(KeyLeaseErrorCode.KEY_UNAVAILABLE)
        if self._finished:
            raise _fail(KeyLeaseErrorCode.TRANSACTION_REPLAY)
        if not callable(publish):
            raise _fail(KeyLeaseErrorCode.PUBLISH_FAILED)
        _zero(self._key)
        self._key = None
        self._finished = True
        self.client._commit(self, publish)
        self._committed = True

    def _context_frame(self, kind: FrameKind) -> TransactionFrame:
        return TransactionFrame(
            kind=kind,
            startup_nonce=self.binding.startup_nonce,
            lease_nonce=bytearray(self.binding.lease_nonce),
            transaction_id=self.binding.transaction_id,
            binding_digest=bytearray(self._binding_digest),
        )

    def _matches_context(self, frame: TransactionFrame) -> bool:
        return (
            frame.startup_nonce == self.binding.startup_nonce
            and frame.transaction_id == self.binding.transaction_id
            and hmac.compare_digest(frame.lease_nonce, self.binding.lease_nonce)
            and hmac.compare_digest(frame.binding_digest, self._binding_digest)
        )

    def _zero_context(self) -> None:
        self.binding.zeroize()
        _zero(self._binding_digest)


def _bindings_equal(left: LeaseBinding, right: LeaseBinding) -> bool:
    left_encoded = _encode_binding(left)
    right_encoded = _encode_binding(right)
    try:
        return hmac.compare_digest(left_encoded, right_encoded)
    finally:
        _zero(left_encoded)
        _zero(right_encoded)


def _zero_frame(frame: KeyLeaseFrame) -> None:
    if isinstance(frame, HelloFrame):
        _zero(frame.lease_nonce)
    elif isinstance(frame, (RequestFrame, GrantFrame, TransactionFrame)):
        frame.zeroize()
