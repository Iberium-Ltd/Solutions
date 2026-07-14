"""Ephemeral, source-grounded reasoning across a bounded local document corpus."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import and_, select

from ariadne_core.api.local_corpus_ai_schemas import (
    LocalCorpusAIConfidence,
    LocalCorpusAIConnection,
    LocalCorpusAIContentOrigin,
    LocalCorpusAICounts,
    LocalCorpusAIExecution,
    LocalCorpusAIFact,
    LocalCorpusAIFallbackReason,
    LocalCorpusAINextStep,
    LocalCorpusAIReferenceKind,
    LocalCorpusAIRequest,
    LocalCorpusAIResult,
    LocalCorpusAIReviewNote,
    LocalCorpusAISection,
    LocalCorpusAISourceCatalogEntry,
    LocalCorpusAISourcePointer,
    LocalCorpusAITask,
    LocalCorpusAITextLabel,
)
from ariadne_core.application.local_corpus import (
    LocalCorpusDocumentInput,
    build_local_corpus,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.local_corpus import CorpusEntity, CorpusSegment, LocalCorpus
from ariadne_core.domain.settings import VaultSettings
from ariadne_core.infrastructure.db.models import profiles
from ariadne_core.infrastructure.db.repositories import SettingsRepository
from ariadne_core.local_ai import (
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpTransport,
    LocalAIProvider,
    LocalAIWorkspaceAnalysis,
    OpenAIResponsesClient,
    OpenAIResponsesConfig,
    WorkspaceAnalysisRequest,
)
from ariadne_core.local_ai import LocalAIWorkspaceTask as ClientWorkspaceTask

_ENGINE_VERSION: Literal["1"] = "1"
_MAX_PROJECTION_BYTES = 58 * 1024
_MAX_REASONING_PROJECTION_BYTES = 40 * 1024
_MAX_REASONING_SEGMENTS = 64
_MAX_PRIORITY_SHARED_ENTITIES = 24
_MAX_SEGMENT_TEXT = 1_200
_MAX_ENTITY_ORIGINS = 32
_WORD = re.compile(r"[\w@.+:/-]{2,}", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "are",
        "does",
        "for",
        "from",
        "have",
        "how",
        "into",
        "not",
        "that",
        "the",
        "their",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)
_POTENTIALLY_EXCLUSIVE_LABELS = frozenset(
    {
        "city",
        "country",
        "employer",
        "handle",
        "location",
        "organisation",
        "organization",
        "role",
        "status",
        "title",
        "username",
    }
)


class LocalCorpusAIUnavailable(RuntimeError):
    """The persisted local-model selection cannot currently be read."""


class LocalCorpusAIConflict(RuntimeError):
    """The request does not match the explicit persisted local-model selection."""


class LocalCorpusAINotFound(LookupError):
    """The requested profile is not present in the unlocked vault."""


@dataclass(frozen=True, slots=True)
class _Source:
    document_id: str
    document_name: str = field(repr=False)
    segment_id: str
    segment_index: int
    locator: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Projection:
    canonical_json: str = field(repr=False)
    references: tuple[str, ...]
    model_references: tuple[str, ...]
    model_to_source_ref: dict[str, str] = field(repr=False)
    sources_by_ref: dict[str, tuple[_Source, ...]] = field(repr=False)
    segments: tuple[CorpusSegment, ...] = field(repr=False)
    entities: tuple[CorpusEntity, ...] = field(repr=False)
    included_counts: LocalCorpusAICounts
    available_counts: LocalCorpusAICounts
    truncated: bool


@dataclass(frozen=True, slots=True)
class _AnalysisContent:
    title: str
    draft_summary: str = field(repr=False)
    sections: tuple[LocalCorpusAISection, ...]
    facts: tuple[LocalCorpusAIFact, ...]
    connections: tuple[LocalCorpusAIConnection, ...]
    next_steps: tuple[LocalCorpusAINextStep, ...]
    unanswered: str | None = field(repr=False)
    uncertainties: tuple[LocalCorpusAIReviewNote, ...]


class LocalCorpusAICoordinator:
    """Run deterministic, loopback, or ephemeral OpenAI analysis without persistence."""

    def __init__(
        self,
        vault: VaultManager,
        *,
        transport: LocalAIHttpTransport | None = None,
    ) -> None:
        self._vault = vault
        self._transport = transport

    def analyze(self, body: LocalCorpusAIRequest) -> LocalCorpusAIResult:
        self._require_profile_scope(body.profile_id)
        manifest_sha256 = body.input_manifest_sha256
        corpus = build_local_corpus(
            tuple(
                LocalCorpusDocumentInput(
                    display_name=document.display_name,
                    declared_media_type=document.declared_media_type.value,
                    content=document.decoded_content(),
                )
                for document in body.documents
            ),
            semantic_enrichment_enabled=body.semantic_enrichment_enabled,
        )
        projection = _build_projection(
            corpus,
            max_segments=body.max_segments,
            task=body.task,
        )
        deterministic = _deterministic_analysis(body, corpus, projection)
        content = deterministic
        execution = LocalCorpusAIExecution.DETERMINISTIC
        fallback_reason: LocalCorpusAIFallbackReason | None = None
        provider = None
        model_id = None
        external_network_used = False
        local_only = True

        if body.execution is LocalCorpusAIExecution.LOCAL_MODEL:
            settings = self._selected_model_settings(body)
            try:
                model_result = LocalAIClient(
                    LocalAIConfig(
                        enabled=True,
                        provider=settings.local_ai_provider,
                        endpoint=settings.local_ai_endpoint,
                        timeout_seconds=98,
                        max_output_tokens=(
                            2_048
                            if body.task
                            in {
                                LocalCorpusAITask.CONNECTIONS,
                                LocalCorpusAITask.GAP_ANALYSIS,
                            }
                            else 3_072
                        ),
                    ),
                    transport=self._transport,
                ).analyze_workspace(
                    WorkspaceAnalysisRequest(
                        task=ClientWorkspaceTask(body.task.value),
                        question=body.question,
                        profile_data_json=projection.canonical_json,
                        allowed_reference_ids=projection.model_references,
                    ),
                    model_id=body.model_id or "",
                )
                content = _model_analysis(
                    body,
                    corpus,
                    projection,
                    model_result,
                    deterministic,
                    origin=LocalCorpusAIContentOrigin.LOCAL_MODEL,
                )
            except LocalAIError as error:
                fallback_reason = _fallback_reason(error.code)
            else:
                execution = LocalCorpusAIExecution.LOCAL_MODEL
                provider = model_result.provider
                model_id = model_result.model_id
        elif body.execution is LocalCorpusAIExecution.OPENAI_RESPONSES:
            api_key = body.openai_api_key
            if api_key is None or body.model_id is None:
                raise LocalCorpusAIConflict(
                    "OpenAI corpus execution requires an ephemeral key and model"
                )
            provider = LocalAIProvider.OPENAI_RESPONSES
            model_id = body.model_id
            external_network_used = True
            local_only = False
            try:
                model_result = OpenAIResponsesClient(
                    OpenAIResponsesConfig(
                        api_key=api_key,
                        timeout_seconds=98,
                        max_output_tokens=4_096,
                    ),
                    transport=self._transport,
                ).analyze_workspace(
                    WorkspaceAnalysisRequest(
                        task=ClientWorkspaceTask(body.task.value),
                        question=body.question,
                        profile_data_json=projection.canonical_json,
                        allowed_reference_ids=projection.model_references,
                    ),
                    model_id=body.model_id,
                )
                content = _model_analysis(
                    body,
                    corpus,
                    projection,
                    model_result,
                    deterministic,
                    origin=LocalCorpusAIContentOrigin.OPENAI_RESPONSES,
                )
            except LocalAIError as error:
                fallback_reason = _fallback_reason(error.code)
            else:
                execution = LocalCorpusAIExecution.OPENAI_RESPONSES

        source_catalog = _source_catalog(projection, _cited_references(content))
        return LocalCorpusAIResult(
            profile_id=body.profile_id,
            corpus_id=corpus.corpus_id,
            input_manifest_sha256=manifest_sha256,
            input_sha256=hashlib.sha256(projection.canonical_json.encode()).hexdigest(),
            task=body.task,
            requested_execution=body.execution,
            execution_mode=execution,
            fallback_reason=fallback_reason,
            provider=provider,
            model_id=model_id,
            engine_version=_ENGINE_VERSION,
            title=content.title,
            draft_summary=content.draft_summary,
            narrative_label="DRAFT_SUMMARY_NOT_A_FACT",
            sections=content.sections,
            facts=content.facts,
            connections=content.connections,
            next_steps=content.next_steps,
            unanswered=content.unanswered,
            uncertainties=content.uncertainties,
            source_catalog=source_catalog,
            included_counts=projection.included_counts,
            available_counts=projection.available_counts,
            projection_truncated=projection.truncated,
            restricted_values_redacted=corpus.restricted_value_count,
            local_only=local_only,
            external_network_used=external_network_used,
            raw_sources_retained=False,
            persisted=False,
            review_only=True,
            human_review_required=True,
        )

    def _require_profile_scope(self, profile_id: str) -> None:
        if not self._vault.is_unlocked:
            raise LocalCorpusAIUnavailable("local corpus AI analysis requires an unlocked vault")
        with self._vault.engine.connect() as connection:
            exists = connection.execute(
                select(profiles.c.id).where(
                    and_(
                        profiles.c.vault_id == self._vault.manifest.vault_id,
                        profiles.c.id == profile_id,
                    )
                )
            ).scalar_one_or_none()
        if exists is None:
            raise LocalCorpusAINotFound("local corpus AI profile is unavailable")

    def _selected_model_settings(self, body: LocalCorpusAIRequest) -> VaultSettings:
        settings = SettingsRepository(self._vault.engine).get(self._vault.manifest.vault_id).values
        if (
            not settings.local_ai_enabled
            or settings.local_ai_selected_model is None
            or body.model_id != settings.local_ai_selected_model
        ):
            raise LocalCorpusAIConflict(
                "local corpus AI model must match the enabled persisted selection"
            )
        return settings


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _bounded(value: str, maximum: int) -> str:
    text = value.strip()
    return text if len(text) <= maximum else text[: maximum - 1].rstrip() + "…"


def _build_projection(
    corpus: LocalCorpus,
    *,
    max_segments: int,
    task: LocalCorpusAITask,
) -> _Projection:
    documents = {document.document_id: document for document in corpus.documents}
    segments_by_id = {segment.segment_id: segment for segment in corpus.segments}
    selected_segments: list[CorpusSegment] = []
    selected_segment_ids: set[str] = set()
    selected_entities: list[CorpusEntity] = []
    selected_entity_ids: set[str] = set()
    records: list[dict[str, object]] = []
    references: list[str] = []
    model_references: list[str] = []
    model_to_source_ref: dict[str, str] = {}
    model_ref_by_source: dict[str, str] = {}
    sources_by_ref: dict[str, tuple[_Source, ...]] = {}
    text_truncated = False
    reasoning_task = task in {
        LocalCorpusAITask.CONNECTIONS,
        LocalCorpusAITask.GAP_ANALYSIS,
    }
    projection_byte_limit = (
        _MAX_REASONING_PROJECTION_BYTES if reasoning_task else _MAX_PROJECTION_BYTES
    )
    segment_limit = min(
        max_segments,
        _MAX_REASONING_SEGMENTS if reasoning_task else max_segments,
    )

    metadata: dict[str, object] = {
        "available": {
            "documents": len(corpus.documents),
            "entities": len(corpus.entities),
            "segments": len(corpus.segments),
        },
        "connectionPolicy": (
            "Only connect two segment refs when one shared ENTITY originRefs list contains both."
        ),
        "corpusId": corpus.corpus_id,
        "provenancePolicy": "Every factual output must cite a supplied segment or entity ref.",
        "restrictedValuesRedacted": corpus.restricted_value_count,
        "selectionPolicy": ("Cross-document entity origins are reserved before general context."),
    }

    def add_record(
        record: dict[str, object],
        *,
        model_ref: str,
        source_ref: str,
    ) -> bool:
        envelope = {
            "metadata": metadata,
            "records": [*records, record],
            "schema": "ariadne.local-corpus-ai-input",
            "version": 1,
        }
        if len(_canonical(envelope).encode()) > projection_byte_limit:
            return False
        records.append(record)
        references.append(source_ref)
        model_references.append(model_ref)
        model_to_source_ref[model_ref] = source_ref
        model_ref_by_source[source_ref] = model_ref
        return True

    def add_segment(segment: CorpusSegment) -> bool:
        nonlocal text_truncated
        if segment.segment_id in selected_segment_ids:
            return True
        if len(selected_segments) >= segment_limit:
            return False
        document = documents[segment.document_id]
        text = _bounded(segment.text, _MAX_SEGMENT_TEXT)
        model_ref = f"segment:s{len(selected_segments) + 1:04d}"
        record: dict[str, object] = {
            "data": {
                "contextLabel": segment.context_label,
                "documentId": segment.document_id,
                "documentName": _bounded(document.display_name, 255),
                "index": segment.index,
                "kind": segment.kind,
                "locator": _bounded(segment.locator, 512),
                "text": text,
                "textSha256": segment.text_sha256,
                "textTruncated": text != segment.text,
            },
            "kind": "DOCUMENT_SEGMENT",
            "ref": model_ref,
        }
        if not add_record(record, model_ref=model_ref, source_ref=segment.segment_id):
            return False
        text_truncated |= text != segment.text
        selected_segments.append(segment)
        selected_segment_ids.add(segment.segment_id)
        sources_by_ref[segment.segment_id] = (
            _Source(
                document_id=segment.document_id,
                document_name=document.display_name,
                segment_id=segment.segment_id,
                segment_index=segment.index,
                locator=segment.locator,
            ),
        )
        return True

    def add_entity(entity: CorpusEntity) -> bool:
        if entity.entity_id in selected_entity_ids:
            return True
        origins = tuple(
            dict.fromkeys(
                occurrence.segment_id
                for occurrence in entity.occurrences
                if occurrence.segment_id in selected_segment_ids
            )
        )[:_MAX_ENTITY_ORIGINS]
        if not origins:
            return False
        model_ref = f"entity:e{len(selected_entities) + 1:04d}"
        record: dict[str, object] = {
            "data": {
                "originRefs": tuple(model_ref_by_source[origin] for origin in origins),
                "sensitivity": entity.sensitivity,
                "type": entity.entity_type,
                "value": entity.canonical_value,
            },
            "kind": "ENTITY",
            "ref": model_ref,
        }
        if not add_record(record, model_ref=model_ref, source_ref=entity.entity_id):
            return False
        selected_entities.append(entity)
        selected_entity_ids.add(entity.entity_id)
        sources_by_ref[entity.entity_id] = tuple(
            sources_by_ref[origin][0] for origin in origins if origin in sources_by_ref
        )
        return True

    priority_limit = _MAX_PRIORITY_SHARED_ENTITIES if reasoning_task else 8
    for entity in _shared_entities(corpus.entities)[:priority_limit]:
        seed_segments = _cross_document_seed_segments(entity, segments_by_id)
        if len(seed_segments) < 2:
            continue
        if not all(add_segment(segment) for segment in seed_segments):
            break
        if not add_entity(entity):
            break

    for segment in _fair_segment_order(corpus):
        if len(selected_segments) >= segment_limit:
            break
        if not add_segment(segment):
            break

    for entity in corpus.entities:
        if entity.entity_id in selected_entity_ids:
            continue
        if any(
            occurrence.segment_id in selected_segment_ids for occurrence in entity.occurrences
        ) and not add_entity(entity):
            break

    envelope = {
        "metadata": metadata,
        "records": records,
        "schema": "ariadne.local-corpus-ai-input",
        "version": 1,
    }
    available_shared = _shared_entity_count(corpus.entities, None)
    included_shared = _shared_entity_count(tuple(selected_entities), selected_segment_ids)
    included_documents = len({segment.document_id for segment in selected_segments})
    return _Projection(
        canonical_json=_canonical(envelope),
        references=tuple(references),
        model_references=tuple(model_references),
        model_to_source_ref=model_to_source_ref,
        sources_by_ref=sources_by_ref,
        segments=tuple(selected_segments),
        entities=tuple(selected_entities),
        included_counts=LocalCorpusAICounts(
            documents=included_documents,
            segments=len(selected_segments),
            entities=len(selected_entities),
            shared_entities=included_shared,
        ),
        available_counts=LocalCorpusAICounts(
            documents=len(corpus.documents),
            segments=len(corpus.segments),
            entities=len(corpus.entities),
            shared_entities=available_shared,
        ),
        truncated=(
            len(selected_segments) < len(corpus.segments)
            or len(selected_entities)
            < sum(
                any(item.segment_id in selected_segment_ids for item in entity.occurrences)
                for entity in corpus.entities
            )
            or text_truncated
        ),
    )


def _shared_entities(entities: tuple[CorpusEntity, ...]) -> tuple[CorpusEntity, ...]:
    return tuple(
        entity
        for entity in entities
        if len(
            {
                occurrence.document_id
                for occurrence in entity.occurrences
                if occurrence.segment_id is not None
            }
        )
        >= 2
    )


def _cross_document_seed_segments(
    entity: CorpusEntity,
    segments_by_id: dict[str, CorpusSegment],
) -> tuple[CorpusSegment, ...]:
    by_document: dict[str, list[CorpusSegment]] = defaultdict(list)
    for occurrence in entity.occurrences:
        if occurrence.segment_id is None:
            continue
        segment = segments_by_id.get(occurrence.segment_id)
        if segment is not None and segment.document_id == occurrence.document_id:
            by_document[occurrence.document_id].append(segment)
    selected = [
        min(items, key=lambda item: (len(item.text.encode()), item.index))
        for items in by_document.values()
    ]
    return tuple(selected[:2])


def _fair_segment_order(corpus: LocalCorpus) -> tuple[CorpusSegment, ...]:
    """Interleave documents so a bounded projection cannot starve later sources."""

    by_document: dict[str, list[CorpusSegment]] = {
        document.document_id: [] for document in corpus.documents
    }
    for segment in corpus.segments:
        by_document[segment.document_id].append(segment)
    maximum = max((len(items) for items in by_document.values()), default=0)
    ordered: list[CorpusSegment] = []
    for index in range(maximum):
        for document in corpus.documents:
            items = by_document[document.document_id]
            if index < len(items):
                ordered.append(items[index])
    return tuple(ordered)


def _shared_entity_count(
    entities: tuple[CorpusEntity, ...],
    allowed_segments: set[str] | None,
) -> int:
    return sum(
        len(
            {
                occurrence.document_id
                for occurrence in entity.occurrences
                if occurrence.segment_id is not None
                and (allowed_segments is None or occurrence.segment_id in allowed_segments)
            }
        )
        >= 2
        for entity in entities
    )


def _base_uncertainties(
    corpus: LocalCorpus,
    projection: _Projection,
) -> tuple[LocalCorpusAIReviewNote, ...]:
    items = [
        LocalCorpusAIReviewNote(
            text=(
                "A shared identifier is a correlation signal, not proof that two records describe "
                "the same person, account, ownership, or time period."
            ),
            label=LocalCorpusAITextLabel.LIMITATION,
            origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
            evidence_refs=(),
        )
    ]
    if projection.truncated:
        items.append(
            LocalCorpusAIReviewNote(
                text="The bounded analysis projection omitted or shortened available content.",
                label=LocalCorpusAITextLabel.LIMITATION,
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                evidence_refs=(),
            )
        )
    if corpus.restricted_value_count:
        restricted_refs = tuple(
            projection.sources_by_ref[segment.segment_id][0].segment_id
            for segment in projection.segments
            if next(
                document
                for document in corpus.documents
                if document.document_id == segment.document_id
            ).restricted_value_count
        )
        items.append(
            LocalCorpusAIReviewNote(
                text="Restricted values were redacted before any reasoning step.",
                label=LocalCorpusAITextLabel.LIMITATION,
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                evidence_refs=tuple(dict.fromkeys(restricted_refs))[:8],
            )
        )
    return tuple(items)


def _segment_fact(segment: CorpusSegment) -> LocalCorpusAIFact:
    text = _bounded(segment.text, 520)
    return LocalCorpusAIFact(
        statement=(
            f"Cited segment text: {text}"
            if text
            else "Cited segment content was fully redacted before analysis."
        ),
        evidence_refs=(segment.segment_id,),
        confidence=LocalCorpusAIConfidence.HIGH,
        origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
    )


def _document_sections(
    corpus: LocalCorpus, projection: _Projection
) -> tuple[LocalCorpusAISection, ...]:
    by_document: dict[str, list[CorpusSegment]] = defaultdict(list)
    for segment in projection.segments:
        by_document[segment.document_id].append(segment)
    sections: list[LocalCorpusAISection] = []
    for document in corpus.documents:
        segments = by_document.get(document.document_id, [])
        if not segments:
            continue
        sections.append(
            LocalCorpusAISection(
                heading=_bounded(document.display_name, 96),
                items=tuple(
                    LocalCorpusAIReviewNote(
                        text=(
                            f"{segment.locator} · {_bounded(segment.text, 440)}"
                            if segment.text.strip()
                            else f"{segment.locator} · content fully redacted"
                        ),
                        label=LocalCorpusAITextLabel.ORGANIZATION,
                        origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                        evidence_refs=(segment.segment_id,),
                    )
                    for segment in segments[:12]
                ),
            )
        )
        if len(sections) == 8:
            break
    return tuple(sections)


def _summary_sections(
    corpus: LocalCorpus, projection: _Projection
) -> tuple[LocalCorpusAISection, ...]:
    document_items: list[LocalCorpusAIReviewNote] = []
    for document in corpus.documents:
        segments = [
            segment
            for segment in projection.segments
            if segment.document_id == document.document_id
        ]
        if not segments:
            continue
        document_items.append(
            LocalCorpusAIReviewNote(
                text=(
                    f"{document.display_name}: {len(segments)} cited segment(s), "
                    f"format {document.source_format}."
                ),
                label=LocalCorpusAITextLabel.CITED_SUMMARY,
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                evidence_refs=(segments[0].segment_id,),
            )
        )
    sections: list[LocalCorpusAISection] = []
    if document_items:
        sections.append(
            LocalCorpusAISection(heading="Document coverage", items=tuple(document_items[:12]))
        )
    by_type: dict[str, list[CorpusEntity]] = defaultdict(list)
    for entity in projection.entities:
        by_type[entity.entity_type].append(entity)
    entity_items: list[LocalCorpusAIReviewNote] = []
    for entity_type, entities in sorted(by_type.items()):
        references = tuple(
            dict.fromkeys(
                source.segment_id
                for entity in entities
                for source in projection.sources_by_ref[entity.entity_id]
            )
        )[:8]
        entity_items.append(
            LocalCorpusAIReviewNote(
                text=f"{entity_type}: {len(entities)} deduplicated signal(s).",
                label=LocalCorpusAITextLabel.CITED_SUMMARY,
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                evidence_refs=references,
            )
        )
    if entity_items:
        sections.append(
            LocalCorpusAISection(heading="Entity signals", items=tuple(entity_items[:12]))
        )
    return tuple(sections)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.casefold() for token in _WORD.findall(value) if token.casefold() not in _STOP_WORDS
    )


def _question_matches(
    question: str,
    projection: _Projection,
) -> tuple[CorpusSegment, ...]:
    question_tokens = _tokens(question)
    ranked = sorted(
        (
            (len(question_tokens & _tokens(segment.text)), index, segment)
            for index, segment in enumerate(projection.segments)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return tuple(item[2] for item in ranked if item[0] > 0)[:8]


def _normal_label(value: str) -> str:
    return "_".join(_WORD.findall(value.casefold()))


def _potential_conflict_refs(
    projection: _Projection,
    document_ids: frozenset[str],
) -> tuple[str, ...]:
    by_label: dict[str, list[CorpusSegment]] = defaultdict(list)
    for segment in projection.segments:
        if segment.document_id not in document_ids or segment.context_label is None:
            continue
        label = _normal_label(segment.context_label)
        if label in _POTENTIALLY_EXCLUSIVE_LABELS:
            by_label[label].append(segment)
    conflicts: list[str] = []
    for segments in by_label.values():
        values = {" ".join(segment.text.casefold().split()) for segment in segments}
        source_documents = {segment.document_id for segment in segments}
        if len(values) > 1 and len(source_documents) > 1:
            conflicts.extend(segment.segment_id for segment in segments)
    return tuple(dict.fromkeys(conflicts))[:8]


def _connection_candidates(
    projection: _Projection,
) -> tuple[LocalCorpusAIConnection, ...]:
    candidates: list[LocalCorpusAIConnection] = []
    for entity in projection.entities:
        sources = projection.sources_by_ref.get(entity.entity_id, ())
        by_document: dict[str, list[_Source]] = defaultdict(list)
        for source in sources:
            by_document[source.document_id].append(source)
        ordered_documents = list(by_document)
        for left_index, left_document in enumerate(ordered_documents):
            for right_document in ordered_documents[left_index + 1 :]:
                left = by_document[left_document][0]
                right = by_document[right_document][0]
                contradictions = _potential_conflict_refs(
                    projection,
                    frozenset({left_document, right_document}),
                )
                relationship = _bounded(f"SHARED_{entity.entity_type}_SIGNAL", 96)
                candidates.append(
                    LocalCorpusAIConnection(
                        from_ref=left.segment_id,
                        to_ref=right.segment_id,
                        shared_entity_refs=(entity.entity_id,),
                        relationship=relationship,
                        supporting_refs=(left.segment_id, right.segment_id, entity.entity_id),
                        contradiction_refs=contradictions,
                        confidence=(
                            LocalCorpusAIConfidence.LOW
                            if contradictions
                            else LocalCorpusAIConfidence.MEDIUM
                        ),
                        origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                        rationale=(
                            "One deduplicated entity signal has exact occurrences in both cited "
                            "document segments. This is correlation, not identity proof."
                        ),
                        verification_suggestion=(
                            "Compare the cited segments, their dates and independent provenance "
                            "before confirming any relationship."
                        ),
                    )
                )
                if len(candidates) == 16:
                    return tuple(candidates)
    return tuple(candidates)


def _gap_steps(
    corpus: LocalCorpus,
    projection: _Projection,
    connections: tuple[LocalCorpusAIConnection, ...],
) -> tuple[LocalCorpusAINextStep, ...]:
    steps: list[LocalCorpusAINextStep] = []
    for connection in connections:
        if not connection.contradiction_refs:
            continue
        steps.append(
            LocalCorpusAINextStep(
                priority=1,
                suggestion="Reconcile the differing structured values before confirming this link.",
                rationale=(
                    "The shared signal spans documents whose same-labelled structured fields "
                    "contain different values; time or context may explain the difference."
                ),
                supporting_refs=tuple(
                    dict.fromkeys((*connection.shared_entity_refs, *connection.contradiction_refs))
                )[:8],
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
            )
        )

    for entity in projection.entities:
        sources = projection.sources_by_ref.get(entity.entity_id, ())
        document_ids = {source.document_id for source in sources}
        if len(document_ids) != 1:
            continue
        steps.append(
            LocalCorpusAINextStep(
                priority=2,
                suggestion=f"Seek independent corroboration for this {entity.entity_type} signal.",
                rationale=(
                    "The deduplicated signal currently appears in only one supplied document."
                ),
                supporting_refs=(entity.entity_id, sources[0].segment_id),
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
            )
        )
        if len(steps) >= 16:
            break

    entity_documents = {
        source.document_id
        for entity in projection.entities
        for source in projection.sources_by_ref.get(entity.entity_id, ())
    }
    for document in corpus.documents:
        if document.document_id in entity_documents:
            continue
        segment = next(
            (item for item in projection.segments if item.document_id == document.document_id),
            None,
        )
        if segment is None:
            continue
        steps.append(
            LocalCorpusAINextStep(
                priority=3,
                suggestion="Review this document for names or identifiers the extractor missed.",
                rationale="No exact, citable entity signal was extracted from the cited document.",
                supporting_refs=(segment.segment_id,),
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
            )
        )
        if len(steps) >= 16:
            break

    if len(corpus.documents) == 1 and projection.segments and len(steps) < 16:
        steps.append(
            LocalCorpusAINextStep(
                priority=2,
                suggestion="Compare this material with an independent, authorized source.",
                rationale="A single supplied document cannot provide cross-source corroboration.",
                supporting_refs=(projection.segments[0].segment_id,),
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
            )
        )
    return tuple(sorted(steps, key=lambda item: item.priority)[:16])


def _deterministic_analysis(
    body: LocalCorpusAIRequest,
    corpus: LocalCorpus,
    projection: _Projection,
) -> _AnalysisContent:
    uncertainties = list(_base_uncertainties(corpus, projection))
    facts = tuple(_segment_fact(segment) for segment in projection.segments[:12])
    if body.task is LocalCorpusAITask.QUESTION:
        matches = _question_matches(body.question or "", projection)
        if not matches:
            return _AnalysisContent(
                title="No grounded answer found",
                draft_summary="No selected segment shared enough terms with the question.",
                sections=(),
                facts=(),
                connections=(),
                next_steps=(),
                unanswered="The supplied documents do not support a deterministic answer.",
                uncertainties=tuple(uncertainties),
            )
        return _AnalysisContent(
            title="Grounded corpus answer",
            draft_summary=f"Found {len(matches)} cited segment(s) relevant to the question.",
            sections=(
                LocalCorpusAISection(
                    heading="Relevant cited segments",
                    items=tuple(
                        LocalCorpusAIReviewNote(
                            text=_bounded(segment.text, 500),
                            label=LocalCorpusAITextLabel.CITED_SUMMARY,
                            origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                            evidence_refs=(segment.segment_id,),
                        )
                        for segment in matches
                    ),
                ),
            ),
            facts=tuple(_segment_fact(segment) for segment in matches),
            connections=(),
            next_steps=(),
            unanswered=None,
            uncertainties=tuple(uncertainties),
        )

    connections = _connection_candidates(projection)
    if body.task is LocalCorpusAITask.CONNECTIONS:
        for connection in connections:
            if connection.contradiction_refs:
                uncertainties.append(
                    LocalCorpusAIReviewNote(
                        text=(
                            "Same-labelled fields differ across these connected documents; this "
                            "may be a contradiction, a change over time, or different context."
                        ),
                        label=LocalCorpusAITextLabel.HYPOTHESIS,
                        origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                        evidence_refs=connection.contradiction_refs,
                    )
                )
        return _AnalysisContent(
            title="Cross-document connection candidates",
            draft_summary=(
                f"Found {len(connections)} review-only candidate connection(s) from shared, "
                "deduplicated entity signals."
            ),
            sections=(
                ()
                if not connections
                else (
                    LocalCorpusAISection(
                        heading="Grounded candidates",
                        items=tuple(
                            LocalCorpusAIReviewNote(
                                text=(
                                    f"{item.relationship}: compare the two cited source segments."
                                ),
                                label=LocalCorpusAITextLabel.CITED_SUMMARY,
                                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                                evidence_refs=item.supporting_refs,
                            )
                            for item in connections[:12]
                        ),
                    ),
                )
            ),
            facts=tuple(
                LocalCorpusAIFact(
                    statement=(
                        "A deduplicated entity signal occurs in both cited document segments."
                    ),
                    evidence_refs=item.supporting_refs,
                    confidence=item.confidence,
                    origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                )
                for item in connections[:12]
            ),
            connections=connections,
            next_steps=(),
            unanswered=(
                None
                if connections
                else "No entity with exact segment provenance appeared in multiple documents."
            ),
            uncertainties=tuple(uncertainties[:12]),
        )

    if body.task is LocalCorpusAITask.GAP_ANALYSIS:
        steps = _gap_steps(corpus, projection, connections)
        return _AnalysisContent(
            title="Evidence-gap and verification suggestions",
            draft_summary=(
                f"Produced {len(steps)} cited review suggestion(s); no search or change was run."
            ),
            sections=(
                ()
                if not steps
                else (
                    LocalCorpusAISection(
                        heading="Prioritized verification",
                        items=tuple(
                            LocalCorpusAIReviewNote(
                                text=f"P{item.priority} · {item.suggestion}",
                                label=LocalCorpusAITextLabel.CITED_SUMMARY,
                                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                                evidence_refs=item.supporting_refs,
                            )
                            for item in steps[:12]
                        ),
                    ),
                )
            ),
            facts=(),
            connections=tuple(item for item in connections if item.contradiction_refs),
            next_steps=steps,
            unanswered=None if steps else "No bounded evidence gap was identified.",
            uncertainties=tuple(uncertainties),
        )

    if body.task is LocalCorpusAITask.ORGANIZE:
        sections = _document_sections(corpus, projection)
        return _AnalysisContent(
            title="Organized local corpus",
            draft_summary=(
                f"Organized {len(projection.segments)} cited segment(s) from "
                f"{projection.included_counts.documents} document(s)."
            ),
            sections=sections,
            facts=facts,
            connections=(),
            next_steps=(),
            unanswered=None,
            uncertainties=tuple(uncertainties),
        )

    by_type = Counter(entity.entity_type for entity in projection.entities)
    return _AnalysisContent(
        title="Cited local corpus summary",
        draft_summary=(
            f"The bounded corpus contains {len(projection.segments)} included segment(s), "
            f"{len(projection.entities)} deduplicated entity signal(s), and "
            f"{sum(by_type.values())} typed signal record(s)."
        ),
        sections=_summary_sections(corpus, projection),
        facts=facts,
        connections=(),
        next_steps=(),
        unanswered=None,
        uncertainties=tuple(uncertainties),
    )


def _model_analysis(
    body: LocalCorpusAIRequest,
    corpus: LocalCorpus,
    projection: _Projection,
    result: LocalAIWorkspaceAnalysis,
    deterministic: _AnalysisContent,
    *,
    origin: LocalCorpusAIContentOrigin,
) -> _AnalysisContent:
    facts = tuple(
        LocalCorpusAIFact(
            statement=item.statement,
            evidence_refs=_resolve_model_refs(item.evidence_refs, projection),
            confidence=LocalCorpusAIConfidence(item.confidence.value),
            origin=origin,
        )
        for item in result.facts
    )
    connections: tuple[LocalCorpusAIConnection, ...] = ()
    rejected_connection_count = 0
    if body.task in {LocalCorpusAITask.CONNECTIONS, LocalCorpusAITask.GAP_ANALYSIS}:
        connections, rejected_connection_count = _validated_model_connections(
            result,
            projection,
            origin=origin,
        )
    next_steps = tuple(
        LocalCorpusAINextStep(
            priority=item.priority,
            suggestion=item.suggestion,
            rationale=item.rationale,
            supporting_refs=_resolve_model_refs(item.supporting_refs, projection),
            origin=origin,
        )
        for item in result.next_steps
    )
    model_sections = tuple(
        LocalCorpusAISection(
            heading=item.heading,
            items=tuple(
                LocalCorpusAIReviewNote(
                    text=section_item.text,
                    label=LocalCorpusAITextLabel.CITED_SUMMARY,
                    origin=origin,
                    evidence_refs=_resolve_model_refs(
                        section_item.evidence_refs,
                        projection,
                    ),
                )
                for section_item in item.items
            ),
        )
        for item in result.sections
    )
    uncertainties = tuple(
        LocalCorpusAIReviewNote(
            text=text,
            label=LocalCorpusAITextLabel.LIMITATION,
            origin=origin,
            evidence_refs=(),
        )
        for text in result.limitations
    )
    if rejected_connection_count:
        uncertainties = (
            *uncertainties,
            LocalCorpusAIReviewNote(
                text=(
                    f"Discarded {rejected_connection_count} model-proposed connection(s) because "
                    "their exact cited records did not satisfy the cross-document provenance rule."
                ),
                label=LocalCorpusAITextLabel.LIMITATION,
                origin=LocalCorpusAIContentOrigin.DETERMINISTIC,
                evidence_refs=(),
            ),
        )

    if body.task is LocalCorpusAITask.CONNECTIONS:
        connections = _merge_connections(connections, deterministic.connections)
    if body.task is LocalCorpusAITask.GAP_ANALYSIS:
        next_steps = _merge_steps(next_steps, deterministic.next_steps)
        connections = _merge_connections(connections, deterministic.connections)
    facts = tuple((*facts, *deterministic.facts))[:20]
    sections = tuple((*model_sections, *deterministic.sections))[:8]
    uncertainties = tuple((*uncertainties, *deterministic.uncertainties))[:12]
    return _AnalysisContent(
        title=result.title,
        draft_summary=result.summary,
        sections=sections,
        facts=facts,
        connections=connections,
        next_steps=next_steps,
        unanswered=result.unanswered,
        uncertainties=uncertainties,
    )


def _resolve_model_refs(
    references: tuple[str, ...],
    projection: _Projection,
) -> tuple[str, ...]:
    try:
        return tuple(projection.model_to_source_ref[reference] for reference in references)
    except KeyError:
        raise LocalAIError(LocalAIErrorCode.INVALID_RESPONSE) from None


def _validated_model_connections(
    result: LocalAIWorkspaceAnalysis,
    projection: _Projection,
    *,
    origin: LocalCorpusAIContentOrigin,
) -> tuple[tuple[LocalCorpusAIConnection, ...], int]:
    validated: list[LocalCorpusAIConnection] = []
    rejected = 0
    for item in result.connections:
        from_ref, to_ref = _resolve_model_refs((item.from_ref, item.to_ref), projection)
        supporting_refs = _resolve_model_refs(item.supporting_refs, projection)
        contradiction_refs = _resolve_model_refs(item.contradiction_refs, projection)
        left_sources = projection.sources_by_ref.get(from_ref)
        right_sources = projection.sources_by_ref.get(to_ref)
        if (
            left_sources is None
            or right_sources is None
            or len(left_sources) != 1
            or len(right_sources) != 1
            or left_sources[0].segment_id != from_ref
            or right_sources[0].segment_id != to_ref
            or left_sources[0].document_id == right_sources[0].document_id
        ):
            rejected += 1
            continue
        shared_entities: list[str] = []
        for reference in supporting_refs:
            sources = projection.sources_by_ref.get(reference)
            if not reference.startswith("corpus-entity:") or sources is None:
                continue
            source_ids = {source.segment_id for source in sources}
            if {from_ref, to_ref}.issubset(source_ids):
                shared_entities.append(reference)
        if not shared_entities:
            rejected += 1
            continue
        allowed_contradictions = frozenset(
            _potential_conflict_refs(
                projection,
                frozenset({left_sources[0].document_id, right_sources[0].document_id}),
            )
        )
        if not set(contradiction_refs).issubset(allowed_contradictions):
            rejected += 1
            continue
        supporting = tuple(
            dict.fromkeys(
                (
                    from_ref,
                    to_ref,
                    *shared_entities[:4],
                    *supporting_refs,
                )
            )
        )[:8]
        validated.append(
            LocalCorpusAIConnection(
                from_ref=from_ref,
                to_ref=to_ref,
                shared_entity_refs=tuple(shared_entities[:4]),
                relationship=item.relationship,
                supporting_refs=supporting,
                contradiction_refs=contradiction_refs,
                confidence=LocalCorpusAIConfidence(item.confidence.value),
                origin=origin,
                rationale=item.rationale,
                verification_suggestion=item.verification_suggestion,
            )
        )
    return tuple(validated), rejected


def _merge_connections(
    preferred: tuple[LocalCorpusAIConnection, ...],
    deterministic: tuple[LocalCorpusAIConnection, ...],
) -> tuple[LocalCorpusAIConnection, ...]:
    merged: list[LocalCorpusAIConnection] = []
    keys: set[tuple[object, ...]] = set()
    for item in (*preferred, *deterministic):
        key = (frozenset({item.from_ref, item.to_ref}), item.shared_entity_refs)
        if key in keys:
            continue
        keys.add(key)
        merged.append(item)
    return tuple(merged[:16])


def _merge_steps(
    preferred: tuple[LocalCorpusAINextStep, ...],
    deterministic: tuple[LocalCorpusAINextStep, ...],
) -> tuple[LocalCorpusAINextStep, ...]:
    merged: list[LocalCorpusAINextStep] = []
    keys: set[tuple[str, tuple[str, ...]]] = set()
    for item in (*preferred, *deterministic):
        key = (item.suggestion.casefold(), item.supporting_refs)
        if key in keys:
            continue
        keys.add(key)
        merged.append(item)
    return tuple(sorted(merged, key=lambda item: item.priority)[:16])


def _cited_references(content: _AnalysisContent) -> frozenset[str]:
    references: set[str] = set()
    for section in content.sections:
        for item in section.items:
            references.update(item.evidence_refs)
    for fact in content.facts:
        references.update(fact.evidence_refs)
    for connection in content.connections:
        references.update((connection.from_ref, connection.to_ref))
        references.update(connection.shared_entity_refs)
        references.update(connection.supporting_refs)
        references.update(connection.contradiction_refs)
    for step in content.next_steps:
        references.update(step.supporting_refs)
    for item in content.uncertainties:
        references.update(item.evidence_refs)
    return frozenset(references)


def _source_catalog(
    projection: _Projection,
    cited: frozenset[str],
) -> tuple[LocalCorpusAISourceCatalogEntry, ...]:
    entries: list[LocalCorpusAISourceCatalogEntry] = []
    for reference in projection.references:
        if reference not in cited:
            continue
        sources = projection.sources_by_ref.get(reference)
        if not sources:
            raise LocalAIError(LocalAIErrorCode.INVALID_RESPONSE)
        entries.append(
            LocalCorpusAISourceCatalogEntry(
                reference_id=reference,
                reference_kind=(
                    LocalCorpusAIReferenceKind.ENTITY
                    if reference.startswith("corpus-entity:")
                    else LocalCorpusAIReferenceKind.SEGMENT
                ),
                sources=tuple(
                    LocalCorpusAISourcePointer(
                        document_id=source.document_id,
                        document_name=source.document_name,
                        segment_id=source.segment_id,
                        segment_index=source.segment_index,
                        locator=source.locator,
                    )
                    for source in sources
                ),
            )
        )
    if len(entries) != len(cited):
        raise LocalAIError(LocalAIErrorCode.INVALID_RESPONSE)
    return tuple(entries)


def _fallback_reason(code: LocalAIErrorCode) -> LocalCorpusAIFallbackReason:
    mapping = {
        LocalAIErrorCode.REQUEST_LIMIT: LocalCorpusAIFallbackReason.REQUEST_LIMIT,
        LocalAIErrorCode.RESPONSE_LIMIT: LocalCorpusAIFallbackReason.RESPONSE_LIMIT,
        LocalAIErrorCode.TIMEOUT: LocalCorpusAIFallbackReason.TIMEOUT,
        LocalAIErrorCode.UNAVAILABLE: LocalCorpusAIFallbackReason.UNAVAILABLE,
        LocalAIErrorCode.UPSTREAM_REJECTED: LocalCorpusAIFallbackReason.UPSTREAM_REJECTED,
        LocalAIErrorCode.INVALID_RESPONSE: LocalCorpusAIFallbackReason.INVALID_RESPONSE,
        LocalAIErrorCode.DISABLED: LocalCorpusAIFallbackReason.CONFIGURATION,
        LocalAIErrorCode.INVALID_CONFIGURATION: LocalCorpusAIFallbackReason.CONFIGURATION,
        LocalAIErrorCode.MODEL_REQUIRED: LocalCorpusAIFallbackReason.CONFIGURATION,
    }
    return mapping.get(code, LocalCorpusAIFallbackReason.UNAVAILABLE)
