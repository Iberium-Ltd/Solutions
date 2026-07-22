"""SQLAlchemy engine creation over a verified SQLCipher DB-API connection.

Every connection is keyed and feature-checked before SQLAlchemy receives it.
Existing vault opens also pin device/inode across validation and connection so a
path replacement cannot redirect an unlock to a different database.
"""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import Version
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

MINIMUM_SQLITE = Version("3.51.3")


class CipherUnavailable(RuntimeError):
    """Raised instead of ever opening a production vault with plaintext SQLite."""


def _validate_existing_database(path: Path) -> tuple[int, int]:
    try:
        parent = path.parent.lstat()
        metadata = path.lstat()
    except OSError as error:
        raise CipherUnavailable("the encrypted database is unavailable") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.getuid()
    ):
        raise CipherUnavailable("the encrypted database directory is unsafe")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise CipherUnavailable("the encrypted database is unsafe")
    return metadata.st_dev, metadata.st_ino


class _ConnectionCompatibility:
    """Add only the modern DB-API keyword missing from pysqlcipher3 1.2.

    SQLAlchemy registers local SQLite helper functions with the optional
    ``deterministic`` keyword. The selected binding exposes the older three-
    positional-argument API even though its linked SQLCipher runtime is current.
    All other methods and attributes are delegated unchanged.
    """

    __slots__ = ("_connection",)

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def create_function(
        self,
        name: str,
        argument_count: int,
        function: Any,
        *,
        deterministic: bool = False,
    ) -> None:
        del deterministic
        self._connection.create_function(name, argument_count, function)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


@dataclass(frozen=True, slots=True)
class CipherRuntime:
    sqlite_version: str
    cipher_version: str
    foreign_keys: bool
    journal_mode: str
    temp_store: int
    fts5: bool
    json: bool


def _load_driver() -> Any:
    try:
        from pysqlcipher3 import dbapi2 as driver  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - exercised in a dependency-isolation test
        raise CipherUnavailable("the approved SQLCipher DB-API driver is unavailable") from error
    return driver


def _apply_key(connection: Any, key: bytes | bytearray) -> None:
    if len(key) != 32:
        raise CipherUnavailable("vault key must contain exactly 256 bits")
    setter = getattr(connection, "set_raw_key", None)
    if not callable(setter):
        raise CipherUnavailable("the SQLCipher driver lacks mutable-buffer key support")
    key_view = memoryview(key)
    try:
        setter(key_view)
    finally:
        key_view.release()


def verify_connection(connection: Any) -> CipherRuntime:
    try:
        sqlite_version = str(connection.execute("SELECT sqlite_version()").fetchone()[0])
        cipher_row = connection.execute("PRAGMA cipher_version").fetchone()
        cipher_version = "" if cipher_row is None else str(cipher_row[0])
        if not cipher_version:
            raise CipherUnavailable("SQLCipher is not active")
        if Version(sqlite_version) < MINIMUM_SQLITE:
            raise CipherUnavailable(
                f"SQLite {sqlite_version} is below the required {MINIMUM_SQLITE}"
            )

        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA temp_store = MEMORY")
        journal_mode = str(connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0])
        foreign_keys = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        temp_store = int(connection.execute("PRAGMA temp_store").fetchone()[0])
        fts5 = any(
            str(row[0]) == "ENABLE_FTS5"
            for row in connection.execute("PRAGMA compile_options").fetchall()
        )
        json_enabled = bool(connection.execute("SELECT json_valid('{}')").fetchone()[0])
        if not foreign_keys or temp_store != 2 or not fts5 or not json_enabled:
            raise CipherUnavailable("required SQLite safety features are unavailable")
        return CipherRuntime(
            sqlite_version=sqlite_version,
            cipher_version=cipher_version,
            foreign_keys=foreign_keys,
            journal_mode=journal_mode,
            temp_store=temp_store,
            fts5=fts5,
            json=json_enabled,
        )
    except CipherUnavailable:
        raise
    except Exception as error:
        raise CipherUnavailable("encrypted database verification failed") from error


def inspect_cipher_runtime() -> CipherRuntime:
    """Inspect the packaged SQLCipher runtime without creating a filesystem database."""

    driver = _load_driver()
    connection = driver.connect(":memory:", check_same_thread=False)
    probe_key = bytearray(32)
    try:
        _apply_key(connection, probe_key)
        return verify_connection(connection)
    finally:
        probe_key[:] = b"\x00" * len(probe_key)
        connection.close()


@dataclass(slots=True)
class SqlcipherEngineFactory:
    path: Path
    key: bytearray
    must_exist: bool = False

    def _connect(self) -> Any:
        """Open, key, verify, and permission the exact database object."""
        driver = _load_driver()
        expected_identity: tuple[int, int] | None = None
        if self.must_exist:
            expected_identity = _validate_existing_database(self.path)
        else:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
        existed = self.path.exists()
        connection = driver.connect(str(self.path), check_same_thread=False)
        try:
            if expected_identity is not None:
                actual_identity = _validate_existing_database(self.path)
                if actual_identity != expected_identity:
                    raise CipherUnavailable("the encrypted database changed while opening")
            _apply_key(connection, self.key)
            verify_connection(connection)
        except Exception:
            connection.close()
            raise
        if not existed:
            os.chmod(self.path, 0o600)
        return _ConnectionCompatibility(connection)

    def create(self) -> Engine:
        # The pysqlite dialect is used only for SQL rendering. The creator always
        # supplies the verified SQLCipher DB-API connection above.
        driver = _load_driver()
        return create_engine(
            "sqlite+pysqlite://",
            creator=self._connect,
            module=driver,
            poolclass=NullPool,
            future=True,
        )

    def probe(self) -> CipherRuntime:
        connection = self._connect()
        try:
            return verify_connection(connection)
        finally:
            connection.close()

    def export_encrypted_snapshot(self, destination: Path) -> CipherRuntime:
        """Create a transactionally consistent SQLCipher snapshot with the same key."""

        if destination.exists() or destination.is_symlink():
            raise CipherUnavailable("snapshot destination is unsafe")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        connection = self._connect()
        attached = False
        try:
            connection.execute(
                "ATTACH DATABASE ? AS ariadne_snapshot KEY ''",
                (str(destination),),
            )
            attached = True
            key_view = memoryview(self.key)
            try:
                connection.set_raw_key(key_view, "ariadne_snapshot")
            finally:
                key_view.release()
            connection.execute("SELECT sqlcipher_export('ariadne_snapshot')").fetchone()
            connection.execute("DETACH DATABASE ariadne_snapshot")
            attached = False
        except Exception as error:
            with suppress(OSError):
                destination.unlink()
            raise CipherUnavailable("encrypted snapshot creation failed") from error
        finally:
            if attached:
                with suppress(Exception):
                    connection.execute("DETACH DATABASE ariadne_snapshot")
            connection.close()
        os.chmod(destination, 0o600)
        return SqlcipherEngineFactory(destination, self.key).probe()
