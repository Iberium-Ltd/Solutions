from __future__ import annotations

import os

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ariadne_core.application.backup_service import BackupService
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.models import backup_records
from ariadne_core.security.backup import (
    MAX_ENVELOPE_BYTES,
    MAX_FOUNDATION_BACKUP_BYTES,
    BackupError,
    commit_staged_restore,
    create_backup,
    decrypt_backup,
    recover_interrupted_restore,
    stage_restore,
)
from ariadne_core.security.file_broker import BrokerOperation, FileBroker
from ariadne_core.security.key_custody import MemoryKeyCustodian


def test_backup_is_authenticated_encrypted_and_stages_on_same_volume(tmp_path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manifest = manager.create(display_name="Synthetic backup vault")
    database = tmp_path / "vault" / "vault.db"
    bundle = tmp_path / "vault" / "synthetic.ariadne-backup"
    broker = FileBroker()
    token = broker.issue(BrokerOperation.BACKUP_WRITE, bundle)
    result = BackupService(vault=manager, custodian=custodian, file_broker=broker).create(token)

    with manager.engine.connect() as connection:
        record = (
            connection.execute(
                select(backup_records).where(backup_records.c.id == result.record_id)
            )
            .mappings()
            .one()
        )
    assert record["state"] == "VERIFIED"
    assert record["ciphertext_sha256"] == result.ciphertext_sha256
    assert record["nonce_b64"]
    assert not list(database.parent.glob(".backup-snapshot-*.db"))

    manager.lock()

    with custodian.borrow(manifest.backup_key_ref) as backup_key:
        decoded, plaintext = decrypt_backup(bundle, backup_key)
        staging = stage_restore(
            bundle=bundle,
            destination_database=database,
            backup_key=backup_key,
            expected_vault_id=manifest.vault_id,
        )

    with custodian.borrow(manifest.database_key_ref) as database_key:

        def verifier(path) -> None:
            SqlcipherEngineFactory(path, database_key).probe()

        commit_staged_restore(
            staging=staging,
            destination_database=database,
            verifier=verifier,
        )

    assert decoded == result.metadata
    assert plaintext == database.read_bytes()
    assert bundle.read_bytes().find(b"Synthetic backup vault") == -1
    assert not staging.exists()
    assert os.stat(bundle).st_mode & 0o777 == 0o600
    assert os.stat(database).st_mode & 0o777 == 0o600

    manager.unlock()
    manager.lock()


def test_backup_corruption_and_wrong_key_fail_closed(tmp_path) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"synthetic encrypted-database stand-in")
    bundle = tmp_path / "backup.bin"
    key = bytearray(b"b" * 32)
    create_backup(
        source_database=source,
        destination=bundle,
        backup_key=key,
        vault_id="01900000-0000-7000-8000-000000000001",
        key_version=1,
    )
    with pytest.raises(BackupError):
        decrypt_backup(bundle, bytearray(b"c" * 32))
    damaged = bytearray(bundle.read_bytes())
    damaged[-1] ^= 1
    bundle.write_bytes(damaged)
    with pytest.raises(BackupError):
        decrypt_backup(bundle, key)


def test_backup_rejects_truncation_header_tamper_and_oversize_before_read(tmp_path) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"synthetic encrypted database")
    bundle = tmp_path / "backup.bin"
    key = bytearray(b"k" * 32)
    create_backup(
        source_database=source,
        destination=bundle,
        backup_key=key,
        vault_id="01900000-0000-7000-8000-000000000001",
        key_version=1,
    )
    original = bundle.read_bytes()
    for cut in (0, 1, len(original) // 2, len(original) - 1):
        bundle.write_bytes(original[:cut])
        with pytest.raises(BackupError):
            decrypt_backup(bundle, key)
    tampered = bytearray(original)
    tampered[14] ^= 1
    bundle.write_bytes(tampered)
    with pytest.raises(BackupError):
        decrypt_backup(bundle, key)

    oversized = tmp_path / "oversized.db"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_FOUNDATION_BACKUP_BYTES + 1)
    with pytest.raises(BackupError, match="size"):
        create_backup(
            source_database=oversized,
            destination=tmp_path / "must-not-exist.bin",
            backup_key=key,
            vault_id="01900000-0000-7000-8000-000000000001",
            key_version=1,
        )
    assert not (tmp_path / "must-not-exist.bin").exists()

    oversized_bundle = tmp_path / "oversized.backup"
    with oversized_bundle.open("wb") as stream:
        stream.truncate(MAX_ENVELOPE_BYTES + 1)
    with pytest.raises(BackupError, match="size"):
        decrypt_backup(oversized_bundle, key)


