#!/usr/bin/env python3
"""Verify the local macOS Tauri packaging spike and its supervised UDS sidecar."""

from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


STARTUP_TIMEOUT_SECONDS = 20
CLEANUP_TIMEOUT_SECONDS = 10
INHERITANCE_PROBE = "ARIADNE_INHERITANCE_PROBE"
FORBIDDEN_ENVIRONMENT = ("ARIADNE_SESSION_TOKEN=", "ARIADNE_BOOTSTRAP=")
FORBIDDEN_DEPENDENCIES = (
    "/opt/homebrew",
    "/usr/local",
    "libcrypto",
    "libssl",
    "libsqlcipher",
    "libsqlite",
)


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    parent_pid: int
    command: str


@dataclass(frozen=True)
class RuntimeObservation:
    descendants: tuple[ProcessRow, ProcessRow]
    socket_path: Path
    startup_ms: int


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, capture_output=True, text=True, check=True)


def _process_rows() -> list[ProcessRow]:
    output = _run("ps", "-axo", "pid=,ppid=,command=").stdout
    rows: list[ProcessRow] = []
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            rows.append(ProcessRow(int(parts[0]), int(parts[1]), parts[2]))
    return rows


def _descendants(parent_pid: int, rows: list[ProcessRow]) -> list[ProcessRow]:
    children: dict[int, list[ProcessRow]] = {}
    for row in rows:
        children.setdefault(row.parent_pid, []).append(row)

    result: list[ProcessRow] = []
    pending = [parent_pid]
    while pending:
        for child in children.get(pending.pop(), []):
            result.append(child)
            pending.append(child.pid)
    return result


def _tcp_listener_count(pid: int) -> int:
    result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return max(0, len(result.stdout.splitlines()) - 1)


def _socket_for_process(pid: int) -> Path | None:
    result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-U"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields and fields[-1].endswith("/core.sock"):
            return Path(fields[-1])
    return None


def _environment(pid: int) -> str:
    return _run("ps", "eww", "-p", str(pid), "-o", "command=").stdout


def _observe_runtime(
    process: subprocess.Popen[str], started: float
) -> RuntimeObservation:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_descendants: list[ProcessRow] = []
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("packaged application exited before sidecar readiness")
        rows = _process_rows()
        last_descendants = _descendants(process.pid, rows)
        if len(last_descendants) == 2:
            direct = next(
                (row for row in last_descendants if row.parent_pid == process.pid), None
            )
            nested = next(
                (
                    row
                    for row in last_descendants
                    if direct is not None and row.parent_pid == direct.pid
                ),
                None,
            )
            socket_path = next(
                (
                    path
                    for row in last_descendants
                    if (path := _socket_for_process(row.pid)) is not None
                ),
                None,
            )
            if direct is not None and nested is not None and socket_path is not None:
                expected_suffix = "ariadne-core serve --bootstrap-stdin --transport uds"
                if not direct.command.endswith(
                    expected_suffix
                ) or not nested.command.endswith(expected_suffix):
                    raise RuntimeError("packaged sidecar arguments are not exact")
                return RuntimeObservation(
                    descendants=(direct, nested),
                    socket_path=socket_path,
                    startup_ms=round((time.monotonic() - started) * 1_000),
                )
        time.sleep(0.1)
    raise RuntimeError(
        f"packaged sidecar readiness timed out with {len(last_descendants)} descendants"
    )


def _verify_runtime_boundary(
    process: subprocess.Popen[str], observation: RuntimeObservation
) -> None:
    processes = (
        ProcessRow(process.pid, os.getpid(), "ariadne-desktop"),
        *observation.descendants,
    )
    if any(_tcp_listener_count(row.pid) != 0 for row in processes):
        raise RuntimeError("packaged application opened a TCP listener")

    for row in observation.descendants:
        environment = _environment(row.pid)
        if f"{INHERITANCE_PROBE}=" in environment:
            raise RuntimeError("packaged sidecar inherited the parent environment")
        if any(marker in environment for marker in FORBIDDEN_ENVIRONMENT):
            raise RuntimeError(
                "packaged sidecar exposed a forbidden credential environment"
            )
        if "Ariadne-Session" in environment or "session_token" in environment:
            raise RuntimeError("packaged sidecar exposed a credential marker")

    socket_metadata = observation.socket_path.stat(follow_symlinks=False)
    parent_metadata = observation.socket_path.parent.stat(follow_symlinks=False)
    if not stat.S_ISSOCK(socket_metadata.st_mode):
        raise RuntimeError("packaged core endpoint is not a Unix socket")
    if stat.S_IMODE(socket_metadata.st_mode) != 0o600:
        raise RuntimeError("packaged core socket mode is not 0600")
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise RuntimeError("packaged core runtime parent is not a directory")
    if stat.S_IMODE(parent_metadata.st_mode) != 0o700:
        raise RuntimeError("packaged core runtime directory mode is not 0700")
    if socket_metadata.st_uid != os.getuid() or parent_metadata.st_uid != os.getuid():
        raise RuntimeError("packaged core runtime is owned by another user")


