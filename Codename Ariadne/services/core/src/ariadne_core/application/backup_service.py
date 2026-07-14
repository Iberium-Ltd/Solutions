"""Consistent encrypted backup orchestration behind file and key capabilities."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy import insert, update
from uuid6 import uuid7

from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.models import backup_records
from ariadne_core.security.backup import BackupError, BackupMetadata, create_backup, decrypt_backup
from ariadne_core.security.file_broker import BrokerOperation, FileBroker
from ariadne_core.security.key_custody import KeyCustodian


@dataclass(frozen=True, slots=True)
class BackupResult:
    record_id: str
    metadata: BackupMetadata
    ciphertext_sha256: str


class BackupService:
    def __init__(
        self,
        *,
        vault: VaultManager,
        custodian: KeyCustodian,
        file_broker: FileBroker,
    ) -> None:
        self.vault = vault
        self.custodian = custodian
        self.file_broker = file_broker

    def create(self, file_broker_token: str) -> BackupResult:
        manifest = self.vault.manifest
        destination = self.file_broker.consume(file_broker_token, BrokerOperation.BACKUP_WRITE)
        record_id = str(uuid7())
        nonce = os.urandom(12)
        nonce_b64 = base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("=")
        timestamp = time.time_ns() // 1_000
        with self.vault.engine.begin() as connection:
            connection.execute(
                insert(backup_records).values(
                    id=record_id,
                    vault_id=manifest.vault_id,
                    bundle_version=1,
                    destination_class="USER_SELECTED",
                    nonce_b64=nonce_b64,
                    ciphertext_sha256="",
                    key_version=1,
                    created_at_us=timestamp,
                    verified_at_us=None,
                    restored_at_us=None,
                    retention_expires_at_us=None,
                    state="RESERVED",
                )
            )

        snapshot = self.vault.root / f".backup-snapshot-{record_id}.db"
        try:
            with self.custodian.borrow(manifest.database_key_ref) as database_key:
                SqlcipherEngineFactory(
                    self.vault.root / "vault.db", database_key
                ).export_encrypted_snapshot(snapshot)
            with self.custodian.borrow(manifest.backup_key_ref) as backup_key:
                metadata = create_backup(
                    source_database=snapshot,
                    destination=destination,
                    backup_key=backup_key,
                    vault_id=manifest.vault_id,
                    key_version=1,
                    nonce=nonce,
                )
                verified_metadata, verified_snapshot = decrypt_backup(destination, backup_key)
            if (
                verified_metadata != metadata
                or hashlib.sha256(verified_snapshot).hexdigest() != metadata.source_sha256
            ):
                raise BackupError("backup verification failed")
            ciphertext_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
            with self.vault.engine.begin() as connection:
                connection.execute(
                    update(backup_records)
                    .where(backup_records.c.id == record_id)
                    .values(
                        ciphertext_sha256=ciphertext_sha256,
                        verified_at_us=time.time_ns() // 1_000,
                        state="VERIFIED",
                    )
                )
            return BackupResult(record_id, metadata, ciphertext_sha256)
        except Exception:
            with suppress(Exception), self.vault.engine.begin() as connection:
                connection.execute(
                    update(backup_records)
                    .where(backup_records.c.id == record_id)
                    .values(state="FAILED")
                )
            raise
        finally:
            with suppress(OSError):
                snapshot.unlink()
