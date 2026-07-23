"""Compose safe decoding, quarantine, extraction, and semantic enrichment.

The order is a security and provenance invariant: decode, quarantine, parse in
isolation, extract deterministically, then propose semantics.  Optional model
suggestions are attached later as review-only, source-grounded candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from ariadne_core.domain.identity_compiler import (
    CandidateEntity,
    CompilationResult,
    ExtractionLimits,
    RestrictedKind,
    SourceSpan,
    compile_text,
)
from ariadne_core.domain.semantic_enrichment import SemanticEnrichment, enrich_semantics
from ariadne_core.intake.isolation import (
    IsolationOperation,
    parse_decoded_source_isolated,
)
from ariadne_core.intake.parsing import (
    DecodedSource,
    ParsedSource,
    ParserLimits,
    PreparseDecision,
    SourceFormat,
    SourceSegment,
    SourceSegmentKind,
    decode_pasted_text,
    decode_selected_bytes,
)
from ariadne_core.local_ai import LocalEntitySuggestion

MAX_PHASE3_SOURCE_BYTES = 1_048_576
PHASE3_PARSER_LIMITS = ParserLimits(
    max_bytes=MAX_PHASE3_SOURCE_BYTES,
    max_rows=20_000,
    max_depth=32,
    max_members=50_000,
    max_cells=200_000,
    max_cell_bytes=32 * 1024,
)
PHASE3_EXTRACTION_LIMITS = ExtractionLimits(max_text_bytes=MAX_PHASE3_SOURCE_BYTES)


class LocalAIIntakeStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    DISABLED = "DISABLED"
    SUCCEEDED = "SUCCEEDED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


@dataclass(frozen=True, slots=True)
class PreparedLocalAIOutcome:
    status: LocalAIIntakeStatus = LocalAIIntakeStatus.NOT_REQUESTED
    provider: str | None = None
    model_id: str | None = None
    engine_version: str | None = None
    suggestions: tuple[LocalEntitySuggestion, ...] = field(default_factory=tuple, repr=False)


@dataclass(frozen=True, slots=True)
class PreparedIntake:
    source_kind: str
    display_name: str = field(repr=False)
    detected_media_type: str
    source_sha256: str
    byte_count: int
    parsed: ParsedSource = field(repr=False)
    deterministic: CompilationResult = field(repr=False)
    structured_candidates: tuple[SegmentCandidate, ...] = field(repr=False)
    structured_quarantine: tuple[StructuredQuarantine, ...] = field(repr=False)
    semantic: SemanticEnrichment = field(repr=False)
    local_ai: PreparedLocalAIOutcome = field(default_factory=PreparedLocalAIOutcome, repr=False)

    @property
    def candidate_count(self) -> int:
        deterministic_keys = {
            (candidate.entity_type.value, candidate.canonical_value)
            for candidate in self.deterministic.candidates
        }
        structured_keys = {
            (item.candidate.entity_type.value, item.candidate.canonical_value)
            for item in self.structured_candidates
        }
        return (
            len(deterministic_keys | structured_keys)
            + len(self.semantic.entities)
            + len(self.local_ai.suggestions)
        )

    @property
    def duplicate_count(self) -> int:
        occurrences = sum(len(candidate.spans) for candidate in self.deterministic.candidates)
        return max(0, occurrences - len(self.deterministic.candidates))

    @property
    def quarantine_count(self) -> int:
        return len(self.deterministic.quarantine) + len(self.structured_quarantine)


@dataclass(frozen=True, slots=True)
class SegmentCandidate:
    segment_index: int
    candidate: CandidateEntity = field(repr=False)


@dataclass(frozen=True, slots=True)
class StructuredQuarantine:
    segment_index: int
    kind: RestrictedKind


class _StructuredGate:
    def __init__(self, source_format: SourceFormat) -> None:
        self.source_format = source_format
        self.csv_headers: tuple[str, ...] | None = None
        self.candidates: list[SegmentCandidate] = []
        self.quarantine: list[StructuredQuarantine] = []

    def __call__(self, segment: SourceSegment) -> SourceSegment:
        if segment.kind is SourceSegmentKind.TEXT:
            return segment
        if self.source_format is SourceFormat.JSON:
            label = segment.context_label or segment.locator.rsplit("/", 1)[-1]
            safe_value = self._gate_value(segment, label=label, value=segment.text, offset=0)
            return replace(segment, text=safe_value)
        if self.source_format is SourceFormat.CSV:
            cells = segment.text.split("\n")
            if self.csv_headers is None:
                self.csv_headers = tuple(cells)
                return segment
            if len(cells) != len(self.csv_headers):
                return replace(segment, text="[restricted]")
            safe_cells: list[str] = []
            offset = 0
            for label, value in zip(self.csv_headers, cells, strict=True):
                safe_cells.append(
                    self._gate_value(segment, label=label, value=value, offset=offset)
                )
                offset += len(value) + 1
            return replace(segment, text="\n".join(safe_cells))
        safe_value = self._gate_value(segment, label=segment.locator, value=segment.text, offset=0)
        return replace(segment, text=safe_value)

    def _gate_value(
        self,
        segment: SourceSegment,
        *,
        label: str,
        value: str,
        offset: int,
    ) -> str:
        prefix = f"{label}: "
        result = compile_text(prefix + value, limits=PHASE3_EXTRACTION_LIMITS)
        if result.quarantine:
            self.quarantine.extend(
                StructuredQuarantine(segment.index, descriptor.kind)
                for descriptor in result.quarantine
            )
            return "*" * len(value)
        for candidate in result.candidates:
            spans = tuple(
                SourceSpan(
                    max(0, span.start - len(prefix) + offset),
                    max(1, span.end - len(prefix) + offset),
                )
                for span in candidate.spans
                if span.end > len(prefix)
            )
            if not spans:
                continue
            self.candidates.append(
                SegmentCandidate(
                    segment.index,
                    CandidateEntity(
                        entity_type=candidate.entity_type,
                        canonical_value=candidate.canonical_value,
                        display_mask=candidate.display_mask,
                        sensitivity=candidate.sensitivity,
                        spans=spans,
                        extractor=candidate.extractor,
                        confidence_micros=candidate.confidence_micros,
                    ),
                )
            )
        return value


def _prepare(
    source: DecodedSource,
    *,
    source_kind: str,
    display_name: str,
    semantic_enrichment_enabled: bool,
) -> PreparedIntake:
    """Build one review package without persisting or dispatching source content."""

    deterministic = compile_text(source.text, limits=PHASE3_EXTRACTION_LIMITS)
    redacted_source = replace(source, text=deterministic.redacted_text)
    structured_gate = _StructuredGate(source.source_format)
    parsed = parse_decoded_source_isolated(
        IsolationOperation.PASTE if source_kind == "PASTE" else IsolationOperation.FILE,
        redacted_source,
        preparse_gate=lambda _source: PreparseDecision.CLEAR,
        segment_gate=structured_gate,
        parser_limits=PHASE3_PARSER_LIMITS,
    )
    semantic = (
        enrich_semantics(deterministic.redacted_text, deterministic.candidates)
        if semantic_enrichment_enabled
        else SemanticEnrichment(entities=(), relationships=(), exclusion_spans=())
    )
    return PreparedIntake(
        source_kind=source_kind,
        display_name=display_name,
        detected_media_type=parsed.detected_media_type,
        source_sha256=source.sha256,
        byte_count=source.byte_count,
        parsed=parsed,
        deterministic=deterministic,
        structured_candidates=tuple(structured_gate.candidates),
        structured_quarantine=tuple(structured_gate.quarantine),
        semantic=semantic,
    )


def prepare_pasted_intake(
    text: str,
    *,
    display_name: str,
    semantic_enrichment_enabled: bool = True,
) -> PreparedIntake:
    """Apply the complete local intake pipeline to user-approved pasted text."""

    source = decode_pasted_text(text, limits=PHASE3_PARSER_LIMITS)
    return _prepare(
        source,
        source_kind="PASTE",
        display_name=display_name,
        semantic_enrichment_enabled=semantic_enrichment_enabled,
    )


def prepare_file_intake(
    *,
    display_name: str,
    content: bytes,
    declared_media_type: str,
    semantic_enrichment_enabled: bool = True,
) -> PreparedIntake:
    """Apply the same bounded intake pipeline to brokered local file bytes."""

    source = decode_selected_bytes(
        display_name,
        content,
        declared_media_type=declared_media_type,
        limits=PHASE3_PARSER_LIMITS,
    )
    return _prepare(
        source,
        source_kind="FILE",
        display_name=display_name,
        semantic_enrichment_enabled=semantic_enrichment_enabled,
    )
