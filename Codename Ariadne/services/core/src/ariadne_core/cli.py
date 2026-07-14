"""Sidecar process entry point with an authenticated one-shot bootstrap."""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal, TypedDict
from uuid import UUID

import anyio
import structlog
import uvicorn
from fastapi import FastAPI
from platformdirs import PlatformDirs

from ariadne_core.api.app import ApiRuntime, create_app
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.vault import VaultManager
from ariadne_core.bootstrap import BootstrapRejected, read_bootstrap
from ariadne_core.infrastructure.db.engine import CipherUnavailable, inspect_cipher_runtime
from ariadne_core.infrastructure.logging import configure_logging
from ariadne_core.security.key_lease import KEY_LEASE_FD, KeyLeaseClient, KeyLeaseError
from ariadne_core.security.sessions import LaunchSession

DEV_ORIGIN = "http://127.0.0.1:1420"
UDS_ORIGIN = "tauri://localhost"
UDS_HOST = "ariadne.local"
DEV_SESSION_TTL_SECONDS = 15 * 60
READINESS_LIMIT_BYTES = 4096


class TcpReadiness(TypedDict):
    status: Literal["ready"]
    transport: Literal["tcp"]
    host: Literal["127.0.0.1"]
    port: int
    contract_version: Literal[1]


class UdsReadiness(TypedDict):
    status: Literal["ready"]
    transport: Literal["uds"]
    socket_path: str
    contract_version: Literal[1]


Readiness = TcpReadiness | UdsReadiness


