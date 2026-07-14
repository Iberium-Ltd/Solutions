"""Build an ephemeral, provenance-preserving corpus through safe intake."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from ariadne_core.application.intake_compiler import prepare_file_intake
from ariadne_core.domain.identity_compiler import (
    CandidateEntity,
    Sensitivity,
    SourceSpan,
    compile_text,
)
from ariadne_core.domain.local_corpus import (
    CorpusDocument,
    CorpusEntity,
    CorpusEntityOccurrence,
    CorpusSegment,
    LocalCorpus,
    corpus_entity_id,
    corpus_id,
)
from ariadne_core.domain.semantic_enrichment import SemanticEntity, enrich_semantics

_HARD_MAX_DOCUMENTS = 50
_HARD_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_HARD_MAX_SEGMENTS = 10_000
_HARD_MAX_ENTITIES = 8_192
_HARD_MAX_ENTITY_OCCURRENCES = 100_000
_SENSITIVITY_RANK = {
    Sensitivity.PUBLIC.value: 0,
    Sensitivity.SENSITIVE.value: 1,
    Sensitivity.HIGHLY_SENSITIVE.value: 2,
    Sensitivity.RESTRICTED.value: 3,
}


class LocalCorpusBuildError(ValueError):
    """Stable corpus-level failure that never contains document data."""


@dataclass(frozen=True, slots=True)
class LocalCorpusLimits:
    max_documents: int = 20
    max_total_bytes: int = 4 * 1024 * 1024
    max_segments: int = 5_000
    max_entities: int = 4_096
    max_entity_occurrences: int = 20_000

    def __post_init__(self) -> None:
        values = (
            (self.max_documents, _HARD_MAX_DOCUMENTS),
            (self.max_total_bytes, _HARD_MAX_TOTAL_BYTES),
            (self.max_segments, _HARD_MAX_SEGMENTS),
            (self.max_entities, _HARD_MAX_ENTITIES),
            (self.max_entity_occurrences, _HARD_MAX_ENTITY_OCCURRENCES),
        )
        if any(value < 1 or value > maximum for value, maximum in values):
            raise ValueError("local corpus limits must be positive and within hard bounds")


@dataclass(frozen=True, slots=True)
class LocalCorpusDocumentInput:
    display_name: str = field(repr=False)
    declared_media_type: str
    content: bytes = field(repr=False)


@dataclass(slots=True)
class _EntityAccumulator:
    entity_type: str
    canonical_value: str = field(repr=False)
    canonical_key: str = field(repr=False)
    display_mask: str = field(repr=False)
    sensitivity: str
    occurrences: list[CorpusEntityOccurrence] = field(default_factory=list, repr=False)
    occurrence_keys: set[tuple[object, ...]] = field(default_factory=set, repr=False)


@dataclass(slots=True)
class _EntityState:
    max_entities: int
    max_occurrences: int
    items: dict[tuple[str, str], _EntityAccumulator] = field(default_factory=dict, repr=False)
    occurrence_count: int = 0


def build_local_corpus(
    document_inputs: Iterable[LocalCorpusDocumentInput],
    *,
    limits: LocalCorpusLimits | None = None,
    semantic_enrichment_enabled: bool = True,
) -> LocalCorpus:
    """Safely parse a small file batch without retaining the source byte payloads."""

    active_limits = limits or LocalCorpusLimits()
    inputs = _bounded_inputs(document_inputs, active_limits)
    documents: list[CorpusDocument] = []
    segments: list[CorpusSegment] = []
    entities = _EntityState(
        max_entities=active_limits.max_entities,
        max_occurrences=active_limits.max_entity_occurrences,
    )

    for ordinal, source in enumerate(inputs):
        prepared = prepare_file_intake(
            display_name=source.display_name,
            content=source.content,
            declared_media_type=source.declared_media_type,
            semantic_enrichment_enabled=False,
        )
        document_id = f"corpus-document:{ordinal + 1:04d}:{prepared.source_sha256}"
        document_segments: list[CorpusSegment] = []
        for segment in prepared.parsed.segments:
            safe_compilation = compile_text(segment.text)
            safe_text = safe_compilation.redacted_text
            segment_id = f"{document_id}:segment:{segment.index}"
            corpus_segment = CorpusSegment(
                segment_id=segment_id,
                document_id=document_id,
                index=segment.index,
                kind=segment.kind.value,
                locator=segment.locator,
                context_label=segment.context_label,
                text=safe_text,
                text_sha256=hashlib.sha256(safe_text.encode("utf-8")).hexdigest(),
            )
            document_segments.append(corpus_segment)
            segments.append(corpus_segment)
            if len(segments) > active_limits.max_segments:
                raise LocalCorpusBuildError("local corpus segment limit exceeded")
            _add_deterministic_candidates(
                entities,
                safe_compilation.candidates,
                document_id=document_id,
                segment=corpus_segment,
                prefix_length=0,
            )

            labelled_text, prefix_length = _labelled_segment(corpus_segment)
            labelled_compilation = (
                safe_compilation if prefix_length == 0 else compile_text(labelled_text)
            )
            if prefix_length:
                _add_deterministic_candidates(
                    entities,
                    labelled_compilation.candidates,
                    document_id=document_id,
                    segment=corpus_segment,
                    prefix_length=prefix_length,
                )
            if semantic_enrichment_enabled:
                semantic = enrich_semantics(
                    labelled_compilation.redacted_text,
                    labelled_compilation.candidates,
                )
                _add_semantic_entities(
                    entities,
                    semantic.entities,
                    document_id=document_id,
                    segment=corpus_segment,
                    prefix_length=prefix_length,
                )

        segment_by_index = {segment.index: segment for segment in document_segments}
        for structured in prepared.structured_candidates:
            structured_segment = segment_by_index.get(structured.segment_index)
            if structured_segment is None:
                continue
            _add_deterministic_candidates(
                entities,
                (structured.candidate,),
                document_id=document_id,
                segment=structured_segment,
                prefix_length=0,
            )

        document_keys = {
            (accumulator.entity_type, accumulator.canonical_key)
            for accumulator in entities.items.values()
            if any(item.document_id == document_id for item in accumulator.occurrences)
        }
        for candidate in prepared.deterministic.candidates:
            key = _candidate_key(candidate.entity_type.value, candidate.canonical_value)
            if key in document_keys:
                continue
            for span in candidate.spans:
                _add_entity(
                    entities,
                    entity_type=candidate.entity_type.value,
                    canonical_value=candidate.canonical_value,
                    display_mask=candidate.display_mask,
                    sensitivity=candidate.sensitivity.value,
                    occurrence=CorpusEntityOccurrence(
                        document_id=document_id,
                        segment_id=None,
                        segment_index=None,
                        span_start=span.start,
                        span_end=span.end,
                        extractor=candidate.extractor,
                        confidence_micros=candidate.confidence_micros,
                    ),
                )

        documents.append(
            CorpusDocument(
                document_id=document_id,
                ordinal=ordinal,
                display_name=source.display_name,
                source_format=prepared.parsed.source_format.value,
                detected_media_type=prepared.detected_media_type,
                source_sha256=prepared.source_sha256,
                byte_count=prepared.byte_count,
                segment_ids=tuple(segment.segment_id for segment in document_segments),
                restricted_value_count=prepared.quarantine_count,
            )
        )
    final_documents = tuple(documents)
    final_entities = tuple(
        CorpusEntity(
            entity_id=corpus_entity_id(item.entity_type, item.canonical_key),
            entity_type=item.entity_type,
            canonical_value=item.canonical_value,
            display_mask=item.display_mask,
            sensitivity=item.sensitivity,
            occurrences=tuple(sorted(item.occurrences, key=_occurrence_sort_key)),
        )
        for item in sorted(
            entities.items.values(),
            key=lambda item: (
                min(_occurrence_sort_key(origin) for origin in item.occurrences),
                item.entity_type,
                item.canonical_key,
            ),
        )
    )
    return LocalCorpus(
        corpus_id=corpus_id(final_documents),
        documents=final_documents,
        segments=tuple(segments),
        entities=final_entities,
    )


def _bounded_inputs(
    document_inputs: Iterable[LocalCorpusDocumentInput],
    limits: LocalCorpusLimits,
) -> tuple[LocalCorpusDocumentInput, ...]:
    selected: list[LocalCorpusDocumentInput] = []
    total_bytes = 0
    for source in document_inputs:
        if not isinstance(source, LocalCorpusDocumentInput):
            raise LocalCorpusBuildError("local corpus input is invalid")
        if (
            not isinstance(source.display_name, str)
            or not isinstance(source.declared_media_type, str)
            or not isinstance(source.content, bytes)
        ):
            raise LocalCorpusBuildError("local corpus input is invalid")
        selected.append(source)
        if len(selected) > limits.max_documents:
            raise LocalCorpusBuildError("local corpus document limit exceeded")
        total_bytes += len(source.content)
        if total_bytes > limits.max_total_bytes:
            raise LocalCorpusBuildError("local corpus byte limit exceeded")
    if not selected:
        raise LocalCorpusBuildError("local corpus requires at least one document")
    return tuple(selected)


def _labelled_segment(segment: CorpusSegment) -> tuple[str, int]:
    if segment.context_label is None:
        return segment.text, 0
    prefix = f"{segment.context_label}: "
    return prefix + segment.text, len(prefix)


def _candidate_key(entity_type: str, canonical_value: str) -> tuple[str, str]:
    semantic_types = {"ALIAS", "EDUCATION", "LOCATION", "ORGANISATION", "PERSON", "PROJECT"}
    canonical_key = canonical_value.casefold() if entity_type in semantic_types else canonical_value
    return entity_type, canonical_key


def _add_deterministic_candidates(
    entities: _EntityState,
    candidates: tuple[CandidateEntity, ...],
    *,
    document_id: str,
    segment: CorpusSegment,
    prefix_length: int,
) -> None:
    for candidate in candidates:
        for span in candidate.spans:
            adjusted = _adjust_span(span, prefix_length, len(segment.text))
            if adjusted is None:
                continue
            _add_entity(
                entities,
                entity_type=candidate.entity_type.value,
                canonical_value=candidate.canonical_value,
                display_mask=candidate.display_mask,
                sensitivity=candidate.sensitivity.value,
                occurrence=CorpusEntityOccurrence(
                    document_id=document_id,
                    segment_id=segment.segment_id,
                    segment_index=segment.index,
                    span_start=adjusted.start,
                    span_end=adjusted.end,
                    extractor=candidate.extractor,
                    confidence_micros=candidate.confidence_micros,
                ),
            )


def _add_semantic_entities(
    entities: _EntityState,
    candidates: tuple[SemanticEntity, ...],
    *,
    document_id: str,
    segment: CorpusSegment,
    prefix_length: int,
) -> None:
    for candidate in candidates:
        adjusted = _adjust_span(candidate.span, prefix_length, len(segment.text))
        if adjusted is None:
            continue
        _add_entity(
            entities,
            entity_type=candidate.entity_type.value,
            canonical_value=candidate.canonical_value,
            display_mask=candidate.display_mask,
            sensitivity=candidate.sensitivity.value,
            occurrence=CorpusEntityOccurrence(
                document_id=document_id,
                segment_id=segment.segment_id,
                segment_index=segment.index,
                span_start=adjusted.start,
                span_end=adjusted.end,
                extractor=candidate.rule_code,
                confidence_micros=candidate.confidence_micros,
            ),
        )


def _adjust_span(span: SourceSpan, prefix_length: int, text_length: int) -> SourceSpan | None:
    start = span.start - prefix_length
    end = span.end - prefix_length
    if end <= 0 or start >= text_length:
        return None
    start = max(0, start)
    end = min(text_length, end)
    if end <= start:
        return None
    return SourceSpan(start, end)


def _add_entity(
    entities: _EntityState,
    *,
    entity_type: str,
    canonical_value: str,
    display_mask: str,
    sensitivity: str,
    occurrence: CorpusEntityOccurrence,
) -> None:
    key = _candidate_key(entity_type, canonical_value)
    accumulator = entities.items.get(key)
    if accumulator is None:
        if len(entities.items) >= entities.max_entities:
            raise LocalCorpusBuildError("local corpus entity limit exceeded")
        accumulator = _EntityAccumulator(
            entity_type=entity_type,
            canonical_value=canonical_value,
            canonical_key=key[1],
            display_mask=display_mask,
            sensitivity=sensitivity,
        )
        entities.items[key] = accumulator
    if _SENSITIVITY_RANK[sensitivity] > _SENSITIVITY_RANK[accumulator.sensitivity]:
        accumulator.sensitivity = sensitivity
        accumulator.display_mask = display_mask
    occurrence_key = (
        occurrence.document_id,
        occurrence.segment_id,
        occurrence.span_start,
        occurrence.span_end,
        occurrence.extractor,
    )
    if occurrence_key not in accumulator.occurrence_keys:
        if entities.occurrence_count >= entities.max_occurrences:
            raise LocalCorpusBuildError("local corpus entity occurrence limit exceeded")
        accumulator.occurrence_keys.add(occurrence_key)
        accumulator.occurrences.append(occurrence)
        entities.occurrence_count += 1


def _occurrence_sort_key(occurrence: CorpusEntityOccurrence) -> tuple[object, ...]:
    return (
        occurrence.document_id,
        occurrence.segment_index is None,
        occurrence.segment_index if occurrence.segment_index is not None else 0,
        occurrence.span_start,
        occurrence.span_end,
        occurrence.extractor,
    )
