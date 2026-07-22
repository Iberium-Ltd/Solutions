"""Bounded projection and review-only local analysis of profile or document data.

The service constructs a source catalog first and accepts model statements only
as cited, reviewable output; it never writes conclusions into canonical facts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import and_, func, select

from ariadne_core.api.local_ai_workspace_schemas import (
    LocalAIWorkspaceConfidence,
    LocalAIWorkspaceConnection,
    LocalAIWorkspaceDocumentKind,
    LocalAIWorkspaceExecution,
    LocalAIWorkspaceFact,
    LocalAIWorkspaceFallbackReason,
    LocalAIWorkspaceNextStep,
    LocalAIWorkspaceRequest,
    LocalAIWorkspaceResult,
    LocalAIWorkspaceScope,
    LocalAIWorkspaceSection,
    LocalAIWorkspaceSectionItem,
    LocalAIWorkspaceSource,
    LocalAIWorkspaceSourceCounts,
    LocalAIWorkspaceTask,
)
from ariadne_core.application.intake_compiler import (
    PreparedIntake,
    prepare_file_intake,
    prepare_pasted_intake,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.models import (
    entities,
    entity_origins,
    extraction_runs,
    graph_edge_origins,
    graph_edges,
    graph_nodes,
    intake_segments,
    intake_sources,
    profiles,
)
from ariadne_core.infrastructure.db.phase5_repository import (
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
)
from ariadne_core.infrastructure.db.phase6_repository import (
    Phase6AuditRepository,
    Phase6RemediationRepository,
)
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
from ariadne_core.local_ai import (
    LocalAIWorkspaceTask as ClientWorkspaceTask,
)

_MAX_PROJECTION_BYTES = 60 * 1024
_MAX_RECORDS = 500
_MAX_ENTITIES = 200
_MAX_GRAPH_NODES = 200
_MAX_GRAPH_EDGES = 200
_MAX_FINDINGS = 100
_MAX_REMEDIATIONS = 100
_MAX_DOCUMENT_SEGMENTS = 200
_MAX_PROVENANCE_PER_RECORD = 6
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{1,63}", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "and",
        "are",
        "can",
        "does",
        "for",
        "from",
        "have",
        "into",
        "its",
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


class LocalAIWorkspaceUnavailable(RuntimeError):
    pass


class LocalAIWorkspaceNotFound(LookupError):
    pass


class LocalAIWorkspaceConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Projection:
    canonical_json: str
    records: tuple[dict[str, object], ...]
    references: tuple[str, ...]
    included_counts: LocalAIWorkspaceSourceCounts
    available_counts: LocalAIWorkspaceSourceCounts
    truncated: bool
    restricted_values_redacted: int


@dataclass(frozen=True, slots=True)
class _AnalysisContent:
    title: str
    summary: str
    sections: tuple[LocalAIWorkspaceSection, ...]
    facts: tuple[LocalAIWorkspaceFact, ...]
    connections: tuple[LocalAIWorkspaceConnection, ...]
    next_steps: tuple[LocalAIWorkspaceNextStep, ...]
    unanswered: str | None
    limitations: tuple[str, ...]


def _model_content(result: LocalAIWorkspaceAnalysis) -> _AnalysisContent:
    return _AnalysisContent(
        title=result.title,
        summary=result.summary,
        sections=tuple(
            LocalAIWorkspaceSection(
                heading=item.heading,
                items=tuple(
                    LocalAIWorkspaceSectionItem(
                        text=section_item.text,
                        evidence_refs=section_item.evidence_refs,
                    )
                    for section_item in item.items
                ),
            )
            for item in result.sections
        ),
        facts=tuple(
            LocalAIWorkspaceFact(
                statement=item.statement,
                evidence_refs=item.evidence_refs,
                confidence=LocalAIWorkspaceConfidence(item.confidence.value),
            )
            for item in result.facts
        ),
        connections=tuple(
            LocalAIWorkspaceConnection(
                from_ref=item.from_ref,
                to_ref=item.to_ref,
                relationship=item.relationship,
                supporting_refs=item.supporting_refs,
                contradiction_refs=item.contradiction_refs,
                confidence=LocalAIWorkspaceConfidence(item.confidence.value),
                rationale=item.rationale,
                verification_suggestion=item.verification_suggestion,
            )
            for item in result.connections
        ),
        next_steps=tuple(
            LocalAIWorkspaceNextStep(
                priority=item.priority,
                suggestion=item.suggestion,
                rationale=item.rationale,
                supporting_refs=item.supporting_refs,
            )
            for item in result.next_steps
        ),
        unanswered=result.unanswered,
        limitations=result.limitations,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _bounded_text(value: object, maximum: int) -> str:
    text = str(value).strip()
    return text if len(text) <= maximum else text[: maximum - 1].rstrip() + "…"


def _url_sha256(value: object) -> str | None:
    return None if not isinstance(value, str) else hashlib.sha256(value.encode("utf-8")).hexdigest()


def _counts(**changes: int) -> LocalAIWorkspaceSourceCounts:
    values = {
        "entities": 0,
        "graph_nodes": 0,
        "graph_edges": 0,
        "findings": 0,
        "remediation_cases": 0,
        "audit_runs": 0,
        "document_segments": 0,
    }
    values.update(changes)
    return LocalAIWorkspaceSourceCounts.model_validate(values)


class LocalAIWorkspaceCoordinator:
    """Project selected encrypted state without loading evidence content bytes."""

    def __init__(
        self,
        vault: VaultManager,
        *,
        transport: LocalAIHttpTransport | None = None,
    ) -> None:
        self._vault = vault
        self._transport = transport

    def analyze(self, body: LocalAIWorkspaceRequest) -> LocalAIWorkspaceResult:
        if not self._vault.is_unlocked:
            raise LocalAIWorkspaceUnavailable("local AI workspace requires an unlocked vault")
        projection = self._project(body)
        requested = body.execution
        execution = LocalAIWorkspaceExecution.DETERMINISTIC
        fallback_reason: LocalAIWorkspaceFallbackReason | None = None
        provider = None
        model_id = None
        external_network_used = False
        local_only = True

        if requested is LocalAIWorkspaceExecution.LOCAL_MODEL:
            settings = (
                SettingsRepository(self._vault.engine).get(self._vault.manifest.vault_id).values
            )
            if (
                not settings.local_ai_enabled
                or settings.local_ai_selected_model is None
                or body.model_id != settings.local_ai_selected_model
            ):
                raise LocalAIWorkspaceConflict(
                    "workspace model must match the enabled explicit local selection"
                )
            try:
                result = LocalAIClient(
                    LocalAIConfig(
                        enabled=True,
                        provider=settings.local_ai_provider,
                        endpoint=settings.local_ai_endpoint,
                        timeout_seconds=60,
                        max_output_tokens=2_048,
                    ),
                    transport=self._transport,
                ).analyze_workspace(
                    WorkspaceAnalysisRequest(
                        task=ClientWorkspaceTask(body.task.value),
                        question=body.question,
                        profile_data_json=projection.canonical_json,
                        allowed_reference_ids=projection.references,
                    ),
                    model_id=body.model_id,
                )
            except LocalAIError as error:
                fallback_reason = _fallback_reason(error.code)
                content = _deterministic_analysis(body, projection)
            else:
                execution = LocalAIWorkspaceExecution.LOCAL_MODEL
                provider = result.provider
                model_id = result.model_id
                content = _model_content(result)
        elif requested is LocalAIWorkspaceExecution.OPENAI_RESPONSES:
            api_key = body.openai_api_key
            if api_key is None or body.model_id is None:
                raise LocalAIWorkspaceConflict(
                    "OpenAI workspace execution requires an ephemeral key and model"
                )
            provider = LocalAIProvider.OPENAI_RESPONSES
            model_id = body.model_id
            external_network_used = True
            local_only = False
            try:
                result = OpenAIResponsesClient(
                    OpenAIResponsesConfig(
                        api_key=api_key,
                        timeout_seconds=60,
                        max_output_tokens=4_096,
                    ),
                    transport=self._transport,
                ).analyze_workspace(
                    WorkspaceAnalysisRequest(
                        task=ClientWorkspaceTask(body.task.value),
                        question=body.question,
                        profile_data_json=projection.canonical_json,
                        allowed_reference_ids=projection.references,
                    ),
                    model_id=body.model_id,
                )
            except LocalAIError as error:
                fallback_reason = _fallback_reason(error.code)
                content = _deterministic_analysis(body, projection)
            else:
                execution = LocalAIWorkspaceExecution.OPENAI_RESPONSES
                content = _model_content(result)
        else:
            content = _deterministic_analysis(body, projection)

        content = _expand_citations(content, projection)
        content = _bound_citations(content)
        return LocalAIWorkspaceResult(
            profile_id=body.profile_id,
            task=body.task,
            selected_scopes=body.scopes,
            requested_execution=requested,
            execution_mode=execution,
            fallback_reason=fallback_reason,
            provider=provider,
            model_id=model_id,
            engine_version="1",
            title=content.title,
            summary=content.summary,
            sections=content.sections,
            facts=content.facts,
            connections=content.connections,
            next_steps=content.next_steps,
            sources=_source_catalog(content, projection),
            unanswered=content.unanswered,
            limitations=content.limitations,
            included_counts=projection.included_counts,
            available_counts=projection.available_counts,
            projection_truncated=projection.truncated,
            input_sha256=hashlib.sha256(projection.canonical_json.encode("utf-8")).hexdigest(),
            restricted_values_redacted=projection.restricted_values_redacted,
            local_only=local_only,
            external_network_used=external_network_used,
            raw_evidence_included=False,
            review_only=True,
            human_review_required=True,
        )

    def _project(self, body: LocalAIWorkspaceRequest) -> _Projection:
        vault_id = self._vault.manifest.vault_id
        with self._vault.engine.connect() as connection:
            profile = (
                connection.execute(
                    select(profiles).where(
                        and_(
                            profiles.c.vault_id == vault_id,
                            profiles.c.id == body.profile_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if profile is None:
            raise LocalAIWorkspaceNotFound("workspace profile is unavailable")

        candidates: list[dict[str, object]] = [
            {
                "data": {
                    "label": _bounded_text(profile["display_label"], 128),
                    "purpose": _bounded_text(profile["purpose"], 240),
                    "status": str(profile["status"]),
                },
                "kind": "PROFILE",
                "ref": f"profile:{body.profile_id}",
            }
        ]
        available = {
            "entities": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "findings": 0,
            "remediation_cases": 0,
            "audit_runs": 0,
            "document_segments": 0,
        }
        loaded = dict(available)
        restricted_values_redacted = 0
        load_truncated = False

        if LocalAIWorkspaceScope.ENTITIES in body.scopes:
            records, count = self._entity_records(body, vault_id)
            candidates.extend(records)
            available["entities"] = count
            loaded["entities"] = sum(item["kind"] == "ENTITY" for item in records)
            load_truncated |= count > loaded["entities"]

        if LocalAIWorkspaceScope.GRAPH in body.scopes:
            records, node_count, edge_count = self._graph_records(body, vault_id)
            candidates.extend(records)
            available["graph_nodes"] = node_count
            available["graph_edges"] = edge_count
            loaded["graph_nodes"] = sum(item["kind"] == "GRAPH_NODE" for item in records)
            loaded["graph_edges"] = sum(item["kind"] == "GRAPH_EDGE" for item in records)
            load_truncated |= (
                node_count > loaded["graph_nodes"] or edge_count > loaded["graph_edges"]
            )

        if LocalAIWorkspaceScope.FINDINGS in body.scopes:
            records, count, finding_records = self._finding_records(body, vault_id)
            candidates.extend(records)
            available["findings"] = count
            loaded["findings"] = finding_records
            load_truncated |= count > finding_records

        if LocalAIWorkspaceScope.REMEDIATION in body.scopes:
            records, count = self._remediation_records(body, vault_id)
            candidates.extend(records)
            available["remediation_cases"] = count
            loaded["remediation_cases"] = len(records)
            load_truncated |= count > len(records)

        if LocalAIWorkspaceScope.AUDIT_COVERAGE in body.scopes:
            records, count = self._audit_records(body, vault_id)
            candidates.extend(records)
            available["audit_runs"] = count
            loaded["audit_runs"] = len(records)
            load_truncated |= count > len(records)

        if LocalAIWorkspaceScope.DOCUMENT in body.scopes:
            prepared = self._prepare_document(body)
            records = _document_records(
                prepared, body.document.display_name if body.document else "Document"
            )
            candidates.extend(records)
            available["document_segments"] = len(prepared.parsed.segments)
            loaded["document_segments"] = len(records)
            restricted_values_redacted = prepared.quarantine_count
            load_truncated |= available["document_segments"] > len(records)

        selected: list[dict[str, object]] = []
        selected_refs: set[str] = set()
        included = dict(available)
        for key in included:
            included[key] = 0
        for candidate in candidates:
            candidate_data = candidate.get("data")
            values = candidate_data if isinstance(candidate_data, dict) else {}
            dependency_keys = (
                "originRefs",
                "evidenceRefs",
                "supportingOriginRefs",
                "contradictionOriginRefs",
                "supportingEvidenceRefs",
                "contradictingEvidenceRefs",
            )
            dependencies_missing = False
            bounded_values = dict(values)
            for key in dependency_keys:
                dependencies = values.get(key)
                if not isinstance(dependencies, list):
                    continue
                available_dependencies = [
                    str(reference) for reference in dependencies if str(reference) in selected_refs
                ]
                if (
                    dependencies
                    and not available_dependencies
                    and key
                    in {
                        "originRefs",
                        "evidenceRefs",
                    }
                ):
                    dependencies_missing = True
                    break
                if len(available_dependencies) != len(dependencies):
                    load_truncated = True
                bounded_values[key] = available_dependencies
            if dependencies_missing:
                load_truncated = True
                continue
            candidate = {**candidate, "data": bounded_values}
            candidate_ref = str(candidate["ref"])
            if candidate_ref in selected_refs:
                continue
            trial = [*selected, candidate]
            envelope = {
                "records": trial,
                "schema": "ariadne.local-ai-workspace-input",
                "version": 1,
            }
            if len(trial) > _MAX_RECORDS or len(_canonical(envelope).encode("utf-8")) > (
                _MAX_PROJECTION_BYTES
            ):
                load_truncated = True
                continue
            selected.append(candidate)
            selected_refs.add(candidate_ref)
            counter = {
                "ENTITY": "entities",
                "GRAPH_NODE": "graph_nodes",
                "GRAPH_EDGE": "graph_edges",
                "FINDING": "findings",
                "REMEDIATION": "remediation_cases",
                "AUDIT_RUN": "audit_runs",
                "DOCUMENT_SEGMENT": "document_segments",
            }.get(str(candidate["kind"]))
            if counter is not None:
                included[counter] += 1

        envelope = {
            "records": selected,
            "schema": "ariadne.local-ai-workspace-input",
            "version": 1,
        }
        canonical = _canonical(envelope)
        references = tuple(str(item["ref"]) for item in selected)
        if not references:
            raise LocalAIWorkspaceConflict("workspace projection is empty")
        return _Projection(
            canonical_json=canonical,
            records=tuple(selected),
            references=references,
            included_counts=_counts(**included),
            available_counts=_counts(**available),
            truncated=load_truncated,
            restricted_values_redacted=restricted_values_redacted,
        )

    def _entity_records(
        self,
        body: LocalAIWorkspaceRequest,
        vault_id: str,
    ) -> tuple[list[dict[str, object]], int]:
        conditions = [
            entities.c.vault_id == vault_id,
            entities.c.profile_id == body.profile_id,
            entities.c.deleted_at_us.is_(None),
        ]
        if not body.include_sensitive_entities:
            conditions.append(entities.c.sensitivity == "PUBLIC")
        with self._vault.engine.connect() as connection:
            count = int(
                connection.execute(
                    select(func.count()).select_from(entities).where(and_(*conditions))
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    select(entities)
                    .where(and_(*conditions))
                    .order_by(entities.c.updated_at_us.desc(), entities.c.id)
                    .limit(_MAX_ENTITIES)
                )
                .mappings()
                .all()
            )
            entity_ids = tuple(str(row["id"]) for row in rows)
            origin_rows = (
                ()
                if not entity_ids
                else connection.execute(
                    select(
                        entity_origins.c.id.label("origin_id"),
                        entity_origins.c.entity_id,
                        entity_origins.c.source_span_start,
                        entity_origins.c.source_span_end,
                        entity_origins.c.extraction_run_id,
                        entity_origins.c.origin_kind,
                        entity_origins.c.observed_at_us,
                        entity_origins.c.confidence_micros,
                        entity_origins.c.explanation,
                        intake_sources.c.id.label("source_id"),
                        intake_sources.c.display_name.label("source_display_name"),
                        intake_sources.c.sha256.label("source_sha256"),
                        intake_segments.c.id.label("segment_id"),
                        intake_segments.c.ordinal.label("segment_index"),
                        intake_segments.c.locator_json.label("segment_locator"),
                        extraction_runs.c.engine_kind.label("extractor_kind"),
                        extraction_runs.c.engine_name.label("extractor_name"),
                        extraction_runs.c.engine_version.label("extractor_version"),
                    )
                    .select_from(
                        entity_origins.join(
                            intake_segments,
                            and_(
                                intake_segments.c.vault_id == entity_origins.c.vault_id,
                                intake_segments.c.profile_id == entity_origins.c.profile_id,
                                intake_segments.c.id == entity_origins.c.intake_segment_id,
                            ),
                        )
                        .join(
                            intake_sources,
                            and_(
                                intake_sources.c.vault_id == intake_segments.c.vault_id,
                                intake_sources.c.profile_id == intake_segments.c.profile_id,
                                intake_sources.c.id == intake_segments.c.intake_source_id,
                            ),
                        )
                        .outerjoin(
                            extraction_runs,
                            and_(
                                extraction_runs.c.vault_id == entity_origins.c.vault_id,
                                extraction_runs.c.profile_id == entity_origins.c.profile_id,
                                extraction_runs.c.id == entity_origins.c.extraction_run_id,
                            ),
                        )
                    )
                    .where(
                        and_(
                            entity_origins.c.vault_id == vault_id,
                            entity_origins.c.profile_id == body.profile_id,
                            entity_origins.c.entity_id.in_(entity_ids),
                        )
                    )
                    .order_by(
                        entity_origins.c.entity_id,
                        entity_origins.c.confidence_micros.desc(),
                        entity_origins.c.observed_at_us,
                        entity_origins.c.id,
                    )
                )
                .mappings()
                .all()
            )
        origins_by_entity: dict[str, list[dict[str, object]]] = {}
        for origin in origin_rows:
            entity_id = str(origin["entity_id"])
            selected = origins_by_entity.setdefault(entity_id, [])
            if len(selected) >= _MAX_PROVENANCE_PER_RECORD:
                continue
            origin_ref = f"entity-origin:{origin['origin_id']}"
            selected.append(
                {
                    "data": {
                        "confidenceMicros": int(origin["confidence_micros"]),
                        "entityRef": f"entity:{entity_id}",
                        "explanation": _bounded_text(origin["explanation"], 500),
                        "extractionRunId": (
                            None
                            if origin["extraction_run_id"] is None
                            else str(origin["extraction_run_id"])
                        ),
                        "extractorKind": (
                            None
                            if origin["extractor_kind"] is None
                            else str(origin["extractor_kind"])
                        ),
                        "extractorName": (
                            None
                            if origin["extractor_name"] is None
                            else str(origin["extractor_name"])
                        ),
                        "extractorVersion": (
                            None
                            if origin["extractor_version"] is None
                            else str(origin["extractor_version"])
                        ),
                        "observedAtUs": int(origin["observed_at_us"]),
                        "originKind": str(origin["origin_kind"]),
                        "segmentId": str(origin["segment_id"]),
                        "segmentIndex": int(origin["segment_index"]),
                        "segmentLocator": _bounded_text(origin["segment_locator"], 600),
                        "sourceDisplayName": _bounded_text(origin["source_display_name"], 255),
                        "sourceId": str(origin["source_id"]),
                        "sourceSha256": str(origin["source_sha256"]),
                        "sourceSpanEnd": (
                            None
                            if origin["source_span_end"] is None
                            else int(origin["source_span_end"])
                        ),
                        "sourceSpanStart": (
                            None
                            if origin["source_span_start"] is None
                            else int(origin["source_span_start"])
                        ),
                    },
                    "kind": "ENTITY_ORIGIN",
                    "ref": origin_ref,
                }
            )
        if entity_ids and set(origins_by_entity) != set(entity_ids):
            raise LocalAIWorkspaceConflict("entity provenance is unavailable")

        records: list[dict[str, object]] = []
        for row in rows:
            entity_id = str(row["id"])
            origin_records = origins_by_entity[entity_id]
            records.extend(origin_records)
            records.append(
                {
                    "data": {
                        "confidenceMicros": max(
                            int(item["data"]["confidenceMicros"])  # type: ignore[index]
                            for item in origin_records
                        ),
                        "originRefs": [str(item["ref"]) for item in origin_records],
                        "reviewState": str(row["review_state"]),
                        "sensitivity": str(row["sensitivity"]),
                        "temporalState": str(row["temporal_state"]),
                        "type": str(row["entity_type"]),
                        "value": _bounded_text(
                            row[
                                "canonical_value"
                                if body.include_sensitive_entities
                                else "display_mask"
                            ],
                            512,
                        ),
                    },
                    "kind": "ENTITY",
                    "ref": f"entity:{entity_id}",
                }
            )
        return records, count

    def _graph_records(
        self,
        body: LocalAIWorkspaceRequest,
        vault_id: str,
    ) -> tuple[list[dict[str, object]], int, int]:
        node_conditions = [
            graph_nodes.c.vault_id == vault_id,
            graph_nodes.c.profile_id == body.profile_id,
            graph_nodes.c.deleted_at_us.is_(None),
        ]
        if not body.include_sensitive_entities:
            node_conditions.append(graph_nodes.c.sensitivity == "PUBLIC")
        with self._vault.engine.connect() as connection:
            node_count = int(
                connection.execute(
                    select(func.count()).select_from(graph_nodes).where(and_(*node_conditions))
                ).scalar_one()
            )
            node_rows = (
                connection.execute(
                    select(graph_nodes)
                    .where(and_(*node_conditions))
                    .order_by(graph_nodes.c.created_at_us, graph_nodes.c.id)
                    .limit(_MAX_GRAPH_NODES)
                )
                .mappings()
                .all()
            )
            all_node_ids = select(graph_nodes.c.id).where(and_(*node_conditions))
            edge_conditions = [
                graph_edges.c.vault_id == vault_id,
                graph_edges.c.profile_id == body.profile_id,
                graph_edges.c.deleted_at_us.is_(None),
                graph_edges.c.review_state.not_in(("REJECTED", "EXCLUDED")),
                graph_edges.c.from_node_id.in_(all_node_ids),
                graph_edges.c.to_node_id.in_(all_node_ids),
            ]
            edge_count = int(
                connection.execute(
                    select(func.count()).select_from(graph_edges).where(and_(*edge_conditions))
                ).scalar_one()
            )
            edge_rows = (
                connection.execute(
                    select(graph_edges)
                    .where(and_(*edge_conditions))
                    .order_by(graph_edges.c.updated_at_us.desc(), graph_edges.c.id)
                    .limit(_MAX_GRAPH_EDGES)
                )
                .mappings()
                .all()
            )
            edge_ids = tuple(str(row["id"]) for row in edge_rows)
            origin_rows = (
                ()
                if not edge_ids
                else connection.execute(
                    select(
                        graph_edge_origins.c.id.label("origin_id"),
                        graph_edge_origins.c.graph_edge_id,
                        graph_edge_origins.c.disposition,
                        graph_edge_origins.c.confidence_micros,
                        graph_edge_origins.c.source_span_start,
                        graph_edge_origins.c.source_span_end,
                        graph_edge_origins.c.observed_at_us,
                        graph_edge_origins.c.origin_type,
                        graph_edge_origins.c.explanation,
                        graph_edge_origins.c.extraction_run_id,
                        intake_sources.c.id.label("source_id"),
                        intake_sources.c.display_name.label("source_display_name"),
                        intake_sources.c.sha256.label("source_sha256"),
                        intake_segments.c.id.label("segment_id"),
                        intake_segments.c.ordinal.label("segment_index"),
                        intake_segments.c.locator_json.label("segment_locator"),
                        extraction_runs.c.engine_kind.label("extractor_kind"),
                        extraction_runs.c.engine_name.label("extractor_name"),
                        extraction_runs.c.engine_version.label("extractor_version"),
                    )
                    .select_from(
                        graph_edge_origins.join(
                            intake_sources,
                            and_(
                                intake_sources.c.vault_id == graph_edge_origins.c.vault_id,
                                intake_sources.c.profile_id == graph_edge_origins.c.profile_id,
                                intake_sources.c.id == graph_edge_origins.c.intake_source_id,
                            ),
                        )
                        .join(
                            intake_segments,
                            and_(
                                intake_segments.c.vault_id == graph_edge_origins.c.vault_id,
                                intake_segments.c.profile_id == graph_edge_origins.c.profile_id,
                                intake_segments.c.intake_source_id
                                == graph_edge_origins.c.intake_source_id,
                                intake_segments.c.id == graph_edge_origins.c.intake_segment_id,
                            ),
                        )
                        .join(
                            extraction_runs,
                            and_(
                                extraction_runs.c.vault_id == graph_edge_origins.c.vault_id,
                                extraction_runs.c.profile_id == graph_edge_origins.c.profile_id,
                                extraction_runs.c.intake_source_id
                                == graph_edge_origins.c.intake_source_id,
                                extraction_runs.c.id == graph_edge_origins.c.extraction_run_id,
                            ),
                        )
                    )
                    .where(
                        and_(
                            graph_edge_origins.c.vault_id == vault_id,
                            graph_edge_origins.c.profile_id == body.profile_id,
                            graph_edge_origins.c.graph_edge_id.in_(edge_ids),
                        )
                    )
                    .order_by(
                        graph_edge_origins.c.graph_edge_id,
                        graph_edge_origins.c.disposition,
                        graph_edge_origins.c.created_at_us,
                        graph_edge_origins.c.id,
                    )
                )
                .mappings()
                .all()
            )
        records: list[dict[str, object]] = [
            {
                "data": {
                    "label": _bounded_text(row["display_label"], 512),
                    "sensitivity": str(row["sensitivity"]),
                    "type": str(row["node_type"]),
                    "visibility": str(row["visibility"]),
                },
                "kind": "GRAPH_NODE",
                "ref": f"graph-node:{row['id']}",
            }
            for row in node_rows
        ]
        origins_by_edge: dict[str, dict[str, list[dict[str, object]]]] = {}
        for origin in origin_rows:
            edge_id = str(origin["graph_edge_id"])
            disposition = str(origin["disposition"])
            by_disposition = origins_by_edge.setdefault(
                edge_id,
                {"SUPPORTS": [], "CONTRADICTS": []},
            )
            selected = by_disposition[disposition]
            if len(selected) >= _MAX_PROVENANCE_PER_RECORD // 2:
                continue
            selected.append(
                {
                    "data": {
                        "confidenceMicros": int(origin["confidence_micros"]),
                        "disposition": disposition,
                        "edgeRef": f"graph-edge:{edge_id}",
                        "explanation": _bounded_text(origin["explanation"], 500),
                        "extractionRunId": str(origin["extraction_run_id"]),
                        "extractorKind": str(origin["extractor_kind"]),
                        "extractorName": str(origin["extractor_name"]),
                        "extractorVersion": str(origin["extractor_version"]),
                        "observedAtUs": int(origin["observed_at_us"]),
                        "originType": str(origin["origin_type"]),
                        "segmentId": str(origin["segment_id"]),
                        "segmentIndex": int(origin["segment_index"]),
                        "segmentLocator": _bounded_text(origin["segment_locator"], 600),
                        "sourceDisplayName": _bounded_text(origin["source_display_name"], 255),
                        "sourceId": str(origin["source_id"]),
                        "sourceSha256": str(origin["source_sha256"]),
                        "sourceSpanEnd": (
                            None
                            if origin["source_span_end"] is None
                            else int(origin["source_span_end"])
                        ),
                        "sourceSpanStart": (
                            None
                            if origin["source_span_start"] is None
                            else int(origin["source_span_start"])
                        ),
                    },
                    "kind": "GRAPH_EDGE_ORIGIN",
                    "ref": f"graph-edge-origin:{origin['origin_id']}",
                }
            )
        if edge_ids and set(origins_by_edge) != set(edge_ids):
            raise LocalAIWorkspaceConflict("graph edge provenance is unavailable")

        for row in edge_rows:
            edge_id = str(row["id"])
            origin_groups = origins_by_edge[edge_id]
            origin_records = [
                *origin_groups["SUPPORTS"],
                *origin_groups["CONTRADICTS"],
            ]
            records.extend(origin_records)
            records.append(
                {
                    "data": {
                        "contradictionOriginRefs": [
                            str(item["ref"]) for item in origin_groups["CONTRADICTS"]
                        ],
                        "confidenceMicros": int(row["confidence_micros"]),
                        "explanation": _bounded_text(row["explanation"], 500),
                        "fromRef": f"graph-node:{row['from_node_id']}",
                        "originRefs": [str(item["ref"]) for item in origin_records],
                        "originType": str(row["origin_type"]),
                        "reviewState": str(row["review_state"]),
                        "supportingOriginRefs": [
                            str(item["ref"]) for item in origin_groups["SUPPORTS"]
                        ],
                        "toRef": f"graph-node:{row['to_node_id']}",
                        "type": str(row["edge_type"]),
                        "visibility": str(row["visibility"]),
                    },
                    "kind": "GRAPH_EDGE",
                    "ref": f"graph-edge:{edge_id}",
                }
            )
        return records, node_count, edge_count

    def _finding_records(
        self,
        body: LocalAIWorkspaceRequest,
        vault_id: str,
    ) -> tuple[list[dict[str, object]], int, int]:
        repository = Phase5AttributionRepository(
            self._vault.engine,
            vault_id=vault_id,
            profile_id=body.profile_id,
        )
        count = repository.count_findings()
        findings = repository.list_findings(limit=_MAX_FINDINGS)
        if not findings:
            return [], count, 0
        materials = repository.local_checkpoint_materials(
            tuple(sorted({item.provider_id for item in findings})),
            maximum_findings=_MAX_FINDINGS,
        )
        evidence_ids = tuple(
            sorted({item.artifact_id for material in materials for item in material.evidence})
        )
        source_urls = (
            {}
            if not evidence_ids
            else {
                item.artifact_id: item.source_url
                for item in Phase5EvidenceRepository(
                    self._vault.engine,
                    vault_id=vault_id,
                    profile_id=body.profile_id,
                ).source_metadata_for_artifacts(evidence_ids)
            }
        )
        selected_ids = {item.finding_id for item in findings}
        records: list[dict[str, object]] = []
        for material in materials:
            finding = material.finding
            if finding.finding_id not in selected_ids:
                continue
            assessment = material.latest_assessment
            decision = material.latest_decision
            selected_evidence = material.evidence[:7]
            evidence_refs = [f"evidence:{item.artifact_id}" for item in selected_evidence]
            available_evidence_ids = {item.artifact_id for item in selected_evidence}
            supporting_evidence_refs = (
                []
                if assessment is None
                else [
                    f"evidence:{reference}"
                    for contribution in assessment.assessment.contributing_signals
                    for reference in contribution.evidence_references
                    if reference in available_evidence_ids
                ]
            )
            contradicting_evidence_refs = (
                []
                if assessment is None
                else [
                    f"evidence:{reference}"
                    for contribution in assessment.assessment.contradictions
                    for reference in contribution.evidence_references
                    if reference in available_evidence_ids
                ]
            )
            records.extend(
                {
                    "data": {
                        "artifactId": evidence.artifact_id,
                        "captureMethod": evidence.capture_method,
                        "capturedAtUs": evidence.captured_at_us,
                        "contentSha256": evidence.content_sha256,
                        "findingRef": f"finding:{finding.finding_id}",
                        "httpStatus": evidence.http_status,
                        "kind": evidence.kind,
                        "providerId": evidence.provider_id,
                        "redirectCount": evidence.redirect_count,
                        "runId": evidence.run_id,
                        "sourceUrl": source_urls.get(evidence.artifact_id),
                        "sourceUrlSha256": _url_sha256(source_urls.get(evidence.artifact_id)),
                    },
                    "kind": "EVIDENCE_METADATA",
                    "ref": f"evidence:{evidence.artifact_id}",
                }
                for evidence in selected_evidence
            )
            records.append(
                {
                    "data": {
                        "attribution": (
                            None
                            if assessment is None
                            else {
                                "confidenceBand": assessment.assessment.confidence_band.value,
                                "contradictions": [
                                    item.signal.value
                                    for item in assessment.assessment.contradictions
                                ],
                                "humanState": (
                                    None if decision is None else decision.decision.state.value
                                ),
                                "missingEvidence": [
                                    item.signal.value
                                    for item in assessment.assessment.missing_evidence
                                ],
                                "score": assessment.assessment.score,
                                "supportingSignals": [
                                    item.signal.value
                                    for item in assessment.assessment.contributing_signals
                                ],
                            }
                        ),
                        "contradictingEvidenceRefs": list(
                            dict.fromkeys(contradicting_evidence_refs)
                        ),
                        "evidenceRefs": evidence_refs,
                        "observedAtUs": finding.observed_at_us,
                        "outcome": finding.outcome.value,
                        "providerId": finding.provider_id,
                        "severity": finding.severity.value,
                        "summary": _bounded_text(finding.summary, 1_000),
                        "supportingEvidenceRefs": list(dict.fromkeys(supporting_evidence_refs)),
                        "title": _bounded_text(finding.title, 256),
                        "visibility": finding.visibility.value,
                    },
                    "kind": "FINDING",
                    "ref": f"finding:{finding.finding_id}",
                }
            )
        return records, count, sum(item["kind"] == "FINDING" for item in records)

    def _remediation_records(
        self,
        body: LocalAIWorkspaceRequest,
        vault_id: str,
    ) -> tuple[list[dict[str, object]], int]:
        repository = Phase6RemediationRepository(
            self._vault.engine,
            vault_id=vault_id,
            profile_id=body.profile_id,
        )
        count = repository.count_cases()
        cases = repository.list_cases(limit=_MAX_REMEDIATIONS)
        return (
            [
                {
                    "data": {
                        "action": record.case.action.value,
                        "deadlineAtUs": record.case.deadline_at_us,
                        "findingRefs": [f"finding:{item}" for item in record.case.finding_ids],
                        "reappearanceCount": record.case.reappearance_count,
                        "status": record.case.status.value,
                        "updatedAtUs": record.case.updated_at_us,
                    },
                    "kind": "REMEDIATION",
                    "ref": f"remediation:{record.case.case_id}",
                }
                for record in cases
            ],
            count,
        )

    def _audit_records(
        self,
        body: LocalAIWorkspaceRequest,
        vault_id: str,
    ) -> tuple[list[dict[str, object]], int]:
        repository = Phase6AuditRepository(
            self._vault.engine,
            vault_id=vault_id,
            profile_id=body.profile_id,
        )
        count = repository.count_snapshots()
        runs = repository.list_run_summaries()
        return (
            [
                {
                    "data": {
                        "capturedAtUs": run.captured_at_us,
                        "findingCount": run.finding_count,
                        "providerCount": run.provider_count,
                        "runState": run.run_state.value,
                        "sequence": run.sequence,
                    },
                    "kind": "AUDIT_RUN",
                    "ref": f"audit-run:{run.run_id}",
                }
                for run in runs
            ],
            count,
        )

    @staticmethod
    def _prepare_document(body: LocalAIWorkspaceRequest) -> PreparedIntake:
        document = body.document
        if document is None:
            raise LocalAIWorkspaceConflict("workspace document is unavailable")
        encoded = document.content.encode("utf-8")
        if not hmac.compare_digest(
            hashlib.sha256(encoded).hexdigest(),
            document.content_sha256,
        ):
            raise ValueError("workspace document hash binding is invalid")
        if document.kind is LocalAIWorkspaceDocumentKind.PASTE:
            return prepare_pasted_intake(
                document.content,
                display_name=document.display_name,
                semantic_enrichment_enabled=False,
            )
        return prepare_file_intake(
            display_name=document.display_name,
            content=encoded,
            declared_media_type=document.declared_media_type or "",
            semantic_enrichment_enabled=False,
        )


def _document_records(
    prepared: PreparedIntake,
    display_name: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for segment in prepared.parsed.segments[:_MAX_DOCUMENT_SEGMENTS]:
        text = _bounded_text(segment.text, 1_200)
        if not text:
            continue
        reference = f"document-segment:{prepared.source_sha256}:{segment.index}"
        records.append(
            {
                "data": {
                    "contentSha256": prepared.source_sha256,
                    "format": prepared.parsed.source_format.value,
                    "displayName": _bounded_text(display_name, 255),
                    "sourceDisplayName": _bounded_text(display_name, 255),
                    "segmentId": reference,
                    "segmentIndex": segment.index,
                    "segmentKind": segment.kind.value,
                    "segmentLocator": _bounded_text(segment.locator, 600),
                    "sourceId": f"document:{prepared.source_sha256}",
                    "text": text,
                },
                "kind": "DOCUMENT_SEGMENT",
                "ref": reference,
            }
        )
    return records


def _fallback_reason(code: LocalAIErrorCode) -> LocalAIWorkspaceFallbackReason:
    mapping = {
        LocalAIErrorCode.REQUEST_LIMIT: LocalAIWorkspaceFallbackReason.REQUEST_LIMIT,
        LocalAIErrorCode.RESPONSE_LIMIT: LocalAIWorkspaceFallbackReason.RESPONSE_LIMIT,
        LocalAIErrorCode.TIMEOUT: LocalAIWorkspaceFallbackReason.TIMEOUT,
        LocalAIErrorCode.UNAVAILABLE: LocalAIWorkspaceFallbackReason.UNAVAILABLE,
        LocalAIErrorCode.UPSTREAM_REJECTED: LocalAIWorkspaceFallbackReason.UPSTREAM_REJECTED,
        LocalAIErrorCode.INVALID_RESPONSE: LocalAIWorkspaceFallbackReason.INVALID_RESPONSE,
    }
    return mapping.get(code, LocalAIWorkspaceFallbackReason.UNAVAILABLE)


def _item_references(item: object) -> tuple[str, ...]:
    if isinstance(item, LocalAIWorkspaceSectionItem):
        return item.evidence_refs
    if isinstance(item, LocalAIWorkspaceFact):
        return item.evidence_refs
    if isinstance(item, LocalAIWorkspaceConnection):
        return (
            item.from_ref,
            item.to_ref,
            *item.supporting_refs,
            *item.contradiction_refs,
        )
    if isinstance(item, LocalAIWorkspaceNextStep):
        return item.supporting_refs
    raise TypeError("workspace citation item is invalid")


def _record_dependency_refs(
    record: dict[str, object],
    *,
    keys: tuple[str, ...] = ("originRefs", "evidenceRefs"),
) -> tuple[str, ...]:
    data = record.get("data")
    values = data if isinstance(data, dict) else {}
    dependencies: list[str] = []
    for key in keys:
        candidates = values.get(key)
        if isinstance(candidates, list):
            dependencies.extend(str(item) for item in candidates)
    return tuple(dict.fromkeys(dependencies))


def _expand_citations(
    content: _AnalysisContent,
    projection: _Projection,
) -> _AnalysisContent:
    records = {str(record["ref"]): record for record in projection.records}

    def expanded(
        values: tuple[str, ...],
        *,
        dependency_keys: tuple[str, ...] = ("originRefs", "evidenceRefs"),
    ) -> tuple[str, ...]:
        output: list[str] = []
        for reference in values:
            if reference not in output:
                output.append(reference)
            record = records.get(reference)
            if record is None:
                continue
            for dependency in _record_dependency_refs(record, keys=dependency_keys):
                if dependency not in output:
                    output.append(dependency)
                if len(output) >= 8:
                    return tuple(output)
        return tuple(output)

    return _AnalysisContent(
        title=content.title,
        summary=content.summary,
        sections=tuple(
            LocalAIWorkspaceSection(
                heading=section.heading,
                items=tuple(
                    LocalAIWorkspaceSectionItem(
                        text=item.text,
                        evidence_refs=expanded(item.evidence_refs),
                    )
                    for item in section.items
                ),
            )
            for section in content.sections
        ),
        facts=tuple(
            LocalAIWorkspaceFact(
                statement=fact.statement,
                evidence_refs=expanded(fact.evidence_refs),
                confidence=fact.confidence,
            )
            for fact in content.facts
        ),
        connections=tuple(
            LocalAIWorkspaceConnection(
                from_ref=connection.from_ref,
                to_ref=connection.to_ref,
                relationship=connection.relationship,
                supporting_refs=expanded(
                    connection.supporting_refs,
                    dependency_keys=(
                        "supportingOriginRefs",
                        "supportingEvidenceRefs",
                        "evidenceRefs",
                    ),
                ),
                contradiction_refs=expanded(
                    connection.contradiction_refs,
                    dependency_keys=(
                        "contradictionOriginRefs",
                        "contradictingEvidenceRefs",
                    ),
                ),
                confidence=connection.confidence,
                rationale=connection.rationale,
                verification_suggestion=connection.verification_suggestion,
            )
            for connection in content.connections
        ),
        next_steps=tuple(
            LocalAIWorkspaceNextStep(
                priority=step.priority,
                suggestion=step.suggestion,
                rationale=step.rationale,
                supporting_refs=expanded(step.supporting_refs),
            )
            for step in content.next_steps
        ),
        unanswered=content.unanswered,
        limitations=content.limitations,
    )


def _bound_citations(content: _AnalysisContent) -> _AnalysisContent:
    references: set[str] = set()

    def bounded[T](items: tuple[T, ...]) -> tuple[T, ...]:
        selected: list[T] = []
        for item in items:
            item_references = set(_item_references(item))
            if len(references | item_references) > 128:
                continue
            references.update(item_references)
            selected.append(item)
        return tuple(selected)

    sections: list[LocalAIWorkspaceSection] = []
    for section in content.sections:
        section_items = bounded(section.items)
        if section_items:
            sections.append(LocalAIWorkspaceSection(heading=section.heading, items=section_items))

    return _AnalysisContent(
        title=content.title,
        summary=content.summary,
        sections=tuple(sections),
        facts=bounded(content.facts),
        connections=bounded(content.connections),
        next_steps=bounded(content.next_steps),
        unanswered=content.unanswered,
        limitations=content.limitations,
    )


def _source_catalog(
    content: _AnalysisContent,
    projection: _Projection,
) -> tuple[LocalAIWorkspaceSource, ...]:
    cited: list[str] = []
    seen: set[str] = set()
    section_items = tuple(item for section in content.sections for item in section.items)
    for item in (*section_items, *content.facts, *content.connections, *content.next_steps):
        for reference in _item_references(item):
            if reference not in seen:
                seen.add(reference)
                cited.append(reference)
    records = {str(record["ref"]): record for record in projection.records}
    if any(reference not in records for reference in cited):
        raise LocalAIWorkspaceConflict("workspace output cited an unavailable source")
    return tuple(_source_for_record(records[reference]) for reference in cited)


def _source_for_record(record: dict[str, object]) -> LocalAIWorkspaceSource:
    reference = str(record["ref"])
    kind = str(record["kind"])
    data = record.get("data")
    values = data if isinstance(data, dict) else {}
    label_candidates = {
        "PROFILE": values.get("label"),
        "ENTITY": f"{values.get('type', 'Entity')} · {values.get('value', '[masked]')}",
        "ENTITY_ORIGIN": f"Entity origin · {values.get('sourceDisplayName', 'source')}",
        "GRAPH_NODE": values.get("label"),
        "GRAPH_EDGE": values.get("type"),
        "GRAPH_EDGE_ORIGIN": (
            f"Graph edge {values.get('disposition', 'origin').lower()} · "
            f"{values.get('sourceDisplayName', 'source')}"
        ),
        "FINDING": values.get("title"),
        "EVIDENCE_METADATA": f"{values.get('kind', 'Evidence')} evidence",
        "REMEDIATION": f"{values.get('action', 'Remediation')} · {values.get('status', 'UNKNOWN')}",
        "AUDIT_RUN": f"Audit checkpoint {values.get('sequence', '?')}",
        "DOCUMENT_SEGMENT": (
            f"{values.get('displayName', 'Document')} · segment {values.get('segmentIndex', '?')}"
        ),
    }
    label = _bounded_text(label_candidates.get(kind) or kind.replace("_", " ").title(), 240)
    locator_parts = [reference]
    if kind == "GRAPH_EDGE":
        locator_parts.append(f"{values.get('fromRef', '?')} → {values.get('toRef', '?')}")
    if values.get("sourceId"):
        locator_parts.append(f"source {values['sourceId']}")
    if values.get("artifactId"):
        locator_parts.append(f"artifact {values['artifactId']}")
    if values.get("segmentId"):
        locator_parts.append(f"segment {values['segmentId']}")
    if values.get("segmentLocator"):
        locator_parts.append(f"locator {values['segmentLocator']}")
    if values.get("sourceSpanStart") is not None:
        locator_parts.append(f"span {values['sourceSpanStart']}-{values.get('sourceSpanEnd', '?')}")
    if values.get("providerId"):
        locator_parts.append(f"provider {values['providerId']}")
    if values.get("runId"):
        locator_parts.append(f"run {values['runId']}")
    content_sha256 = values.get("sourceSha256") or values.get("contentSha256")
    if content_sha256:
        locator_parts.append(f"sha256 {content_sha256}")
    if values.get("sourceUrlSha256"):
        locator_parts.append(f"URL sha256 {values['sourceUrlSha256']}")
    source_url = values.get("sourceUrl")
    return LocalAIWorkspaceSource(
        ref=reference,
        kind=kind,
        label=label,
        locator=_bounded_text(" · ".join(locator_parts), 600),
        source_url=str(source_url) if isinstance(source_url, str) else None,
        content_sha256=str(content_sha256) if content_sha256 else None,
        provider_id=str(values["providerId"]) if values.get("providerId") else None,
        source_id=str(values["sourceId"]) if values.get("sourceId") else None,
        source_display_name=(
            str(values["sourceDisplayName"]) if values.get("sourceDisplayName") else None
        ),
        artifact_id=str(values["artifactId"]) if values.get("artifactId") else None,
        segment_id=str(values["segmentId"]) if values.get("segmentId") else None,
        segment_index=(
            int(values["segmentIndex"]) if values.get("segmentIndex") is not None else None
        ),
        segment_locator=(str(values["segmentLocator"]) if values.get("segmentLocator") else None),
        source_span_start=(
            int(values["sourceSpanStart"]) if values.get("sourceSpanStart") is not None else None
        ),
        source_span_end=(
            int(values["sourceSpanEnd"]) if values.get("sourceSpanEnd") is not None else None
        ),
        extraction_run_id=(
            str(values["extractionRunId"]) if values.get("extractionRunId") else None
        ),
        extractor_kind=(str(values["extractorKind"]) if values.get("extractorKind") else None),
        extractor_name=(str(values["extractorName"]) if values.get("extractorName") else None),
        extractor_version=(
            str(values["extractorVersion"]) if values.get("extractorVersion") else None
        ),
        run_id=str(values["runId"]) if values.get("runId") else None,
        origin_kind=str(values["originKind"]) if values.get("originKind") else None,
        origin_type=str(values["originType"]) if values.get("originType") else None,
        observed_at_us=(
            int(str(values.get("observedAtUs", values.get("capturedAtUs"))))
            if values.get("observedAtUs", values.get("capturedAtUs")) is not None
            else None
        ),
        confidence_micros=(
            int(values["confidenceMicros"]) if values.get("confidenceMicros") is not None else None
        ),
        disposition=str(values["disposition"]) if values.get("disposition") else None,
        source_url_sha256=(
            str(values["sourceUrlSha256"]) if values.get("sourceUrlSha256") else None
        ),
        capture_method=(str(values["captureMethod"]) if values.get("captureMethod") else None),
        http_status=(int(values["httpStatus"]) if values.get("httpStatus") is not None else None),
        redirect_count=(
            int(values["redirectCount"]) if values.get("redirectCount") is not None else None
        ),
    )


def _record_text(record: dict[str, object]) -> str:
    return _canonical(record.get("data", {}))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.casefold() for token in _WORD.findall(value) if token.casefold() not in _STOP_WORDS
    )


def _summary_item(record: dict[str, object]) -> str:
    data = record.get("data")
    values = data if isinstance(data, dict) else {}
    kind = str(record["kind"]).replace("_", " ").title()
    for key in ("title", "value", "label", "text", "action", "runState"):
        if key in values and values[key] not in {None, ""}:
            return f"{kind}: {_bounded_text(values[key], 300)}"
    return f"{kind}: {record['ref']}"


def _section_item_for(
    record: dict[str, object],
    *,
    text: str | None = None,
) -> LocalAIWorkspaceSectionItem:
    return LocalAIWorkspaceSectionItem(
        text=_summary_item(record) if text is None else _bounded_text(text, 600),
        evidence_refs=(str(record["ref"]),),
    )


def _fact_for(record: dict[str, object]) -> LocalAIWorkspaceFact:
    data = record.get("data")
    values = data if isinstance(data, dict) else {}
    ref = str(record["ref"])
    kind = str(record["kind"])
    if kind == "FINDING":
        statement = (
            f"{_bounded_text(values.get('title', 'Finding'), 220)} — "
            f"{values.get('outcome', 'UNKNOWN')}, severity {values.get('severity', 'UNKNOWN')}."
        )
        confidence = LocalAIWorkspaceConfidence.MEDIUM
    elif kind == "REMEDIATION":
        statement = (
            f"Remediation action {values.get('action', 'UNKNOWN')} is "
            f"{values.get('status', 'UNKNOWN')}."
        )
        confidence = LocalAIWorkspaceConfidence.HIGH
    elif kind == "AUDIT_RUN":
        statement = (
            f"Audit checkpoint {values.get('sequence', '?')} is "
            f"{values.get('runState', 'UNKNOWN')} "
            f"with {values.get('findingCount', 0)} finding records."
        )
        confidence = LocalAIWorkspaceConfidence.HIGH
    elif kind == "GRAPH_EDGE":
        statement = (
            f"The stored graph contains a {values.get('type', 'relationship')} edge with "
            f"{values.get('confidenceMicros', 0)} micros confidence."
        )
        confidence = LocalAIWorkspaceConfidence.MEDIUM
    elif kind == "ENTITY":
        statement = (
            f"A {values.get('type', 'OTHER')} entity is stored as "
            f"{_bounded_text(values.get('value', '[masked]'), 260)} and reviewed "
            f"{values.get('reviewState', 'UNREVIEWED')}."
        )
        confidence = LocalAIWorkspaceConfidence.HIGH
    elif kind == "DOCUMENT_SEGMENT":
        statement = f"Document excerpt: {_bounded_text(values.get('text', ''), 520)}"
        confidence = LocalAIWorkspaceConfidence.MEDIUM
    else:
        statement = _summary_item(record)
        confidence = LocalAIWorkspaceConfidence.MEDIUM
    return LocalAIWorkspaceFact(
        statement=statement,
        evidence_refs=(ref,),
        confidence=confidence,
    )


def _connection_for(
    record: dict[str, object],
    *,
    allowed_refs: frozenset[str],
) -> LocalAIWorkspaceConnection | None:
    if record.get("kind") != "GRAPH_EDGE":
        return None
    data = record.get("data")
    values = data if isinstance(data, dict) else {}
    edge_ref = str(record["ref"])
    from_ref = str(values.get("fromRef", ""))
    to_ref = str(values.get("toRef", ""))
    if edge_ref not in allowed_refs or from_ref not in allowed_refs or to_ref not in allowed_refs:
        return None
    confidence_micros = int(values.get("confidenceMicros", 0))
    confidence = (
        LocalAIWorkspaceConfidence.HIGH
        if confidence_micros >= 800_000
        else (
            LocalAIWorkspaceConfidence.MEDIUM
            if confidence_micros >= 500_000
            else LocalAIWorkspaceConfidence.LOW
        )
    )
    relationship = _bounded_text(values.get("type", "POSSIBLE_CONNECTION"), 96)
    explanation = _bounded_text(values.get("explanation", "Stored graph relationship."), 500)
    return LocalAIWorkspaceConnection(
        from_ref=from_ref,
        to_ref=to_ref,
        relationship=relationship,
        supporting_refs=(edge_ref,),
        contradiction_refs=(),
        confidence=confidence,
        rationale=explanation,
        verification_suggestion=(
            "Review the cited graph edge and its underlying provenance before confirming "
            "this relationship."
        ),
    )


def _gap_steps(records: tuple[dict[str, object], ...]) -> tuple[LocalAIWorkspaceNextStep, ...]:
    steps: list[LocalAIWorkspaceNextStep] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        data = record.get("data")
        values = data if isinstance(data, dict) else {}
        reference = str(record["ref"])
        if record.get("kind") == "FINDING":
            attribution = values.get("attribution")
            attribution_values = attribution if isinstance(attribution, dict) else {}
            missing = attribution_values.get("missingEvidence")
            if isinstance(missing, list):
                for signal in missing:
                    signal_text = _bounded_text(signal, 96)
                    key = (reference, signal_text)
                    if key in seen:
                        continue
                    seen.add(key)
                    severity = str(values.get("severity", "INFO"))
                    steps.append(
                        LocalAIWorkspaceNextStep(
                            priority=1 if severity in {"CRITICAL", "HIGH"} else 2,
                            suggestion=f"Verify or collect evidence for {signal_text}.",
                            rationale=(
                                "The cited finding's current attribution assessment marks this "
                                "evidence category as missing."
                            ),
                            supporting_refs=(reference,),
                        )
                    )
        elif record.get("kind") == "ENTITY" and values.get("reviewState") == "UNREVIEWED":
            steps.append(
                LocalAIWorkspaceNextStep(
                    priority=2,
                    suggestion="Review this extracted entity before using it in searches.",
                    rationale="The cited entity is still marked UNREVIEWED.",
                    supporting_refs=(reference,),
                )
            )
        if len(steps) >= 16:
            break
    return tuple(sorted(steps, key=lambda item: item.priority)[:16])


def _deterministic_analysis(
    body: LocalAIWorkspaceRequest,
    projection: _Projection,
) -> _AnalysisContent:
    records = tuple(
        item
        for item in projection.records
        if item["kind"]
        not in {"PROFILE", "ENTITY_ORIGIN", "GRAPH_EDGE_ORIGIN", "EVIDENCE_METADATA"}
    )
    by_kind = Counter(str(item["kind"]) for item in records)
    limitations = [
        "Deterministic mode groups and retrieves stored records; it does not infer unstated facts.",
        "Evidence content bytes are excluded; only selected metadata and record references "
        "are available.",
    ]
    if projection.truncated:
        limitations.append(
            "The bounded projection omitted records; counts show the available scope."
        )
    if projection.restricted_values_redacted:
        limitations.append(
            "Restricted values detected in the document were redacted before analysis."
        )

    if body.task is LocalAIWorkspaceTask.QUESTION:
        question_tokens = _tokens(body.question or "")
        ranked = sorted(
            (
                (len(question_tokens & _tokens(_record_text(record))), index, record)
                for index, record in enumerate(records)
            ),
            key=lambda item: (-item[0], item[1]),
        )
        matches = tuple(item[2] for item in ranked if item[0] > 0)[:8]
        if not matches:
            return _AnalysisContent(
                title="No grounded answer found",
                summary=(
                    "The selected local records do not contain a deterministic match for "
                    "this question."
                ),
                sections=(),
                facts=(),
                connections=(),
                next_steps=(),
                unanswered=("No selected record contained enough matching terms to answer safely."),
                limitations=tuple(limitations),
            )
        return _AnalysisContent(
            title="Grounded local answer",
            summary=(f"Found {len(matches)} selected records with terms relevant to the question."),
            sections=(
                LocalAIWorkspaceSection(
                    heading="Matching records",
                    items=tuple(_section_item_for(item) for item in matches),
                ),
            ),
            facts=tuple(_fact_for(item) for item in matches),
            connections=(),
            next_steps=(),
            unanswered=None,
            limitations=tuple(limitations),
        )

    if body.task is LocalAIWorkspaceTask.CONNECTIONS:
        allowed_refs = frozenset(projection.references)
        connections = tuple(
            connection
            for record in records
            if (connection := _connection_for(record, allowed_refs=allowed_refs)) is not None
        )[:16]
        return _AnalysisContent(
            title="Review possible connections",
            summary=(
                f"Found {len(connections)} bounded graph relationships with cited endpoints and "
                "support. No connection was confirmed or persisted by this analysis."
            ),
            sections=(
                ()
                if not connections
                else (
                    LocalAIWorkspaceSection(
                        heading="Connection candidates",
                        items=tuple(
                            LocalAIWorkspaceSectionItem(
                                text=(f"{item.from_ref} → {item.relationship} → {item.to_ref}"),
                                evidence_refs=tuple(
                                    dict.fromkeys(
                                        (
                                            item.from_ref,
                                            item.to_ref,
                                            *item.supporting_refs,
                                            *item.contradiction_refs,
                                        )
                                    )
                                )[:8],
                            )
                            for item in connections
                        ),
                    ),
                )
            ),
            facts=tuple(
                _fact_for(record) for record in records if record.get("kind") == "GRAPH_EDGE"
            )[:12],
            connections=connections,
            next_steps=(),
            unanswered=(
                None
                if connections
                else "No fully projected graph edge connected two selected record references."
            ),
            limitations=tuple(limitations),
        )

    if body.task is LocalAIWorkspaceTask.GAP_ANALYSIS:
        next_steps = _gap_steps(records)
        return _AnalysisContent(
            title="Evidence gap analysis",
            summary=(
                f"Identified {len(next_steps)} review or evidence suggestions from explicit stored "
                "states. These are drafts only; no search or change was executed."
            ),
            sections=(
                ()
                if not next_steps
                else (
                    LocalAIWorkspaceSection(
                        heading="Prioritized verification",
                        items=tuple(
                            LocalAIWorkspaceSectionItem(
                                text=f"P{item.priority} · {item.suggestion}",
                                evidence_refs=item.supporting_refs,
                            )
                            for item in next_steps
                        ),
                    ),
                )
            ),
            facts=(),
            connections=(),
            next_steps=next_steps,
            unanswered=(
                None
                if next_steps
                else "No explicit missing-evidence or unreviewed-entity state was selected."
            ),
            limitations=tuple(limitations),
        )

    facts = tuple(_fact_for(item) for item in records[:12])
    if body.task is LocalAIWorkspaceTask.ORGANIZE:
        organized_sections = tuple(
            LocalAIWorkspaceSection(
                heading=kind.replace("_", " ").title(),
                items=tuple(
                    _section_item_for(item) for item in records if str(item["kind"]) == kind
                )[:12],
            )
            for kind in sorted(by_kind)
            if by_kind[kind] > 0
        )[:8]
        return _AnalysisContent(
            title="Organized local records",
            summary=(
                f"Organized {len(records)} selected records into "
                f"{len(organized_sections)} bounded groups."
            ),
            sections=organized_sections,
            facts=facts,
            connections=(),
            next_steps=(),
            unanswered=None,
            limitations=tuple(limitations),
        )

    coverage_items = tuple(
        _section_item_for(
            next(item for item in records if str(item["kind"]) == kind),
            text=f"{kind.replace('_', ' ').title()}: {count} included",
        )
        for kind, count in sorted(by_kind.items())
        if count
    )[:12]
    sections: tuple[LocalAIWorkspaceSection, ...] = (
        ()
        if not coverage_items
        else (LocalAIWorkspaceSection(heading="Selected record coverage", items=coverage_items),)
    )
    return _AnalysisContent(
        title="Local profile summary",
        summary=(
            f"The selected workspace contains {len(records)} bounded records across "
            f"{len(by_kind)} record types. Review the cited records before relying on conclusions."
        ),
        sections=sections,
        facts=facts,
        connections=(),
        next_steps=(),
        unanswered=None,
        limitations=tuple(limitations),
    )
