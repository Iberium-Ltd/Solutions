"""Pure, bounded models for an ephemeral multi-document local corpus.

The corpus contains only safely parsed, restricted-value-redacted segments.  It
does not retain input bytes and has no persistence or network behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

_SEARCH_TOKEN = re.compile(r"[\w@.+:/-]+", re.UNICODE)
_MAX_QUERY_BYTES = 2_048
_MAX_QUERY_TERMS = 128
_HARD_MAX_SEARCH_RESULTS = 100
_HARD_MAX_PROJECTION_BYTES = 64 * 1024
_HARD_MAX_PROJECTION_SEGMENTS = 500


class CorpusQueryError(ValueError):
    """Stable failure for an invalid bounded corpus query."""


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    document_id: str
    ordinal: int
    display_name: str = field(repr=False)
    source_format: str
    detected_media_type: str
    source_sha256: str
    byte_count: int
    segment_ids: tuple[str, ...]
    restricted_value_count: int


@dataclass(frozen=True, slots=True)
class CorpusSegment:
    segment_id: str
    document_id: str
    index: int
    kind: str
    locator: str = field(repr=False)
    context_label: str | None = field(repr=False)
    text: str = field(repr=False)
    text_sha256: str


@dataclass(frozen=True, slots=True)
class CorpusEntityOccurrence:
    document_id: str
    segment_id: str | None
    segment_index: int | None
    span_start: int
    span_end: int
    extractor: str
    confidence_micros: int


@dataclass(frozen=True, slots=True)
class CorpusEntity:
    entity_id: str
    entity_type: str
    canonical_value: str = field(repr=False)
    display_mask: str = field(repr=False)
    sensitivity: str
    occurrences: tuple[CorpusEntityOccurrence, ...]


@dataclass(frozen=True, slots=True)
class CorpusSearchResult:
    segment_id: str
    document_id: str
    document_name: str = field(repr=False)
    segment_index: int
    locator: str = field(repr=False)
    score: int
    matched_terms: tuple[str, ...]
    excerpt: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CorpusAnalysisProjection:
    canonical_json: str = field(repr=False)
    references: tuple[str, ...]
    input_sha256: str
    included_documents: int
    included_segments: int
    included_entities: int
    available_documents: int
    available_segments: int
    available_entities: int
    restricted_values_redacted: int
    truncated: bool
    local_only: bool = True
    raw_sources_included: bool = False


@dataclass(frozen=True, slots=True)
class LocalCorpus:
    corpus_id: str
    documents: tuple[CorpusDocument, ...]
    segments: tuple[CorpusSegment, ...] = field(repr=False)
    entities: tuple[CorpusEntity, ...] = field(repr=False)
    raw_sources_retained: bool = False

    @property
    def restricted_value_count(self) -> int:
        return sum(document.restricted_value_count for document in self.documents)

    def search(self, query: str, *, limit: int = 50) -> tuple[CorpusSearchResult, ...]:
        """Search processed segment text with deterministic AND-term matching."""

        phrase, terms = _parse_query(query)
        if not 1 <= limit <= _HARD_MAX_SEARCH_RESULTS:
            raise CorpusQueryError("search result limit is outside its bounds")
        documents = {document.document_id: document for document in self.documents}
        ranked: list[tuple[int, int, int, CorpusSearchResult]] = []
        for segment in self.segments:
            document = documents[segment.document_id]
            searchable = _normalise_search_text(
                "\n".join(
                    part
                    for part in (
                        document.display_name,
                        segment.context_label,
                        segment.locator,
                        segment.text,
                    )
                    if part
                )
            )
            if any(term not in searchable for term in terms):
                continue
            occurrences = sum(searchable.count(term) for term in terms)
            score = 10_000 * len(terms) + min(occurrences, 9_999)
            if phrase in searchable:
                score += 1_000_000
            result = CorpusSearchResult(
                segment_id=segment.segment_id,
                document_id=segment.document_id,
                document_name=document.display_name,
                segment_index=segment.index,
                locator=segment.locator,
                score=score,
                matched_terms=terms,
                excerpt=_excerpt(segment.text, terms[0]),
            )
            ranked.append((-score, document.ordinal, segment.index, result))
        ranked.sort(key=lambda item: item[:3])
        return tuple(item[3] for item in ranked[:limit])


def build_corpus_analysis_projection(
    corpus: LocalCorpus,
    *,
    query: str | None = None,
    max_bytes: int = 60 * 1024,
    max_segments: int = 200,
) -> CorpusAnalysisProjection:
    """Build canonical, citation-ready JSON for a selected local model."""

    if not 4_096 <= max_bytes <= _HARD_MAX_PROJECTION_BYTES:
        raise CorpusQueryError("analysis projection byte limit is outside its bounds")
    if not 1 <= max_segments <= _HARD_MAX_PROJECTION_SEGMENTS:
        raise CorpusQueryError("analysis projection segment limit is outside its bounds")

    if query is None:
        selected_segments = corpus.segments[:max_segments]
        query_result_count = 0
    else:
        hits = corpus.search(query, limit=min(max_segments, 100))
        segment_by_id = {segment.segment_id: segment for segment in corpus.segments}
        selected_segments = tuple(
            segment_by_id[item.segment_id] for item in hits if item.segment_id in segment_by_id
        )
        query_result_count = len(hits)

    selected_segment_ids = {segment.segment_id for segment in selected_segments}
    selected_document_ids = {segment.document_id for segment in selected_segments}
    if not selected_document_ids:
        selected_document_ids = {document.document_id for document in corpus.documents}
    selected_documents = tuple(
        document for document in corpus.documents if document.document_id in selected_document_ids
    )
    selected_entities = tuple(
        entity
        for entity in corpus.entities
        if any(
            occurrence.segment_id in selected_segment_ids
            or (occurrence.segment_id is None and occurrence.document_id in selected_document_ids)
            for occurrence in entity.occurrences
        )
    )

    records: list[dict[str, object]] = []
    references: list[str] = []
    truncated = (
        len(selected_segments) < len(corpus.segments)
        if query is None
        else (
            query_result_count == min(max_segments, 100)
            and len(corpus.segments) > query_result_count
        )
    )
    metadata: dict[str, object] = {
        "available": {
            "documents": len(corpus.documents),
            "entities": len(corpus.entities),
            "segments": len(corpus.segments),
        },
        "corpusId": corpus.corpus_id,
        "queryApplied": query is not None,
        "restrictedValuesRedacted": corpus.restricted_value_count,
    }

    def add_record(record: dict[str, object]) -> bool:
        trial = [*records, record]
        envelope = {
            "metadata": metadata,
            "records": trial,
            "schema": "ariadne.local-corpus-analysis",
            "version": 1,
        }
        if len(_canonical(envelope).encode("utf-8")) > max_bytes:
            return False
        records.append(record)
        references.append(str(record["ref"]))
        return True

    for document in selected_documents:
        added = add_record(
            {
                "data": {
                    "byteCount": document.byte_count,
                    "displayName": _bounded(document.display_name, 255),
                    "format": document.source_format,
                    "mediaType": document.detected_media_type,
                    "sha256": document.source_sha256,
                },
                "kind": "DOCUMENT",
                "ref": document.document_id,
            }
        )
        truncated |= not added

    included_segment_ids: set[str] = set()
    for segment in selected_segments:
        text = _bounded(segment.text, 4_000)
        added = add_record(
            {
                "data": {
                    "contextLabel": segment.context_label,
                    "documentRef": segment.document_id,
                    "kind": segment.kind,
                    "locator": _bounded(segment.locator, 512),
                    "text": text,
                    "textSha256": segment.text_sha256,
                    "textTruncated": text != segment.text,
                },
                "kind": "DOCUMENT_SEGMENT",
                "ref": segment.segment_id,
            }
        )
        if added:
            included_segment_ids.add(segment.segment_id)
            truncated |= text != segment.text
        else:
            truncated = True

    included_entity_ids: set[str] = set()
    for entity in selected_entities:
        origins = tuple(
            occurrence.segment_id or occurrence.document_id
            for occurrence in entity.occurrences
            if occurrence.segment_id is None or occurrence.segment_id in included_segment_ids
        )
        origins = tuple(dict.fromkeys(origins))[:32]
        if not origins:
            continue
        added = add_record(
            {
                "data": {
                    "originRefs": origins,
                    "sensitivity": entity.sensitivity,
                    "type": entity.entity_type,
                    "value": entity.canonical_value,
                },
                "kind": "ENTITY",
                "ref": entity.entity_id,
            }
        )
        if added:
            included_entity_ids.add(entity.entity_id)
        else:
            truncated = True

    envelope = {
        "metadata": metadata,
        "records": records,
        "schema": "ariadne.local-corpus-analysis",
        "version": 1,
    }
    canonical_json = _canonical(envelope)
    kinds = [str(record["kind"]) for record in records]
    return CorpusAnalysisProjection(
        canonical_json=canonical_json,
        references=tuple(references),
        input_sha256=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        included_documents=kinds.count("DOCUMENT"),
        included_segments=len(included_segment_ids),
        included_entities=len(included_entity_ids),
        available_documents=len(corpus.documents),
        available_segments=len(corpus.segments),
        available_entities=len(corpus.entities),
        restricted_values_redacted=corpus.restricted_value_count,
        truncated=truncated,
    )


def corpus_entity_id(entity_type: str, canonical_key: str) -> str:
    """Derive a stable corpus entity id so repeated local processing remains deterministic."""

    digest = hashlib.sha256(f"{entity_type}\0{canonical_key}".encode()).hexdigest()
    return f"corpus-entity:{digest}"


def corpus_id(documents: tuple[CorpusDocument, ...]) -> str:
    """Derive a stable corpus id so repeated local processing remains deterministic."""

    material = "\n".join(
        "\0".join(
            (
                str(document.ordinal),
                document.display_name,
                document.source_format,
                document.detected_media_type,
                document.source_sha256,
            )
        )
        for document in documents
    )
    return f"corpus:{hashlib.sha256(material.encode()).hexdigest()}"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _bounded(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[: maximum - 1].rstrip() + "…"


def _normalise_search_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _parse_query(query: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(query, str) or not query.strip():
        raise CorpusQueryError("search query must not be empty")
    try:
        query_bytes = query.encode()
    except UnicodeEncodeError:
        raise CorpusQueryError("search query is outside its bounds") from None
    if len(query_bytes) > _MAX_QUERY_BYTES or any(
        unicodedata.category(character) in {"Cc", "Cs"} for character in query
    ):
        raise CorpusQueryError("search query is outside its bounds")
    phrase = _normalise_search_text(query)
    terms = tuple(dict.fromkeys(_SEARCH_TOKEN.findall(phrase)))
    if not terms:
        raise CorpusQueryError("search query has no searchable terms")
    if len(terms) > _MAX_QUERY_TERMS:
        raise CorpusQueryError("search query has too many terms")
    return phrase, terms


def _excerpt(text: str, first_term: str, maximum: int = 320) -> str:
    if len(text) <= maximum:
        return text
    position = text.casefold().find(first_term)
    if position < 0:
        position = 0
    start = max(0, position - maximum // 3)
    end = min(len(text), start + maximum)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
