from __future__ import annotations

import os
from functools import partial
from pathlib import Path

import pytest

from ariadne_core.intake.parsing import (
    DecodedSource,
    ParserLimits,
    PreparseDecision,
    SafeParseError,
    SafeParseErrorCode,
    SourceFormat,
    SourceSegmentKind,
    decode_file,
    decode_pasted_text,
    decode_selected_bytes,
)
from ariadne_core.intake.parsing import (
    parse_decoded_source as _parse_decoded_source,
)
from ariadne_core.intake.parsing import (
    parse_file as _parse_file,
)
from ariadne_core.intake.parsing import (
    parse_pasted_text as _parse_pasted_text,
)


def clear_source(_source: DecodedSource) -> PreparseDecision:
    return PreparseDecision.CLEAR


def clear_segment(segment):  # type: ignore[no-untyped-def]
    return segment


parse_decoded_source = partial(_parse_decoded_source, segment_gate=clear_segment)
parse_file = partial(_parse_file, segment_gate=clear_segment)
parse_pasted_text = partial(_parse_pasted_text, segment_gate=clear_segment)


def test_selected_bytes_use_only_a_sanitized_basename_and_declared_type() -> None:
    decoded = decode_selected_bytes(
        "synthetic.json",
        b'{"alias":"synthetic_user"}',
        declared_media_type="application/json",
    )
    result = parse_decoded_source(decoded, preparse_gate=clear_source, segment_gate=clear_segment)
    assert result.source_format is SourceFormat.JSON

    for name in ("../synthetic.json", "/tmp/synthetic.json", "folder\\synthetic.json"):
        with pytest.raises(SafeParseError) as captured:
            decode_selected_bytes(name, b"{}", declared_media_type="application/json")
        assert captured.value.code is SafeParseErrorCode.UNSAFE_SOURCE

    with pytest.raises(SafeParseError) as captured:
        decode_selected_bytes(
            "synthetic.json",
            b"{}",
            declared_media_type="text/csv",
        )
    assert captured.value.code is SafeParseErrorCode.MEDIA_TYPE_MISMATCH


@pytest.mark.parametrize(
    ("name", "content", "media_type", "source_format", "kind"),
    [
        (
            "synthetic.txt",
            b"Synthetic alias\r\nSecond clue\n",
            "text/plain",
            SourceFormat.TEXT,
            SourceSegmentKind.TEXT,
        ),
        (
            "synthetic.md",
            b"# Synthetic profile\n- Alias\n",
            "text/markdown",
            SourceFormat.MARKDOWN,
            SourceSegmentKind.TEXT,
        ),
        (
            "synthetic.csv",
            b"kind,value\r\nalias,synthetic_user\r\n",
            "text/csv",
            SourceFormat.CSV,
            SourceSegmentKind.RECORD,
        ),
        (
            "synthetic.json",
            b'{"alias":"synthetic_user"}',
            "application/json",
            SourceFormat.JSON,
            SourceSegmentKind.JSON_VALUE,
        ),
        (
            "synthetic.vcf",
            b"BEGIN:VCARD\r\nVERSION:4.0\r\nFN:Synthetic Person\r\nEND:VCARD\r\n",
            "text/vcard",
            SourceFormat.VCARD,
            SourceSegmentKind.CONTACT,
        ),
    ],
)
def test_mvp_formats_produce_normalized_compiler_segments(
    tmp_path: Path,
    name: str,
    content: bytes,
    media_type: str,
    source_format: SourceFormat,
    kind: SourceSegmentKind,
) -> None:
    path = tmp_path / name
    path.write_bytes(content)

    result = parse_file(
        path,
        declared_media_type=f"{media_type}; charset=UTF-8",
        preparse_gate=clear_source,
        segment_gate=clear_segment,
    )

    assert result.source_format is source_format
    assert result.detected_media_type == media_type
    assert result.byte_count == len(content)
    assert len(result.sha256) == 64
    assert result.segments[0].kind is kind
    assert result.text_segments == tuple(segment.text for segment in result.segments)
    assert all("\r" not in segment for segment in result.text_segments)


