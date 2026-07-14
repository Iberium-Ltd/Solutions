"""Per-launch authentication and bounded request replay protection."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr

from ariadne_core.bootstrap import BootstrapRejected, decode_session_token

DEFAULT_REPLAY_CAPACITY = 4096
DEFAULT_REPLAY_TTL_SECONDS = 300.0


class LaunchSession:
    """Stores only a token digest and bounded replay metadata."""

    __slots__ = (
        "_expires_at",
        "_expires_monotonic",
        "_replay_capacity",
        "_replay_lock",
        "_replay_seen",
        "_replay_ttl_seconds",
        "_token_digest",
    )

    def __init__(
        self,
        *,
        token_digest: bytes,
        ttl_seconds: float | None,
        replay_capacity: int = DEFAULT_REPLAY_CAPACITY,
        replay_ttl_seconds: float = DEFAULT_REPLAY_TTL_SECONDS,
    ) -> None:
        if len(token_digest) != hashlib.sha256().digest_size:
            raise ValueError("token digest is invalid")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("session ttl must be positive")
        if replay_capacity <= 0 or replay_ttl_seconds <= 0:
            raise ValueError("replay bounds must be positive")

        self._token_digest = bytes(token_digest)
        self._expires_monotonic = None if ttl_seconds is None else time.monotonic() + ttl_seconds
        self._expires_at = (
            None if ttl_seconds is None else datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        )
        self._replay_capacity = replay_capacity
        self._replay_ttl_seconds = replay_ttl_seconds
        self._replay_seen: OrderedDict[str, float] = OrderedDict()
        self._replay_lock = threading.Lock()

    @classmethod
    def from_secret(
        cls,
        token: SecretStr,
        *,
        ttl_seconds: float | None,
        replay_capacity: int = DEFAULT_REPLAY_CAPACITY,
        replay_ttl_seconds: float = DEFAULT_REPLAY_TTL_SECONDS,
    ) -> LaunchSession:
        token_bytes = bytearray(decode_session_token(token.get_secret_value()))
        try:
            digest = hashlib.sha256(token_bytes).digest()
        finally:
            for index in range(len(token_bytes)):
                token_bytes[index] = 0
        return cls(
            token_digest=digest,
            ttl_seconds=ttl_seconds,
            replay_capacity=replay_capacity,
            replay_ttl_seconds=replay_ttl_seconds,
        )

    @classmethod
    def from_token_bytes(
        cls,
        token: bytes,
        *,
        ttl_seconds: float | None,
        replay_capacity: int = DEFAULT_REPLAY_CAPACITY,
        replay_ttl_seconds: float = DEFAULT_REPLAY_TTL_SECONDS,
    ) -> LaunchSession:
        if len(token) != 32:
            raise ValueError("token must contain 256 bits")
        return cls(
            token_digest=hashlib.sha256(token).digest(),
            ttl_seconds=ttl_seconds,
            replay_capacity=replay_capacity,
            replay_ttl_seconds=replay_ttl_seconds,
        )

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def replay_size(self) -> int:
        with self._replay_lock:
            return len(self._replay_seen)

    def is_expired(self) -> bool:
        return self._expires_monotonic is not None and time.monotonic() >= self._expires_monotonic

    def authenticate(self, supplied_token: str | None) -> bool:
        if supplied_token is None or self.is_expired():
            return False
        try:
            supplied_bytes = bytearray(decode_session_token(supplied_token))
        except BootstrapRejected:
            return False
        try:
            supplied_digest = hashlib.sha256(supplied_bytes).digest()
        finally:
            for index in range(len(supplied_bytes)):
                supplied_bytes[index] = 0
        return hmac.compare_digest(self._token_digest, supplied_digest)

    def accept_request_id(self, request_id: str) -> bool:
        """Accept a canonical UUID once within a bounded monotonic replay window."""
        try:
            parsed = UUID(request_id)
        except (ValueError, AttributeError, TypeError):
            return False
        if str(parsed) != request_id:
            return False

        now = time.monotonic()
        with self._replay_lock:
            while self._replay_seen:
                oldest_id, expires_at = next(iter(self._replay_seen.items()))
                if expires_at > now:
                    break
                del self._replay_seen[oldest_id]

            if request_id in self._replay_seen:
                return False
            while len(self._replay_seen) >= self._replay_capacity:
                self._replay_seen.popitem(last=False)
            self._replay_seen[request_id] = now + self._replay_ttl_seconds
        return True
