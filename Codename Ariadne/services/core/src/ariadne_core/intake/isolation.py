"""Spawn-isolated execution for bounded intake parsing.

File reads, text decoding, and the mandatory restricted-content decision happen
in the parent.  Only a cleared :class:`DecodedSource` crosses the anonymous
process pipe; source material is never placed in process arguments, argv, or
environment variables.  The child has no network API, applies operating-system
resource limits where the platform supports them, and returns a bounded JSON
result containing no exception text.
"""

from __future__ import annotations

import ctypes
import json
import math
import multiprocessing
import os
import re
import resource
import signal
import socket
import sys
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import NoReturn, cast

from ariadne_core.intake.parsing import (
    DecodedSource,
    ParsedSource,
    ParserLimits,
    PreparseDecision,
    PreparseGate,
    SafeParseError,
    SafeParseErrorCode,
    SegmentGate,
    SourceFormat,
    SourceSegment,
    SourceSegmentKind,
    decode_file,
    decode_pasted_text,
    parse_decoded_source,
)

_WIRE_VERSION = 1
_DEFAULT_PARSER_LIMITS = ParserLimits()
_CONTROL_RESPONSE_BYTES = 1024
_REAP_GRACE_SECONDS = 0.5
_MAX_TIMEOUT_SECONDS = 30.0
_MAX_IPC_BYTES = 128 * 1024 * 1024
_MAX_CPU_SECONDS = 30
_MAX_ADDRESS_SPACE_BYTES = 8 * 1024 * 1024 * 1024
_MAX_FILE_SIZE_BYTES = 64 * 1024 * 1024
_MAX_OPEN_FILES = 256
_MAX_CONTEXT_LABEL_BYTES = 32 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_ACTIVE_ELEMENT = re.compile(
    r"<\s*/?\s*(?:script|iframe|object|embed|svg|math|applet)\b", re.IGNORECASE
)
_EVENT_HANDLER = re.compile(r"<[^>]{0,512}\bon[a-z][a-z0-9_-]{0,31}\s*=", re.IGNORECASE)
_ACTIVE_SCHEME = re.compile(r"\b(?:javascript|vbscript)\s*:", re.IGNORECASE)
_ACTIVE_DATA_URI = re.compile(
    r"\bdata\s*:\s*(?:text/html|image/svg\+xml|application/(?:javascript|x-shockwave-flash))",
    re.IGNORECASE,
)
_MEDIA_TYPE_BY_FORMAT: dict[SourceFormat, str] = {
    SourceFormat.TEXT: "text/plain",
    SourceFormat.MARKDOWN: "text/markdown",
    SourceFormat.CSV: "text/csv",
    SourceFormat.JSON: "application/json",
    SourceFormat.VCARD: "text/vcard",
}


class IsolationOperation(StrEnum):
    """Strictly allowed intake operations."""

    PASTE = "PASTE"
    FILE = "FILE"


class IsolationErrorCode(StrEnum):
    """Stable parent-visible failures that never contain source material."""

    INVALID_OPERATION = "INVALID_OPERATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    PAYLOAD_LIMIT = "PAYLOAD_LIMIT"
    RESULT_LIMIT = "RESULT_LIMIT"
    TIMEOUT = "TIMEOUT"
    WORKER_CRASH = "WORKER_CRASH"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


_ISOLATION_ERROR_MESSAGES: dict[IsolationErrorCode, str] = {
    IsolationErrorCode.INVALID_OPERATION: "the isolated intake operation is not allowed",
    IsolationErrorCode.INVALID_REQUEST: "the isolated intake request is invalid",
    IsolationErrorCode.PAYLOAD_LIMIT: "the isolated intake payload exceeds its limit",
    IsolationErrorCode.RESULT_LIMIT: "the isolated intake result exceeds its limit",
    IsolationErrorCode.TIMEOUT: "the isolated intake worker exceeded its time limit",
    IsolationErrorCode.WORKER_CRASH: "the isolated intake worker stopped unexpectedly",
    IsolationErrorCode.PROTOCOL_ERROR: "the isolated intake worker returned an invalid response",
}