def test_utf8_bom_and_unicode_are_normalized_without_entering_repr(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbfCafe\xcc\x81\r\nSynthetic"
    path = tmp_path / "synthetic.txt"
    path.write_bytes(raw)

    decoded = decode_file(path)
    result = parse_decoded_source(decoded, preparse_gate=clear_source, segment_gate=clear_segment)

    assert decoded.had_utf8_bom is True
    assert decoded.byte_count == len(raw)
    assert decoded.text == "Caf\u00e9\nSynthetic"
    assert "Caf\u00e9" not in repr(decoded)
    assert result.text_segments == ("Caf\u00e9", "Synthetic")
    assert "Caf\u00e9" not in repr(result.segments[0])


def test_restricted_gate_runs_before_structured_parsing_and_fails_closed() -> None:
    decoded = decode_pasted_text("synthetic marker")
    calls: list[str] = []

    def quarantine(source: DecodedSource) -> PreparseDecision:
        calls.append(source.sha256)
        return PreparseDecision.QUARANTINE

    with pytest.raises(SafeParseError) as captured:
        parse_decoded_source(decoded, preparse_gate=quarantine, segment_gate=clear_segment)
    assert captured.value.code is SafeParseErrorCode.RESTRICTED_CONTENT
    assert calls == [decoded.sha256]

    malformed = DecodedSource(
        source_format=SourceFormat.JSON,
        detected_media_type="application/json",
        sha256="0" * 64,
        byte_count=1,
        had_utf8_bom=False,
        text="{",
    )
    calls.clear()
    with pytest.raises(SafeParseError) as malformed_error:
        parse_decoded_source(malformed, preparse_gate=quarantine, segment_gate=clear_segment)
    assert malformed_error.value.code is SafeParseErrorCode.RESTRICTED_CONTENT
    assert calls == [malformed.sha256]


def test_gate_exceptions_are_redacted_and_fail_closed() -> None:
    decoded = decode_pasted_text("synthetic secret marker")

    def broken_gate(_source: DecodedSource) -> PreparseDecision:
        raise RuntimeError("synthetic secret marker")

    with pytest.raises(SafeParseError) as captured:
        parse_decoded_source(decoded, preparse_gate=broken_gate, segment_gate=clear_segment)
    assert captured.value.code is SafeParseErrorCode.RESTRICTED_CONTENT
    assert "marker" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


def test_exact_byte_and_row_limits_are_inclusive() -> None:
    exact_bytes = ParserLimits(max_bytes=3)
    assert (
        parse_pasted_text(
            "abc",
            limits=exact_bytes,
            preparse_gate=clear_source,
            segment_gate=clear_segment,
        ).byte_count
        == 3
    )
    with pytest.raises(SafeParseError) as captured:
        parse_pasted_text(
            "abcd",
            limits=exact_bytes,
            preparse_gate=clear_source,
            segment_gate=clear_segment,
        )
    assert captured.value.code is SafeParseErrorCode.SIZE_LIMIT

    exact_rows = ParserLimits(max_rows=2)
    assert parse_pasted_text(
        "one\ntwo\n", limits=exact_rows, preparse_gate=clear_source
    ).text_segments == ("one", "two")
    with pytest.raises(SafeParseError) as captured:
        parse_pasted_text("one\ntwo\nthree", limits=exact_rows, preparse_gate=clear_source)
    assert captured.value.code is SafeParseErrorCode.ROW_LIMIT


def test_json_depth_and_member_limits_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text('{"first":[],"second":2}', encoding="utf-8")
    exact = ParserLimits(max_depth=2, max_members=2)
    result = parse_file(path, limits=exact, preparse_gate=clear_source)
    assert result.text_segments == ("2",)

    path.write_text('{"first":[[]]}', encoding="utf-8")
    with pytest.raises(SafeParseError) as depth_error:
        parse_file(path, limits=exact, preparse_gate=clear_source)
    assert depth_error.value.code is SafeParseErrorCode.DEPTH_LIMIT

    path.write_text('{"first":1,"second":2,"third":3}', encoding="utf-8")
    with pytest.raises(SafeParseError) as member_error:
        parse_file(path, limits=exact, preparse_gate=clear_source)
    assert member_error.value.code is SafeParseErrorCode.MEMBER_LIMIT


def test_json_decimal_expansion_is_rejected_before_fixed_point_formatting(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text('{"value":1e60000}', encoding="utf-8")

    with pytest.raises(SafeParseError) as captured:
        parse_file(path, preparse_gate=clear_source)
    assert captured.value.code is SafeParseErrorCode.MALFORMED


def test_csv_row_cell_count_and_cell_byte_limits_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    path.write_text("a,b\nc,d\n", encoding="utf-8")
    exact = ParserLimits(max_rows=2, max_cells=4, max_cell_bytes=1)
    assert len(parse_file(path, limits=exact, preparse_gate=clear_source).segments) == 2

    with pytest.raises(SafeParseError) as total_cells:
        parse_file(
            path,
            limits=ParserLimits(max_rows=2, max_cells=3),
            preparse_gate=clear_source,
        )
    assert total_cells.value.code is SafeParseErrorCode.CELL_LIMIT

    path.write_text("a,\u00e9\n", encoding="utf-8")
    assert parse_file(
        path,
        limits=ParserLimits(max_cell_bytes=2),
        preparse_gate=clear_source,
    ).text_segments == ("a\n\u00e9",)
    with pytest.raises(SafeParseError) as cell_bytes:
        parse_file(
            path,
            limits=ParserLimits(max_cell_bytes=1),
            preparse_gate=clear_source,
        )
    assert cell_bytes.value.code is SafeParseErrorCode.CELL_LIMIT


def test_extension_declared_type_and_structured_content_must_agree(tmp_path: Path) -> None:
    unsupported = tmp_path / "synthetic.zip"
    unsupported.write_bytes(b"not an archive")
    with pytest.raises(SafeParseError) as suffix_error:
        decode_file(unsupported)
    assert suffix_error.value.code is SafeParseErrorCode.UNSUPPORTED_TYPE

    json_path = tmp_path / "synthetic.json"
    json_path.write_text("kind,value\nalias,synthetic", encoding="utf-8")
    with pytest.raises(SafeParseError) as json_error:
        parse_file(json_path, preparse_gate=clear_source)
    assert json_error.value.code is SafeParseErrorCode.MALFORMED

    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_text('{"kind":"alias"}', encoding="utf-8")
    with pytest.raises(SafeParseError) as csv_error:
        parse_file(csv_path, preparse_gate=clear_source)
    assert csv_error.value.code is SafeParseErrorCode.CONTENT_MISMATCH

    with pytest.raises(SafeParseError) as media_error:
        decode_file(csv_path, declared_media_type="application/json")
    assert media_error.value.code is SafeParseErrorCode.MEDIA_TYPE_MISMATCH


@pytest.mark.parametrize(
    "content",
    [
        b"PK\x03\x04synthetic archive",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic macro document",
        b"%PDF-1.7 synthetic",
    ],
)
def test_archive_and_binary_document_signatures_are_never_parsed(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "synthetic.txt"
    path.write_bytes(content)
    with pytest.raises(SafeParseError) as captured:
        decode_file(path)
    assert captured.value.code is SafeParseErrorCode.UNSUPPORTED_CONTAINER


@pytest.mark.parametrize(
    "text",
    [
        "#!/bin/sh\necho synthetic",
        "<script>synthetic()</script>",
        '<div onclick="synthetic()">text</div>',
        "[synthetic](javascript:synthetic())",
        "\x00synthetic",
    ],
)
def test_scripts_handlers_active_schemes_and_controls_are_rejected(text: str) -> None:
    with pytest.raises(SafeParseError) as captured:
        decode_pasted_text(text)
    assert captured.value.code is SafeParseErrorCode.ACTIVE_CONTENT


def test_csv_formulas_and_malformed_shapes_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.csv"
    for formula in (
        '=HYPERLINK("https://invalid.example")',
        "+1",
        "-1",
        "@A1",
    ):
        path.write_text(f'kind,value\nalias,"{formula.replace(chr(34), chr(34) * 2)}"\n')
        with pytest.raises(SafeParseError) as formula_error:
            parse_file(path, preparse_gate=clear_source)
        assert formula_error.value.code is SafeParseErrorCode.ACTIVE_CONTENT

    path.write_text("kind,value\nalias\n")
    with pytest.raises(SafeParseError) as shape_error:
        parse_file(path, preparse_gate=clear_source)
    assert shape_error.value.code is SafeParseErrorCode.MALFORMED


def test_json_rejects_duplicate_keys_constants_and_malformed_depth(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.json"
    for content in ('{"alias":1,"alias":2}', '{"alias":NaN}', '{"alias":1]]'):
        path.write_text(content)
        with pytest.raises(SafeParseError) as captured:
            parse_file(path, preparse_gate=clear_source)
        assert captured.value.code is SafeParseErrorCode.MALFORMED


def test_vcard_requires_bounded_plain_contacts(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.vcf"
    cards = (
        "BEGIN:VCARD\nVERSION:4.0\nFN:Synthetic One\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:4.0\nFN:Synthetic Two\nEND:VCARD\n"
    )
    path.write_text(cards)
    assert (
        len(
            parse_file(
                path,
                limits=ParserLimits(max_members=2, max_cells=4),
                preparse_gate=clear_source,
            ).segments
        )
        == 2
    )
    with pytest.raises(SafeParseError) as member_error:
        parse_file(
            path,
            limits=ParserLimits(max_members=1),
            preparse_gate=clear_source,
        )
    assert member_error.value.code is SafeParseErrorCode.MEMBER_LIMIT

    path.write_text(
        "BEGIN:VCARD\nVERSION:4.0\nFN:Synthetic\nPHOTO;ENCODING=BASE64:c3ludGhldGlj\nEND:VCARD\n"
    )
    with pytest.raises(SafeParseError) as embedded_error:
        parse_file(path, preparse_gate=clear_source)
    assert embedded_error.value.code is SafeParseErrorCode.ACTIVE_CONTENT

    path.write_text("BEGIN:VCARD\nVERSION:4.0\nEND:VCARD\n")
    with pytest.raises(SafeParseError) as malformed_error:
        parse_file(path, preparse_gate=clear_source)
    assert malformed_error.value.code is SafeParseErrorCode.MALFORMED


def test_symlinks_symlinked_parents_directories_and_fifos_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "synthetic.txt"
    target.write_text("synthetic")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    with pytest.raises(SafeParseError) as link_error:
        decode_file(link)
    assert link_error.value.code is SafeParseErrorCode.UNSAFE_SOURCE

    real_parent = tmp_path / "real"
    real_parent.mkdir()
    (real_parent / "synthetic.txt").write_text("synthetic")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(SafeParseError) as parent_error:
        decode_file(linked_parent / "synthetic.txt")
    assert parent_error.value.code is SafeParseErrorCode.UNSAFE_SOURCE

    directory = tmp_path / "directory.txt"
    directory.mkdir()
    with pytest.raises(SafeParseError) as directory_error:
        decode_file(directory)
    assert directory_error.value.code is SafeParseErrorCode.UNSAFE_SOURCE

    fifo = tmp_path / "pipe.txt"
    os.mkfifo(fifo)
    with pytest.raises(SafeParseError) as fifo_error:
        decode_file(fifo)
    assert fifo_error.value.code is SafeParseErrorCode.UNSAFE_SOURCE


def test_encoding_failures_and_embedded_bom_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.txt"
    for content in (b"\xffsynthetic", "synthetic\ufeffvalue".encode()):
        path.write_bytes(content)
        with pytest.raises(SafeParseError) as captured:
            decode_file(path)
        assert captured.value.code is SafeParseErrorCode.INVALID_ENCODING


def test_errors_are_fixed_and_never_contain_paths_or_rejected_values(tmp_path: Path) -> None:
    sensitive_marker = "synthetic-private-marker"
    path = tmp_path / f"{sensitive_marker}.json"
    path.write_text(f'{{"{sensitive_marker}":')
    with pytest.raises(SafeParseError) as captured:
        parse_file(path, preparse_gate=clear_source)

    assert captured.value.code is SafeParseErrorCode.MALFORMED
    assert str(captured.value) == "the source structure is malformed"
    assert sensitive_marker not in str(captured.value)
    assert str(path) not in str(captured.value)


def test_relative_paths_and_invalid_limits_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SafeParseError) as path_error:
        decode_file(Path("synthetic.txt"))
    assert path_error.value.code is SafeParseErrorCode.UNSAFE_SOURCE
    with pytest.raises(ValueError, match="parser limits must be positive"):
        ParserLimits(max_rows=0)
