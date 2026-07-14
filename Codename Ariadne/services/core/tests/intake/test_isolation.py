from __future__ import annotations

import ctypes
import hashlib
import multiprocessing
import os
import socket
import sys
import threading
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

import pytest

from ariadne_core.intake import isolation
from ariadne_core.intake.isolation import (
    IsolationError,
    IsolationErrorCode,
    IsolationLimits,
    IsolationOperation,
    parse_decoded_source_isolated,
    parse_file_isolated,
    parse_pasted_text_isolated,
)
from ariadne_core.intake.parsing import (
    DecodedSource,
    PreparseDecision,
    SafeParseError,
    SafeParseErrorCode,
    SourceFormat,
    SourceSegment,
)


def clear_source(_source: DecodedSource) -> PreparseDecision:
    return PreparseDecision.CLEAR


def keep_segment(segment: SourceSegment) -> SourceSegment:
    return segment


def _hanging_worker(
    _request_receiver: Connection,
    _result_sender: Connection,
    _limits: object,
) -> None:
    time.sleep(60)


def _crashing_worker(
    _request_receiver: Connection,
    _result_sender: Connection,
    _limits: object,
) -> None:
    os._exit(23)


def _network_probe(sender: Connection) -> None:
    isolation._disable_child_network()
    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(None, use_errno=True)
            descriptor = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            if descriptor < 0:
                sender.send_bytes(b"blocked")
            else:

                class SockaddrIn(ctypes.Structure):
                    _fields_ = [
                        ("sin_len", ctypes.c_uint8),
                        ("sin_family", ctypes.c_uint8),
                        ("sin_port", ctypes.c_uint16),
                        ("sin_addr", ctypes.c_uint32),
                        ("sin_zero", ctypes.c_uint8 * 8),
                    ]

                address = SockaddrIn(
                    sin_len=ctypes.sizeof(SockaddrIn),
                    sin_family=socket.AF_INET,
                    sin_port=socket.htons(9),
                    sin_addr=ctypes.c_uint32.from_buffer_copy(socket.inet_aton("127.0.0.1")).value,
                )
                connected = libc.connect(
                    descriptor,
                    ctypes.byref(address),
                    ctypes.sizeof(address),
                )
                blocked = connected < 0 and ctypes.get_errno() in {1, 13}
                os.close(descriptor)
                sender.send_bytes(b"blocked" if blocked else b"open")
        else:
            try:
                socket.socket()
            except PermissionError:
                sender.send_bytes(b"blocked")
            else:  # pragma: no cover - proves the fail-closed branch on regression
                sender.send_bytes(b"open")
    finally:
        sender.close()


def _child_pids() -> set[int | None]:
    return {child.pid for child in multiprocessing.active_children()}


def _intake_thread_names() -> set[str]:
    return {thread.name for thread in threading.enumerate() if thread.name.startswith("ariadne-")}


def test_spawned_paste_and_file_parsing_succeed_with_synthetic_data(
    tmp_path: Path,
) -> None:
    pasted = parse_pasted_text_isolated(
        "Synthetic alias\nSecond clue",
        preparse_gate=clear_source,
        segment_gate=keep_segment,
    )
    assert pasted.source_format is SourceFormat.TEXT
    assert pasted.text_segments == ("Synthetic alias", "Second clue")

    path = tmp_path / "synthetic.json"
    path.write_text('{"alias":"synthetic_user"}', encoding="utf-8")
    parsed_file = parse_file_isolated(
        path,
        declared_media_type="application/json",
        preparse_gate=clear_source,
        segment_gate=keep_segment,
    )
    assert parsed_file.source_format is SourceFormat.JSON
    assert parsed_file.text_segments == ("synthetic_user",)


def test_parent_segment_gate_redacts_before_result_is_returned() -> None:
    canary = "SYNTHETIC-STRUCTURED-CANARY-5107"

    def redact(segment: SourceSegment) -> SourceSegment:
        return SourceSegment(
            index=segment.index,
            kind=segment.kind,
            locator=segment.locator,
            text="[REDACTED]",
            context_label=segment.context_label,
        )

    parsed = parse_pasted_text_isolated(
        canary,
        preparse_gate=clear_source,
        segment_gate=redact,
    )

    assert parsed.text_segments == ("[REDACTED]",)
    assert canary not in repr(parsed)


def test_context_label_crosses_ipc_privately_for_parent_gate(tmp_path: Path) -> None:
    canary = "SYNTHETIC-CONTEXT-CANARY-2076"
    path = tmp_path / "synthetic.json"
    path.write_text(f'{{"{canary}":"safe value"}}', encoding="utf-8")
    observed_labels: list[str | None] = []

    def inspect_context(segment: SourceSegment) -> SourceSegment:
        observed_labels.append(segment.context_label)
        return segment

    parsed = parse_file_isolated(
        path,
        preparse_gate=clear_source,
        segment_gate=inspect_context,
    )

    assert observed_labels == [canary]
    assert parsed.text_segments == ("safe value",)
    assert canary not in repr(parsed)


