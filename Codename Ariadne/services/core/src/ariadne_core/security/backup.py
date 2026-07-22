"""Authenticated, device-bound backup envelope for the Phase 2 foundation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ARIADNEBK1"
FORMAT_VERSION = 1
MAX_FOUNDATION_BACKUP_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 4096
GCM_TAG_BYTES = 16
MAX_ENVELOPE_BYTES = len(MAGIC) + 4 + MAX_HEADER_BYTES + MAX_FOUNDATION_BACKUP_BYTES + GCM_TAG_BYTES


class BackupError(RuntimeError):
    """Stable error that deliberately excludes paths and cryptographic details."""


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    vault_id: str
    created_at_us: int
    key_version: int
    source_sha256: str
    plaintext_bytes: int


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    """Publish a complete private file by same-directory atomic replacement."""
    parent = path.parent.resolve(strict=True)
    if path.exists() and path.is_symlink():
        raise BackupError("backup destination is unsafe")
    temporary = parent / f".{path.name}.{secrets_token()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def secrets_token() -> str:
    import secrets

    return secrets.token_hex(8)


def _read_bounded_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    """Read one stable regular file only after bounding it with ``fstat``."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 1:
                raise BackupError(f"{label} is invalid")
            if metadata.st_size > maximum:
                raise BackupError(f"{label} exceeds the foundation size limit")
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = -1
                content = stream.read(maximum + 1)
            if len(content) != metadata.st_size or len(content) > maximum:
                raise BackupError(f"{label} changed while it was read")
            return content
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except BackupError:
        raise
    except OSError as error:
        raise BackupError(f"{label} could not be read") from error


def create_backup(
    *,
    source_database: Path,
    destination: Path,
    backup_key: bytes | bytearray,
    vault_id: str,
    key_version: int,
    nonce: bytes | None = None,
    clock_us: Callable[[], int] = lambda: time.time_ns() // 1_000,
) -> BackupMetadata:
    """Authenticate canonical metadata and one bounded encrypted snapshot."""
    if len(backup_key) != 32:
        raise BackupError("backup key is unavailable")
    try:
        if str(UUID(vault_id)) != vault_id:
            raise ValueError
    except ValueError as error:
        raise BackupError("vault identity is invalid") from error
    plaintext = _read_bounded_regular_file(
        source_database,
        maximum=MAX_FOUNDATION_BACKUP_BYTES,
        label="vault backup source",
    )

    source_sha256 = hashlib.sha256(plaintext).hexdigest()
    nonce = os.urandom(12) if nonce is None else nonce
    if len(nonce) != 12:
        raise BackupError("backup nonce is invalid")
    header = _canonical_json(
        {
            "createdAtUs": clock_us(),
            "formatVersion": FORMAT_VERSION,
            "keyVersion": key_version,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("="),
            "plaintextBytes": len(plaintext),
            "sourceSha256": source_sha256,
            "vaultId": vault_id,
        }
    )
    if len(header) > MAX_HEADER_BYTES:
        raise BackupError("backup metadata is too large")
    associated_data = MAGIC + struct.pack(">I", len(header)) + header
    ciphertext = AESGCM(bytes(backup_key)).encrypt(nonce, plaintext, associated_data)
    _atomic_write(destination, associated_data + ciphertext)
    decoded = json.loads(header)
    return BackupMetadata(
        vault_id=vault_id,
        created_at_us=int(decoded["createdAtUs"]),
        key_version=key_version,
        source_sha256=source_sha256,
        plaintext_bytes=len(plaintext),
    )


