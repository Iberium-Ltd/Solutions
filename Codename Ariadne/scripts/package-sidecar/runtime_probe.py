#!/usr/bin/env python3
"""Runtime verification for the locally built SQLCipher DB-API extension.

The probe loads from the candidate package path, verifies encryption and
features, and confirms a wrong key cannot authenticate the test database. It is
not interchangeable with checking that the extension merely imports.
"""

from __future__ import annotations

import json
import platform
import sys
import tempfile
from pathlib import Path


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: runtime_probe.py PACKAGE_DIR SQLCIPHER_VERSION MIN_SQLITE_VERSION"
        )

    package_dir = Path(sys.argv[1]).resolve()
    expected_cipher = sys.argv[2]
    minimum_sqlite = sys.argv[3]

    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"CPython 3.12 required, found {platform.python_version()}")
    if platform.machine() != "arm64":
        raise RuntimeError(f"arm64 Python required, found {platform.machine()}")

    sys.path.insert(0, str(package_dir))
    from pysqlcipher3 import dbapi2  # type: ignore[import-not-found]  # noqa: PLC0415

    module_path = Path(dbapi2.__file__).resolve()
    if package_dir not in module_path.parents:
        raise RuntimeError(f"loaded binding outside package directory: {module_path}")

    with dbapi2.connect(":memory:") as connection:
        if not callable(getattr(connection, "set_raw_key", None)):
            raise RuntimeError("binding lacks mutable-buffer raw key support")
        cipher_version = connection.execute("PRAGMA cipher_version").fetchone()[0]
        sqlite_version = connection.execute("SELECT sqlite_version()").fetchone()[0]
        compile_options = {
            row[0] for row in connection.execute("PRAGMA compile_options").fetchall()
        }
        json_available = connection.execute("SELECT json_valid(?)", ("{}",)).fetchone()[
            0
        ]
        connection.execute("CREATE VIRTUAL TABLE documents USING fts5(body)")
        connection.execute(
            "INSERT INTO documents VALUES (?)", ("synthetic local marker",)
        )
        fts_count = connection.execute(
            "SELECT count(*) FROM documents WHERE documents MATCH ?", ("synthetic",)
        ).fetchone()[0]

    if not cipher_version.startswith(f"{expected_cipher} "):
        raise RuntimeError(
            f"expected SQLCipher {expected_cipher}, found {cipher_version!r}"
        )
    if version_tuple(sqlite_version) < version_tuple(minimum_sqlite):
        raise RuntimeError(
            f"SQLite {sqlite_version} is below required {minimum_sqlite}"
        )

    required_options = {"HAS_CODEC", "ENABLE_FTS5", "TEMP_STORE=2", "THREADSAFE=1"}
    missing_options = required_options - compile_options
    if missing_options:
        raise RuntimeError(f"missing compile options: {sorted(missing_options)}")
    if json_available != 1 or fts_count != 1:
        raise RuntimeError("JSON or FTS5 runtime probe failed")

    canary = b"synthetic encrypted value"
    exact_key = bytearray(range(32))
    wrong_key = bytearray(reversed(range(32)))

    try:
        with tempfile.TemporaryDirectory(
            prefix="ariadne-sqlcipher-probe-"
        ) as directory:
            database_path = Path(directory) / "vault.db"
            with dbapi2.connect(str(database_path)) as connection:
                connection.set_raw_key(memoryview(exact_key))
                connection.execute("CREATE TABLE check_value(value TEXT NOT NULL)")
                connection.execute(
                    "INSERT INTO check_value VALUES (?)", (canary.decode(),)
                )
                connection.commit()

            payload = database_path.read_bytes()
            if payload.startswith(b"SQLite format 3\x00"):
                raise RuntimeError("database has a plaintext SQLite header")
            if canary in payload:
                raise RuntimeError("plaintext canary was found in the database")

            wrong_key_failed = False
            with dbapi2.connect(str(database_path)) as connection:
                try:
                    connection.set_raw_key(memoryview(wrong_key))
                    connection.execute("SELECT value FROM check_value").fetchone()
                except dbapi2.DatabaseError:
                    wrong_key_failed = True
            if not wrong_key_failed:
                raise RuntimeError("wrong-key database read unexpectedly succeeded")

            no_key_failed = False
            with dbapi2.connect(str(database_path)) as connection:
                try:
                    connection.execute("SELECT value FROM check_value").fetchone()
                except dbapi2.DatabaseError:
                    no_key_failed = True
            if not no_key_failed:
                raise RuntimeError(
                    "unkeyed encrypted-database read unexpectedly succeeded"
                )

            with dbapi2.connect(str(database_path)) as connection:
                connection.set_raw_key(memoryview(exact_key))
                roundtrip = connection.execute(
                    "SELECT value FROM check_value"
                ).fetchone()[0]
                integrity_rows = connection.execute(
                    "PRAGMA cipher_integrity_check"
                ).fetchall()

            if roundtrip != canary.decode():
                raise RuntimeError("encrypted database round trip failed")
            if integrity_rows:
                raise RuntimeError(f"cipher integrity check failed: {integrity_rows!r}")
    finally:
        exact_key[:] = b"\x00" * len(exact_key)
        wrong_key[:] = b"\x00" * len(wrong_key)

    result = {
        "binding": "pysqlcipher3",
        "binding_version": dbapi2.version,
        "cipher_version": cipher_version,
        "sqlite_version": sqlite_version,
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
        "json": "passed",
        "fts5": "passed",
        "encrypted_roundtrip": "passed",
        "wrong_key": "rejected",
        "missing_key": "rejected",
        "cipher_integrity": "passed",
        "mutable_buffer_key": "passed",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