def test_operation_is_strict_and_restricted_gate_runs_before_spawn() -> None:
    source_text = "synthetic marker"
    source = DecodedSource(
        source_format=SourceFormat.TEXT,
        detected_media_type="text/plain",
        sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        byte_count=len(source_text),
        had_utf8_bom=False,
        text=source_text,
    )
    before = _child_pids()

    with pytest.raises(IsolationError) as operation_error:
        parse_decoded_source_isolated(
            cast(IsolationOperation, "PASTE"),
            source,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
        )
    assert operation_error.value.code is IsolationErrorCode.INVALID_OPERATION

    with pytest.raises(SafeParseError) as gate_error:
        parse_decoded_source_isolated(
            IsolationOperation.PASTE,
            source,
            preparse_gate=lambda _source: PreparseDecision.QUARANTINE,
            segment_gate=keep_segment,
        )
    assert gate_error.value.code is SafeParseErrorCode.RESTRICTED_CONTENT
    assert _child_pids() == before


def test_ipc_payload_and_result_limits_fail_closed_without_disclosure() -> None:
    canary = "SYNTHETIC-RAW-CANARY-9481"
    before = _child_pids()
    with pytest.raises(IsolationError) as payload_error:
        parse_pasted_text_isolated(
            canary,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
            isolation_limits=IsolationLimits(max_payload_bytes=1),
        )
    assert payload_error.value.code is IsolationErrorCode.PAYLOAD_LIMIT
    assert canary not in str(payload_error.value)
    assert canary not in repr(payload_error.value)
    assert _child_pids() == before

    with pytest.raises(IsolationError) as result_error:
        parse_pasted_text_isolated(
            canary,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
            isolation_limits=IsolationLimits(max_result_bytes=1),
        )
    assert result_error.value.code is IsolationErrorCode.RESULT_LIMIT
    assert canary not in str(result_error.value)
    assert canary not in repr(result_error.value)


def test_timeout_terminates_and_reaps_spawned_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "SYNTHETIC-TIMEOUT-CANARY-1830"
    before = _child_pids()
    threads_before = _intake_thread_names()
    monkeypatch.setattr(isolation, "_worker_entry", _hanging_worker)

    started = time.monotonic()
    with pytest.raises(IsolationError) as captured:
        parse_pasted_text_isolated(
            canary,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
            isolation_limits=IsolationLimits(timeout_seconds=0.15),
        )
    elapsed = time.monotonic() - started

    assert captured.value.code is IsolationErrorCode.TIMEOUT
    assert canary not in str(captured.value)
    assert canary not in repr(captured.value)
    assert elapsed < 2
    assert _child_pids() == before
    assert _intake_thread_names() == threads_before


def test_crash_is_redacted_and_reaps_spawned_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "SYNTHETIC-CRASH-CANARY-7624"
    before = _child_pids()
    threads_before = _intake_thread_names()
    monkeypatch.setattr(isolation, "_worker_entry", _crashing_worker)

    with pytest.raises(IsolationError) as captured:
        parse_pasted_text_isolated(
            canary,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
        )

    assert captured.value.code is IsolationErrorCode.WORKER_CRASH
    assert canary not in str(captured.value)
    assert canary not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert _child_pids() == before
    assert _intake_thread_names() == threads_before


def test_child_network_api_is_disabled_under_spawn() -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_network_probe, args=(sender,))
    process.start()
    sender.close()
    try:
        assert receiver.poll(2)
        assert receiver.recv_bytes(16) == b"blocked"
        process.join(2)
        assert process.exitcode == 0
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
            process.join()
        process.close()


def test_worker_parse_error_and_decoded_source_repr_do_not_expose_raw_canary() -> None:
    canary = "SYNTHETIC-MALFORMED-CANARY-3305"
    malformed = f'{{"alias":"{canary}"'
    source = DecodedSource(
        source_format=SourceFormat.JSON,
        detected_media_type="application/json",
        sha256=hashlib.sha256(malformed.encode()).hexdigest(),
        byte_count=len(malformed.encode()),
        had_utf8_bom=False,
        text=malformed,
    )

    with pytest.raises(SafeParseError) as captured:
        parse_decoded_source_isolated(
            IsolationOperation.FILE,
            source,
            preparse_gate=clear_source,
            segment_gate=keep_segment,
        )

    assert captured.value.code is SafeParseErrorCode.MALFORMED
    assert canary not in repr(source)
    assert canary not in str(captured.value)
    assert canary not in repr(captured.value)

    def unsafe_gate(_segment: SourceSegment) -> SourceSegment:
        error = SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)
        error.args = (canary,)
        raise error

    with pytest.raises(SafeParseError) as gate_error:
        parse_pasted_text_isolated(
            canary,
            preparse_gate=clear_source,
            segment_gate=unsafe_gate,
        )
    assert gate_error.value.code is SafeParseErrorCode.RESTRICTED_CONTENT
    assert canary not in str(gate_error.value)
    assert canary not in repr(gate_error.value)
    assert gate_error.value.__cause__ is None