def decrypt_backup(bundle: Path, backup_key: bytes | bytearray) -> tuple[BackupMetadata, bytes]:
    if len(backup_key) != 32:
        raise BackupError("backup key is unavailable")
    try:
        content = _read_bounded_regular_file(
            bundle,
            maximum=MAX_ENVELOPE_BYTES,
            label="backup envelope",
        )
        if len(content) < len(MAGIC) + 4 + GCM_TAG_BYTES or not content.startswith(MAGIC):
            raise BackupError("backup format is invalid")
        header_length = struct.unpack(">I", content[len(MAGIC) : len(MAGIC) + 4])[0]
        if header_length < 2 or header_length > MAX_HEADER_BYTES:
            raise BackupError("backup format is invalid")
        header_end = len(MAGIC) + 4 + header_length
        if header_end + GCM_TAG_BYTES > len(content):
            raise BackupError("backup format is invalid")
        header_bytes = content[len(MAGIC) + 4 : header_end]
        header = json.loads(header_bytes)
        if not isinstance(header, dict) or set(header) != {
            "createdAtUs",
            "formatVersion",
            "keyVersion",
            "nonce",
            "plaintextBytes",
            "sourceSha256",
            "vaultId",
        }:
            raise BackupError("backup format is invalid")
        if header_bytes != _canonical_json(header):
            raise BackupError("backup format is invalid")
        if type(header["formatVersion"]) is not int or header["formatVersion"] != FORMAT_VERSION:
            raise BackupError("backup version is unsupported")
        if (
            type(header["createdAtUs"]) is not int
            or header["createdAtUs"] < 1
            or type(header["keyVersion"]) is not int
            or not 1 <= header["keyVersion"] <= 2_147_483_647
            or type(header["plaintextBytes"]) is not int
            or not 1 <= header["plaintextBytes"] <= MAX_FOUNDATION_BACKUP_BYTES
            or not isinstance(header["nonce"], str)
            or not isinstance(header["sourceSha256"], str)
        ):
            raise BackupError("backup format is invalid")
        nonce_text = header["nonce"]
        nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
        if (
            len(nonce) != 12
            or base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("=") != nonce_text
        ):
            raise BackupError("backup format is invalid")
        declared_length = header["plaintextBytes"]
        if len(content) - header_end != declared_length + GCM_TAG_BYTES:
            raise BackupError("backup format is invalid")
        source_digest = header["sourceSha256"]
        if len(source_digest) != 64 or any(
            character not in "0123456789abcdef" for character in source_digest
        ):
            raise BackupError("backup format is invalid")
        associated_data = content[:header_end]
        plaintext = AESGCM(bytes(backup_key)).decrypt(nonce, content[header_end:], associated_data)
        if len(plaintext) != declared_length:
            raise BackupError("backup authentication failed")
        digest = hashlib.sha256(plaintext).hexdigest()
        if digest != source_digest:
            raise BackupError("backup authentication failed")
        if not isinstance(header["vaultId"], str):
            raise BackupError("backup identity is invalid")
        vault_id = header["vaultId"]
        if str(UUID(vault_id)) != vault_id:
            raise BackupError("backup identity is invalid")
        metadata = BackupMetadata(
            vault_id=vault_id,
            created_at_us=header["createdAtUs"],
            key_version=header["keyVersion"],
            source_sha256=digest,
            plaintext_bytes=len(plaintext),
        )
        return metadata, plaintext
    except BackupError:
        raise
    except (InvalidTag, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        raise BackupError("backup authentication failed") from error


def stage_restore(
    *,
    bundle: Path,
    destination_database: Path,
    backup_key: bytes | bytearray,
    expected_vault_id: str,
) -> Path:
    """Authenticate into a same-filesystem staging file without replacing a vault."""
    metadata, plaintext = decrypt_backup(bundle, backup_key)
    if metadata.vault_id != expected_vault_id:
        raise BackupError("backup belongs to a different vault")
    parent = destination_database.parent.resolve(strict=True)
    staging = parent / f".{destination_database.name}.{secrets_token()}.restore"
    _atomic_write(staging, plaintext)
    return staging


def commit_staged_restore(
    *,
    staging: Path,
    destination_database: Path,
    verifier: Callable[[Path], None],
) -> None:
    """Verify and replace one locked database on the same filesystem.

    The previous database is retained under an opaque rollback name until the
    replacement has been verified in place. Recovery of a process death between
    the two renames is handled by ``recover_interrupted_restore``.
    """

    try:
        parent = destination_database.parent.resolve(strict=True)
        if staging.parent.resolve(strict=True) != parent:
            raise BackupError("restore staging must share the vault filesystem")
        if not destination_database.is_file() or destination_database.is_symlink():
            raise BackupError("restore destination is unsafe")
        if not staging.is_file() or staging.is_symlink():
            raise BackupError("restore staging is unsafe")
        verifier(staging)
        rollback = parent / f".{destination_database.name}.restore-rollback"
        if rollback.exists():
            raise BackupError("an interrupted restore requires recovery")
        os.replace(destination_database, rollback)
        try:
            os.replace(staging, destination_database)
            os.chmod(destination_database, 0o600)
            verifier(destination_database)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            destination_database.unlink(missing_ok=True)
            os.replace(rollback, destination_database)
            raise
        rollback.unlink()
    except BackupError:
        raise
    except Exception as error:
        raise BackupError("restore replacement failed") from error


def recover_interrupted_restore(destination_database: Path) -> bool:
    """Restore the retained original if a crash left the destination absent."""

    parent = destination_database.parent.resolve(strict=True)
    rollback = parent / f".{destination_database.name}.restore-rollback"
    if not rollback.exists():
        return False
    if rollback.is_symlink():
        raise BackupError("restore recovery file is unsafe")
    if destination_database.exists():
        raise BackupError("restore recovery state is ambiguous")
    os.replace(rollback, destination_database)
    os.chmod(destination_database, 0o600)
    return True