class IsolationError(RuntimeError):
    """A redacted, stable failure at the process-isolation boundary."""

    def __init__(self, code: IsolationErrorCode) -> None:
        self.code = code
        super().__init__(_ISOLATION_ERROR_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class IsolationLimits:
    """Inclusive IPC and child-process limits for one parse operation."""

    timeout_seconds: float = 5.0
    max_payload_bytes: int = 64 * 1024 * 1024
    max_result_bytes: int = 64 * 1024 * 1024
    max_cpu_seconds: int = 3
    max_address_space_bytes: int = 2 * 1024 * 1024 * 1024
    max_file_size_bytes: int = 0
    max_open_files: int = 32

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("isolation timeout must be finite and positive")
        positive_integers = (
            self.max_payload_bytes,
            self.max_result_bytes,
            self.max_cpu_seconds,
            self.max_address_space_bytes,
            self.max_open_files,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in positive_integers
        ):
            raise ValueError("isolation limits must be positive integers")
        if (
            self.max_payload_bytes > _MAX_IPC_BYTES
            or self.max_result_bytes > _MAX_IPC_BYTES
            or self.max_cpu_seconds > _MAX_CPU_SECONDS
            or self.max_address_space_bytes > _MAX_ADDRESS_SPACE_BYTES
            or self.max_open_files > _MAX_OPEN_FILES
        ):
            raise ValueError("isolation limits exceed the hard safety ceiling")
        if (
            isinstance(self.max_file_size_bytes, bool)
            or not isinstance(self.max_file_size_bytes, int)
            or self.max_file_size_bytes < 0
            or self.max_file_size_bytes > _MAX_FILE_SIZE_BYTES
        ):
            raise ValueError("isolation file-size limit must be a non-negative integer")


_DEFAULT_ISOLATION_LIMITS = IsolationLimits()


@dataclass(frozen=True, slots=True)
class _ClearedRequest:
    operation: IsolationOperation
    source: DecodedSource = field(repr=False)
    parser_limits: ParserLimits


def parse_pasted_text_isolated(
    text: str,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    parser_limits: ParserLimits = _DEFAULT_PARSER_LIMITS,
    isolation_limits: IsolationLimits = _DEFAULT_ISOLATION_LIMITS,
) -> ParsedSource:
    """Decode and gate pasted text, then parse it in a fresh spawned child."""

    source = decode_pasted_text(text, limits=parser_limits)
    return parse_decoded_source_isolated(
        IsolationOperation.PASTE,
        source,
        preparse_gate=preparse_gate,
        segment_gate=segment_gate,
        parser_limits=parser_limits,
        isolation_limits=isolation_limits,
    )


def parse_file_isolated(
    path: Path,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    declared_media_type: str | None = None,
    parser_limits: ParserLimits = _DEFAULT_PARSER_LIMITS,
    isolation_limits: IsolationLimits = _DEFAULT_ISOLATION_LIMITS,
) -> ParsedSource:
    """Safely decode and gate a selected file, then parse it in a spawned child."""

    source = decode_file(
        path,
        declared_media_type=declared_media_type,
        limits=parser_limits,
    )
    return parse_decoded_source_isolated(
        IsolationOperation.FILE,
        source,
        preparse_gate=preparse_gate,
        segment_gate=segment_gate,
        parser_limits=parser_limits,
        isolation_limits=isolation_limits,
    )


def parse_decoded_source_isolated(
    operation: IsolationOperation,
    source: DecodedSource,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    parser_limits: ParserLimits = _DEFAULT_PARSER_LIMITS,
    isolation_limits: IsolationLimits = _DEFAULT_ISOLATION_LIMITS,
) -> ParsedSource:
    """Gate a parent-supplied decoded source and parse it across the boundary.

    A caller may provide already-redacted decoded text, but the gate remains
    mandatory and executes before any structured parsing or IPC transfer.
    ``operation`` deliberately requires the enum itself rather than accepting a
    string that could silently expand the process protocol.
    """

    if type(operation) is not IsolationOperation:
        raise IsolationError(IsolationErrorCode.INVALID_OPERATION)
    if (
        type(isolation_limits) is not IsolationLimits
        or not isinstance(source, DecodedSource)
        or not isinstance(parser_limits, ParserLimits)
        or not _is_valid_decoded_source(operation, source, parser_limits)
    ):
        raise IsolationError(IsolationErrorCode.INVALID_REQUEST)

    _apply_preparse_gate(source, preparse_gate)
    request = _ClearedRequest(operation, source, parser_limits)
    payload = _encode_request(request)
    if len(payload) > isolation_limits.max_payload_bytes:
        raise IsolationError(IsolationErrorCode.PAYLOAD_LIMIT)
    parsed = _run_spawned_worker(payload, isolation_limits)
    if not _result_matches_source(parsed, source):
        raise IsolationError(IsolationErrorCode.PROTOCOL_ERROR)
    return _apply_segment_gate(parsed, segment_gate)


def _apply_preparse_gate(source: DecodedSource, gate: PreparseGate) -> None:
    try:
        decision = gate(source)
    except Exception:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT) from None
    if decision is not PreparseDecision.CLEAR:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)


