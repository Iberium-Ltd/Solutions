from __future__ import annotations

import base64
import json
import os
import selectors
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import TextIO, cast
from uuid import UUID, uuid4

import httpx
import pytest

from ariadne_core.security.key_lease import (
    KEY_LEASE_FD,
    LEASE_NONCE_BYTES,
    HelloFrame,
    receive_frame,
)

ROOT = Path(__file__).resolve().parents[4]


def _bootstrap(startup_nonce: UUID, *, multiplier: int) -> tuple[dict[str, object], str]:
    raw_token = bytes((index * multiplier) % 256 for index in range(32))
    token = base64.urlsafe_b64encode(raw_token).rstrip(b"=").decode()
    return (
        {
            "protocol_version": 1,
            "contract_version": 1,
            "session_token": token,
            "parent_pid": os.getpid(),
            "startup_nonce": str(startup_nonce),
        },
        token,
    )


def _uds_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "ariadne_core.cli",
        "serve",
        "--bootstrap-stdin",
        "--transport",
        "uds",
    ]


def _spawn_uds_with_key_lease() -> tuple[subprocess.Popen[str], socket.socket]:
    lease_peer, child_endpoint = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    lease_peer.settimeout(15)
    child_fd = child_endpoint.fileno()
    # The exec launcher installs fd 198 without a pre-exec callback in the threaded
    # pytest parent, then replaces itself so the sidecar sees only its production argv.
    launcher = (
        "import os,sys;"
        "source=int(sys.argv[1]);target=int(sys.argv[2]);"
        "os.set_inheritable(source,True) if source==target "
        "else os.dup2(source,target,inheritable=True);"
        "os.close(source) if source!=target else None;"
        "os.execv(sys.executable,[sys.executable,*sys.argv[3:]])"
    )

    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                launcher,
                str(child_fd),
                str(KEY_LEASE_FD),
                *_uds_command()[1:],
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(child_fd,),
        )
    except BaseException:
        lease_peer.close()
        child_endpoint.close()
        raise
    child_endpoint.close()
    assert child_endpoint.fileno() == -1
    return process, lease_peer


def _readline_with_timeout(stream: TextIO, timeout: float = 10.0) -> str:
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    try:
        if not selector.select(timeout):
            raise TimeoutError("sidecar readiness timed out")
        return stream.readline()
    finally:
        selector.close()


@pytest.mark.timeout(20)
def test_live_loopback_launch_authentication_and_shutdown() -> None:
    bootstrap, token = _bootstrap(uuid4(), multiplier=3)
    process = subprocess.Popen(
        [sys.executable, "-m", "ariadne_core.cli", "serve", "--bootstrap-stdin"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        process.stdin.write(json.dumps(bootstrap, separators=(",", ":")) + "\n")
        process.stdin.flush()
        readiness_line = _readline_with_timeout(cast(TextIO, process.stdout))
        readiness = json.loads(readiness_line)

        assert readiness == {
            "contract_version": 1,
            "host": "127.0.0.1",
            "port": readiness["port"],
            "status": "ready",
            "transport": "tcp",
        }
        assert len(readiness_line.encode()) <= 4096

        headers = {
            "Ariadne-Session": token,
            "Ariadne-Contract-Version": "1",
            "Ariadne-Request-Id": str(uuid4()),
            "Origin": "http://127.0.0.1:1420",
        }
        response = httpx.get(
            f"http://127.0.0.1:{readiness['port']}/v1/session",
            headers=headers,
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["lockState"] == "LOCKED"
    finally:
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)

    assert token not in stderr
    assert str(Path.home()) not in stderr


@pytest.mark.timeout(20)
def test_live_uds_launch_uses_private_socket_and_cleans_up() -> None:
    startup_nonce = uuid4()
    bootstrap, token = _bootstrap(startup_nonce, multiplier=5)
    process, lease_peer = _spawn_uds_with_key_lease()
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    socket_path: Path | None = None
    try:
        process.stdin.write(json.dumps(bootstrap, separators=(",", ":")) + "\n")
        process.stdin.flush()

        hello = receive_frame(lease_peer)
        assert isinstance(hello, HelloFrame)
        assert hello.startup_nonce == startup_nonce
        assert len(hello.lease_nonce) == LEASE_NONCE_BYTES
        hello.lease_nonce[:] = b"\x00" * len(hello.lease_nonce)

        readiness_line = _readline_with_timeout(cast(TextIO, process.stdout))
        readiness = json.loads(readiness_line)
        socket_path = Path(readiness["socket_path"])

        assert readiness["status"] == "ready"
        assert readiness["transport"] == "uds"
        assert readiness["contract_version"] == 1
        assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600

        transport = httpx.HTTPTransport(uds=str(socket_path))
        headers = {
            "Ariadne-Session": token,
            "Ariadne-Contract-Version": "1",
            "Ariadne-Request-Id": str(uuid4()),
            "Origin": "tauri://localhost",
        }
        with httpx.Client(transport=transport, base_url="http://ariadne.local") as client:
            response = client.get("/v1/system/capabilities", headers=headers)
        assert response.status_code == 200
        assert response.json()["transport"] == "UNIX_SOCKET"
    finally:
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)
        try:
            assert lease_peer.recv(1) == b""
        finally:
            lease_peer.close()

    assert token not in stderr
    if socket_path is not None:
        assert not socket_path.exists()
        assert not socket_path.parent.exists()


@pytest.mark.timeout(20)
def test_live_uds_launch_without_fd198_fails_generically_before_readiness() -> None:
    startup_nonce = uuid4()
    bootstrap, token = _bootstrap(startup_nonce, multiplier=7)
    process = subprocess.Popen(
        _uds_command(),
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(
        json.dumps(bootstrap, separators=(",", ":")) + "\n",
        timeout=15,
    )

    assert process.returncode == 3
    assert stdout == ""
    assert "Ariadne core secure channel rejected." in stderr
    assert "KEY_LEASE" not in stderr
    assert token not in stderr
    assert str(Path.home()) not in stderr