class _GracefulServer(uvicorn.Server):
    """Restore signal handlers without re-raising before private-file cleanup."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        handled_signals = (signal.SIGINT, signal.SIGTERM)
        original_handlers = {
            handled_signal: signal.signal(handled_signal, self.handle_exit)
            for handled_signal in handled_signals
        }
        try:
            yield
        finally:
            for handled_signal, original_handler in original_handlers.items():
                signal.signal(handled_signal, original_handler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ariadne-core")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="start the authenticated local sidecar")
    serve.add_argument("--bootstrap-stdin", action="store_true")
    serve.add_argument("--transport", choices=("tcp", "uds"), default="tcp")
    contracts = commands.add_parser("generate-contracts", help="generate local API contracts")
    contracts.add_argument("--check", action="store_true")
    return parser


def _parent_is_alive(parent_pid: int) -> bool:
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _runtime_directory(startup_nonce: UUID) -> Path:
    root = PlatformDirs("codename-ariadne", appauthor=False).user_runtime_path
    instance = root / f"core-{startup_nonce.hex[:12]}"
    instance.mkdir(mode=0o700, parents=True, exist_ok=False)
    instance.chmod(0o700)
    metadata = instance.stat(follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError("private runtime directory unavailable")
    if metadata.st_uid != os.getuid():
        raise RuntimeError("private runtime directory unavailable")
    return instance


def _vault_root() -> Path:
    return (
        PlatformDirs(
            "app.codenameariadne.desktop",
            appauthor=False,
        ).user_data_path
        / "vault"
    )


def _key_lease_fd_is_open() -> bool:
    try:
        os.fstat(KEY_LEASE_FD)
    except OSError:
        return False
    return True


def _tcp_socket() -> tuple[socket.socket, str, TcpReadiness]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    host, port = listener.getsockname()
    if host != "127.0.0.1":
        listener.close()
        raise RuntimeError("loopback binding failed")
    readiness: TcpReadiness = {
        "status": "ready",
        "transport": "tcp",
        "host": "127.0.0.1",
        "port": port,
        "contract_version": 1,
    }
    return listener, f"127.0.0.1:{port}", readiness


def _uds_socket(startup_nonce: UUID) -> tuple[socket.socket, Path, UdsReadiness]:
    runtime_directory = _runtime_directory(startup_nonce)
    socket_path = runtime_directory / "core.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(socket_path))
        socket_path.chmod(0o600)
        metadata = socket_path.stat(follow_symlinks=False)
        if not stat.S_ISSOCK(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("private socket unavailable")
        if metadata.st_uid != os.getuid():
            raise RuntimeError("private socket unavailable")
        listener.listen(128)
        listener.setblocking(False)
    except BaseException:
        listener.close()
        socket_path.unlink(missing_ok=True)
        runtime_directory.rmdir()
        raise

    readiness: UdsReadiness = {
        "status": "ready",
        "transport": "uds",
        "socket_path": str(socket_path),
        "contract_version": 1,
    }
    return listener, runtime_directory, readiness


def _emit_readiness(readiness: Readiness) -> None:
    encoded = json.dumps(readiness, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) + 1 > READINESS_LIMIT_BYTES:
        raise RuntimeError("readiness payload is too large")
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


async def _watch_parent(server: uvicorn.Server, parent_pid: int) -> None:
    while not server.should_exit:
        if not _parent_is_alive(parent_pid):
            structlog.get_logger().warning("sidecar_parent_unavailable")
            server.should_exit = True
            return
        await anyio.sleep(0.25)


async def _announce_when_started(server: uvicorn.Server, readiness: Readiness) -> None:
    while not server.started and not server.should_exit:
        await anyio.sleep(0.01)
    if server.started:
        _emit_readiness(readiness)


async def _serve(
    *,
    app: FastAPI,
    listener: socket.socket,
    readiness: Readiness,
    parent_pid: int,
) -> None:
    config = uvicorn.Config(
        app=app,
        access_log=False,
        date_header=False,
        lifespan="on",
        log_config=None,
        server_header=False,
    )
    server = _GracefulServer(config)

    async with anyio.create_task_group() as tasks:

        async def run_server() -> None:
            try:
                await server.serve(sockets=[listener])
            finally:
                tasks.cancel_scope.cancel()

        tasks.start_soon(run_server)
        tasks.start_soon(_announce_when_started, server, readiness)
        tasks.start_soon(_watch_parent, server, parent_pid)


def _run_sidecar(transport: Literal["tcp", "uds"]) -> int:
    try:
        bootstrap = read_bootstrap(sys.stdin.buffer)
    except BootstrapRejected:
        print("Ariadne core bootstrap rejected.", file=sys.stderr)
        return 2

    configure_logging()
    logger = structlog.get_logger()
    parent_pid = bootstrap.parent_pid
    startup_nonce = bootstrap.startup_nonce
    session = LaunchSession.from_secret(
        bootstrap.session_token,
        ttl_seconds=DEV_SESSION_TTL_SECONDS if transport == "tcp" else None,
    )
    del bootstrap

    key_lease_client: KeyLeaseClient | None = None
    vault_manager: VaultManager | None = None
    cipher_runtime = None
    if transport == "uds" or _key_lease_fd_is_open():
        try:
            key_lease_client = KeyLeaseClient.from_inherited_fd(startup_nonce)
            key_lease_client.handshake()
            cipher_runtime = inspect_cipher_runtime()
            vault_manager = VaultManager(_vault_root())
        except (KeyLeaseError, CipherUnavailable, OSError):
            if key_lease_client is not None:
                key_lease_client.close()
            print("Ariadne core secure channel rejected.", file=sys.stderr)
            return 3

    runtime_directory: Path | None = None
    readiness: Readiness
    if transport == "tcp":
        listener, expected_host, tcp_readiness = _tcp_socket()
        readiness = tcp_readiness
        runtime_transport = RuntimeTransport.DEV_LOOPBACK
        allowed_origins = frozenset({DEV_ORIGIN})
    else:
        listener, runtime_directory, uds_readiness = _uds_socket(startup_nonce)
        readiness = uds_readiness
        expected_host = UDS_HOST
        runtime_transport = RuntimeTransport.UNIX_SOCKET
        allowed_origins = frozenset({UDS_ORIGIN})

    app = create_app(
        ApiRuntime(
            transport=runtime_transport,
            expected_host=expected_host,
            allowed_origins=allowed_origins,
            session=session,
            vault_manager=vault_manager,
            key_lease_client=key_lease_client,
            cipher_runtime=cipher_runtime,
        )
    )
    logger.info("sidecar_starting", transport=transport)
    try:

        async def serve_runtime() -> None:
            await _serve(
                app=app,
                listener=listener,
                readiness=readiness,
                parent_pid=parent_pid,
            )

        anyio.run(serve_runtime)
    finally:
        if vault_manager is not None:
            with contextlib.suppress(Exception):
                vault_manager.lock()
        if key_lease_client is not None:
            key_lease_client.close()
        listener.close()
        if runtime_directory is not None:
            (runtime_directory / "core.sock").unlink(missing_ok=True)
            runtime_directory.rmdir()
    logger.info("sidecar_stopped", transport=transport)
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    if parsed.command == "generate-contracts":
        root = Path(__file__).resolve().parents[4]
        command = [sys.executable, str(root / "packages" / "contracts" / "generate.py")]
        if parsed.check:
            command.append("--check")
        return subprocess.run(command, cwd=root, check=False).returncode
    if parsed.command != "serve" or not parsed.bootstrap_stdin:
        print("Ariadne core bootstrap rejected.", file=sys.stderr)
        return 2
    return _run_sidecar(parsed.transport)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
