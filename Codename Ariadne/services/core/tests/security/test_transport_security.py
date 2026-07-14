from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

import ariadne_core.cli as cli


class _TestPlatformDirs:
    def __init__(self, _appname: str, *, appauthor: bool) -> None:
        assert appauthor is False

    user_runtime_path: Path


def test_tcp_listener_is_random_ipv4_loopback_only() -> None:
    listener, expected_host, readiness = cli._tcp_socket()
    try:
        host, port = listener.getsockname()
        assert host == "127.0.0.1"
        assert port > 0
        assert expected_host == f"127.0.0.1:{port}"
        assert readiness == {
            "status": "ready",
            "transport": "tcp",
            "host": "127.0.0.1",
            "port": port,
            "contract_version": 1,
        }
    finally:
        listener.close()


def test_uds_runtime_directory_and_socket_are_private(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as temporary_root:
        _TestPlatformDirs.user_runtime_path = Path(temporary_root)
        monkeypatch.setattr(cli, "PlatformDirs", _TestPlatformDirs)
        listener, runtime_directory, readiness = cli._uds_socket(uuid4())
        socket_path = runtime_directory / "core.sock"
        try:
            assert readiness["transport"] == "uds"
            assert readiness["socket_path"] == str(socket_path)
            assert stat.S_IMODE(runtime_directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
            assert runtime_directory.stat().st_uid == os.getuid()
            assert socket_path.stat().st_uid == os.getuid()
        finally:
            listener.close()
            socket_path.unlink()
            runtime_directory.rmdir()
