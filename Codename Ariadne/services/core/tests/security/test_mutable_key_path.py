from __future__ import annotations

import inspect

import pytest

from ariadne_core.infrastructure.db import engine as engine_module
from ariadne_core.infrastructure.db.engine import CipherUnavailable


class _BufferKeyConnection:
    def __init__(self) -> None:
        self.seen_object: object | None = None
        self.seen_bytes: bytes | None = None

    def set_raw_key(self, key: memoryview) -> None:
        self.seen_object = key.obj
        self.seen_bytes = key.tobytes()


def test_apply_key_passes_the_original_mutable_buffer_to_the_driver() -> None:
    key = bytearray(range(32))
    connection = _BufferKeyConnection()

    engine_module._apply_key(connection, key)

    assert connection.seen_object is key
    assert connection.seen_bytes == bytes(range(32))


def test_apply_key_fails_closed_without_buffer_protocol_driver_support() -> None:
    with pytest.raises(CipherUnavailable, match="mutable-buffer key support"):
        engine_module._apply_key(object(), bytearray(32))


def test_engine_source_never_formats_key_material_as_hex_or_sql() -> None:
    source = inspect.getsource(engine_module)

    assert ".hex()" not in source
    assert "PRAGMA key" not in source
    assert "x'{" not in source
