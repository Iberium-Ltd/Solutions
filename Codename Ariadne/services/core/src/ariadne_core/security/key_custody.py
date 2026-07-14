"""Key-custody ports; production custody is mediated by the macOS shell."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Protocol


class KeyCustodyError(RuntimeError):
    pass


class KeyCustodian(Protocol):
    """Opaque key references are persisted; key bytes are borrowed only while unlocked."""

    def create(self, reference: str, *, size: int = 32) -> None: ...

    def borrow(self, reference: str) -> AbstractContextManager[bytearray]: ...

    def delete(self, reference: str) -> None: ...


@dataclass(slots=True)
class MemoryKeyCustodian:
    """Deterministic test adapter; never selected by production bootstrap."""

    values: dict[str, bytes] = field(default_factory=dict)

    def create(self, reference: str, *, size: int = 32) -> None:
        import secrets

        if reference in self.values:
            raise KeyCustodyError("key reference already exists")
        self.values[reference] = secrets.token_bytes(size)

    @contextmanager
    def borrow(self, reference: str) -> Iterator[bytearray]:
        value = self.values.get(reference)
        if value is None:
            raise KeyCustodyError("key reference is unavailable")
        borrowed = bytearray(value)
        try:
            yield borrowed
        finally:
            borrowed[:] = b"\x00" * len(borrowed)

    def delete(self, reference: str) -> None:
        if self.values.pop(reference, None) is None:
            raise KeyCustodyError("key reference is unavailable")
