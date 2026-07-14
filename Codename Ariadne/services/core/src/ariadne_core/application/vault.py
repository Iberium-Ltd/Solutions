"""Vault lifecycle with shell-mediated key custody and fail-closed locking."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import RFC_4122, UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from uuid6 import uuid7

from ariadne_core.domain.settings import VaultSettings
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.migrate import require_current_revision, upgrade_to_head
from ariadne_core.infrastructure.db.models import (
    event_stream_sessions,
    settings,
    vault_crypto,
    vaults,
)
from ariadne_core.security.key_custody import KeyCustodian
from ariadne_core.security.key_lease import KeyLeaseTransaction, LeaseOperation


class VaultLifecycleError(RuntimeError):
    pass


VAULT_FORMAT_VERSION = 1
DATABASE_KEY_VERSION = 1
KEY_REFERENCE_PREFIX = "kc:v1:"
MAX_MANIFEST_BYTES = 4096


class VaultSubkeyPurpose(StrEnum):
    INTAKE_FINGERPRINT = "INTAKE_FINGERPRINT"
    QUERY_POLICY = "QUERY_POLICY"
    PUBLIC_DISCOVERY_CAPTURE = "PUBLIC_DISCOVERY_CAPTURE"


def _validate_uuid(value: str, *, label: str) -> None:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise VaultLifecycleError(f"{label} is invalid") from error
    if str(parsed) != value or parsed.variant != RFC_4122:
        raise VaultLifecycleError(f"{label} is invalid")


def _validate_key_reference(value: str) -> None:
    if not isinstance(value, str) or not value.startswith(KEY_REFERENCE_PREFIX):
        raise VaultLifecycleError("vault key reference is invalid")
    encoded = value.removeprefix(KEY_REFERENCE_PREFIX)
    try:
        parsed = UUID(encoded)
    except (ValueError, AttributeError, TypeError) as error:
        raise VaultLifecycleError("vault key reference is invalid") from error
    if str(parsed) != encoded or parsed.version != 4 or parsed.variant != RFC_4122:
        raise VaultLifecycleError("vault key reference is invalid")


@dataclass(frozen=True, slots=True)
class VaultManifest:
    vault_id: str
    format_version: int
    database_key_ref: str
    backup_key_ref: str
    database_key_version: int = DATABASE_KEY_VERSION

    def __post_init__(self) -> None:
        _validate_uuid(self.vault_id, label="vault identifier")
        if type(self.format_version) is not int or self.format_version != VAULT_FORMAT_VERSION:
            raise VaultLifecycleError("vault format version is unsupported")
        if (
            type(self.database_key_version) is not int
            or self.database_key_version != DATABASE_KEY_VERSION
        ):
            raise VaultLifecycleError("vault key version is unsupported")
        _validate_key_reference(self.database_key_ref)
        _validate_key_reference(self.backup_key_ref)
        if self.database_key_ref == self.backup_key_ref:
            raise VaultLifecycleError("vault key references must be distinct")

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "backupKeyRef": self.backup_key_ref,
                "databaseKeyVersion": self.database_key_version,
                "databaseKeyRef": self.database_key_ref,
                "formatVersion": self.format_version,
                "vaultId": self.vault_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def digest(self) -> bytes:
        return hashlib.sha256(self.to_json()).digest()

    @classmethod
    def from_path(cls, path: Path) -> VaultManifest:
        try:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
            ):
                raise ValueError
            encoded = path.read_bytes()
            if not encoded or len(encoded) > MAX_MANIFEST_BYTES:
                raise ValueError
            raw = json.loads(encoded)
            if not isinstance(raw, dict) or set(raw) != {
                "backupKeyRef",
                "databaseKeyRef",
                "databaseKeyVersion",
                "formatVersion",
                "vaultId",
            }:
                raise ValueError
            manifest = cls(
                vault_id=str(raw["vaultId"]),
                format_version=raw["formatVersion"],
                database_key_ref=str(raw["databaseKeyRef"]),
                backup_key_ref=str(raw["backupKeyRef"]),
                database_key_version=raw["databaseKeyVersion"],
            )
            if encoded != manifest.to_json():
                raise ValueError
            return manifest
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            VaultLifecycleError,
        ) as error:
            raise VaultLifecycleError("vault manifest is invalid") from error


def _write_manifest(path: Path, manifest: VaultManifest) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(manifest.to_json())
        stream.flush()
        os.fsync(stream.fileno())


class VaultManager:
    def __init__(self, root: Path, custodian: KeyCustodian | None = None) -> None:
        self.root = root
        self.custodian = custodian
        self._engine: Engine | None = None
        self._key: bytearray | None = None
        self._manifest: VaultManifest | None = None
        self._borrowed_subkeys: list[bytearray] = []

    def _require_custodian(self) -> KeyCustodian:
        if self.custodian is None:
            raise VaultLifecycleError("direct key custody is unavailable")
        return self.custodian

    @property
    def is_unlocked(self) -> bool:
        return self._engine is not None

    @property
    def has_manifest(self) -> bool:
        manifest_path = self.root / "vault.json"
        return manifest_path.is_file() and not manifest_path.is_symlink()

    def descriptor(self) -> VaultManifest:
        if self._manifest is not None and self._engine is not None:
            return self._manifest
        if not self.has_manifest:
            raise VaultLifecycleError("vault is unavailable")
        return VaultManifest.from_path(self.root / "vault.json")

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise VaultLifecycleError("vault is locked")
        return self._engine

    @property
    def manifest(self) -> VaultManifest:
        if self._manifest is None or self._engine is None:
            raise VaultLifecycleError("vault is locked")
        return self._manifest

    @contextmanager
    def borrow_subkey(self, purpose: VaultSubkeyPurpose) -> Iterator[bytearray]:
        """Derive one purpose-bound working key and clear it after use."""

        key, manifest = self._key, self._manifest
        if key is None or manifest is None or self._engine is None:
            raise VaultLifecycleError("vault is locked")
        context = (
            b"ariadne-subkey-v1\x00"
            + purpose.value.encode("ascii")
            + b"\x00"
            + manifest.vault_id.encode("ascii")
        )
        derived = bytearray(hmac.digest(key, context, "sha256"))
        self._borrowed_subkeys.append(derived)
        try:
            yield derived
        finally:
            derived[:] = b"\x00" * len(derived)
            with suppress(ValueError):
                self._borrowed_subkeys.remove(derived)

    def create(self, *, display_name: str) -> VaultManifest:
        custodian = self._require_custodian()
        if self.root.exists() and any(self.root.iterdir()):
            raise VaultLifecycleError("vault destination is not empty")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        vault_id = str(uuid7())
        database_key_ref = f"{KEY_REFERENCE_PREFIX}{uuid4()}"
        backup_key_ref = f"{KEY_REFERENCE_PREFIX}{uuid4()}"
        custodian.create(database_key_ref)
        try:
            custodian.create(backup_key_ref)
            manifest = VaultManifest(
                vault_id,
                VAULT_FORMAT_VERSION,
                database_key_ref,
                backup_key_ref,
                DATABASE_KEY_VERSION,
            )
            _write_manifest(self.root / "vault.json", manifest)
            self._open_manifest(manifest, must_exist=False)
            self._initialize_rows(
                display_name,
                engine=self.engine,
                manifest=manifest,
            )
            return manifest
        except Exception:
            with suppress(Exception):
                self.lock()
            for reference in (backup_key_ref, database_key_ref):
                with suppress(Exception):
                    custodian.delete(reference)
            for name in (
                "vault.db-journal",
                "vault.db-shm",
                "vault.db-wal",
                "vault.db",
                "vault.json",
            ):
                with suppress(OSError):
                    (self.root / name).unlink()
            raise

    def unlock(self) -> VaultManifest:
        self._require_custodian()
        manifest = VaultManifest.from_path(self.root / "vault.json")
        self._open_manifest(manifest, must_exist=True)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(vaults.c.id).where(vaults.c.id == manifest.vault_id)
            ).scalar_one_or_none()
            if existing is None:
                self.lock()
                raise VaultLifecycleError("vault identity verification failed")
            connection.execute(
                update(vaults)
                .where(vaults.c.id == manifest.vault_id)
                .values(state="UNLOCKED", updated_at_us=time.time_ns() // 1_000)
            )
        return manifest

    def create_with_lease(
        self,
        *,
        display_name: str,
        manifest: VaultManifest,
        transaction: KeyLeaseTransaction,
    ) -> VaultManifest:
        """Create and publish a vault only inside the lease commit boundary."""

        if self.is_unlocked:
            raise VaultLifecycleError("vault is already unlocked")
        root_existed = self.root.exists()
        if root_existed and (self.root.is_symlink() or any(self.root.iterdir())):
            raise VaultLifecycleError("vault destination is not empty")
        self._require_transaction_binding(
            manifest,
            transaction,
            LeaseOperation.DATABASE_CREATE_V1,
        )
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._require_safe_root()

        engine: Engine | None = None
        retained_key: bytearray | None = None
        published = False
        try:
            with transaction as lease:
                retained_key = bytearray(lease.key)
                _write_manifest(self.root / "vault.json", manifest)
                engine = self._prepare_engine(
                    manifest,
                    retained_key,
                    must_exist=False,
                    migrate=True,
                )
                self._initialize_rows(display_name, engine=engine, manifest=manifest)

                def publish() -> None:
                    nonlocal published
                    if engine is None or retained_key is None:
                        raise VaultLifecycleError("prepared vault is unavailable")
                    self._engine = engine
                    self._key = retained_key
                    self._manifest = manifest
                    published = True

                lease.commit(publish)
            return manifest
        except BaseException:
            if published:
                with suppress(Exception):
                    self.lock()
            elif engine is not None:
                engine.dispose()
            if retained_key is not None:
                retained_key[:] = b"\x00" * len(retained_key)
            self._remove_created_vault_files()
            if not root_existed:
                with suppress(OSError):
                    self.root.rmdir()
            raise

    def unlock_with_lease(
        self,
        *,
        transaction: KeyLeaseTransaction,
    ) -> VaultManifest:
        """Stage an existing vault, then publish it between COMMIT and COMMITTED."""

        if self.is_unlocked:
            raise VaultLifecycleError("vault is already unlocked")
        self._require_safe_root()
        manifest = VaultManifest.from_path(self.root / "vault.json")
        self._require_transaction_binding(
            manifest,
            transaction,
            LeaseOperation.DATABASE_UNLOCK_V1,
        )

        engine: Engine | None = None
        retained_key: bytearray | None = None
        published = False
        try:
            with transaction as lease:
                retained_key = bytearray(lease.key)
                engine = self._prepare_engine(
                    manifest,
                    retained_key,
                    must_exist=True,
                    migrate=True,
                )

                def publish() -> None:
                    nonlocal published
                    if engine is None or retained_key is None:
                        raise VaultLifecycleError("prepared vault is unavailable")
                    with engine.begin() as connection:
                        connection.execute(
                            update(vaults)
                            .where(vaults.c.id == manifest.vault_id)
                            .values(
                                state="UNLOCKED",
                                updated_at_us=time.time_ns() // 1_000,
                            )
                        )
                    self._engine = engine
                    self._key = retained_key
                    self._manifest = manifest
                    published = True

                lease.commit(publish)
            return manifest
        except BaseException:
            if published:
                with suppress(Exception):
                    self.lock()
            elif engine is not None:
                engine.dispose()
            if retained_key is not None:
                retained_key[:] = b"\x00" * len(retained_key)
            raise

    def _require_transaction_binding(
        self,
        manifest: VaultManifest,
        transaction: KeyLeaseTransaction,
        operation: LeaseOperation,
    ) -> None:
        binding = transaction.binding
        expected_digest = manifest.digest()
        if (
            str(binding.vault_id) != manifest.vault_id
            or binding.reference != manifest.database_key_ref
            or binding.key_version != manifest.database_key_version
            or binding.operation is not operation
            or not hmac.compare_digest(binding.manifest_digest, expected_digest)
        ):
            raise VaultLifecycleError("vault lease binding does not match the manifest")

    def _require_safe_root(self) -> None:
        try:
            metadata = self.root.lstat()
        except OSError as error:
            raise VaultLifecycleError("vault root is unavailable") from error
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise VaultLifecycleError("vault root is unsafe")

    def _prepare_engine(
        self,
        manifest: VaultManifest,
        key: bytearray,
        *,
        must_exist: bool,
        migrate: bool,
    ) -> Engine:
        factory = SqlcipherEngineFactory(
            self.root / "vault.db",
            key,
            must_exist=must_exist,
        )
        engine = factory.create()
        try:
            factory.probe()
            if migrate:
                upgrade_to_head(engine)
            else:
                require_current_revision(engine)
            with engine.connect() as connection:
                existing = connection.execute(
                    select(vaults.c.id).where(vaults.c.id == manifest.vault_id)
                ).scalar_one_or_none()
            if must_exist and existing is None:
                raise VaultLifecycleError("vault identity verification failed")
            if not must_exist and existing is not None:
                raise VaultLifecycleError("vault identity already exists")
            return engine
        except Exception:
            engine.dispose()
            raise

    def _remove_created_vault_files(self) -> None:
        for name in (
            "vault.db-journal",
            "vault.db-shm",
            "vault.db-wal",
            "vault.db",
            "vault.json",
        ):
            with suppress(OSError):
                (self.root / name).unlink()

    def _open_manifest(self, manifest: VaultManifest, *, must_exist: bool) -> None:
        if self.is_unlocked:
            raise VaultLifecycleError("vault is already unlocked")
        custodian = self._require_custodian()
        with custodian.borrow(manifest.database_key_ref) as borrowed:
            key = bytearray(borrowed)
        factory = SqlcipherEngineFactory(self.root / "vault.db", key, must_exist=must_exist)
        engine = factory.create()
        try:
            factory.probe()
            upgrade_to_head(engine)
        except Exception:
            engine.dispose()
            key[:] = b"\x00" * len(key)
            raise
        self._manifest = manifest
        self._key = key
        self._engine = engine

    def _initialize_rows(
        self,
        display_name: str,
        *,
        engine: Engine,
        manifest: VaultManifest,
    ) -> None:
        now = time.time_ns() // 1_000
        default_settings = VaultSettings()
        with engine.begin() as connection:
            connection.execute(
                insert(vaults).values(
                    id=manifest.vault_id,
                    display_name=display_name,
                    state="UNLOCKED",
                    format_version=VAULT_FORMAT_VERSION,
                    auto_lock_seconds=default_settings.auto_lock_seconds,
                    settings_revision=1,
                    created_at_us=now,
                    updated_at_us=now,
                    revision=1,
                )
            )
            connection.execute(
                insert(vault_crypto).values(
                    vault_id=manifest.vault_id,
                    key_version=manifest.database_key_version,
                    keychain_key_ref=manifest.database_key_ref,
                    wrapped_dek=None,
                    wrap_algorithm="SHELL_KEYCHAIN_DIRECT_V1",
                    sqlcipher_profile="SQLCIPHER4_DEFAULT_V1",
                    evidence_cipher="AES_256_GCM_V1",
                    rotated_at_us=None,
                )
            )
            connection.execute(
                insert(settings),
                [
                    {
                        "id": str(uuid7()),
                        "vault_id": manifest.vault_id,
                        "profile_id": None,
                        "setting_key": key,
                        "value_json": json.dumps(value, separators=(",", ":")),
                        "schema_version": 1,
                        "source": "DEFAULT",
                        "created_at_us": now,
                        "updated_at_us": now,
                        "revision": 1,
                    }
                    for key, value in default_settings.model_dump(mode="json").items()
                ],
            )
            connection.execute(
                insert(event_stream_sessions).values(
                    id=str(uuid7()),
                    vault_id=manifest.vault_id,
                    started_at_us=now,
                    closed_at_us=None,
                    next_sequence=1,
                    minimum_retained_sequence=1,
                    contract_version=1,
                )
            )

    def lock(self) -> None:
        engine, key, manifest = self._engine, self._key, self._manifest
        self._engine = None
        self._manifest = None
        self._key = None
        for subkey in self._borrowed_subkeys:
            subkey[:] = b"\x00" * len(subkey)
        self._borrowed_subkeys.clear()
        try:
            if engine is not None and manifest is not None:
                with engine.begin() as connection:
                    connection.execute(
                        update(vaults)
                        .where(vaults.c.id == manifest.vault_id)
                        .values(state="LOCKED", updated_at_us=time.time_ns() // 1_000)
                    )
        finally:
            if engine is not None:
                engine.dispose()
            if key is not None:
                key[:] = b"\x00" * len(key)