def _apply_segment_gate(
    parsed: ParsedSource,
    gate: SegmentGate,
) -> ParsedSource:
    gated_segments: list[SourceSegment] = []
    try:
        for segment in parsed.segments:
            gated = gate(segment)
            if (
                not isinstance(gated, SourceSegment)
                or gated.index != segment.index
                or gated.kind is not segment.kind
                or gated.locator != segment.locator
                or gated.context_label != segment.context_label
            ):
                raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)
            _validate_gated_text(gated.text, segment.text)
            gated_segments.append(gated)
    except SafeParseError as error:
        code = (
            error.code
            if type(error.code) is SafeParseErrorCode
            else SafeParseErrorCode.RESTRICTED_CONTENT
        )
        raise SafeParseError(code) from None
    except Exception:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT) from None
    return ParsedSource(
        source_format=parsed.source_format,
        detected_media_type=parsed.detected_media_type,
        sha256=parsed.sha256,
        byte_count=parsed.byte_count,
        had_utf8_bom=parsed.had_utf8_bom,
        segments=tuple(gated_segments),
    )


def _validate_gated_text(value: str, original: str) -> None:
    try:
        if len(value.encode("utf-8")) > len(original.encode("utf-8")):
            raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)
    except UnicodeEncodeError:
        raise SafeParseError(SafeParseErrorCode.INVALID_ENCODING) from None
    if any(
        unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}
        for character in value
    ) or value.lstrip().startswith("#!"):
        raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)
    if (
        _ACTIVE_ELEMENT.search(value)
        or _EVENT_HANDLER.search(value)
        or _ACTIVE_SCHEME.search(value)
        or _ACTIVE_DATA_URI.search(value)
    ):
        raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)


def _is_valid_decoded_source(
    operation: IsolationOperation,
    source: DecodedSource,
    limits: ParserLimits,
) -> bool:
    try:
        return (
            type(source.source_format) is SourceFormat
            and source.detected_media_type == _MEDIA_TYPE_BY_FORMAT[source.source_format]
            and type(source.sha256) is str
            and _SHA256_PATTERN.fullmatch(source.sha256) is not None
            and type(source.byte_count) is int
            and 1 <= source.byte_count <= limits.max_bytes
            and type(source.had_utf8_bom) is bool
            and type(source.text) is str
            and len(source.text.encode("utf-8")) <= limits.max_bytes
            and (operation is IsolationOperation.FILE or source.source_format is SourceFormat.TEXT)
        )
    except (KeyError, UnicodeEncodeError):
        return False


def _result_matches_source(parsed: ParsedSource, source: DecodedSource) -> bool:
    expected_kind = {
        SourceFormat.TEXT: SourceSegmentKind.TEXT,
        SourceFormat.MARKDOWN: SourceSegmentKind.TEXT,
        SourceFormat.CSV: SourceSegmentKind.RECORD,
        SourceFormat.JSON: SourceSegmentKind.JSON_VALUE,
        SourceFormat.VCARD: SourceSegmentKind.CONTACT,
    }[source.source_format]
    return (
        parsed.source_format is source.source_format
        and parsed.detected_media_type == source.detected_media_type
        and parsed.sha256 == source.sha256
        and parsed.byte_count == source.byte_count
        and parsed.had_utf8_bom is source.had_utf8_bom
        and all(
            segment.index == index and segment.kind is expected_kind
            for index, segment in enumerate(parsed.segments)
        )
    )


def _encode_request(request: _ClearedRequest) -> bytes:
    source = request.source
    value = {
        "version": _WIRE_VERSION,
        "operation": request.operation.value,
        "source": {
            "source_format": source.source_format.value,
            "detected_media_type": source.detected_media_type,
            "sha256": source.sha256,
            "byte_count": source.byte_count,
            "had_utf8_bom": source.had_utf8_bom,
            "text": source.text,
        },
        "parser_limits": asdict(request.parser_limits),
    }
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError):
        raise IsolationError(IsolationErrorCode.INVALID_REQUEST) from None


