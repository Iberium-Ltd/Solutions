"""One-shot file capabilities; API callers never submit filesystem paths."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class FileBrokerError(RuntimeError):
    pass


class BrokerOperation(StrEnum):
    BACKUP_WRITE = "BACKUP_WRITE"
    EXPORT_WRITE = "EXPORT_WRITE"
    IMPORT_READ = "IMPORT_READ"
    RESTORE_READ = "RESTORE_READ"


@dataclass(frozen=True, slots=True)
class BrokeredPath:
    operation: BrokerOperation
    path: Path
    expires_at: float


class FileBroker:
    """Exchange a shell-selected path for one short-lived, operation-bound token."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[bytes, BrokeredPath] = {}

    def issue(
        self,
        operation: BrokerOperation,
        path: Path,
        *,
        ttl_seconds: int = 60,
    ) -> str:
        if ttl_seconds < 1 or ttl_seconds > 300:
            raise FileBrokerError("file capability lifetime is outside the allowed range")
        if not path.is_absolute():
            raise FileBrokerError("file selection must resolve to an absolute path")

        parent = path.parent.resolve(strict=True)
        if parent.is_symlink() or not parent.is_dir():
            raise FileBrokerError("file selection parent is unsafe")
        safe_path = parent / path.name
        if safe_path.exists() and safe_path.is_symlink():
            raise FileBrokerError("symbolic-link destinations are not accepted")

        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).digest()
        self._entries[digest] = BrokeredPath(
            operation=operation,
            path=safe_path,
            expires_at=self._clock() + ttl_seconds,
        )
        return token

    def consume(self, token: str, operation: BrokerOperation) -> Path:
        # Pop before validation so an expired or wrong-operation capability is
        # still burned and cannot be probed repeatedly or reused in another flow.
        digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
        entry = self._entries.pop(digest, None)
        if entry is None or entry.expires_at < self._clock() or entry.operation is not operation:
            raise FileBrokerError("file capability is invalid or expired")
        return entry.path

    def purge_expired(self) -> None:
        now = self._clock()
        self._entries = {
            digest: entry for digest, entry in self._entries.items() if entry.expires_at >= now
        }
