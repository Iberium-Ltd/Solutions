from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from uuid6 import uuid7

from ariadne_core.application.vault import VaultManager, VaultManifest
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.security.key_lease import (
    KeyLeaseTransaction,
    LeaseBinding,
    LeaseOperation,
)


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


@dataclass(slots=True)
class _FakeLeaseTransaction:
    binding: LeaseBinding
    key: bytearray
    manager: VaultManager
    fail_after_publish: bool = False
    committed: bool = False

    def __enter__(self) -> _FakeLeaseTransaction:
        return self

    def commit(self, publish: Callable[[], None]) -> None:
        assert self.manager.is_unlocked is False
        self.key[:] = b"\x00" * len(self.key)
        publish()
        assert self.manager.is_unlocked is True
        if self.fail_after_publish:
            raise RuntimeError("synthetic committed-write failure")
        self.committed = True

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exception_type, exception, traceback
        return False


def _transaction(
    manager: VaultManager,
    manifest: VaultManifest,
    key: bytearray,
    operation: LeaseOperation,
    *,
    fail_after_publish: bool = False,
) -> tuple[KeyLeaseTransaction, _FakeLeaseTransaction]:
    fake = _FakeLeaseTransaction(
        binding=LeaseBinding(
            startup_nonce=uuid4(),
            lease_nonce=bytearray(b"l" * 32),
            transaction_id=uuid4(),
            vault_id=UUID(manifest.vault_id),
            manifest_digest=bytearray(manifest.digest()),
            reference=manifest.database_key_ref,
            key_version=manifest.database_key_version,
            operation=operation,
        ),
        key=key,
        manager=manager,
        fail_after_publish=fail_after_publish,
    )
    return cast(KeyLeaseTransaction, fake), fake


def test_unlock_stays_private_until_commit_and_zeroizes_on_lock(tmp_path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manifest = manager.create(display_name="Synthetic leased unlock vault")
    manager.lock()
    with custodian.borrow(manifest.database_key_ref) as borrowed:
        leased_key = bytearray(borrowed)
    transaction, fake = _transaction(
        manager,
        manifest,
        leased_key,
        LeaseOperation.DATABASE_UNLOCK_V1,
    )

    assert manager.unlock_with_lease(transaction=transaction) == manifest
    assert fake.committed is True
    assert fake.key == bytearray(32)
    retained_key = manager._key
    assert retained_key is not None and any(retained_key)

    manager.lock()
    assert manager.is_unlocked is False
    assert retained_key == bytearray(32)


def test_create_uses_the_same_staged_commit_boundary(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault")
    manifest = _manifest()
    transaction, fake = _transaction(
        manager,
        manifest,
        bytearray(range(32)),
        LeaseOperation.DATABASE_CREATE_V1,
    )

    assert (
        manager.create_with_lease(
            display_name="Synthetic leased create vault",
            manifest=manifest,
            transaction=transaction,
        )
        == manifest
    )
    assert fake.committed is True
    assert (tmp_path / "vault" / "vault.json").read_bytes() == manifest.to_json()
    assert not (tmp_path / "vault" / "vault.db").read_bytes().startswith(b"SQLite format 3")
    manager.lock()


def test_ambiguous_create_commit_locks_and_removes_staged_files(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault")
    manifest = _manifest()
    transaction, _fake = _transaction(
        manager,
        manifest,
        bytearray(reversed(range(32))),
        LeaseOperation.DATABASE_CREATE_V1,
        fail_after_publish=True,
    )

    with pytest.raises(RuntimeError, match="synthetic committed-write failure"):
        manager.create_with_lease(
            display_name="Synthetic failed create vault",
            manifest=manifest,
            transaction=transaction,
        )

    assert manager.is_unlocked is False
    assert not (tmp_path / "vault" / "vault.json").exists()
    assert not (tmp_path / "vault" / "vault.db").exists()