def _run_spawned_worker(payload: bytes, limits: IsolationLimits) -> ParsedSource:
    context = multiprocessing.get_context("spawn")
    request_receiver, request_sender = context.Pipe(duplex=False)
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_entry,
        args=(request_receiver, sender, limits),
        name="ariadne-intake-parser",
        daemon=False,
    )
    deadline = time.monotonic() + float(limits.timeout_seconds)
    started = False
    response: bytes | None = None
    failure: IsolationErrorCode | None = None
    sender_thread: threading.Thread | None = None
    receiver_thread: threading.Thread | None = None
    response_ready = threading.Event()
    receiver_failed = False

    def send_request() -> None:
        try:
            request_sender.send_bytes(payload)
        except (BrokenPipeError, EOFError, OSError):
            pass
        finally:
            request_sender.close()

    def receive_result() -> None:
        nonlocal receiver_failed, response
        try:
            response = receiver.recv_bytes(max(limits.max_result_bytes, _CONTROL_RESPONSE_BYTES))
        except (EOFError, OSError):
            receiver_failed = True
        finally:
            response_ready.set()

    try:
        try:
            process.start()
            started = True
        except (OSError, RuntimeError):
            failure = IsolationErrorCode.WORKER_CRASH
        finally:
            request_receiver.close()
            sender.close()

        if failure is None:
            sender_thread = threading.Thread(
                target=send_request,
                name="ariadne-intake-request",
                daemon=True,
            )
            sender_thread.start()
            receiver_thread = threading.Thread(
                target=receive_result,
                name="ariadne-intake-response",
                daemon=True,
            )
            receiver_thread.start()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not response_ready.wait(remaining):
                failure = IsolationErrorCode.TIMEOUT
            elif receiver_failed:
                failure = IsolationErrorCode.WORKER_CRASH

        if failure is None:
            remaining = max(0.0, deadline - time.monotonic())
            process.join(remaining)
            if process.is_alive():
                failure = IsolationErrorCode.TIMEOUT
            elif process.exitcode != 0:
                failure = IsolationErrorCode.WORKER_CRASH
    finally:
        if started and process.is_alive():
            _terminate_and_reap(process)
        elif started:
            process.join()
        request_sender.close()
        receiver.close()
        if sender_thread is not None:
            sender_thread.join(_REAP_GRACE_SECONDS)
        if receiver_thread is not None:
            receiver_thread.join(_REAP_GRACE_SECONDS)
        if started and not process.is_alive():
            process.close()

    if failure is not None:
        raise IsolationError(failure) from None
    if response is None:
        raise IsolationError(IsolationErrorCode.PROTOCOL_ERROR)
    return _decode_response(response, limits.max_result_bytes)