def _wait_for_cleanup(
    process: subprocess.Popen[str], observation: RuntimeObservation
) -> int:
    try:
        process.wait(timeout=CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "packaged application did not exit within its cleanup bound"
        ) from error

    deadline = time.monotonic() + CLEANUP_TIMEOUT_SECONDS
    descendant_ids = {row.pid for row in observation.descendants}
    while time.monotonic() < deadline:
        live_ids = {row.pid for row in _process_rows()}
        if (
            not (live_ids & descendant_ids)
            and not observation.socket_path.exists()
            and not observation.socket_path.parent.exists()
        ):
            return process.returncode
        time.sleep(0.1)
    raise RuntimeError("packaged sidecar or private socket survived application exit")


def _best_effort_cleanup(
    process: subprocess.Popen[str], observation: RuntimeObservation | None
) -> None:
    if process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    if observation is None:
        return
    for row in observation.descendants:
        try:
            os.kill(row.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    socket_path = observation.socket_path
    if socket_path.is_socket():
        socket_path.unlink()
    try:
        socket_path.parent.rmdir()
    except OSError:
        pass


def _exercise_lifecycle(main: Path, abrupt: bool) -> dict[str, object]:
    environment = os.environ.copy()
    environment[INHERITANCE_PROBE] = "synthetic-probe"
    started = time.monotonic()
    process = subprocess.Popen(
        [str(main)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=True,
    )
    observation: RuntimeObservation | None = None
    try:
        observation = _observe_runtime(process, started)
        _verify_runtime_boundary(process, observation)
        if abrupt:
            process.kill()
        else:
            _run(
                "osascript",
                "-e",
                'tell application id "app.codenameariadne.desktop" to quit',
            )
        return_code = _wait_for_cleanup(process, observation)
        _stdout, stderr = process.communicate(timeout=1)
        if "Ariadne Core unavailable" in stderr:
            raise RuntimeError("packaged application reported the core unavailable")
        if "session_token" in stderr or "Ariadne-Session" in stderr:
            raise RuntimeError("packaged application logged a credential marker")
        return {
            "cleanup": True,
            "exit": "abrupt" if abrupt else "requested",
            "exit_code": return_code,
            "sidecar_processes": len(observation.descendants),
            "startup_ms": observation.startup_ms,
            "tcp_listener_count": 0,
            "uds_directory_mode": "0700",
            "uds_socket_mode": "0600",
        }
    finally:
        _best_effort_cleanup(process, observation)


def _inspect_bundle(bundle: Path) -> tuple[Path, Path]:
    main = bundle / "Contents" / "MacOS" / "ariadne-desktop"
    sidecar = bundle / "Contents" / "MacOS" / "ariadne-core"
    if not main.is_file() or not os.access(main, os.X_OK):
        raise RuntimeError("packaged application executable is unavailable")
    if not sidecar.is_file() or not os.access(sidecar, os.X_OK):
        raise RuntimeError("packaged sidecar executable is unavailable")

    _run("codesign", "--verify", "--deep", "--strict", str(bundle))
    for executable in (main, sidecar):
        if _run("lipo", "-archs", str(executable)).stdout.strip() != "arm64":
            raise RuntimeError("packaged executable is not native arm64")

    sidecar_mode = stat.S_IMODE(sidecar.stat(follow_symlinks=False).st_mode)
    if sidecar.is_symlink() or sidecar_mode & 0o022 != 0 or sidecar_mode & 0o111 == 0:
        raise RuntimeError("packaged sidecar permissions are unsafe")

    dependencies = _run("otool", "-L", str(sidecar)).stdout.casefold()
    if any(
        dependency.casefold() in dependencies for dependency in FORBIDDEN_DEPENDENCIES
    ):
        raise RuntimeError("packaged sidecar has a forbidden dynamic dependency")

    with (bundle / "Contents" / "Info.plist").open("rb") as file:
        metadata = plistlib.load(file)
    if metadata.get("CFBundleIdentifier") != "app.codenameariadne.desktop":
        raise RuntimeError("packaged application identifier is unexpected")
    if metadata.get("LSMinimumSystemVersion") != "14.0":
        raise RuntimeError("packaged application minimum macOS version is unexpected")

    main_signature = _run("codesign", "-d", "--verbose=4", str(main)).stderr
    sidecar_signature = _run("codesign", "-d", "--verbose=4", str(sidecar)).stderr
    local_spike_signature = re.compile(r"flags=0x2\(adhoc\)")
    if not local_spike_signature.search(
        main_signature
    ) or not local_spike_signature.search(sidecar_signature):
        raise RuntimeError(
            "local packaging spike unexpectedly enabled a release signature"
        )
    return main, sidecar


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_packaged_app.py APPLICATION_BUNDLE")
    bundle = Path(sys.argv[1]).resolve(strict=True)
    application, _sidecar = _inspect_bundle(bundle)
    results = [
        _exercise_lifecycle(application, abrupt=False),
        _exercise_lifecycle(application, abrupt=True),
    ]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
