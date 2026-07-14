"""Atomic profile-scoped intake, identity, provenance, review, and graph persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field

from sqlalchemy import Connection, and_, exists, func, insert, or_, select, update
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.sql import FromClause
from uuid6 import uuid7

from ariadne_core.domain.identity_compiler import IdentityCompilerError, detect_restricted_values
from ariadne_core.infrastructure.db.models import (
    audit_events,
    entities,
    entity_decisions,
    entity_origins,
    entity_variant_decisions,
    entity_variants,
    extraction_runs,
    graph_edge_decisions,
    graph_edge_origins,
    graph_edges,
    graph_nodes,
    intake_segments,
    intake_sources,
    profiles,
    quarantine_items,
)
from ariadne_core.infrastructure.db.repositories import RevisionConflict, _append_event, now_us

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_CONTENT_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_PROFILE_STATES = frozenset({"DRAFT", "ACTIVE", "ARCHIVED", "PURGE_PENDING"})
_SOURCE_KINDS = frozenset({"PASTE", "FILE", "EXPORT", "CONNECTOR", "MANUAL_EVIDENCE"})
_RETENTION_STATES = frozenset({"TEMPORARY", "RETAINED", "PURGE_PENDING"})
_SEGMENT_KINDS = frozenset({"TEXT", "RECORD", "CONTACT", "JSON_VALUE", "FILE_MEMBER"})
_QUARANTINE_REASONS = frozenset(
    {
        "RESTRICTED_VALUE",
        "MIME_MISMATCH",
        "ACTIVE_CONTENT",
        "SIZE_LIMIT",
        "MALFORMED",
        "UNSAFE_ARCHIVE",
    }
)
_ENGINE_KINDS = frozenset({"DETERMINISTIC", "LOCAL_MODEL"})
_EXTRACTION_STATES = frozenset(
    {"DRAFT", "QUEUED", "RUNNING", "PAUSED", "CANCELLED", "SUCCEEDED", "PARTIAL", "FAILED"}
)
_ENTITY_TYPES = frozenset(
    {
        "PERSON",
        "ALIAS",
        "USERNAME",
        "EMAIL",
        "TELEPHONE",
        "ADDRESS",
        "LOCATION",
        "ORGANISATION",
        "EMPLOYMENT",
        "EDUCATION",
        "DOMAIN",
        "URL",
        "PLATFORM_ACCOUNT",
        "COMPANY",
        "PROJECT",
        "IMAGE",
        "DOCUMENT",
        "DATE",
        "IP_ADDRESS",
        "COORDINATE",
        "COMPANY_NUMBER",
        "PLATFORM_ID",
        "POSTAL_CODE",
        "WALLET_ADDRESS",
        "OTHER",
    }
)
_SENSITIVITIES = frozenset({"PUBLIC", "SENSITIVE", "HIGHLY_SENSITIVE"})
_REVIEW_STATES = frozenset(
    {"UNREVIEWED", "CONFIRMED", "PROBABLE", "POSSIBLE", "FALSE_POSITIVE", "EXCLUDED"}
)
_TEMPORAL_STATES = frozenset({"CURRENT", "HISTORICAL", "UNKNOWN"})
_SEARCH_POLICIES = frozenset({"SEARCH_ALLOWED", "APPROVAL_REQUIRED", "STORE_ONLY", "SEARCH_DENIED"})
_TRANSMISSION_POLICIES = frozenset(
    {"LOCAL_ONLY", "APPROVAL_REQUIRED", "PROVIDER_ALLOWLIST", "TRANSMISSION_DENIED"}
)
_VARIANT_TYPES = frozenset(
    {
        "EXACT",
        "CASE",
        "SEPARATOR",
        "TRANSLITERATION",
        "DIACRITIC",
        "NATIONAL_FORMAT",
        "E164",
        "LOCAL_PART",
        "DOMAIN",
        "CONTROLLED_TYPO",
        "OTHER",
    }
)
_RISKS = frozenset({"LOW", "MEDIUM", "HIGH"})
_ORIGIN_KINDS = frozenset({"USER_INPUT", "DETERMINISTIC", "LOCAL_MODEL", "MANUAL"})
_VISIBILITIES = frozenset(
    {
        "PUBLICLY_ATTRIBUTABLE",
        "PUBLIC_PSEUDONYMOUS",
        "PRIVATELY_LINKABLE",
        "HISTORICAL_RESIDUE",
        "PRIVATE_ONLY",
        "UNKNOWN",
    }
)
_EDGE_TYPES = frozenset(
    {
        "OWNS",
        "USED",
        "RECOVERY_FOR",
        "EMPLOYED_BY",
        "STUDIED_AT",
        "LIVED_AT",
        "LOCATED_IN",
        "LINKS_TO",
        "MENTIONS",
        "AUTHORED",
        "CREATED",
        "MIRRORS",
        "REPOSTS",
        "SAME_AS",
        "POSSIBLY_SAME_AS",
        "NOT_SAME_AS",
        "PREVIOUS_USERNAME",
        "CURRENT_USERNAME",
        "FOUND_BY",
        "SUPPORTED_BY",
        "CONTRADICTED_BY",
        "REMOVAL_REQUEST_FOR",
    }
)
_EDGE_ORIGINS = frozenset({"HUMAN", "DETERMINISTIC", "LOCAL_MODEL", "PROVIDER"})
_EDGE_DISPOSITIONS = frozenset({"SUPPORTS", "CONTRADICTS"})
_DECISION_TYPES = frozenset(
    {"CONFIRM", "REJECT", "EXCLUDE", "EDIT", "MERGE", "SPLIT", "CLASSIFY", "POLICY_CHANGE"}
)
_VARIANT_DECISION_TYPES = frozenset({"APPROVE", "REVOKE", "RERANK", "EXCLUDE"})
_EDGE_DECISION_TYPES = frozenset({"CONFIRM", "REJECT", "CORRECT", "EXCLUDE"})
_EDGE_REVIEW_STATES = frozenset({"UNREVIEWED", "CONFIRMED", "REJECTED", "EXCLUDED"})
_LOCAL_AI_INTAKE_STATES = frozenset(
    {"NOT_REQUESTED", "DISABLED", "SUCCEEDED", "TIMEOUT", "UNAVAILABLE", "INVALID_RESPONSE"}
)
_LOCAL_AI_PROVIDERS = frozenset({"OLLAMA", "OPENAI_COMPATIBLE"})
ENTITY_ORIGIN_PROJECTION_LIMIT = 32
ENTITY_ORIGIN_PAGE_LIMIT = 12


def _bounded(value: str, *, label: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    if _CONTROL.search(value):
        raise ValueError(f"{label} contains control characters")
    return value


def _member(value: str, allowed: frozenset[str], *, label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} is invalid")
    return value


def _safe_provenance_text(value: str, *, fallback: str) -> str:
    """Return metadata only when it does not itself contain a restricted value."""

    try:
        scan = detect_restricted_values(value)
    except IdentityCompilerError:
        return fallback
    return fallback if scan.has_restricted_values else value


def _validate_entity_policy(
    *,
    review_state: str,
    sensitivity: str,
    search_policy: str,
    transmission_policy: str,
) -> None:
    if review_state in {"FALSE_POSITIVE", "EXCLUDED"} and (
        search_policy != "SEARCH_DENIED" or transmission_policy != "TRANSMISSION_DENIED"
    ):
        raise ValueError("negatively reviewed entities must remain search and transmission denied")
    if sensitivity == "HIGHLY_SENSITIVE" and (
        search_policy == "SEARCH_ALLOWED" or transmission_policy == "PROVIDER_ALLOWLIST"
    ):
        raise ValueError("highly sensitive entity policy requires explicit approval")


def _bounded_content(value: str, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("segment content is invalid")
    if _UNSAFE_CONTENT_CONTROL.search(value):
        raise ValueError("segment content contains unsafe control characters")
    return value


def _digest(value: str | None, *, label: str, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if value is None or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _validate_enrichment_outcome(outcome: EnrichmentOutcomeDraft) -> None:
    _member(outcome.status, _LOCAL_AI_INTAKE_STATES, label="local AI intake status")
    if outcome.suggestion_count < 0 or outcome.suggestion_count > 64:
        raise ValueError("local AI suggestion count is outside the allowed range")
    attempted = outcome.status not in {"NOT_REQUESTED", "DISABLED"}
    if attempted:
        if outcome.provider is None or outcome.model_id is None or outcome.engine_version is None:
            raise ValueError("attempted local AI enrichment requires engine identity")
        _member(outcome.provider, _LOCAL_AI_PROVIDERS, label="local AI provider")
        _bounded(outcome.model_id, label="local AI model", maximum=256)
        _bounded(outcome.engine_version, label="local AI engine version", maximum=48)
    elif any(
        value is not None for value in (outcome.provider, outcome.model_id, outcome.engine_version)
    ):
        raise ValueError("inactive local AI enrichment cannot carry engine identity")
    if outcome.status != "SUCCEEDED" and outcome.suggestion_count != 0:
        raise ValueError("failed local AI enrichment cannot carry suggestions")


def _read_enrichment_outcome(metadata_json: object) -> EnrichmentOutcomeDraft:
    if metadata_json is None:
        return EnrichmentOutcomeDraft()
    try:
        metadata = json.loads(str(metadata_json))
    except (TypeError, ValueError):
        raise RuntimeError("intake compilation audit event is malformed") from None
    if not isinstance(metadata, dict) or "localAIStatus" not in metadata:
        return EnrichmentOutcomeDraft()
    values = (
        metadata.get("localAIStatus"),
        metadata.get("localAIProvider"),
        metadata.get("localAIModel"),
        metadata.get("localAIEngineVersion"),
        metadata.get("localAISuggestionCount"),
    )
    status, provider, model_id, engine_version, suggestion_count = values
    if (
        not isinstance(status, str)
        or (provider is not None and not isinstance(provider, str))
        or (model_id is not None and not isinstance(model_id, str))
        or (engine_version is not None and not isinstance(engine_version, str))
        or not isinstance(suggestion_count, int)
        or isinstance(suggestion_count, bool)
    ):
        raise RuntimeError("intake compilation audit event is malformed")
    outcome = EnrichmentOutcomeDraft(
        status=status,
        provider=provider,
        model_id=model_id,
        engine_version=engine_version,
        suggestion_count=suggestion_count,
    )
    try:
        _validate_enrichment_outcome(outcome)
    except ValueError:
        raise RuntimeError("intake compilation audit event is malformed") from None
    return outcome


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    id: str
    vault_id: str
    display_label: str = field(repr=False)
    purpose: str = field(repr=False)
    status: str
    revision: int


@dataclass(frozen=True, slots=True)
class SourceDraft:
    source_kind: str
    display_name: str = field(repr=False)
    detected_mime: str
    byte_size: int
    sha256: str
    retention_state: str
    consent_confirmed_at_us: int
    retention_expires_at_us: int | None = None
    broker_handle: str | None = None
    declared_mime: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    ordinal: int
    segment_kind: str
    locator_json: str = field(repr=False)
    content_text: str | None = field(default=None, repr=False)
    language: str | None = None


@dataclass(frozen=True, slots=True)
class QuarantineDraft:
    reason_code: str
    retention_expires_at_us: int
    opaque_blob_key: str | None = None
    mime_type: str | None = None
    byte_size_plaintext: int | None = None
    byte_size_ciphertext: int | None = None
    sha256_plaintext: str | None = None
    sha256_ciphertext: str | None = None
    encryption_version: str | None = None
    key_version: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractionDraft:
    job_id: str
    engine_kind: str
    engine_name: str
    engine_version: str
    configuration_hash: str
    state: str = "SUCCEEDED"
    started_at_us: int | None = None
    finished_at_us: int | None = None


@dataclass(frozen=True, slots=True)
class EnrichmentOutcomeDraft:
    status: str = "NOT_REQUESTED"
    provider: str | None = None
    model_id: str | None = None
    engine_version: str | None = None
    suggestion_count: int = 0


@dataclass(frozen=True, slots=True)
class VariantDraft:
    variant_type: str
    value: str = field(repr=False)
    generator: str
    generator_version: str
    rank: int
    estimated_risk: str
    approved_for_search: bool = False


@dataclass(frozen=True, slots=True)
class EntityOriginDraft:
    source_segment_ordinal: int
    origin_kind: str
    confidence_micros: int
    explanation: str
    source_span_start: int | None = None
    source_span_end: int | None = None


@dataclass(frozen=True, slots=True)
class EntityDraft:
    local_key: str
    source_segment_ordinal: int
    entity_type: str
    canonical_value: str = field(repr=False)
    display_mask: str = field(repr=False)
    sensitivity: str
    review_state: str
    temporal_state: str
    search_policy: str
    transmission_policy: str
    origin_kind: str
    origin_confidence_micros: int
    origin_explanation: str
    source_span_start: int | None = None
    source_span_end: int | None = None
    valid_from_us: int | None = None
    valid_to_us: int | None = None
    variants: tuple[VariantDraft, ...] = field(default_factory=tuple)
    graph_node_type: str | None = None
    graph_visibility: str = "UNKNOWN"
    origins: tuple[EntityOriginDraft, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class EdgeDraft:
    from_entity_key: str
    to_entity_key: str
    edge_type: str
    confidence_micros: int
    visibility: str
    observed_at_us: int
    origin_type: str
    explanation: str
    valid_from_us: int | None = None
    valid_to_us: int | None = None
    source_segment_ordinal: int = 0
    disposition: str = "SUPPORTS"
    source_span_start: int | None = None
    source_span_end: int | None = None


@dataclass(frozen=True, slots=True)
class CompilationRecord:
    source_id: str
    extraction_run_id: str
    segment_ids: tuple[tuple[int, str], ...]
    quarantine_ids: tuple[str, ...]
    entity_ids: tuple[tuple[str, str], ...]
    graph_node_ids: tuple[tuple[str, str], ...]
    graph_edge_ids: tuple[str, ...]
    duplicate_entity_count: int = 0
    duplicate_variant_count: int = 0
    duplicate_edge_count: int = 0


@dataclass(frozen=True, slots=True)
class EntityOriginSummary:
    source_id: str
    source_display_name: str = field(repr=False)
    source_sha256: str
    segment_id: str
    segment_index: int
    segment_locator: str = field(repr=False)
    source_span_start: int | None
    source_span_end: int | None
    extraction_run_id: str | None
    extractor_kind: str | None
    extractor_name: str | None
    extractor_version: str | None
    origin_kind: str
    observed_at_us: int
    confidence_micros: int
    explanation: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class EntitySummary:
    id: str
    entity_type: str
    display_mask: str = field(repr=False)
    sensitivity: str
    review_state: str
    temporal_state: str
    search_policy: str
    transmission_policy: str
    confidence_micros: int
    provenance_label: str = field(repr=False)
    origins: tuple[EntityOriginSummary, ...] = field(repr=False)
    origins_truncated: bool
    revision: int


@dataclass(frozen=True, slots=True)
class SourceSummary:
    id: str
    profile_id: str
    source_kind: str
    segment_count: int
    entity_count: int
    quarantine_count: int
    revision: int
    local_ai_status: str = "NOT_REQUESTED"
    local_ai_provider: str | None = None
    local_ai_model: str | None = None
    local_ai_engine_version: str | None = None
    local_ai_suggestion_count: int = 0


@dataclass(frozen=True, slots=True)
class VariantSummary:
    id: str
    entity_id: str
    variant_type: str
    rank: int
    estimated_risk: str
    approved_for_search: bool
    revision: int


@dataclass(frozen=True, slots=True)
class GraphNodeSummary:
    id: str
    node_type: str
    display_label: str = field(repr=False)
    sensitivity: str
    visibility: str
    entity_id: str | None


@dataclass(frozen=True, slots=True)
class GraphEdgeSummary:
    id: str
    from_node_id: str
    to_node_id: str
    edge_type: str
    confidence_micros: int
    visibility: str
    review_state: str
    origin_type: str
    explanation: str = field(repr=False)
    revision: int
    support_count: int = 0
    contradiction_count: int = 0
    evidence: tuple[GraphEdgeEvidenceSummary, ...] = field(default_factory=tuple, repr=False)
    evidence_truncated: bool = False


@dataclass(frozen=True, slots=True)
class GraphEdgeEvidenceSummary:
    source_id: str
    segment_ordinal: int
    disposition: str
    confidence_micros: int
    visibility: str
    source_span_start: int | None
    source_span_end: int | None
    observed_at_us: int
    origin_type: str
    explanation: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    nodes: tuple[GraphNodeSummary, ...]
    edges: tuple[GraphEdgeSummary, ...]


class IntakeIdentityRepository:
    """One profile-scoped persistence boundary; fingerprint material never leaves memory."""

    def __init__(self, engine: Engine, *, fingerprint_key: bytes | bytearray) -> None:
        if len(fingerprint_key) != 32:
            raise ValueError("fingerprint HMAC key must contain exactly 256 bits")
        self.engine = engine
        self._fingerprint_key = bytearray(fingerprint_key)
        self._closed = False

    def close(self) -> None:
        self._fingerprint_key[:] = b"\x00" * len(self._fingerprint_key)
        self._closed = True

    def _fingerprint(self, value: str) -> str:
        if self._closed:
            raise RuntimeError("repository fingerprint key is unavailable")
        return hmac.new(
            self._fingerprint_key,
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def create_profile(
        self,
        *,
        vault_id: str,
        display_label: str,
        purpose: str,
        status: str = "ACTIVE",
        profile_id: str | None = None,
    ) -> ProfileRecord:
        display_label = _bounded(display_label, label="profile display label", maximum=128)
        purpose = _bounded(purpose, label="profile purpose", maximum=512)
        status = _member(status, _PROFILE_STATES, label="profile status")
        profile_id = str(uuid7()) if profile_id is None else profile_id
        timestamp = now_us()
        with self.engine.begin() as connection:
            connection.execute(
                insert(profiles).values(
                    id=profile_id,
                    vault_id=vault_id,
                    display_label=display_label,
                    purpose=purpose,
                    status=status,
                    correlation_boundary="ISOLATED",
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                )
            )
            _append_event(
                connection,
                vault_id=vault_id,
                event_type="PROFILE_CREATED",
                target_type="PROFILE",
                target_id=profile_id,
                resource_revision=1,
                metadata={"status": status},
            )
        return ProfileRecord(profile_id, vault_id, display_label, purpose, status, 1)

    def get_profile(self, vault_id: str, profile_id: str) -> ProfileRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(profiles).where(
                        and_(
                            profiles.c.vault_id == vault_id,
                            profiles.c.id == profile_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError("profile is unavailable in this vault")
        return ProfileRecord(
            id=str(row["id"]),
            vault_id=str(row["vault_id"]),
            display_label=str(row["display_label"]),
            purpose=str(row["purpose"]),
            status=str(row["status"]),
            revision=int(row["revision"]),
        )

    def list_profiles(self, vault_id: str, *, limit: int) -> tuple[ProfileRecord, ...]:
        if limit < 1 or limit > 101:
            raise ValueError("profile list limit is invalid")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(profiles)
                    .where(profiles.c.vault_id == vault_id)
                    .order_by(profiles.c.updated_at_us.desc(), profiles.c.id.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(
            ProfileRecord(
                id=str(row["id"]),
                vault_id=str(row["vault_id"]),
                display_label=str(row["display_label"]),
                purpose=str(row["purpose"]),
                status=str(row["status"]),
                revision=int(row["revision"]),
            )
            for row in rows
        )

    def purge_expired_temporary_content(
        self,
        *,
        vault_id: str,
        timestamp_us: int | None = None,
    ) -> int:
        """Scrub expired source text while retaining contentless provenance anchors."""

        timestamp = now_us() if timestamp_us is None else timestamp_us
        purged = 0
        with self.engine.begin() as connection:
            expired_sources = (
                connection.execute(
                    select(
                        intake_sources.c.id,
                        intake_sources.c.profile_id,
                        intake_sources.c.revision,
                    ).where(
                        and_(
                            intake_sources.c.vault_id == vault_id,
                            intake_sources.c.retention_state == "TEMPORARY",
                            intake_sources.c.retention_expires_at_us.is_not(None),
                            intake_sources.c.retention_expires_at_us <= timestamp,
                            intake_sources.c.deleted_at_us.is_(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
            for source in expired_sources:
                source_id = str(source["id"])
                profile_id = str(source["profile_id"])
                segments = (
                    connection.execute(
                        select(
                            intake_segments.c.id,
                            intake_segments.c.locator_json,
                        ).where(
                            and_(
                                intake_segments.c.vault_id == vault_id,
                                intake_segments.c.profile_id == profile_id,
                                intake_segments.c.intake_source_id == source_id,
                                intake_segments.c.deleted_at_us.is_(None),
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                for segment in segments:
                    locator_json = str(segment["locator_json"])
                    connection.execute(
                        update(intake_segments)
                        .where(
                            and_(
                                intake_segments.c.vault_id == vault_id,
                                intake_segments.c.profile_id == profile_id,
                                intake_segments.c.id == str(segment["id"]),
                            )
                        )
                        .values(
                            content_text=None,
                            content_hmac=self._fingerprint(locator_json),
                        )
                    )
                next_revision = int(source["revision"]) + 1
                changed = connection.execute(
                    update(intake_sources)
                    .where(
                        and_(
                            intake_sources.c.vault_id == vault_id,
                            intake_sources.c.profile_id == profile_id,
                            intake_sources.c.id == source_id,
                            intake_sources.c.retention_state == "TEMPORARY",
                            intake_sources.c.revision == int(source["revision"]),
                        )
                    )
                    .values(
                        retention_state="PURGE_PENDING",
                        retention_expires_at_us=None,
                        updated_at_us=timestamp,
                        revision=next_revision,
                    )
                )
                if changed.rowcount != 1:
                    raise RevisionConflict("intake source retention revision is stale")
                _append_event(
                    connection,
                    vault_id=vault_id,
                    event_type="INTAKE_SOURCE_CONTENT_PURGED",
                    target_type="INTAKE_SOURCE",
                    target_id=source_id,
                    resource_revision=next_revision,
                    metadata={"segmentCount": len(segments)},
                )
                purged += 1
        return purged

    def persist_compilation(
        self,
        *,
        vault_id: str,
        profile_id: str,
        source: SourceDraft,
        extraction: ExtractionDraft,
        segments: Sequence[SegmentDraft],
        quarantine: Sequence[QuarantineDraft] = (),
        entities_input: Sequence[EntityDraft] = (),
        edges: Sequence[EdgeDraft] = (),
        enrichment_outcome: EnrichmentOutcomeDraft | None = None,
        connection: Connection | None = None,
    ) -> CompilationRecord:
        """Persist one bounded compiler result and its redacted event atomically."""

        enrichment_outcome = (
            EnrichmentOutcomeDraft() if enrichment_outcome is None else enrichment_outcome
        )
        self._validate_compilation(
            source,
            extraction,
            segments,
            quarantine,
            entities_input,
            edges,
            enrichment_outcome,
        )
        timestamp = now_us()
        source_id = str(uuid7())
        extraction_id = str(uuid7())
        segment_ids = {segment.ordinal: str(uuid7()) for segment in segments}
        quarantine_ids = tuple(str(uuid7()) for _ in quarantine)
        entity_ids: dict[str, str] = {}
        node_ids: dict[str, str] = {}
        edge_ids: list[str] = []
        duplicate_entity_count = 0
        duplicate_variant_count = 0
        duplicate_edge_count = 0

        transaction = self.engine.begin() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            self._insert_source(
                active_connection, vault_id, profile_id, source_id, source, timestamp
            )
            for segment in segments:
                active_connection.execute(
                    insert(intake_segments).values(
                        id=segment_ids[segment.ordinal],
                        vault_id=vault_id,
                        profile_id=profile_id,
                        intake_source_id=source_id,
                        ordinal=segment.ordinal,
                        segment_kind=segment.segment_kind,
                        content_text=segment.content_text,
                        content_hmac=self._fingerprint(
                            segment.content_text
                            if segment.content_text is not None
                            else segment.locator_json
                        ),
                        locator_json=segment.locator_json,
                        language=segment.language,
                        created_at_us=timestamp,
                        deleted_at_us=None,
                    )
                )
            for quarantine_id, item in zip(quarantine_ids, quarantine, strict=True):
                self._insert_quarantine(
                    active_connection,
                    vault_id,
                    profile_id,
                    source_id,
                    quarantine_id,
                    item,
                    timestamp,
                )
            active_connection.execute(
                insert(extraction_runs).values(
                    id=extraction_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    intake_source_id=source_id,
                    job_id=extraction.job_id,
                    engine_kind=extraction.engine_kind,
                    engine_name=extraction.engine_name,
                    engine_version=extraction.engine_version,
                    configuration_hash=extraction.configuration_hash,
                    state=extraction.state,
                    started_at_us=extraction.started_at_us,
                    finished_at_us=extraction.finished_at_us,
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                    deleted_at_us=None,
                )
            )
            for entity in entities_input:
                origins = self._entity_origins(entity)
                value_hmac = self._fingerprint(entity.canonical_value)
                stored = self._find_live_entity(
                    active_connection,
                    vault_id,
                    profile_id,
                    entity.entity_type,
                    value_hmac,
                )
                if stored is None:
                    entity_id = str(uuid7())
                    self._insert_entity(
                        active_connection,
                        vault_id,
                        profile_id,
                        entity_id,
                        entity,
                        value_hmac,
                        timestamp,
                    )
                    stored_sensitivity = entity.sensitivity
                    duplicate_entity_count += max(0, len(origins) - 1)
                else:
                    if str(stored["canonical_value"]) != entity.canonical_value:
                        raise RuntimeError("entity fingerprint collision")
                    entity_id = str(stored["id"])
                    stored_sensitivity = str(stored["sensitivity"])
                    duplicate_entity_count += len(origins)
                entity_ids[entity.local_key] = entity_id
                self._insert_entity_origins(
                    active_connection,
                    vault_id,
                    profile_id,
                    entity_id,
                    extraction_id,
                    segment_ids,
                    origins,
                    timestamp,
                )
                duplicate_variant_count += self._insert_missing_variants(
                    active_connection,
                    vault_id,
                    profile_id,
                    entity_id,
                    stored_sensitivity,
                    entity.variants,
                    timestamp,
                )
                if entity.graph_node_type is not None:
                    node_id = active_connection.execute(
                        select(graph_nodes.c.id).where(
                            and_(
                                graph_nodes.c.vault_id == vault_id,
                                graph_nodes.c.profile_id == profile_id,
                                graph_nodes.c.entity_id == entity_id,
                                graph_nodes.c.deleted_at_us.is_(None),
                            )
                        )
                    ).scalar_one_or_none()
                    if node_id is None:
                        node_id = str(uuid7())
                        active_connection.execute(
                            insert(graph_nodes).values(
                                id=node_id,
                                vault_id=vault_id,
                                profile_id=profile_id,
                                node_type=entity.graph_node_type,
                                display_label=entity.display_mask,
                                sensitivity=stored_sensitivity,
                                visibility=entity.graph_visibility,
                                entity_id=entity_id,
                                position_json=None,
                                created_at_us=timestamp,
                                updated_at_us=timestamp,
                                revision=1,
                                deleted_at_us=None,
                            )
                        )
                    node_ids[entity.local_key] = str(node_id)
            for edge in edges:
                from_node_id = node_ids[edge.from_entity_key]
                to_node_id = node_ids[edge.to_entity_key]
                if from_node_id == to_node_id:
                    duplicate_edge_count += 1
                    continue
                existing_edge_id = active_connection.execute(
                    select(graph_edges.c.id).where(
                        and_(
                            graph_edges.c.vault_id == vault_id,
                            graph_edges.c.profile_id == profile_id,
                            graph_edges.c.from_node_id == from_node_id,
                            graph_edges.c.to_node_id == to_node_id,
                            graph_edges.c.edge_type == edge.edge_type,
                            graph_edges.c.deleted_at_us.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if existing_edge_id is not None:
                    edge_id = str(existing_edge_id)
                    edge_ids.append(edge_id)
                    duplicate_edge_count += 1
                else:
                    edge_id = str(uuid7())
                    active_connection.execute(
                        insert(graph_edges).values(
                            id=edge_id,
                            vault_id=vault_id,
                            profile_id=profile_id,
                            from_node_id=from_node_id,
                            to_node_id=to_node_id,
                            edge_type=edge.edge_type,
                            confidence_micros=edge.confidence_micros,
                            visibility=edge.visibility,
                            valid_from_us=edge.valid_from_us,
                            valid_to_us=edge.valid_to_us,
                            observed_at_us=edge.observed_at_us,
                            origin_type=edge.origin_type,
                            explanation=edge.explanation,
                            review_state="UNREVIEWED",
                            current_decision_id=None,
                            created_at_us=timestamp,
                            updated_at_us=timestamp,
                            revision=1,
                            deleted_at_us=None,
                        )
                    )
                    edge_ids.append(edge_id)
                self._insert_edge_origin(
                    active_connection,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    source_id=source_id,
                    edge_id=edge_id,
                    extraction_id=extraction_id,
                    segment_id=segment_ids[edge.source_segment_ordinal],
                    edge=edge,
                    timestamp=timestamp,
                )
            _append_event(
                active_connection,
                vault_id=vault_id,
                event_type="INTAKE_COMPILATION_PERSISTED",
                target_type="INTAKE_SOURCE",
                target_id=source_id,
                resource_revision=1,
                metadata={
                    "edgeCount": len(edges),
                    "duplicateEdgeCount": duplicate_edge_count,
                    "duplicateEntityCount": duplicate_entity_count,
                    "duplicateVariantCount": duplicate_variant_count,
                    "entityCount": len(entities_input),
                    "localAIEngineVersion": enrichment_outcome.engine_version,
                    "localAIModel": enrichment_outcome.model_id,
                    "localAIProvider": enrichment_outcome.provider,
                    "localAIStatus": enrichment_outcome.status,
                    "localAISuggestionCount": enrichment_outcome.suggestion_count,
                    "quarantineCount": len(quarantine),
                    "segmentCount": len(segments),
                },
            )

        return CompilationRecord(
            source_id=source_id,
            extraction_run_id=extraction_id,
            segment_ids=tuple(sorted(segment_ids.items())),
            quarantine_ids=quarantine_ids,
            entity_ids=tuple(
                (item.local_key, entity_ids[item.local_key]) for item in entities_input
            ),
            graph_node_ids=tuple((key, node_ids[key]) for key in node_ids),
            graph_edge_ids=tuple(edge_ids),
            duplicate_entity_count=duplicate_entity_count,
            duplicate_variant_count=duplicate_variant_count,
            duplicate_edge_count=duplicate_edge_count,
        )

    def get_source_summary(
        self,
        vault_id: str,
        profile_id: str,
        source_id: str,
    ) -> SourceSummary:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(intake_sources).where(
                        and_(
                            intake_sources.c.vault_id == vault_id,
                            intake_sources.c.profile_id == profile_id,
                            intake_sources.c.id == source_id,
                            intake_sources.c.deleted_at_us.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError("intake source is unavailable in this profile")
            segment_count = connection.execute(
                select(func.count())
                .select_from(intake_segments)
                .where(
                    and_(
                        intake_segments.c.vault_id == vault_id,
                        intake_segments.c.profile_id == profile_id,
                        intake_segments.c.intake_source_id == source_id,
                        intake_segments.c.deleted_at_us.is_(None),
                    )
                )
            ).scalar_one()
            entity_count = connection.execute(
                select(func.count(func.distinct(entity_origins.c.entity_id)))
                .select_from(
                    entity_origins.join(
                        intake_segments,
                        and_(
                            intake_segments.c.vault_id == entity_origins.c.vault_id,
                            intake_segments.c.profile_id == entity_origins.c.profile_id,
                            intake_segments.c.id == entity_origins.c.intake_segment_id,
                        ),
                    )
                )
                .where(
                    and_(
                        entity_origins.c.vault_id == vault_id,
                        entity_origins.c.profile_id == profile_id,
                        intake_segments.c.intake_source_id == source_id,
                    )
                )
            ).scalar_one()
            quarantine_count = connection.execute(
                select(func.count())
                .select_from(quarantine_items)
                .where(
                    and_(
                        quarantine_items.c.vault_id == vault_id,
                        quarantine_items.c.profile_id == profile_id,
                        quarantine_items.c.intake_source_id == source_id,
                    )
                )
            ).scalar_one()
            metadata_json = connection.execute(
                select(audit_events.c.metadata_json).where(
                    and_(
                        audit_events.c.vault_id == vault_id,
                        audit_events.c.event_type == "INTAKE_COMPILATION_PERSISTED",
                        audit_events.c.target_type == "INTAKE_SOURCE",
                        audit_events.c.target_id == source_id,
                    )
                )
            ).scalar_one_or_none()
            enrichment_outcome = _read_enrichment_outcome(metadata_json)
        return SourceSummary(
            id=str(row["id"]),
            profile_id=str(row["profile_id"]),
            source_kind=str(row["source_kind"]),
            segment_count=int(segment_count),
            entity_count=int(entity_count),
            quarantine_count=int(quarantine_count),
            revision=int(row["revision"]),
            local_ai_status=enrichment_outcome.status,
            local_ai_provider=enrichment_outcome.provider,
            local_ai_model=enrichment_outcome.model_id,
            local_ai_engine_version=enrichment_outcome.engine_version,
            local_ai_suggestion_count=enrichment_outcome.suggestion_count,
        )

    def get_source_summary_by_job(
        self,
        vault_id: str,
        profile_id: str,
        job_id: str,
    ) -> SourceSummary | None:
        with self.engine.connect() as connection:
            source_id = connection.execute(
                select(extraction_runs.c.intake_source_id).where(
                    and_(
                        extraction_runs.c.vault_id == vault_id,
                        extraction_runs.c.profile_id == profile_id,
                        extraction_runs.c.job_id == job_id,
                        extraction_runs.c.deleted_at_us.is_(None),
                    )
                )
            ).scalar_one_or_none()
        if source_id is None:
            return None
        return self.get_source_summary(vault_id, profile_id, str(source_id))

    def get_source_id_by_job(
        self,
        vault_id: str,
        profile_id: str,
        job_id: str,
        *,
        connection: Connection | None = None,
    ) -> str | None:
        transaction = self.engine.connect() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            source_id = active_connection.execute(
                select(extraction_runs.c.intake_source_id).where(
                    and_(
                        extraction_runs.c.vault_id == vault_id,
                        extraction_runs.c.profile_id == profile_id,
                        extraction_runs.c.job_id == job_id,
                        extraction_runs.c.deleted_at_us.is_(None),
                    )
                )
            ).scalar_one_or_none()
        return None if source_id is None else str(source_id)

    def get_source_duplicate_count(
        self,
        vault_id: str,
        source_id: str,
        *,
        connection: Connection | None = None,
    ) -> int:
        """Return the original receipt count from its redacted durable audit event."""

        transaction = self.engine.connect() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            metadata_json = active_connection.execute(
                select(audit_events.c.metadata_json).where(
                    and_(
                        audit_events.c.vault_id == vault_id,
                        audit_events.c.event_type == "INTAKE_COMPILATION_PERSISTED",
                        audit_events.c.target_type == "INTAKE_SOURCE",
                        audit_events.c.target_id == source_id,
                    )
                )
            ).scalar_one_or_none()
        if metadata_json is None:
            raise LookupError("intake compilation audit event is unavailable")
        metadata = json.loads(str(metadata_json))
        duplicate_count = (
            metadata.get("duplicateEntityCount") if isinstance(metadata, dict) else None
        )
        if not isinstance(duplicate_count, int) or isinstance(duplicate_count, bool):
            raise RuntimeError("intake compilation audit event is malformed")
        if duplicate_count < 0:
            raise RuntimeError("intake compilation duplicate count is invalid")
        return duplicate_count

    def list_entities(
        self,
        vault_id: str,
        profile_id: str,
        *,
        limit: int = ENTITY_ORIGIN_PAGE_LIMIT,
        source_id: str | None = None,
    ) -> tuple[EntitySummary, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("entity list limit is outside the allowed range")
        source_match = None
        if source_id is not None:
            source_match = exists(
                select(entity_origins.c.id)
                .select_from(
                    entity_origins.join(
                        intake_segments,
                        and_(
                            intake_segments.c.vault_id == entity_origins.c.vault_id,
                            intake_segments.c.profile_id == entity_origins.c.profile_id,
                            intake_segments.c.id == entity_origins.c.intake_segment_id,
                        ),
                    )
                )
                .where(
                    and_(
                        entity_origins.c.vault_id == entities.c.vault_id,
                        entity_origins.c.profile_id == entities.c.profile_id,
                        entity_origins.c.entity_id == entities.c.id,
                        intake_segments.c.intake_source_id == source_id,
                    )
                )
            )
        conditions = [
            entities.c.vault_id == vault_id,
            entities.c.profile_id == profile_id,
            entities.c.deleted_at_us.is_(None),
        ]
        if source_match is not None:
            conditions.append(source_match)
        origin_from: FromClause = entity_origins
        origin_conditions = [
            entity_origins.c.vault_id == entities.c.vault_id,
            entity_origins.c.profile_id == entities.c.profile_id,
            entity_origins.c.entity_id == entities.c.id,
        ]
        if source_id is not None:
            origin_from = entity_origins.join(
                intake_segments,
                and_(
                    intake_segments.c.vault_id == entity_origins.c.vault_id,
                    intake_segments.c.profile_id == entity_origins.c.profile_id,
                    intake_segments.c.id == entity_origins.c.intake_segment_id,
                ),
            )
            origin_conditions.append(intake_segments.c.intake_source_id == source_id)
        origin_confidence = (
            select(entity_origins.c.confidence_micros)
            .select_from(origin_from)
            .where(and_(*origin_conditions))
            .order_by(
                entity_origins.c.confidence_micros.desc(),
                entity_origins.c.created_at_us,
                entity_origins.c.id,
            )
            .limit(1)
            .correlate(entities)
            .scalar_subquery()
        )
        origin_explanation = (
            select(entity_origins.c.explanation)
            .select_from(origin_from)
            .where(and_(*origin_conditions))
            .order_by(
                entity_origins.c.confidence_micros.desc(),
                entity_origins.c.created_at_us,
                entity_origins.c.id,
            )
            .limit(1)
            .correlate(entities)
            .scalar_subquery()
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        entities,
                        origin_confidence.label("origin_confidence_micros"),
                        origin_explanation.label("origin_explanation"),
                    )
                    .where(and_(*conditions))
                    .order_by(entities.c.created_at_us, entities.c.id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            entity_ids = tuple(str(row["id"]) for row in rows)
            origins, origin_counts = self._list_entity_origins(
                connection,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_ids=entity_ids,
                source_id=source_id,
            )
        return tuple(
            self._entity_summary(
                row,
                origins=origins.get(str(row["id"]), ()),
                origins_truncated=(
                    origin_counts.get(str(row["id"]), 0) > ENTITY_ORIGIN_PROJECTION_LIMIT
                ),
            )
            for row in rows
        )

    def get_entity(self, vault_id: str, profile_id: str, entity_id: str) -> EntitySummary:
        with self.engine.connect() as connection:
            row = self._scoped_entity(connection, vault_id, profile_id, entity_id)
            origins, origin_counts = self._list_entity_origins(
                connection,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_ids=(entity_id,),
            )
        return self._entity_summary(
            row,
            origins=origins.get(entity_id, ()),
            origins_truncated=origin_counts.get(entity_id, 0) > ENTITY_ORIGIN_PROJECTION_LIMIT,
        )

    def list_entity_origins(
        self,
        vault_id: str,
        profile_id: str,
        entity_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[EntityOriginSummary, ...], int]:
        """Return one stable, metadata-only provenance page for a scoped entity."""

        if offset < 0 or offset > 100_000_000:
            raise ValueError("entity origin offset is outside the allowed range")
        if limit < 1 or limit > ENTITY_ORIGIN_PAGE_LIMIT:
            raise ValueError("entity origin page limit is outside the allowed range")
        with self.engine.connect() as connection:
            scoped_entity_id = connection.execute(
                select(entities.c.id).where(
                    and_(
                        entities.c.vault_id == vault_id,
                        entities.c.profile_id == profile_id,
                        entities.c.id == entity_id,
                        entities.c.deleted_at_us.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if scoped_entity_id is None:
                raise LookupError("entity is unavailable in this profile")
            total = int(
                connection.execute(
                    select(func.count())
                    .select_from(entity_origins)
                    .where(
                        and_(
                            entity_origins.c.vault_id == vault_id,
                            entity_origins.c.profile_id == profile_id,
                            entity_origins.c.entity_id == entity_id,
                        )
                    )
                ).scalar_one()
            )
            origins, _counts = self._list_entity_origins(
                connection,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_ids=(entity_id,),
                projection_offset=offset,
                projection_limit=limit,
            )
        return origins.get(entity_id, ()), total

    @staticmethod
    def _list_entity_origins(
        connection: Connection,
        *,
        vault_id: str,
        profile_id: str,
        entity_ids: Sequence[str],
        source_id: str | None = None,
        observed_at_us_lte: int | None = None,
        projection_offset: int = 0,
        projection_limit: int = ENTITY_ORIGIN_PROJECTION_LIMIT,
    ) -> tuple[dict[str, tuple[EntityOriginSummary, ...]], dict[str, int]]:
        if not entity_ids:
            return {}, {}
        if projection_offset < 0 or projection_limit < 1:
            raise ValueError("entity origin projection range is invalid")
        order = (
            entity_origins.c.confidence_micros.desc(),
            entity_origins.c.observed_at_us,
            entity_origins.c.created_at_us,
            entity_origins.c.id,
        )
        conditions = [
            entity_origins.c.vault_id == vault_id,
            entity_origins.c.profile_id == profile_id,
            entity_origins.c.entity_id.in_(tuple(entity_ids)),
        ]
        if source_id is not None:
            conditions.append(intake_sources.c.id == source_id)
        if observed_at_us_lte is not None:
            conditions.append(entity_origins.c.observed_at_us <= observed_at_us_lte)
        provenance_join = (
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
                    extraction_runs.c.intake_source_id == intake_sources.c.id,
                ),
            )
        )
        ranked = (
            select(
                entity_origins.c.entity_id.label("entity_id"),
                intake_sources.c.id.label("source_id"),
                intake_sources.c.display_name.label("source_display_name"),
                intake_sources.c.sha256.label("source_sha256"),
                intake_segments.c.id.label("segment_id"),
                intake_segments.c.ordinal.label("segment_index"),
                intake_segments.c.locator_json.label("segment_locator"),
                entity_origins.c.source_span_start.label("source_span_start"),
                entity_origins.c.source_span_end.label("source_span_end"),
                entity_origins.c.extraction_run_id.label("extraction_run_id"),
                extraction_runs.c.engine_kind.label("extractor_kind"),
                extraction_runs.c.engine_name.label("extractor_name"),
                extraction_runs.c.engine_version.label("extractor_version"),
                entity_origins.c.origin_kind.label("origin_kind"),
                entity_origins.c.observed_at_us.label("observed_at_us"),
                entity_origins.c.confidence_micros.label("confidence_micros"),
                entity_origins.c.explanation.label("explanation"),
                func.row_number()
                .over(partition_by=entity_origins.c.entity_id, order_by=order)
                .label("origin_position"),
                func.count().over(partition_by=entity_origins.c.entity_id).label("origin_count"),
            )
            .select_from(provenance_join)
            .where(and_(*conditions))
            .subquery()
        )
        rows = (
            connection.execute(
                select(ranked)
                .where(
                    and_(
                        ranked.c.origin_position > projection_offset,
                        ranked.c.origin_position <= projection_offset + projection_limit,
                    )
                )
                .order_by(ranked.c.entity_id, ranked.c.origin_position)
            )
            .mappings()
            .all()
        )
        projected: dict[str, list[EntityOriginSummary]] = {}
        counts: dict[str, int] = {}
        for row in rows:
            entity_id = str(row["entity_id"])
            extraction_run_id = row["extraction_run_id"]
            projected.setdefault(entity_id, []).append(
                EntityOriginSummary(
                    source_id=str(row["source_id"]),
                    source_display_name=_safe_provenance_text(
                        str(row["source_display_name"]),
                        fallback="Restricted source label",
                    ),
                    source_sha256=str(row["source_sha256"]),
                    segment_id=str(row["segment_id"]),
                    segment_index=int(row["segment_index"]),
                    segment_locator=_safe_provenance_text(
                        str(row["segment_locator"]),
                        fallback='{"kind":"restricted_locator"}',
                    ),
                    source_span_start=(
                        None if row["source_span_start"] is None else int(row["source_span_start"])
                    ),
                    source_span_end=(
                        None if row["source_span_end"] is None else int(row["source_span_end"])
                    ),
                    extraction_run_id=(
                        None if extraction_run_id is None else str(extraction_run_id)
                    ),
                    extractor_kind=(
                        None if row["extractor_kind"] is None else str(row["extractor_kind"])
                    ),
                    extractor_name=(
                        None if row["extractor_name"] is None else str(row["extractor_name"])
                    ),
                    extractor_version=(
                        None if row["extractor_version"] is None else str(row["extractor_version"])
                    ),
                    origin_kind=str(row["origin_kind"]),
                    observed_at_us=int(row["observed_at_us"]),
                    confidence_micros=int(row["confidence_micros"]),
                    explanation=_safe_provenance_text(
                        str(row["explanation"]),
                        fallback="Restricted provenance detail",
                    ),
                )
            )
            counts[entity_id] = int(row["origin_count"])
        return {key: tuple(value) for key, value in projected.items()}, counts

    def count_quarantine(
        self,
        vault_id: str,
        profile_id: str,
        *,
        source_id: str | None = None,
    ) -> int:
        conditions = [
            quarantine_items.c.vault_id == vault_id,
            quarantine_items.c.profile_id == profile_id,
        ]
        if source_id is not None:
            conditions.append(quarantine_items.c.intake_source_id == source_id)
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count()).select_from(quarantine_items).where(and_(*conditions))
                ).scalar_one()
            )

    def record_decision(
        self,
        *,
        vault_id: str,
        profile_id: str,
        entity_id: str,
        expected_revision: int,
        decision_type: str,
        review_state: str,
        sensitivity: str | None = None,
        temporal_state: str | None = None,
        search_policy: str | None = None,
        transmission_policy: str | None = None,
        reason_code: str | None = None,
        decision_id: str | None = None,
    ) -> EntitySummary:
        decision_type = _member(decision_type, _DECISION_TYPES, label="decision type")
        review_state = _member(review_state, _REVIEW_STATES, label="review state")
        if reason_code is not None:
            reason_code = _bounded(reason_code, label="decision reason code", maximum=64)
        required_state = {
            "CONFIRM": "CONFIRMED",
            "REJECT": "FALSE_POSITIVE",
            "EXCLUDE": "EXCLUDED",
        }.get(decision_type)
        if required_state is not None and review_state != required_state:
            raise ValueError("decision type and review state disagree")
        if decision_type == "CLASSIFY" and review_state not in {"PROBABLE", "POSSIBLE"}:
            raise ValueError("classification decision has an invalid review state")
        decision_id = str(uuid7()) if decision_id is None else decision_id
        timestamp = now_us()
        # Set deferral before the first DML statement starts SQLite's transaction.
        # Setting it inside ``engine.begin()`` is too late for SQLCipher's SQLite
        # driver and causes the first parent sensitivity update to fail immediately.
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            if connection.exec_driver_sql("PRAGMA defer_foreign_keys").scalar_one() != 1:
                raise RuntimeError("deferred foreign keys are unavailable")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            current = self._scoped_entity(connection, vault_id, profile_id, entity_id)
            if int(current["revision"]) != expected_revision:
                raise RevisionConflict("entity revision is stale")
            next_sensitivity = str(current["sensitivity"]) if sensitivity is None else sensitivity
            next_temporal_state = (
                str(current["temporal_state"]) if temporal_state is None else temporal_state
            )
            next_search_policy = (
                str(current["search_policy"]) if search_policy is None else search_policy
            )
            next_transmission_policy = (
                str(current["transmission_policy"])
                if transmission_policy is None
                else transmission_policy
            )
            _member(next_sensitivity, _SENSITIVITIES, label="entity sensitivity")
            _member(next_temporal_state, _TEMPORAL_STATES, label="entity temporal state")
            _member(next_search_policy, _SEARCH_POLICIES, label="entity search policy")
            _member(
                next_transmission_policy,
                _TRANSMISSION_POLICIES,
                label="entity transmission policy",
            )
            _validate_entity_policy(
                review_state=review_state,
                sensitivity=next_sensitivity,
                search_policy=next_search_policy,
                transmission_policy=next_transmission_policy,
            )
            if decision_type == "POLICY_CHANGE":
                if review_state != str(current["review_state"]):
                    raise ValueError("policy change cannot alter entity review state")
                if (
                    next_sensitivity == str(current["sensitivity"])
                    and next_temporal_state == str(current["temporal_state"])
                    and next_search_policy == str(current["search_policy"])
                    and next_transmission_policy == str(current["transmission_policy"])
                ):
                    raise ValueError("policy change must alter an entity policy")
            next_revision = expected_revision + 1
            connection.execute(
                insert(entity_decisions).values(
                    id=decision_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    entity_id=entity_id,
                    decision_type=decision_type,
                    before_review_state=current["review_state"],
                    after_review_state=review_state,
                    before_sensitivity=current["sensitivity"],
                    after_sensitivity=next_sensitivity,
                    before_temporal_state=current["temporal_state"],
                    after_temporal_state=next_temporal_state,
                    before_search_policy=current["search_policy"],
                    after_search_policy=next_search_policy,
                    before_transmission_policy=current["transmission_policy"],
                    after_transmission_policy=next_transmission_policy,
                    actor_type="LOCAL_USER",
                    actor_version=None,
                    reason_code=reason_code,
                    before_revision=expected_revision,
                    after_revision=next_revision,
                    supersedes_decision_id=current["current_decision_id"],
                    decided_at_us=timestamp,
                )
            )
            changed = connection.execute(
                update(entities)
                .where(
                    and_(
                        entities.c.vault_id == vault_id,
                        entities.c.profile_id == profile_id,
                        entities.c.id == entity_id,
                        entities.c.revision == expected_revision,
                        entities.c.deleted_at_us.is_(None),
                    )
                )
                .values(
                    review_state=review_state,
                    sensitivity=next_sensitivity,
                    temporal_state=next_temporal_state,
                    search_policy=next_search_policy,
                    transmission_policy=next_transmission_policy,
                    current_decision_id=decision_id,
                    revision=next_revision,
                    updated_at_us=timestamp,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("entity revision is stale")
            if next_sensitivity != str(current["sensitivity"]):
                connection.execute(
                    update(graph_nodes)
                    .where(
                        and_(
                            graph_nodes.c.vault_id == vault_id,
                            graph_nodes.c.profile_id == profile_id,
                            graph_nodes.c.entity_id == entity_id,
                            graph_nodes.c.deleted_at_us.is_(None),
                        )
                    )
                    .values(
                        sensitivity=next_sensitivity,
                        revision=graph_nodes.c.revision + 1,
                        updated_at_us=timestamp,
                    )
                )
                connection.execute(
                    update(entity_variants)
                    .where(
                        and_(
                            entity_variants.c.vault_id == vault_id,
                            entity_variants.c.profile_id == profile_id,
                            entity_variants.c.entity_id == entity_id,
                            entity_variants.c.deleted_at_us.is_(None),
                        )
                    )
                    .values(
                        sensitivity=next_sensitivity,
                        revision=entity_variants.c.revision + 1,
                        updated_at_us=timestamp,
                    )
                )
            _append_event(
                connection,
                vault_id=vault_id,
                event_type="ENTITY_REVIEW_DECIDED",
                target_type="ENTITY",
                target_id=entity_id,
                resource_revision=next_revision,
                metadata={
                    "decisionType": decision_type,
                    "reviewState": review_state,
                    "searchPolicy": next_search_policy,
                    "sensitivity": next_sensitivity,
                    "temporalState": next_temporal_state,
                    "transmissionPolicy": next_transmission_policy,
                },
            )
            updated = self._scoped_entity(connection, vault_id, profile_id, entity_id)
            origins, origin_counts = self._list_entity_origins(
                connection,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_ids=(entity_id,),
            )
            projected = self._entity_summary(
                updated,
                origins=origins.get(entity_id, ()),
                origins_truncated=origin_counts.get(entity_id, 0) > ENTITY_ORIGIN_PROJECTION_LIMIT,
            )
            connection.commit()
        return projected

    def get_entity_for_decision(
        self,
        vault_id: str,
        profile_id: str,
        decision_id: str,
    ) -> EntitySummary | None:
        with self.engine.connect() as connection:
            decision = (
                connection.execute(
                    select(entity_decisions).where(
                        and_(
                            entity_decisions.c.vault_id == vault_id,
                            entity_decisions.c.profile_id == profile_id,
                            entity_decisions.c.id == decision_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if decision is None:
                return None
            entity = (
                connection.execute(
                    select(entities).where(
                        and_(
                            entities.c.vault_id == vault_id,
                            entities.c.profile_id == profile_id,
                            entities.c.id == str(decision["entity_id"]),
                            entities.c.deleted_at_us.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if entity is None:
                raise LookupError("decision entity is unavailable in this profile")
            origin = (
                connection.execute(
                    select(
                        entity_origins.c.confidence_micros,
                        entity_origins.c.explanation,
                    )
                    .where(
                        and_(
                            entity_origins.c.vault_id == vault_id,
                            entity_origins.c.profile_id == profile_id,
                            entity_origins.c.entity_id == str(decision["entity_id"]),
                            entity_origins.c.created_at_us <= int(decision["decided_at_us"]),
                        )
                    )
                    .order_by(
                        entity_origins.c.confidence_micros.desc(),
                        entity_origins.c.created_at_us,
                        entity_origins.c.id,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if origin is None:
                raise RuntimeError("decision entity provenance is unavailable")
            origins, origin_counts = self._list_entity_origins(
                connection,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_ids=(str(decision["entity_id"]),),
                observed_at_us_lte=int(decision["decided_at_us"]),
            )
            entity_origins_at_decision = origins.get(str(decision["entity_id"]), ())
        return EntitySummary(
            id=str(decision["entity_id"]),
            entity_type=str(entity["entity_type"]),
            display_mask=str(entity["display_mask"]),
            sensitivity=str(decision["after_sensitivity"]),
            review_state=str(decision["after_review_state"]),
            temporal_state=str(decision["after_temporal_state"]),
            search_policy=str(decision["after_search_policy"]),
            transmission_policy=str(decision["after_transmission_policy"]),
            confidence_micros=int(origin["confidence_micros"]),
            provenance_label=_safe_provenance_text(
                str(origin["explanation"])[:160],
                fallback="Restricted provenance detail",
            ),
            origins=entity_origins_at_decision,
            origins_truncated=(
                origin_counts.get(str(decision["entity_id"]), 0) > ENTITY_ORIGIN_PROJECTION_LIMIT
            ),
            revision=int(decision["after_revision"]),
        )

    def record_variant_decision(
        self,
        *,
        vault_id: str,
        profile_id: str,
        variant_id: str,
        expected_revision: int,
        decision_type: str,
        approved_for_search: bool,
        rank: int,
        reason_code: str | None = None,
    ) -> VariantSummary:
        decision_type = _member(
            decision_type,
            _VARIANT_DECISION_TYPES,
            label="variant decision type",
        )
        if not 0 <= rank <= 1_000_000:
            raise ValueError("variant rank is outside the allowed range")
        if decision_type == "APPROVE" and not approved_for_search:
            raise ValueError("approve decision must enable the variant")
        if decision_type in {"REVOKE", "EXCLUDE"} and approved_for_search:
            raise ValueError("revocation decision must disable the variant")
        if reason_code is not None:
            reason_code = _bounded(reason_code, label="decision reason code", maximum=64)
        decision_id = str(uuid7())
        timestamp = now_us()
        with self.engine.begin() as connection:
            current = self._scoped_variant(connection, vault_id, profile_id, variant_id)
            if int(current["revision"]) != expected_revision:
                raise RevisionConflict("entity variant revision is stale")
            next_revision = expected_revision + 1
            connection.execute(
                insert(entity_variant_decisions).values(
                    id=decision_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    variant_id=variant_id,
                    decision_type=decision_type,
                    before_approved=current["approved_for_search"],
                    after_approved=int(approved_for_search),
                    before_rank=current["rank"],
                    after_rank=rank,
                    actor_type="LOCAL_USER",
                    actor_version=None,
                    reason_code=reason_code,
                    before_revision=expected_revision,
                    after_revision=next_revision,
                    supersedes_decision_id=current["current_decision_id"],
                    decided_at_us=timestamp,
                )
            )
            changed = connection.execute(
                update(entity_variants)
                .where(
                    and_(
                        entity_variants.c.vault_id == vault_id,
                        entity_variants.c.profile_id == profile_id,
                        entity_variants.c.id == variant_id,
                        entity_variants.c.revision == expected_revision,
                        entity_variants.c.deleted_at_us.is_(None),
                    )
                )
                .values(
                    approved_for_search=int(approved_for_search),
                    rank=rank,
                    current_decision_id=decision_id,
                    revision=next_revision,
                    updated_at_us=timestamp,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("entity variant revision is stale")
            _append_event(
                connection,
                vault_id=vault_id,
                event_type="ENTITY_VARIANT_REVIEW_DECIDED",
                target_type="ENTITY_VARIANT",
                target_id=variant_id,
                resource_revision=next_revision,
                metadata={
                    "approvedForSearch": approved_for_search,
                    "decisionType": decision_type,
                    "rank": rank,
                },
            )
            updated = self._scoped_variant(connection, vault_id, profile_id, variant_id)
        return self._variant_summary(updated)

    def record_graph_edge_decision(
        self,
        *,
        vault_id: str,
        profile_id: str,
        edge_id: str,
        expected_revision: int,
        decision_type: str,
        review_state: str,
        reason_code: str | None = None,
    ) -> GraphEdgeSummary:
        decision_type = _member(
            decision_type,
            _EDGE_DECISION_TYPES,
            label="graph edge decision type",
        )
        review_state = _member(review_state, _EDGE_REVIEW_STATES, label="graph edge review state")
        required_state = {
            "CONFIRM": "CONFIRMED",
            "REJECT": "REJECTED",
            "EXCLUDE": "EXCLUDED",
        }.get(decision_type)
        if required_state is not None and review_state != required_state:
            raise ValueError("graph edge decision type and review state disagree")
        if reason_code is not None:
            reason_code = _bounded(reason_code, label="decision reason code", maximum=64)
        decision_id = str(uuid7())
        timestamp = now_us()
        with self.engine.begin() as connection:
            current = self._scoped_edge(connection, vault_id, profile_id, edge_id)
            if int(current["revision"]) != expected_revision:
                raise RevisionConflict("graph edge revision is stale")
            next_revision = expected_revision + 1
            connection.execute(
                insert(graph_edge_decisions).values(
                    id=decision_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    edge_id=edge_id,
                    decision_type=decision_type,
                    before_review_state=current["review_state"],
                    after_review_state=review_state,
                    actor_type="LOCAL_USER",
                    actor_version=None,
                    reason_code=reason_code,
                    before_revision=expected_revision,
                    after_revision=next_revision,
                    supersedes_decision_id=current["current_decision_id"],
                    decided_at_us=timestamp,
                )
            )
            changed = connection.execute(
                update(graph_edges)
                .where(
                    and_(
                        graph_edges.c.vault_id == vault_id,
                        graph_edges.c.profile_id == profile_id,
                        graph_edges.c.id == edge_id,
                        graph_edges.c.revision == expected_revision,
                        graph_edges.c.deleted_at_us.is_(None),
                    )
                )
                .values(
                    review_state=review_state,
                    current_decision_id=decision_id,
                    revision=next_revision,
                    updated_at_us=timestamp,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("graph edge revision is stale")
            _append_event(
                connection,
                vault_id=vault_id,
                event_type="GRAPH_EDGE_REVIEW_DECIDED",
                target_type="GRAPH_EDGE",
                target_id=edge_id,
                resource_revision=next_revision,
                metadata={"decisionType": decision_type, "reviewState": review_state},
            )
            updated = self._scoped_edge(connection, vault_id, profile_id, edge_id)
        return self._edge_summary(updated)

    def graph_snapshot(
        self,
        vault_id: str,
        profile_id: str,
        *,
        limit: int = 1_000,
        include_sensitive: bool = True,
        edge_node_limit: int | None = None,
        edge_limit: int | None = None,
    ) -> GraphSnapshot:
        if limit < 1 or limit > 5_000:
            raise ValueError("graph snapshot limit is outside the allowed range")
        active_edge_node_limit = limit if edge_node_limit is None else edge_node_limit
        active_edge_limit = limit if edge_limit is None else edge_limit
        if active_edge_node_limit < 1 or active_edge_node_limit > limit:
            raise ValueError("graph edge node limit is outside the allowed range")
        if active_edge_limit < 1 or active_edge_limit > 5_000:
            raise ValueError("graph edge limit is outside the allowed range")
        with self.engine.connect() as connection:
            node_conditions = [
                graph_nodes.c.vault_id == vault_id,
                graph_nodes.c.profile_id == profile_id,
                graph_nodes.c.deleted_at_us.is_(None),
                or_(
                    graph_nodes.c.entity_id.is_(None),
                    entities.c.review_state.not_in(("FALSE_POSITIVE", "EXCLUDED")),
                ),
            ]
            if not include_sensitive:
                node_conditions.append(graph_nodes.c.sensitivity == "PUBLIC")
            node_rows = (
                connection.execute(
                    select(graph_nodes)
                    .select_from(
                        graph_nodes.outerjoin(
                            entities,
                            and_(
                                entities.c.vault_id == graph_nodes.c.vault_id,
                                entities.c.profile_id == graph_nodes.c.profile_id,
                                entities.c.id == graph_nodes.c.entity_id,
                                entities.c.deleted_at_us.is_(None),
                            ),
                        )
                    )
                    .where(and_(*node_conditions))
                    .order_by(graph_nodes.c.created_at_us, graph_nodes.c.id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            node_ids = tuple(str(row["id"]) for row in node_rows[:active_edge_node_limit])
            edge_rows: Sequence[RowMapping] = ()
            evidence_counts: dict[str, tuple[int, int]] = {}
            evidence_by_edge: dict[str, list[GraphEdgeEvidenceSummary]] = {}
            if node_ids:
                edge_rows = (
                    connection.execute(
                        select(graph_edges)
                        .where(
                            and_(
                                graph_edges.c.vault_id == vault_id,
                                graph_edges.c.profile_id == profile_id,
                                graph_edges.c.from_node_id.in_(node_ids),
                                graph_edges.c.to_node_id.in_(node_ids),
                                graph_edges.c.review_state.not_in(("REJECTED", "EXCLUDED")),
                                graph_edges.c.deleted_at_us.is_(None),
                            )
                        )
                        .order_by(graph_edges.c.created_at_us, graph_edges.c.id)
                        .limit(active_edge_limit)
                    )
                    .mappings()
                    .all()
                )
                edge_ids = tuple(str(row["id"]) for row in edge_rows)
                if edge_ids:
                    count_rows = connection.execute(
                        select(
                            graph_edge_origins.c.graph_edge_id,
                            func.count()
                            .filter(graph_edge_origins.c.disposition == "SUPPORTS")
                            .label("support_count"),
                            func.count()
                            .filter(graph_edge_origins.c.disposition == "CONTRADICTS")
                            .label("contradiction_count"),
                        )
                        .where(
                            and_(
                                graph_edge_origins.c.vault_id == vault_id,
                                graph_edge_origins.c.profile_id == profile_id,
                                graph_edge_origins.c.graph_edge_id.in_(edge_ids),
                            )
                        )
                        .group_by(graph_edge_origins.c.graph_edge_id)
                    ).mappings()
                    evidence_counts = {
                        str(row["graph_edge_id"]): (
                            int(row["support_count"]),
                            int(row["contradiction_count"]),
                        )
                        for row in count_rows
                    }
                    if set(evidence_counts) != set(edge_ids):
                        raise RuntimeError("graph edge provenance is unavailable")
                    ranked_evidence = (
                        select(
                            graph_edge_origins,
                            intake_segments.c.ordinal.label("segment_ordinal"),
                            func.row_number()
                            .over(
                                partition_by=(
                                    graph_edge_origins.c.graph_edge_id,
                                    graph_edge_origins.c.disposition,
                                ),
                                order_by=(
                                    graph_edge_origins.c.created_at_us,
                                    graph_edge_origins.c.id,
                                ),
                            )
                            .label("evidence_rank"),
                        )
                        .select_from(
                            graph_edge_origins.join(
                                intake_segments,
                                and_(
                                    intake_segments.c.vault_id == graph_edge_origins.c.vault_id,
                                    intake_segments.c.profile_id == graph_edge_origins.c.profile_id,
                                    intake_segments.c.intake_source_id
                                    == graph_edge_origins.c.intake_source_id,
                                    intake_segments.c.id == graph_edge_origins.c.intake_segment_id,
                                ),
                            )
                        )
                        .where(
                            and_(
                                graph_edge_origins.c.vault_id == vault_id,
                                graph_edge_origins.c.profile_id == profile_id,
                                graph_edge_origins.c.graph_edge_id.in_(edge_ids),
                            )
                        )
                        .subquery()
                    )
                    evidence_rows = (
                        connection.execute(
                            select(ranked_evidence)
                            .where(ranked_evidence.c.evidence_rank == 1)
                            .order_by(
                                ranked_evidence.c.created_at_us,
                                ranked_evidence.c.id,
                            )
                        )
                        .mappings()
                        .all()
                    )
                    for row in evidence_rows:
                        edge_evidence = evidence_by_edge.setdefault(str(row["graph_edge_id"]), [])
                        if len(edge_evidence) >= 8:
                            continue
                        edge_evidence.append(
                            GraphEdgeEvidenceSummary(
                                source_id=str(row["intake_source_id"]),
                                segment_ordinal=int(row["segment_ordinal"]),
                                disposition=str(row["disposition"]),
                                confidence_micros=int(row["confidence_micros"]),
                                visibility=str(row["visibility"]),
                                source_span_start=(
                                    None
                                    if row["source_span_start"] is None
                                    else int(row["source_span_start"])
                                ),
                                source_span_end=(
                                    None
                                    if row["source_span_end"] is None
                                    else int(row["source_span_end"])
                                ),
                                observed_at_us=int(row["observed_at_us"]),
                                origin_type=str(row["origin_type"]),
                                explanation=str(row["explanation"])[:160],
                            )
                        )
                    if set(evidence_by_edge) != set(edge_ids):
                        raise RuntimeError("graph edge evidence sample is unavailable")
        return GraphSnapshot(
            nodes=tuple(
                GraphNodeSummary(
                    id=str(row["id"]),
                    node_type=str(row["node_type"]),
                    display_label=str(row["display_label"]),
                    sensitivity=str(row["sensitivity"]),
                    visibility=str(row["visibility"]),
                    entity_id=None if row["entity_id"] is None else str(row["entity_id"]),
                )
                for row in node_rows
            ),
            edges=tuple(
                self._edge_summary(
                    row,
                    counts=evidence_counts.get(str(row["id"]), (0, 0)),
                    evidence=tuple(evidence_by_edge.get(str(row["id"]), ())),
                )
                for row in edge_rows
            ),
        )

    def _validate_compilation(
        self,
        source: SourceDraft,
        extraction: ExtractionDraft,
        segments: Sequence[SegmentDraft],
        quarantine: Sequence[QuarantineDraft],
        entities_input: Sequence[EntityDraft],
        edges: Sequence[EdgeDraft],
        enrichment_outcome: EnrichmentOutcomeDraft,
    ) -> None:
        if len(segments) > 10_000 or len(quarantine) > 10_000 or len(entities_input) > 10_000:
            raise ValueError("compilation collection exceeds its bound")
        if len(edges) > 20_000:
            raise ValueError("compilation edge collection exceeds its bound")
        _validate_enrichment_outcome(enrichment_outcome)
        _member(source.source_kind, _SOURCE_KINDS, label="source kind")
        display_name = _bounded(source.display_name, label="source display name", maximum=255)
        if "/" in display_name or "\\" in display_name:
            raise ValueError("source display name must be a basename")
        _bounded(source.detected_mime, label="detected MIME", maximum=128)
        if source.declared_mime is not None:
            _bounded(source.declared_mime, label="declared MIME", maximum=128)
        if source.broker_handle is not None:
            _bounded(source.broker_handle, label="broker handle", maximum=128)
        if source.byte_size < 0 or source.byte_size > 1_073_741_824:
            raise ValueError("source byte size is outside the allowed range")
        _digest(source.sha256, label="source SHA-256", required=True)
        _member(source.retention_state, _RETENTION_STATES, label="retention state")
        if source.retention_state == "TEMPORARY" and source.retention_expires_at_us is None:
            raise ValueError("temporary source requires a retention deadline")
        _member(extraction.engine_kind, _ENGINE_KINDS, label="extraction engine kind")
        _bounded(extraction.engine_name, label="extraction engine name", maximum=96)
        _bounded(extraction.engine_version, label="extraction engine version", maximum=48)
        _digest(extraction.configuration_hash, label="configuration hash", required=True)
        _member(extraction.state, _EXTRACTION_STATES, label="extraction state")
        if extraction.finished_at_us is not None and extraction.started_at_us is None:
            raise ValueError("finished extraction requires a start time")

        ordinals: set[int] = set()
        for segment in segments:
            if segment.ordinal < 0 or segment.ordinal in ordinals:
                raise ValueError("segment ordinal is invalid or duplicated")
            ordinals.add(segment.ordinal)
            _member(segment.segment_kind, _SEGMENT_KINDS, label="segment kind")
            _bounded(segment.locator_json, label="segment locator", maximum=16_384)
            if segment.content_text is not None:
                _bounded_content(segment.content_text, maximum=4_194_304)
            if segment.language is not None:
                _bounded(segment.language, label="segment language", maximum=35)

        for item in quarantine:
            _member(item.reason_code, _QUARANTINE_REASONS, label="quarantine reason")
            if item.opaque_blob_key is not None:
                _bounded(item.opaque_blob_key, label="quarantine object key", maximum=128)
            if item.mime_type is not None:
                _bounded(item.mime_type, label="quarantine MIME", maximum=128)
            if item.byte_size_plaintext is not None and item.byte_size_plaintext < 0:
                raise ValueError("quarantine plaintext size is invalid")
            if item.byte_size_ciphertext is not None and item.byte_size_ciphertext < 0:
                raise ValueError("quarantine ciphertext size is invalid")
            _digest(item.sha256_plaintext, label="quarantine plaintext SHA-256")
            _digest(item.sha256_ciphertext, label="quarantine ciphertext SHA-256")

        local_keys: set[str] = set()
        graph_keys: set[str] = set()
        origin_count = 0
        for entity in entities_input:
            _bounded(entity.local_key, label="entity local key", maximum=64)
            if entity.local_key in local_keys:
                raise ValueError("entity local key is duplicated")
            local_keys.add(entity.local_key)
            _member(entity.entity_type, _ENTITY_TYPES, label="entity type")
            _bounded(entity.canonical_value, label="entity canonical value", maximum=16_384)
            _bounded(entity.display_mask, label="entity display mask", maximum=512)
            _member(entity.sensitivity, _SENSITIVITIES, label="entity sensitivity")
            _member(entity.review_state, _REVIEW_STATES, label="entity review state")
            _member(entity.temporal_state, _TEMPORAL_STATES, label="entity temporal state")
            _member(entity.search_policy, _SEARCH_POLICIES, label="entity search policy")
            _member(
                entity.transmission_policy,
                _TRANSMISSION_POLICIES,
                label="entity transmission policy",
            )
            _validate_entity_policy(
                review_state=entity.review_state,
                sensitivity=entity.sensitivity,
                search_policy=entity.search_policy,
                transmission_policy=entity.transmission_policy,
            )
            entity_origins_input = self._entity_origins(entity)
            origin_count += len(entity_origins_input)
            if len(entity_origins_input) > 10_000 or origin_count > 100_000:
                raise ValueError("entity origin collection exceeds its bound")
            for origin in entity_origins_input:
                if origin.source_segment_ordinal not in ordinals:
                    raise ValueError("entity source segment is unavailable")
                _member(origin.origin_kind, _ORIGIN_KINDS, label="entity origin kind")
                _bounded(origin.explanation, label="origin explanation", maximum=2_048)
                if not 0 <= origin.confidence_micros <= 1_000_000:
                    raise ValueError("origin confidence is outside the allowed range")
                if (origin.source_span_start is None) != (origin.source_span_end is None):
                    raise ValueError("source span must contain both bounds")
                if origin.source_span_start is not None and (
                    origin.source_span_start < 0
                    or origin.source_span_end is None
                    or origin.source_span_end <= origin.source_span_start
                ):
                    raise ValueError("source span is invalid")
            if (
                entity.valid_from_us is not None
                and entity.valid_to_us is not None
                and entity.valid_to_us < entity.valid_from_us
            ):
                raise ValueError("entity validity interval is invalid")
            if len(entity.variants) > 128:
                raise ValueError("entity variant collection exceeds its bound")
            for variant in entity.variants:
                _member(variant.variant_type, _VARIANT_TYPES, label="variant type")
                _bounded(variant.value, label="variant value", maximum=16_384)
                _bounded(variant.generator, label="variant generator", maximum=96)
                _bounded(variant.generator_version, label="variant generator version", maximum=48)
                _member(variant.estimated_risk, _RISKS, label="variant risk")
                if not 0 <= variant.rank <= 1_000_000:
                    raise ValueError("variant rank is outside the allowed range")
            if entity.graph_node_type is not None:
                _bounded(entity.graph_node_type, label="graph node type", maximum=32)
                _member(entity.graph_visibility, _VISIBILITIES, label="graph visibility")
                graph_keys.add(entity.local_key)

        for edge in edges:
            if edge.from_entity_key not in graph_keys or edge.to_entity_key not in graph_keys:
                raise ValueError("graph edge endpoint is unavailable")
            if edge.from_entity_key == edge.to_entity_key:
                raise ValueError("graph self-edges are unavailable")
            _member(edge.edge_type, _EDGE_TYPES, label="graph edge type")
            _member(edge.visibility, _VISIBILITIES, label="graph edge visibility")
            _member(edge.origin_type, _EDGE_ORIGINS, label="graph edge origin")
            _member(edge.disposition, _EDGE_DISPOSITIONS, label="graph edge disposition")
            _bounded(edge.explanation, label="graph edge explanation", maximum=2_048)
            if edge.source_segment_ordinal not in ordinals:
                raise ValueError("graph edge source segment is unavailable")
            if (edge.source_span_start is None) != (edge.source_span_end is None):
                raise ValueError("graph edge source span must contain both bounds")
            if edge.source_span_start is not None and (
                edge.source_span_start < 0
                or edge.source_span_end is None
                or edge.source_span_end <= edge.source_span_start
            ):
                raise ValueError("graph edge source span is invalid")
            if not 0 <= edge.confidence_micros <= 1_000_000:
                raise ValueError("graph edge confidence is outside the allowed range")
            if (
                edge.valid_from_us is not None
                and edge.valid_to_us is not None
                and edge.valid_to_us < edge.valid_from_us
            ):
                raise ValueError("graph edge validity interval is invalid")

    def _insert_source(
        self,
        connection: Connection,
        vault_id: str,
        profile_id: str,
        source_id: str,
        source: SourceDraft,
        timestamp: int,
    ) -> None:
        connection.execute(
            insert(intake_sources).values(
                id=source_id,
                vault_id=vault_id,
                profile_id=profile_id,
                source_kind=source.source_kind,
                display_name=source.display_name,
                broker_handle=source.broker_handle,
                declared_mime=source.declared_mime,
                detected_mime=source.detected_mime,
                byte_size=source.byte_size,
                sha256=source.sha256,
                retention_state=source.retention_state,
                retention_expires_at_us=source.retention_expires_at_us,
                consent_confirmed_at_us=source.consent_confirmed_at_us,
                created_at_us=timestamp,
                updated_at_us=timestamp,
                revision=1,
                deleted_at_us=None,
            )
        )

    def _insert_quarantine(
        self,
        connection: Connection,
        vault_id: str,
        profile_id: str,
        source_id: str,
        quarantine_id: str,
        item: QuarantineDraft,
        timestamp: int,
    ) -> None:
        connection.execute(
            insert(quarantine_items).values(
                id=quarantine_id,
                vault_id=vault_id,
                profile_id=profile_id,
                intake_source_id=source_id,
                reason_code=item.reason_code,
                opaque_blob_key=item.opaque_blob_key,
                mime_type=item.mime_type,
                byte_size_plaintext=item.byte_size_plaintext,
                byte_size_ciphertext=item.byte_size_ciphertext,
                sha256_plaintext=item.sha256_plaintext,
                sha256_ciphertext=item.sha256_ciphertext,
                encryption_version=item.encryption_version,
                key_version=item.key_version,
                state="PENDING_REVIEW",
                retention_expires_at_us=item.retention_expires_at_us,
                reviewed_at_us=None,
                deletion_verified_at_us=None,
                created_at_us=timestamp,
                updated_at_us=timestamp,
                revision=1,
            )
        )

    def _insert_entity(
        self,
        connection: Connection,
        vault_id: str,
        profile_id: str,
        entity_id: str,
        entity: EntityDraft,
        value_hmac: str,
        timestamp: int,
    ) -> None:
        connection.execute(
            insert(entities).values(
                id=entity_id,
                vault_id=vault_id,
                profile_id=profile_id,
                entity_type=entity.entity_type,
                canonical_value=entity.canonical_value,
                display_mask=entity.display_mask,
                value_hmac=value_hmac,
                sensitivity=entity.sensitivity,
                review_state=entity.review_state,
                temporal_state=entity.temporal_state,
                valid_from_us=entity.valid_from_us,
                valid_to_us=entity.valid_to_us,
                search_policy=entity.search_policy,
                transmission_policy=entity.transmission_policy,
                current_decision_id=None,
                created_at_us=timestamp,
                updated_at_us=timestamp,
                revision=1,
                deleted_at_us=None,
            )
        )

    @staticmethod
    def _entity_origins(entity: EntityDraft) -> tuple[EntityOriginDraft, ...]:
        if entity.origins:
            return entity.origins
        return (
            EntityOriginDraft(
                source_segment_ordinal=entity.source_segment_ordinal,
                origin_kind=entity.origin_kind,
                confidence_micros=entity.origin_confidence_micros,
                explanation=entity.origin_explanation,
                source_span_start=entity.source_span_start,
                source_span_end=entity.source_span_end,
            ),
        )

    @staticmethod
    def _find_live_entity(
        connection: Connection,
        vault_id: str,
        profile_id: str,
        entity_type: str,
        value_hmac: str,
    ) -> RowMapping | None:
        return (
            connection.execute(
                select(entities).where(
                    and_(
                        entities.c.vault_id == vault_id,
                        entities.c.profile_id == profile_id,
                        entities.c.entity_type == entity_type,
                        entities.c.value_hmac == value_hmac,
                        entities.c.deleted_at_us.is_(None),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _insert_entity_origins(
        connection: Connection,
        vault_id: str,
        profile_id: str,
        entity_id: str,
        extraction_id: str,
        segment_ids: dict[int, str],
        origins: Sequence[EntityOriginDraft],
        timestamp: int,
    ) -> None:
        for origin in origins:
            connection.execute(
                insert(entity_origins).values(
                    id=str(uuid7()),
                    vault_id=vault_id,
                    profile_id=profile_id,
                    entity_id=entity_id,
                    extraction_run_id=extraction_id,
                    intake_segment_id=segment_ids[origin.source_segment_ordinal],
                    raw_result_id=None,
                    evidence_artifact_id=None,
                    source_span_start=origin.source_span_start,
                    source_span_end=origin.source_span_end,
                    origin_kind=origin.origin_kind,
                    confidence_micros=origin.confidence_micros,
                    explanation=origin.explanation,
                    observed_at_us=timestamp,
                    created_at_us=timestamp,
                )
            )

    def _insert_edge_origin(
        self,
        connection: Connection,
        *,
        vault_id: str,
        profile_id: str,
        source_id: str,
        edge_id: str,
        extraction_id: str,
        segment_id: str,
        edge: EdgeDraft,
        timestamp: int,
    ) -> None:
        observation = json.dumps(
            {
                "confidenceMicros": edge.confidence_micros,
                "disposition": edge.disposition,
                "explanation": edge.explanation,
                "extractionRunId": extraction_id,
                "intakeSegmentId": segment_id,
                "intakeSourceId": source_id,
                "observedAtUs": edge.observed_at_us,
                "originType": edge.origin_type,
                "sourceSpanEnd": edge.source_span_end,
                "sourceSpanStart": edge.source_span_start,
                "visibility": edge.visibility,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        observation_hmac = self._fingerprint(observation)
        exists_already = connection.execute(
            select(graph_edge_origins.c.id).where(
                and_(
                    graph_edge_origins.c.vault_id == vault_id,
                    graph_edge_origins.c.profile_id == profile_id,
                    graph_edge_origins.c.graph_edge_id == edge_id,
                    graph_edge_origins.c.observation_hmac == observation_hmac,
                )
            )
        ).scalar_one_or_none()
        if exists_already is not None:
            return
        connection.execute(
            insert(graph_edge_origins).values(
                id=str(uuid7()),
                vault_id=vault_id,
                profile_id=profile_id,
                graph_edge_id=edge_id,
                intake_source_id=source_id,
                intake_segment_id=segment_id,
                extraction_run_id=extraction_id,
                disposition=edge.disposition,
                confidence_micros=edge.confidence_micros,
                visibility=edge.visibility,
                source_span_start=edge.source_span_start,
                source_span_end=edge.source_span_end,
                observed_at_us=edge.observed_at_us,
                origin_type=edge.origin_type,
                explanation=edge.explanation,
                observation_hmac=observation_hmac,
                created_at_us=timestamp,
            )
        )

    def _insert_missing_variants(
        self,
        connection: Connection,
        vault_id: str,
        profile_id: str,
        entity_id: str,
        sensitivity: str,
        variants: Sequence[VariantDraft],
        timestamp: int,
    ) -> int:
        rows = (
            connection.execute(
                select(
                    entity_variants.c.variant_type,
                    entity_variants.c.value,
                    entity_variants.c.value_hmac,
                ).where(
                    and_(
                        entity_variants.c.vault_id == vault_id,
                        entity_variants.c.profile_id == profile_id,
                        entity_variants.c.entity_id == entity_id,
                        entity_variants.c.deleted_at_us.is_(None),
                    )
                )
            )
            .mappings()
            .all()
        )
        known: dict[tuple[str, str], str] = {
            (str(row["variant_type"]), str(row["value_hmac"])): str(row["value"]) for row in rows
        }
        values_by_hmac = {str(row["value_hmac"]): str(row["value"]) for row in rows}
        duplicate_count = 0
        for variant in variants:
            value_hmac = self._fingerprint(variant.value)
            known_value = values_by_hmac.get(value_hmac)
            if known_value is not None and known_value != variant.value:
                raise RuntimeError("variant fingerprint collision")
            key = (variant.variant_type, value_hmac)
            existing_value = known.get(key)
            if existing_value is not None:
                if existing_value != variant.value:
                    raise RuntimeError("variant fingerprint collision")
                duplicate_count += 1
                continue
            connection.execute(
                insert(entity_variants).values(
                    id=str(uuid7()),
                    vault_id=vault_id,
                    profile_id=profile_id,
                    entity_id=entity_id,
                    sensitivity=sensitivity,
                    variant_type=variant.variant_type,
                    value=variant.value,
                    value_hmac=value_hmac,
                    generator=variant.generator,
                    generator_version=variant.generator_version,
                    rank=variant.rank,
                    estimated_risk=variant.estimated_risk,
                    approved_for_search=int(variant.approved_for_search),
                    current_decision_id=None,
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                    deleted_at_us=None,
                )
            )
            known[key] = variant.value
            values_by_hmac[value_hmac] = variant.value
        return duplicate_count

    @staticmethod
    def _scoped_entity(
        connection: Connection,
        vault_id: str,
        profile_id: str,
        entity_id: str,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(
                    entities,
                    select(entity_origins.c.confidence_micros)
                    .where(
                        and_(
                            entity_origins.c.vault_id == entities.c.vault_id,
                            entity_origins.c.profile_id == entities.c.profile_id,
                            entity_origins.c.entity_id == entities.c.id,
                        )
                    )
                    .order_by(
                        entity_origins.c.confidence_micros.desc(),
                        entity_origins.c.created_at_us,
                        entity_origins.c.id,
                    )
                    .limit(1)
                    .correlate(entities)
                    .scalar_subquery()
                    .label("origin_confidence_micros"),
                    select(entity_origins.c.explanation)
                    .where(
                        and_(
                            entity_origins.c.vault_id == entities.c.vault_id,
                            entity_origins.c.profile_id == entities.c.profile_id,
                            entity_origins.c.entity_id == entities.c.id,
                        )
                    )
                    .order_by(
                        entity_origins.c.confidence_micros.desc(),
                        entity_origins.c.created_at_us,
                        entity_origins.c.id,
                    )
                    .limit(1)
                    .correlate(entities)
                    .scalar_subquery()
                    .label("origin_explanation"),
                ).where(
                    and_(
                        entities.c.vault_id == vault_id,
                        entities.c.profile_id == profile_id,
                        entities.c.id == entity_id,
                        entities.c.deleted_at_us.is_(None),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("entity is unavailable in this profile")
        return row

    @staticmethod
    def _scoped_variant(
        connection: Connection,
        vault_id: str,
        profile_id: str,
        variant_id: str,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(entity_variants).where(
                    and_(
                        entity_variants.c.vault_id == vault_id,
                        entity_variants.c.profile_id == profile_id,
                        entity_variants.c.id == variant_id,
                        entity_variants.c.deleted_at_us.is_(None),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("entity variant is unavailable in this profile")
        return row

    @staticmethod
    def _scoped_edge(
        connection: Connection,
        vault_id: str,
        profile_id: str,
        edge_id: str,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(graph_edges).where(
                    and_(
                        graph_edges.c.vault_id == vault_id,
                        graph_edges.c.profile_id == profile_id,
                        graph_edges.c.id == edge_id,
                        graph_edges.c.deleted_at_us.is_(None),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("graph edge is unavailable in this profile")
        return row

    @staticmethod
    def _entity_summary(
        row: RowMapping,
        *,
        origins: tuple[EntityOriginSummary, ...],
        origins_truncated: bool,
    ) -> EntitySummary:
        confidence = row["origin_confidence_micros"]
        provenance = row["origin_explanation"]
        if confidence is None or provenance is None or not origins:
            raise RuntimeError("entity provenance is unavailable")
        return EntitySummary(
            id=str(row["id"]),
            entity_type=str(row["entity_type"]),
            display_mask=str(row["display_mask"]),
            sensitivity=str(row["sensitivity"]),
            review_state=str(row["review_state"]),
            temporal_state=str(row["temporal_state"]),
            search_policy=str(row["search_policy"]),
            transmission_policy=str(row["transmission_policy"]),
            confidence_micros=int(confidence),
            provenance_label=_safe_provenance_text(
                str(provenance)[:160],
                fallback="Restricted provenance detail",
            ),
            origins=origins,
            origins_truncated=origins_truncated,
            revision=int(row["revision"]),
        )

    @staticmethod
    def _variant_summary(row: RowMapping) -> VariantSummary:
        return VariantSummary(
            id=str(row["id"]),
            entity_id=str(row["entity_id"]),
            variant_type=str(row["variant_type"]),
            rank=int(row["rank"]),
            estimated_risk=str(row["estimated_risk"]),
            approved_for_search=bool(row["approved_for_search"]),
            revision=int(row["revision"]),
        )

    @staticmethod
    def _edge_summary(
        row: RowMapping,
        *,
        counts: tuple[int, int] = (0, 0),
        evidence: tuple[GraphEdgeEvidenceSummary, ...] = (),
    ) -> GraphEdgeSummary:
        support_count, contradiction_count = counts
        return GraphEdgeSummary(
            id=str(row["id"]),
            from_node_id=str(row["from_node_id"]),
            to_node_id=str(row["to_node_id"]),
            edge_type=str(row["edge_type"]),
            confidence_micros=int(row["confidence_micros"]),
            visibility=str(row["visibility"]),
            review_state=str(row["review_state"]),
            origin_type=str(row["origin_type"]),
            explanation=str(row["explanation"]),
            revision=int(row["revision"]),
            support_count=support_count,
            contradiction_count=contradiction_count,
            evidence=evidence,
            evidence_truncated=len(evidence) < support_count + contradiction_count,
        )
