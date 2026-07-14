"""Fail-closed parsing for the Phase 3 local intake allowlist.

Decoding and structured parsing are deliberately separate.  A restricted-value
scanner must clear decoded text before CSV, JSON, or vCard structure is parsed.
Neither stage logs source bytes, text, filenames, paths, or rejected values.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

_UTF8_BOM = b"\xef\xbb\xbf"
_READ_CHUNK_BYTES = 64 * 1024
_MAX_JSON_NUMBER_OUTPUT_BYTES = 4096


class SourceFormat(StrEnum):
    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    CSV = "CSV"
    JSON = "JSON"
    VCARD = "VCARD"


class SourceSegmentKind(StrEnum):
    TEXT = "TEXT"
    RECORD = "RECORD"
    JSON_VALUE = "JSON_VALUE"
    CONTACT = "CONTACT"


class PreparseDecision(StrEnum):
    """A gate result supplied by the restricted-value scanner."""

    CLEAR = "CLEAR"
    QUARANTINE = "QUARANTINE"


class SafeParseErrorCode(StrEnum):
    UNSAFE_SOURCE = "UNSAFE_SOURCE"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    MEDIA_TYPE_MISMATCH = "MEDIA_TYPE_MISMATCH"
    CONTENT_MISMATCH = "CONTENT_MISMATCH"
    UNSUPPORTED_CONTAINER = "UNSUPPORTED_CONTAINER"
    EMPTY_SOURCE = "EMPTY_SOURCE"
    SIZE_LIMIT = "SIZE_LIMIT"
    ROW_LIMIT = "ROW_LIMIT"
    DEPTH_LIMIT = "DEPTH_LIMIT"
    MEMBER_LIMIT = "MEMBER_LIMIT"
    CELL_LIMIT = "CELL_LIMIT"
    INVALID_ENCODING = "INVALID_ENCODING"
    ACTIVE_CONTENT = "ACTIVE_CONTENT"
    RESTRICTED_CONTENT = "RESTRICTED_CONTENT"
    MALFORMED = "MALFORMED"


_ERROR_MESSAGES: dict[SafeParseErrorCode, str] = {
    SafeParseErrorCode.UNSAFE_SOURCE: "the selected source is not a safe regular file",
    SafeParseErrorCode.UNSUPPORTED_TYPE: "the selected source type is not supported",
    SafeParseErrorCode.MEDIA_TYPE_MISMATCH: "the declared media type does not match the source",
    SafeParseErrorCode.CONTENT_MISMATCH: "the source content does not match its type",
    SafeParseErrorCode.UNSUPPORTED_CONTAINER: (
        "container and binary document formats are not accepted"
    ),
    SafeParseErrorCode.EMPTY_SOURCE: "the source contains no parseable text",
    SafeParseErrorCode.SIZE_LIMIT: "the source exceeds the byte limit",
    SafeParseErrorCode.ROW_LIMIT: "the source exceeds the row limit",
    SafeParseErrorCode.DEPTH_LIMIT: "the source exceeds the nesting-depth limit",
    SafeParseErrorCode.MEMBER_LIMIT: "the source exceeds the member limit",
    SafeParseErrorCode.CELL_LIMIT: "the source exceeds a cell limit",
    SafeParseErrorCode.INVALID_ENCODING: "the source is not valid UTF-8 text",
    SafeParseErrorCode.ACTIVE_CONTENT: "active content is not accepted",
    SafeParseErrorCode.RESTRICTED_CONTENT: "restricted content requires quarantine",
    SafeParseErrorCode.MALFORMED: "the source structure is malformed",
}


class SafeParseError(ValueError):
    """A stable error that never includes input data or filesystem paths."""

    def __init__(self, code: SafeParseErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class ParserLimits:
    """Inclusive intake limits; exceeding any value fails closed."""

    max_bytes: int = 25 * 1024 * 1024
    max_rows: int = 100_000
    max_depth: int = 64
    max_members: int = 100_000
    max_cells: int = 1_000_000
    max_cell_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_bytes,
            self.max_rows,
            self.max_depth,
            self.max_members,
            self.max_cells,
            self.max_cell_bytes,
        )
        if any(value < 1 for value in values):
            raise ValueError("parser limits must be positive")


_DEFAULT_LIMITS = ParserLimits()


@dataclass(frozen=True, slots=True)
class DecodedSource:
    """UTF-8 source awaiting the mandatory restricted-value gate.

    ``text`` is excluded from repr so an accidental diagnostic does not disclose
    source material.  Callers must not preview, persist, or log it before gating.
    """

    source_format: SourceFormat
    detected_media_type: str
    sha256: str
    byte_count: int
    had_utf8_bom: bool
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SourceSegment:
    """One normalized, inert parse unit with a non-executable locator."""

    index: int
    kind: SourceSegmentKind
    locator: str = field(repr=False)
    text: str = field(repr=False)
    context_label: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ParsedSource:
    source_format: SourceFormat
    detected_media_type: str
    sha256: str
    byte_count: int
    had_utf8_bom: bool
    segments: tuple[SourceSegment, ...]

    @property
    def text_segments(self) -> tuple[str, ...]:
        """Return compiler-ready normalized text in stable source order."""

        return tuple(segment.text for segment in self.segments)


PreparseGate = Callable[[DecodedSource], PreparseDecision]
SegmentGate = Callable[[SourceSegment], SourceSegment]


@dataclass(frozen=True, slots=True)
class _FormatPolicy:
    source_format: SourceFormat
    media_type: str
    accepted_media_types: frozenset[str]


_FORMAT_BY_SUFFIX: dict[str, _FormatPolicy] = {
    ".txt": _FormatPolicy(SourceFormat.TEXT, "text/plain", frozenset({"text/plain"})),
    ".md": _FormatPolicy(
        SourceFormat.MARKDOWN,
        "text/markdown",
        frozenset({"text/markdown", "text/x-markdown"}),
    ),
    ".csv": _FormatPolicy(SourceFormat.CSV, "text/csv", frozenset({"text/csv"})),
    ".json": _FormatPolicy(
        SourceFormat.JSON,
        "application/json",
        frozenset({"application/json"}),
    ),
    ".vcf": _FormatPolicy(
        SourceFormat.VCARD,
        "text/vcard",
        frozenset({"text/vcard", "text/x-vcard"}),
    ),
}

_PASTE_POLICY = _FORMAT_BY_SUFFIX[".txt"]

_CONTAINER_SIGNATURES = (
    b"PK\x03\x04",  # ZIP and ZIP-based macro-capable documents
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",  # gzip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
    b"7z\xbc\xaf'\x1c",  # 7-Zip
    b"Rar!\x1a\x07",  # RAR
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE/compound documents
    b"%PDF-",
)

_ACTIVE_ELEMENT = re.compile(
    r"<\s*/?\s*(?:script|iframe|object|embed|svg|math|applet)\b", re.IGNORECASE
)
_EVENT_HANDLER = re.compile(r"<[^>]{0,512}\bon[a-z][a-z0-9_-]{0,31}\s*=", re.IGNORECASE)
_ACTIVE_SCHEME = re.compile(r"\b(?:javascript|vbscript)\s*:", re.IGNORECASE)
_ACTIVE_DATA_URI = re.compile(
    r"\bdata\s*:\s*(?:text/html|image/svg\+xml|application/(?:javascript|x-shockwave-flash))",
    re.IGNORECASE,
)
_VCARD_PROPERTY = re.compile(r"^(?:[A-Za-z0-9-]+\.)?([A-Za-z0-9-]+)(?:;(.*))?$", re.ASCII)


def decode_file(
    path: Path,
    *,
    declared_media_type: str | None = None,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> DecodedSource:
    """Read a selected regular file without following any path symlink."""

    policy = _policy_for_path(path)
    _validate_declared_media_type(declared_media_type, policy)
    raw = _read_regular_file(path, limits.max_bytes)
    return _decode(raw, policy, limits)


def decode_pasted_text(
    text: str,
    *,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> DecodedSource:
    """Normalize clipboard text without treating it as a structured format."""

    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        raise SafeParseError(SafeParseErrorCode.INVALID_ENCODING) from None
    if len(raw) > limits.max_bytes:
        raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)
    return _decode(raw, _PASTE_POLICY, limits)


def decode_selected_bytes(
    display_name: str,
    content: bytes,
    *,
    declared_media_type: str | None = None,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> DecodedSource:
    """Decode browser-mediated file bytes without accepting a filesystem path."""

    if display_name != Path(display_name).name or "/" in display_name or "\\" in display_name:
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)
    _validate_safe_basename(display_name)
    policy = _FORMAT_BY_SUFFIX.get(Path(display_name).suffix.casefold())
    if policy is None:
        raise SafeParseError(SafeParseErrorCode.UNSUPPORTED_TYPE)
    _validate_declared_media_type(declared_media_type, policy)
    if len(content) > limits.max_bytes:
        raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)
    return _decode(content, policy, limits)


def parse_decoded_source(
    source: DecodedSource,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> ParsedSource:
    """Gate decoded text and each structured segment before returning content."""

    try:
        decision = preparse_gate(source)
    except Exception:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT) from None
    if decision is not PreparseDecision.CLEAR:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)

    if source.byte_count > limits.max_bytes:
        raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)

    parsers: dict[SourceFormat, Callable[[str, ParserLimits], tuple[SourceSegment, ...]]] = {
        SourceFormat.TEXT: _parse_lines,
        SourceFormat.MARKDOWN: _parse_lines,
        SourceFormat.CSV: _parse_csv,
        SourceFormat.JSON: _parse_json,
        SourceFormat.VCARD: _parse_vcard,
    }
    segments = parsers[source.source_format](source.text, limits)
    if not segments:
        raise SafeParseError(SafeParseErrorCode.EMPTY_SOURCE)
    gated_segments: list[SourceSegment] = []
    try:
        for segment in segments:
            gated = segment_gate(segment)
            if (
                not isinstance(gated, SourceSegment)
                or gated.index != segment.index
                or gated.kind is not segment.kind
                or gated.locator != segment.locator
                or gated.context_label != segment.context_label
            ):
                raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)
            if len(gated.text.encode("utf-8")) > len(segment.text.encode("utf-8")):
                raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT)
            _validate_inert_text(gated.text)
            gated_segments.append(gated)
    except SafeParseError:
        raise
    except Exception:
        raise SafeParseError(SafeParseErrorCode.RESTRICTED_CONTENT) from None
    return ParsedSource(
        source_format=source.source_format,
        detected_media_type=source.detected_media_type,
        sha256=source.sha256,
        byte_count=source.byte_count,
        had_utf8_bom=source.had_utf8_bom,
        segments=tuple(gated_segments),
    )


def parse_file(
    path: Path,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    declared_media_type: str | None = None,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> ParsedSource:
    """Decode, gate, and parse one explicitly selected local file."""

    source = decode_file(path, declared_media_type=declared_media_type, limits=limits)
    return parse_decoded_source(
        source,
        preparse_gate=preparse_gate,
        segment_gate=segment_gate,
        limits=limits,
    )


def parse_pasted_text(
    text: str,
    *,
    preparse_gate: PreparseGate,
    segment_gate: SegmentGate,
    limits: ParserLimits = _DEFAULT_LIMITS,
) -> ParsedSource:
    """Decode, gate, and segment explicitly pasted text."""

    source = decode_pasted_text(text, limits=limits)
    return parse_decoded_source(
        source,
        preparse_gate=preparse_gate,
        segment_gate=segment_gate,
        limits=limits,
    )


def _policy_for_path(path: Path) -> _FormatPolicy:
    if not isinstance(path, Path) or not path.is_absolute():
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)
    _validate_safe_basename(path.name)
    policy = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if policy is None:
        raise SafeParseError(SafeParseErrorCode.UNSUPPORTED_TYPE)
    return policy


def _validate_safe_basename(value: str) -> None:
    if (
        not value
        or len(value.encode("utf-8")) > 1024
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)


def _validate_declared_media_type(value: str | None, policy: _FormatPolicy) -> None:
    if value is None:
        return
    if len(value) > 128 or not value.isascii():
        raise SafeParseError(SafeParseErrorCode.MEDIA_TYPE_MISMATCH)
    components = [component.strip() for component in value.lower().split(";")]
    if not components or components[0] not in policy.accepted_media_types:
        raise SafeParseError(SafeParseErrorCode.MEDIA_TYPE_MISMATCH)
    for parameter in components[1:]:
        name, separator, parameter_value = parameter.partition("=")
        if (
            separator != "="
            or name.strip() != "charset"
            or parameter_value.strip().strip('"') not in {"utf-8", "utf8"}
        ):
            raise SafeParseError(SafeParseErrorCode.MEDIA_TYPE_MISMATCH)


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    descriptor = -1
    try:
        descriptor = _open_without_symlinks(path)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)
        if metadata.st_size > max_bytes:
            raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)

        chunks: list[bytes] = []
        byte_count = 0
        while True:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, max_bytes - byte_count + 1))
            if not chunk:
                break
            chunks.append(chunk)
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)
        return b"".join(chunks)
    except SafeParseError:
        raise
    except (OSError, ValueError):
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _open_without_symlinks(path: Path) -> int:
    parts = path.parts
    if path.anchor != os.sep or len(parts) < 2 or any(part in {".", ".."} for part in parts):
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)

    no_follow: int | None = getattr(os, "O_NOFOLLOW", None)
    directory_only: int | None = getattr(os, "O_DIRECTORY", None)
    close_on_exec: int | None = getattr(os, "O_CLOEXEC", None)
    non_blocking: int | None = getattr(os, "O_NONBLOCK", None)
    if no_follow is None or directory_only is None or close_on_exec is None or non_blocking is None:
        raise SafeParseError(SafeParseErrorCode.UNSAFE_SOURCE)

    directory_flags = os.O_RDONLY | no_follow | directory_only | close_on_exec
    file_flags = os.O_RDONLY | no_follow | close_on_exec | non_blocking
    directory_descriptor = os.open(path.anchor, directory_flags)
    try:
        for component in parts[1:-1]:
            next_descriptor = os.open(component, directory_flags, dir_fd=directory_descriptor)
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        return os.open(parts[-1], file_flags, dir_fd=directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _decode(raw: bytes, policy: _FormatPolicy, limits: ParserLimits) -> DecodedSource:
    if not raw:
        raise SafeParseError(SafeParseErrorCode.EMPTY_SOURCE)
    if len(raw) > limits.max_bytes:
        raise SafeParseError(SafeParseErrorCode.SIZE_LIMIT)
    if any(raw.startswith(signature) for signature in _CONTAINER_SIGNATURES):
        raise SafeParseError(SafeParseErrorCode.UNSUPPORTED_CONTAINER)

    had_bom = raw.startswith(_UTF8_BOM)
    encoded_text = raw[len(_UTF8_BOM) :] if had_bom else raw
    try:
        text = encoded_text.decode("utf-8")
    except UnicodeDecodeError:
        raise SafeParseError(SafeParseErrorCode.INVALID_ENCODING) from None
    if "\ufeff" in text:
        raise SafeParseError(SafeParseErrorCode.INVALID_ENCODING)

    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    _validate_inert_text(text)
    if not text.strip():
        raise SafeParseError(SafeParseErrorCode.EMPTY_SOURCE)
    return DecodedSource(
        source_format=policy.source_format,
        detected_media_type=policy.media_type,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        had_utf8_bom=had_bom,
        text=text,
    )


def _validate_inert_text(text: str) -> None:
    for character in text:
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}:
            raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)
    stripped = text.lstrip()
    if stripped.startswith("#!"):
        raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)
    if (
        _ACTIVE_ELEMENT.search(text)
        or _EVENT_HANDLER.search(text)
        or _ACTIVE_SCHEME.search(text)
        or _ACTIVE_DATA_URI.search(text)
    ):
        raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)


def _physical_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_lines(text: str, limits: ParserLimits) -> tuple[SourceSegment, ...]:
    lines = _physical_lines(text)
    _enforce_count(len(lines), limits.max_rows, SafeParseErrorCode.ROW_LIMIT)
    segments = [
        SourceSegment(
            index=index,
            kind=SourceSegmentKind.TEXT,
            locator=f"line:{line_number}",
            text=line.strip(),
        )
        for index, (line_number, line) in enumerate(
            item for item in enumerate(lines, start=1) if item[1].strip()
        )
    ]
    return tuple(segments)


def _parse_csv(text: str, limits: ParserLimits) -> tuple[SourceSegment, ...]:
    if _looks_like_json(text):
        raise SafeParseError(SafeParseErrorCode.CONTENT_MISMATCH)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    segments: list[SourceSegment] = []
    expected_width: int | None = None
    cell_count = 0
    try:
        for row_number, row in enumerate(reader, start=1):
            _enforce_count(row_number, limits.max_rows, SafeParseErrorCode.ROW_LIMIT)
            if not row:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            if expected_width is None:
                expected_width = len(row)
            elif len(row) != expected_width:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            cell_count += len(row)
            _enforce_count(cell_count, limits.max_cells, SafeParseErrorCode.CELL_LIMIT)
            for cell in row:
                _validate_cell(cell, limits)
                if _is_spreadsheet_formula(cell):
                    raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)
            segments.append(
                SourceSegment(
                    index=row_number - 1,
                    kind=SourceSegmentKind.RECORD,
                    locator=f"row:{row_number}",
                    text="\n".join(row),
                )
            )
    except csv.Error:
        raise SafeParseError(SafeParseErrorCode.MALFORMED) from None
    return tuple(segments)


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return False
    return True


def _is_spreadsheet_formula(cell: str) -> bool:
    candidate = cell.lstrip(" \t")
    return bool(candidate) and candidate[0] in {"=", "+", "-", "@"}


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError


def _parse_json(text: str, limits: ParserLimits) -> tuple[SourceSegment, ...]:
    _validate_json_depth(text, limits.max_depth)

    def parse_decimal(raw: str) -> Decimal:
        return _parse_bounded_decimal(
            raw,
            maximum_output_bytes=min(
                limits.max_cell_bytes,
                _MAX_JSON_NUMBER_OUTPUT_BYTES,
            ),
        )

    try:
        value: object = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_float=parse_decimal,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, _DuplicateJsonKey, RecursionError, ValueError):
        raise SafeParseError(SafeParseErrorCode.MALFORMED) from None

    segments: list[SourceSegment] = []
    member_count = 0
    stack: list[tuple[tuple[str | int, ...], object]] = [((), value)]
    while stack:
        path, item = stack.pop()
        if isinstance(item, dict):
            member_count += len(item)
            _enforce_count(member_count, limits.max_members, SafeParseErrorCode.MEMBER_LIMIT)
            children: list[tuple[tuple[str | int, ...], object]] = []
            for key, child in item.items():
                _validate_cell(key, limits)
                children.append(((*path, key), child))
            stack.extend(reversed(children))
        elif isinstance(item, list):
            member_count += len(item)
            _enforce_count(member_count, limits.max_members, SafeParseErrorCode.MEMBER_LIMIT)
            stack.extend(reversed([((*path, index), child) for index, child in enumerate(item)]))
        else:
            normalized = _normalize_json_scalar(item)
            _validate_cell(normalized, limits)
            segments.append(
                SourceSegment(
                    index=len(segments),
                    kind=SourceSegmentKind.JSON_VALUE,
                    locator=f"json:{_json_pointer(path)}",
                    text=normalized,
                    context_label=None if not path else str(path[-1]),
                )
            )
    return tuple(segments)


def _parse_bounded_decimal(raw: str, *, maximum_output_bytes: int) -> Decimal:
    if len(raw) > 128:
        raise ValueError
    exponent_match = re.search(r"[eE]([+-]?\d+)$", raw)
    if exponent_match is not None:
        exponent_text = exponent_match.group(1).lstrip("+-")
        if len(exponent_text) > 6:
            raise ValueError
        if abs(int(exponent_match.group(1))) > maximum_output_bytes:
            raise ValueError
    value = Decimal(raw)
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError
    digit_count = len(digits)
    if exponent >= 0:
        output_length = sign + digit_count + exponent
    else:
        decimal_position = digit_count + exponent
        output_length = (
            sign + digit_count + 1
            if decimal_position > 0
            else sign + 2 + abs(decimal_position) + digit_count
        )
    if output_length > maximum_output_bytes:
        raise ValueError
    return value


def _validate_json_depth(text: str, max_depth: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > max_depth:
                raise SafeParseError(SafeParseErrorCode.DEPTH_LIMIT)
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
    if depth != 0 or in_string:
        raise SafeParseError(SafeParseErrorCode.MALFORMED)


def _normalize_json_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    raise SafeParseError(SafeParseErrorCode.MALFORMED)


def _json_pointer(path: Iterable[str | int]) -> str:
    encoded: list[str] = []
    for item in path:
        safe = "".join(
            (f"\\u{ord(character):04x}" if ord(character) <= 0xFFFF else f"\\U{ord(character):08x}")
            if not 0x20 <= ord(character) <= 0x7E
            else character
            for character in str(item)
        )
        encoded.append(safe.replace("~", "~0").replace("/", "~1"))
    pointer = "/" + "/".join(encoded) if encoded else "/"
    if len(pointer.encode("utf-8")) > 4096:
        raise SafeParseError(SafeParseErrorCode.CELL_LIMIT)
    return pointer


@dataclass(frozen=True, slots=True)
class _LogicalVCardLine:
    number: int
    text: str


def _parse_vcard(text: str, limits: ParserLimits) -> tuple[SourceSegment, ...]:
    physical_lines = _physical_lines(text)
    _enforce_count(len(physical_lines), limits.max_rows, SafeParseErrorCode.ROW_LIMIT)
    logical_lines = _unfold_vcard_lines(physical_lines)

    segments: list[SourceSegment] = []
    properties: list[str] | None = None
    begin_line = 0
    version_count = 0
    full_name_count = 0
    property_count = 0

    for logical in logical_lines:
        line = logical.text
        upper_line = line.upper()
        if upper_line == "BEGIN:VCARD":
            if properties is not None:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            properties = []
            begin_line = logical.number
            version_count = 0
            full_name_count = 0
            continue
        if upper_line == "END:VCARD":
            if properties is None or version_count != 1 or full_name_count != 1:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            card_number = len(segments) + 1
            _enforce_count(card_number, limits.max_members, SafeParseErrorCode.MEMBER_LIMIT)
            segments.append(
                SourceSegment(
                    index=card_number - 1,
                    kind=SourceSegmentKind.CONTACT,
                    locator=f"card:{card_number}:lines:{begin_line}-{logical.number}",
                    text="\n".join(properties),
                )
            )
            properties = None
            continue
        if not line:
            if properties is not None:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            continue
        if properties is None:
            raise SafeParseError(SafeParseErrorCode.CONTENT_MISMATCH)

        header, separator, value = line.partition(":")
        if separator != ":":
            raise SafeParseError(SafeParseErrorCode.MALFORMED)
        match = _VCARD_PROPERTY.fullmatch(header)
        if match is None:
            raise SafeParseError(SafeParseErrorCode.MALFORMED)
        _validate_cell(header, limits)
        property_name = match.group(1).upper()
        parameters = (match.group(2) or "").upper()
        if _has_embedded_vcard_payload(parameters, value):
            raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)
        _validate_cell(value, limits)
        property_count += 1
        _enforce_count(property_count, limits.max_cells, SafeParseErrorCode.CELL_LIMIT)
        if property_name == "VERSION":
            version_count += 1
            if value not in {"3.0", "4.0"}:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
        elif property_name == "FN":
            full_name_count += 1
        properties.append(f"{header.upper()}:{value}")

    if properties is not None:
        raise SafeParseError(SafeParseErrorCode.MALFORMED)
    return tuple(segments)


def _unfold_vcard_lines(lines: list[str]) -> list[_LogicalVCardLine]:
    logical: list[_LogicalVCardLine] = []
    for line_number, line in enumerate(lines, start=1):
        if line.startswith((" ", "\t")):
            if not logical:
                raise SafeParseError(SafeParseErrorCode.MALFORMED)
            previous = logical[-1]
            logical[-1] = _LogicalVCardLine(previous.number, previous.text + line[1:])
        else:
            logical.append(_LogicalVCardLine(line_number, line))
    return logical


def _has_embedded_vcard_payload(parameters: str, value: str) -> bool:
    normalized_parameters = parameters.replace('"', "")
    if re.search(r"(?:^|;)ENCODING=(?:B|BASE64)(?:;|$)", normalized_parameters):
        return True
    if re.search(r"(?:^|;)VALUE=BINARY(?:;|$)", normalized_parameters):
        return True
    return value.lstrip().lower().startswith("data:")


def _validate_cell(value: str, limits: ParserLimits) -> None:
    try:
        byte_count = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise SafeParseError(SafeParseErrorCode.INVALID_ENCODING) from None
    if byte_count > limits.max_cell_bytes:
        raise SafeParseError(SafeParseErrorCode.CELL_LIMIT)
    for character in value:
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}:
            raise SafeParseError(SafeParseErrorCode.ACTIVE_CONTENT)


def _enforce_count(count: int, maximum: int, code: SafeParseErrorCode) -> None:
    if count > maximum:
        raise SafeParseError(code)