def _terminate_and_reap(process: BaseProcess) -> None:
    process.terminate()
    process.join(_REAP_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(_REAP_GRACE_SECONDS)
    if process.is_alive():  # pragma: no cover - an unkillable local process is OS failure
        pid = process.pid
        if pid is not None:
            os.kill(pid, signal.SIGKILL)
        process.join()


def _worker_entry(
    request_receiver: Connection,
    result_sender: Connection,
    limits: IsolationLimits,
) -> None:
    try:
        _apply_child_resource_limits(limits)
        _disable_child_network()
        payload = request_receiver.recv_bytes(limits.max_payload_bytes)
        request_receiver.close()
        request = _decode_request(payload)
        result = parse_decoded_source(
            request.source,
            preparse_gate=_worker_clear_gate,
            segment_gate=_worker_passthrough_segment_gate,
            limits=request.parser_limits,
        )
        response = _encode_success_response(result)
        if len(response) > limits.max_result_bytes:
            response = _encode_isolation_error(IsolationErrorCode.RESULT_LIMIT)
    except SafeParseError as error:
        response = _encode_parse_error(error.code)
    except IsolationError as error:
        response = _encode_isolation_error(error.code)
    except BaseException:
        response = _encode_isolation_error(IsolationErrorCode.WORKER_CRASH)

    try:
        result_sender.send_bytes(response)
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        request_receiver.close()
        result_sender.close()


def _worker_clear_gate(_source: DecodedSource) -> PreparseDecision:
    """Second, fixed gate proving the child cannot bypass the parse contract."""

    return PreparseDecision.CLEAR


def _worker_passthrough_segment_gate(segment: SourceSegment) -> SourceSegment:
    """Defer the caller's non-pickleable contextual gate to the parent."""

    return segment


def _apply_child_resource_limits(limits: IsolationLimits) -> None:
    _set_required_limit("RLIMIT_CPU", limits.max_cpu_seconds)
    _set_required_limit("RLIMIT_FSIZE", limits.max_file_size_bytes)
    _set_required_limit("RLIMIT_NOFILE", limits.max_open_files)
    _set_optional_address_space_limit(limits.max_address_space_bytes)
    if hasattr(resource, "RLIMIT_CORE"):
        _set_resource_limit(cast(int, resource.RLIMIT_CORE), 0)


def _set_required_limit(name: str, value: int) -> None:
    identifier = getattr(resource, name, None)
    if identifier is not None:
        _set_resource_limit(cast(int, identifier), value)


def _set_optional_address_space_limit(value: int) -> None:
    identifier = getattr(resource, "RLIMIT_AS", None)
    if identifier is None:
        return
    try:
        _set_resource_limit(cast(int, identifier), value)
    except (OSError, ValueError):
        # Darwin maps its shared cache into every process at a virtual size far
        # above physical memory, so a useful RLIMIT_AS is rejected as already
        # below the current address space. Other child limits remain enforced.
        if sys.platform != "darwin":
            raise


def _set_resource_limit(identifier: int, requested: int) -> None:
    _soft, hard = resource.getrlimit(identifier)
    bounded = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
    resource.setrlimit(identifier, (bounded, bounded))


def _disable_child_network() -> None:
    if sys.platform == "darwin":
        _apply_darwin_no_network_sandbox()

    def deny_network(*_args: object, **_kwargs: object) -> NoReturn:
        raise PermissionError("network access is disabled in the intake worker")

    def audit_network(event: str, arguments: tuple[object, ...]) -> None:
        if event.startswith("socket."):
            deny_network(event, arguments)

    sys.addaudithook(audit_network)
    for name in (
        "socket",
        "socketpair",
        "fromfd",
        "create_connection",
        "create_server",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
    ):
        if hasattr(socket, name):
            setattr(socket, name, deny_network)


def _apply_darwin_no_network_sandbox() -> None:
    """Irreversibly deny the worker's network syscalls with macOS Seatbelt."""

    try:
        library = ctypes.CDLL("/usr/lib/libsandbox.1.dylib")
        sandbox_init = library.sandbox_init
        sandbox_init.argtypes = (
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_char_p),
        )
        sandbox_init.restype = ctypes.c_int
        error_pointer = ctypes.c_char_p()
        result = sandbox_init(
            b"(version 1)(allow default)(deny network*)",
            0,
            ctypes.byref(error_pointer),
        )
        if error_pointer.value is not None:
            sandbox_free_error = library.sandbox_free_error
            sandbox_free_error.argtypes = (ctypes.c_char_p,)
            sandbox_free_error.restype = None
            sandbox_free_error(error_pointer)
        if result != 0:
            raise RuntimeError
    except (AttributeError, OSError, TypeError, ValueError):
        raise RuntimeError("the intake worker network sandbox could not start") from None


def _decode_request(payload: bytes) -> _ClearedRequest:
    try:
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {
            "version",
            "operation",
            "source",
            "parser_limits",
        }:
            raise ValueError
        if value["version"] != _WIRE_VERSION:
            raise ValueError
        operation = IsolationOperation(_strict_string(value["operation"]))
        raw_source = value["source"]
        raw_limits = value["parser_limits"]
        if not isinstance(raw_source, dict) or set(raw_source) != {
            "source_format",
            "detected_media_type",
            "sha256",
            "byte_count",
            "had_utf8_bom",
            "text",
        }:
            raise ValueError
        expected_limit_fields = set(ParserLimits.__dataclass_fields__)
        if not isinstance(raw_limits, dict) or set(raw_limits) != expected_limit_fields:
            raise ValueError
        parser_limits = ParserLimits(
            **{name: _strict_integer(raw_limits[name]) for name in expected_limit_fields}
        )
        source_format = SourceFormat(_strict_string(raw_source["source_format"]))
        media_type = _strict_string(raw_source["detected_media_type"])
        digest = _strict_string(raw_source["sha256"])
        byte_count = _strict_integer(raw_source["byte_count"])
        had_utf8_bom = raw_source["had_utf8_bom"]
        text = _strict_string(raw_source["text"])
        source = DecodedSource(
            source_format=source_format,
            detected_media_type=media_type,
            sha256=digest,
            byte_count=byte_count,
            had_utf8_bom=had_utf8_bom,
            text=text,
        )
        if not _is_valid_decoded_source(operation, source, parser_limits):
            raise ValueError
        return _ClearedRequest(operation, source, parser_limits)
    except (KeyError, TypeError, UnicodeEncodeError, ValueError):
        raise IsolationError(IsolationErrorCode.PROTOCOL_ERROR) from None