def test_interrupted_backup_fails_record_and_cleans_snapshot(tmp_path, monkeypatch) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manager.create(display_name="Synthetic interrupted backup vault")
    destination = tmp_path / "vault" / "interrupted.ariadne-backup"
    broker = FileBroker()
    token = broker.issue(BrokerOperation.BACKUP_WRITE, destination)

    from ariadne_core.application import backup_service as backup_module

    def fail_backup(**_kwargs) -> None:  # type: ignore[no-untyped-def]
        raise BackupError("synthetic interrupted backup")

    monkeypatch.setattr(backup_module, "create_backup", fail_backup)
    with pytest.raises(BackupError, match="interrupted"):
        BackupService(vault=manager, custodian=custodian, file_broker=broker).create(token)
    with manager.engine.connect() as connection:
        states = connection.execute(select(backup_records.c.state)).scalars().all()
    assert states == ["FAILED"]
    assert not destination.exists()
    assert not list(manager.root.glob(".backup-snapshot-*.db"))
    manager.lock()


def test_nonce_reservation_is_durable_and_never_reused(tmp_path, monkeypatch) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manager.create(display_name="Synthetic nonce vault")
    broker = FileBroker()
    from ariadne_core.application import backup_service as backup_module

    monkeypatch.setattr(backup_module.os, "urandom", lambda _size: b"n" * 12)
    service = BackupService(vault=manager, custodian=custodian, file_broker=broker)
    first = broker.issue(BrokerOperation.BACKUP_WRITE, tmp_path / "vault" / "first.backup")
    service.create(first)
    second_path = tmp_path / "vault" / "second.backup"
    second = broker.issue(BrokerOperation.BACKUP_WRITE, second_path)
    with pytest.raises(IntegrityError):
        service.create(second)
    assert not second_path.exists()
    manager.lock()


def test_restore_failures_preserve_or_recover_original_at_every_swap_boundary(tmp_path) -> None:
    parent = tmp_path / "vault"
    parent.mkdir(mode=0o700)
    destination = parent / "vault.db"
    original = b"synthetic encrypted original"
    replacement = b"synthetic encrypted replacement"
    destination.write_bytes(original)
    destination.chmod(0o600)

    precheck_stage = parent / ".vault.db.precheck.restore"
    precheck_stage.write_bytes(replacement)
    precheck_stage.chmod(0o600)
    with pytest.raises(BackupError):
        commit_staged_restore(
            staging=precheck_stage,
            destination_database=destination,
            verifier=lambda _path: (_ for _ in ()).throw(RuntimeError("synthetic precheck")),
        )
    assert destination.read_bytes() == original

    postcheck_stage = parent / ".vault.db.postcheck.restore"
    postcheck_stage.write_bytes(replacement)
    postcheck_stage.chmod(0o600)
    calls = 0

    def fail_postcheck(_path) -> None:  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic post-swap failure")

    with pytest.raises(BackupError):
        commit_staged_restore(
            staging=postcheck_stage,
            destination_database=destination,
            verifier=fail_postcheck,
        )
    assert destination.read_bytes() == original
    assert not (parent / ".vault.db.restore-rollback").exists()

    rollback = parent / ".vault.db.restore-rollback"
    os.replace(destination, rollback)
    assert recover_interrupted_restore(destination) is True
    assert destination.read_bytes() == original
    assert recover_interrupted_restore(destination) is False

    rollback.write_bytes(original)
    rollback.chmod(0o600)
    with pytest.raises(BackupError, match="ambiguous"):
        recover_interrupted_restore(destination)