def _strict_string(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return cast(str, value)


def _strict_integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError
    return cast(int, value)


def _encode_success_response(result: ParsedSource) -> bytes:
    value = {
        "version": _WIRE_VERSION,
        "result": {
            "source_format": result.source_format.value,
            "detected_media_type": result.detected_media_type,
            "sha256": result.sha256,
            "byte_count": result.byte_count,
            "had_utf8_bom": result.had_utf8_bom,
            "segments": [_encode_wire_segment(segment) for segment in result.segments],
        },
    }
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"O" + body


def _encode_wire_segment(segment: SourceSegment) -> dict[str, object]:
    context_label = segment.context_label
    if context_label is not None and len(context_label.encode("utf-8")) > _MAX_CONTEXT_LABEL_BYTES:
        raise IsolationError(IsolationErrorCode.RESULT_LIMIT)
    return {
        "index": segment.index,
        "kind": segment.kind.value,
        "locator": segment.locator,
        "text": segment.text,
        "context_label": context_label,
    }


def _encode_parse_error(code: SafeParseErrorCode) -> bytes:
    return b"P" + code.value.encode("ascii")


def _encode_isolation_error(code: IsolationErrorCode) -> bytes:
    return b"I" + code.value.encode("ascii")


def _decode_response(payload: bytes, max_result_bytes: int) -> ParsedSource:
    if not payload or len(payload) > max(max_result_bytes, _CONTROL_RESPONSE_BYTES):
        raise IsolationError(IsolationErrorCode.PROTOCOL_ERROR)
    response_type = payload[:1]
    body = payload[1:]
    try:
        if response_type == b"P":
            raise SafeParseError(SafeParseErrorCode(body.decode("ascii")))
        if response_type == b"I":
            raise IsolationError(IsolationErrorCode(body.decode("ascii")))
        if response_type != b"O":
            raise ValueError
        if len(payload) > max_result_bytes:
            raise IsolationError(IsolationErrorCode.RESULT_LIMIT)
        value = json.loads(body)
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "result"}
            or value["version"] != _WIRE_VERSION
        ):
            raise ValueError
        return _decode_parsed_source(value["result"])
    except (IsolationError, SafeParseError):
        raise
    except (KeyError, TypeError, UnicodeDecodeError, ValueError):
        raise IsolationError(IsolationErrorCode.PROTOCOL_ERROR) from None


def _decode_parsed_source(value: object) -> ParsedSource:
    if not isinstance(value, dict) or set(value) != {
        "source_format",
        "detected_media_type",
        "sha256",
        "byte_count",
        "had_utf8_bom",
        "segments",
    }:
        raise ValueError
    raw_segments = value["segments"]
    if not isinstance(raw_segments, list):
        raise ValueError
    segments: list[SourceSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict) or set(raw_segment) != {
            "index",
            "kind",
            "locator",
            "text",
            "context_label",
        }:
            raise ValueError
        index = _strict_integer(raw_segment["index"])
        locator = _strict_string(raw_segment["locator"])
        if index < 0 or len(locator) > 4096 or not locator.isascii():
            raise ValueError
        context_label = raw_segment["context_label"]
        if context_label is not None and (
            type(context_label) is not str
            or len(context_label.encode("utf-8")) > _MAX_CONTEXT_LABEL_BYTES
        ):
            raise ValueError
        segments.append(
            SourceSegment(
                index=index,
                kind=SourceSegmentKind(_strict_string(raw_segment["kind"])),
                locator=locator,
                text=_strict_string(raw_segment["text"]),
                context_label=cast(str | None, context_label),
            )
        )
    media_type = _strict_string(value["detected_media_type"])
    digest = _strict_string(value["sha256"])
    byte_count = _strict_integer(value["byte_count"])
    had_utf8_bom = value["had_utf8_bom"]
    if (
        len(media_type) > 128
        or not media_type.isascii()
        or _SHA256_PATTERN.fullmatch(digest) is None
        or byte_count < 1
        or type(had_utf8_bom) is not bool
    ):
        raise ValueError
    return ParsedSource(
        source_format=SourceFormat(_strict_string(value["source_format"])),
        detected_media_type=media_type,
        sha256=digest,
        byte_count=byte_count,
        had_utf8_bom=had_utf8_bom,
        segments=tuple(segments),
    )
