"""Authenticated Phase 3 intake and identity application boundary.

Preparation is kept separate from the atomic repository compilation so source,
candidate, origin, decision, and graph projections cannot be partially stored.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Final
from uuid import UUID

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from ariadne_core.api.intake_schemas import (
    MAX_PROFILE_SUMMARIES,
    EntityDecisionRequest,
    EntityOrigin,
    EntityOriginPageRequest,
    EntityOriginPageResult,
    EntityReviewRequest,
    EntityReviewResult,
    EntitySummary,
    FileIntakeRequest,
    GraphEdge,
    GraphEdgeEvidence,
    GraphEvidenceDisposition,
    GraphNode,
    GraphSnapshot,
    GraphSnapshotRequest,
    GraphVisibility,
    IntakeReceipt,
    PasteIntakeRequest,
    ProfileCreateRequest,
    ProfileDeleteRequest,
    ProfileDeleteResult,
    ProfileListResult,
    ProfileSummary,
    ReviewState,
    SearchPolicy,
    Sensitivity,
    TemporalState,
    TransmissionPolicy,
)
from ariadne_core.api.intake_schemas import (
    LocalAIIntakeStatus as ApiLocalAIIntakeStatus,
)
from ariadne_core.application.intake_compiler import (
    LocalAIIntakeStatus,
    PreparedIntake,
    PreparedLocalAIOutcome,
    prepare_file_intake,
    prepare_pasted_intake,
)
from ariadne_core.application.vault import VaultManager, VaultSubkeyPurpose
from ariadne_core.domain.identity_compiler import SourceSpan
from ariadne_core.infrastructure.db.intake_identity_repository import (
    EdgeDraft,
    EnrichmentOutcomeDraft,
    EntityDraft,
    EntityOriginDraft,
    EntityOriginSummary,
    ExtractionDraft,
    IntakeIdentityRepository,
    QuarantineDraft,
    SegmentDraft,
    SourceDraft,
    SourceSummary,
)
from ariadne_core.infrastructure.db.intake_identity_repository import (
    EntitySummary as StoredEntitySummary,
)
from ariadne_core.infrastructure.db.models import idempotency_records
from ariadne_core.infrastructure.db.repositories import (
    IdempotencyConflict,
    JobManifest,
    JobRepository,
    RevisionConflict,
    SettingsRepository,
    canonical_json,
    now_us,
)
from ariadne_core.intake.parsing import SourceFormat
from ariadne_core.local_ai import (
    LOCAL_AI_ENRICHMENT_ENGINE_VERSION,
    EnrichmentRequest,
    LocalAIClient,
    LocalAIConfig,
    LocalAIError,
    LocalAIErrorCode,
    LocalAIHttpTransport,
    LocalAIProvider,
    LocalEntitySuggestion,
)

_RETENTION_US: Final = 86_400_000_000
_IDEMPOTENCY_RESERVATION_US: Final = 60_000_000
_IDEMPOTENCY_REPLAY_US: Final = 86_400_000_000
_COMPILER_CONFIGURATION_PREFIX: Final = "ariadne-intake-compiler-v1"

_SEARCH_TO_STORAGE: Final = {
    SearchPolicy.ALLOW: "SEARCH_ALLOWED",
    SearchPolicy.REQUIRE_APPROVAL: "APPROVAL_REQUIRED",
    SearchPolicy.STORE_ONLY: "STORE_ONLY",
    SearchPolicy.DENY: "SEARCH_DENIED",
}
_SEARCH_FROM_STORAGE: Final = {
    "SEARCH_ALLOWED": SearchPolicy.ALLOW,
    "APPROVAL_REQUIRED": SearchPolicy.REQUIRE_APPROVAL,
    "STORE_ONLY": SearchPolicy.STORE_ONLY,
    "SEARCH_DENIED": SearchPolicy.DENY,
}
_TRANSMISSION_TO_STORAGE: Final = {
    TransmissionPolicy.LOCAL_ONLY: "LOCAL_ONLY",
    TransmissionPolicy.POLICY_CONTROLLED: "PROVIDER_ALLOWLIST",
    TransmissionPolicy.REQUIRE_EACH_APPROVAL: "APPROVAL_REQUIRED",
    TransmissionPolicy.NEVER: "TRANSMISSION_DENIED",
}
_TRANSMISSION_FROM_STORAGE: Final = {
    "LOCAL_ONLY": TransmissionPolicy.LOCAL_ONLY,
    "APPROVAL_REQUIRED": TransmissionPolicy.REQUIRE_EACH_APPROVAL,
    "PROVIDER_ALLOWLIST": TransmissionPolicy.POLICY_CONTROLLED,
    "TRANSMISSION_DENIED": TransmissionPolicy.NEVER,
}


class Phase3Unavailable(RuntimeError):
    """The unlocked, profile-scoped Phase 3 boundary is unavailable."""


class Phase3NotFound(RuntimeError):
    """A resource is absent from the requested profile scope."""


class Phase3Conflict(RuntimeError):
    """A request conflicts with durable state or idempotency."""


class Phase3InvalidRequest(ValueError):
    """A bounded request failed validation without retaining its value."""


class _IdempotencyReservation:
    def __init__(
        self,
        repository: IntakeIdentityRepository,
        key: bytearray,
        *,
        vault_id: str,
        route_code: str,
        idempotency_key: str,
        request_digest: str,
    ) -> None:
        self._repository = repository
        self._vault_id = vault_id
        self._route_code = route_code
        self._token_hmac = hmac.new(
            key,
            idempotency_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self._request_digest = request_digest
        self._record_id: str | None = None

    def reserve(self) -> str | None:
        timestamp = now_us()
        with self._repository.engine.begin() as connection:
            existing = (
                connection.execute(
                    select(idempotency_records).where(
                        and_(
                            idempotency_records.c.vault_id == self._vault_id,
                            idempotency_records.c.route_code == self._route_code,
                            idempotency_records.c.actor_class == "LOCAL_USER",
                            idempotency_records.c.idempotency_key_hmac == self._token_hmac,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                expired = int(existing["expires_at_us"]) <= timestamp
                same_request = str(existing["request_digest"]) == self._request_digest
                result_id = existing["result_id"]
                if not expired:
                    if not same_request:
                        raise Phase3Conflict("idempotency request conflict")
                    if result_id is None:
                        raise Phase3Conflict("idempotency request is incomplete")
                    return str(result_id)
                if result_id is None:
                    if not same_request:
                        # The deterministic operation ID may already own a committed
                        # profile or decision even though completion was interrupted.
                        raise Phase3Conflict("idempotency request conflict")
                    self._record_id = str(existing["id"])
                    changed = connection.execute(
                        update(idempotency_records)
                        .where(
                            and_(
                                idempotency_records.c.vault_id == self._vault_id,
                                idempotency_records.c.id == self._record_id,
                                idempotency_records.c.result_id.is_(None),
                                idempotency_records.c.expires_at_us <= timestamp,
                            )
                        )
                        .values(
                            created_at_us=timestamp,
                            expires_at_us=timestamp + _IDEMPOTENCY_RESERVATION_US,
                        )
                    )
                    if changed.rowcount != 1:
                        raise Phase3Conflict("idempotency recovery conflict")
                    return None
                connection.execute(
                    delete(idempotency_records).where(
                        and_(
                            idempotency_records.c.vault_id == self._vault_id,
                            idempotency_records.c.id == str(existing["id"]),
                            idempotency_records.c.expires_at_us <= timestamp,
                        )
                    )
                )
            self._record_id = str(uuid7())
            connection.execute(
                insert(idempotency_records).values(
                    id=self._record_id,
                    vault_id=self._vault_id,
                    route_code=self._route_code,
                    actor_class="LOCAL_USER",
                    idempotency_key_hmac=self._token_hmac,
                    request_digest=self._request_digest,
                    result_type=None,
                    result_id=None,
                    created_at_us=timestamp,
                    expires_at_us=timestamp + _IDEMPOTENCY_RESERVATION_US,
                )
            )
        return None

    def complete(self, *, result_type: str, result_id: str) -> None:
        if self._record_id is None:
            return
        with self._repository.engine.begin() as connection:
            changed = connection.execute(
                update(idempotency_records)
                .where(
                    and_(
                        idempotency_records.c.vault_id == self._vault_id,
                        idempotency_records.c.id == self._record_id,
                        idempotency_records.c.result_id.is_(None),
                    )
                )
                .values(
                    result_type=result_type,
                    result_id=result_id,
                    expires_at_us=now_us() + _IDEMPOTENCY_REPLAY_US,
                )
            )
        if changed.rowcount != 1:
            raise Phase3Conflict("idempotency completion conflict")
        self._record_id = None

    @property
    def operation_id(self) -> str:
        if self._record_id is None:
            raise Phase3Conflict("idempotency reservation is unavailable")
        return self._record_id

    def abort(self) -> None:
        if self._record_id is None:
            return
        with self._repository.engine.begin() as connection:
            connection.execute(
                delete(idempotency_records).where(
                    and_(
                        idempotency_records.c.vault_id == self._vault_id,
                        idempotency_records.c.id == self._record_id,
                        idempotency_records.c.result_id.is_(None),
                    )
                )
            )
        self._record_id = None


class Phase3Coordinator:
    """Serialize local side effects and keep scoped key material request-local."""

    def __init__(
        self,
        vault: VaultManager,
        *,
        local_ai_transport: LocalAIHttpTransport | None = None,
    ) -> None:
        self._vault = vault
        self._local_ai_transport = local_ai_transport
        self._side_effect_lock = threading.RLock()

    @contextmanager
    def _repository(self) -> Iterator[tuple[IntakeIdentityRepository, bytearray]]:
        if not self._vault.is_unlocked:
            raise Phase3Unavailable("phase 3 requires an unlocked vault")
        with self._vault.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as key:
            repository = IntakeIdentityRepository(self._vault.engine, fingerprint_key=key)
            try:
                with self._side_effect_lock:
                    repository.purge_expired_temporary_content(
                        vault_id=self._vault.manifest.vault_id,
                    )
                yield repository, key
            finally:
                repository.close()

    def create_profile(self, body: ProfileCreateRequest) -> ProfileSummary:
        with self._side_effect_lock, self._repository() as (repository, key):
            vault_id = self._vault.manifest.vault_id
            digest = _request_digest(
                {
                    "displayLabel": body.display_label,
                    "purpose": body.purpose,
                }
            )
            reservation = _IdempotencyReservation(
                repository,
                key,
                vault_id=vault_id,
                route_code="PHASE3_PROFILE_CREATE",
                idempotency_key=body.idempotency_key,
                request_digest=digest,
            )
            existing_id = reservation.reserve()
            if existing_id is not None:
                try:
                    return _profile_summary(repository.get_profile(vault_id, existing_id))
                except LookupError as error:
                    raise Phase3Conflict("idempotency result is unavailable") from error
            operation_id = reservation.operation_id
            try:
                profile = repository.get_profile(vault_id, operation_id)
            except LookupError:
                try:
                    profile = repository.create_profile(
                        vault_id=vault_id,
                        display_label=body.display_label,
                        purpose=body.purpose,
                        profile_id=operation_id,
                    )
                except Exception:
                    reservation.abort()
                    raise
            try:
                reservation.complete(result_type="PROFILE", result_id=operation_id)
            except Exception:
                # Preserve the deterministic reservation ID: an expired lease can
                # recover the already-committed profile without creating a second one.
                raise
            if profile.id != operation_id:
                reservation.abort()
                raise Phase3Conflict("idempotency profile recovery conflict")
            return _profile_summary(profile)

    def list_profiles(self) -> ProfileListResult:
        with self._repository() as (repository, _key):
            profiles = repository.list_profiles(
                self._vault.manifest.vault_id,
                limit=MAX_PROFILE_SUMMARIES + 1,
            )
            return ProfileListResult(
                profiles=tuple(
                    _profile_summary(profile) for profile in profiles[:MAX_PROFILE_SUMMARIES]
                ),
                has_more=len(profiles) > MAX_PROFILE_SUMMARIES,
            )

    def delete_profile(self, body: ProfileDeleteRequest) -> ProfileDeleteResult:
        """Physically purge one confirmed profile and its profile-scoped records."""

        with self._side_effect_lock, self._repository() as (repository, _key):
            deleted_rows = repository.delete_profile(
                vault_id=self._vault.manifest.vault_id,
                profile_id=body.profile_id,
                expected_revision=body.expected_revision,
                confirmation_label=body.confirmation_label,
            )
        return ProfileDeleteResult(profile_id=body.profile_id, deleted_rows=deleted_rows)

    def ingest_paste(self, body: PasteIntakeRequest) -> IntakeReceipt:
        with self._side_effect_lock, self._repository() as (repository, key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            prepared = prepare_pasted_intake(
                body.content,
                display_name=body.display_name,
                semantic_enrichment_enabled=body.semantic_enrichment_enabled,
            )
            return self._persist_intake(
                repository,
                key,
                vault_id=vault_id,
                profile_id=body.profile_id,
                idempotency_key=body.idempotency_key,
                route_code="PHASE3_INTAKE_PASTE",
                prepared=prepared,
                retain_raw_source=body.retain_raw_source,
                declared_media_type=None,
                semantic_enrichment_enabled=body.semantic_enrichment_enabled,
            )

    def ingest_file(self, body: FileIntakeRequest) -> IntakeReceipt:
        with self._side_effect_lock, self._repository() as (repository, key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            content = _decode_selected_content(body.content_base64)
            if len(content) != body.expected_size_bytes or not hmac.compare_digest(
                hashlib.sha256(content).hexdigest(),
                body.expected_sha256,
            ):
                raise Phase3InvalidRequest("selected file binding is invalid")
            prepared = prepare_file_intake(
                display_name=body.display_name,
                content=content,
                declared_media_type=body.declared_media_type,
                semantic_enrichment_enabled=body.semantic_enrichment_enabled,
            )
            return self._persist_intake(
                repository,
                key,
                vault_id=vault_id,
                profile_id=body.profile_id,
                idempotency_key=body.idempotency_key,
                route_code="PHASE3_INTAKE_FILE",
                prepared=prepared,
                retain_raw_source=body.retain_raw_source,
                declared_media_type=body.declared_media_type,
                semantic_enrichment_enabled=body.semantic_enrichment_enabled,
            )

    def _persist_intake(
        self,
        repository: IntakeIdentityRepository,
        key: bytearray,
        *,
        vault_id: str,
        profile_id: str,
        idempotency_key: str,
        route_code: str,
        prepared: PreparedIntake,
        retain_raw_source: bool,
        declared_media_type: str | None,
        semantic_enrichment_enabled: bool,
    ) -> IntakeReceipt:
        digest = _request_digest(
            {
                "declaredMediaType": declared_media_type,
                "displayName": prepared.display_name,
                "profileId": profile_id,
                "retainRawSource": retain_raw_source,
                "semanticEnrichmentEnabled": semantic_enrichment_enabled,
                "sourceSha256": prepared.source_sha256,
            }
        )
        jobs = JobRepository(repository.engine, idempotency_hmac_key=key)
        manifest = JobManifest(
            operation="INTAKE_EXTRACT",
            resource_ids=[UUID(profile_id)],
            input_digest_sha256=digest,
        )
        job_idempotency_key = hashlib.sha256(f"{route_code}:{idempotency_key}".encode()).hexdigest()
        existing_job = jobs.find_active_replay(
            vault_id=vault_id,
            manifest=manifest,
            idempotency_key=job_idempotency_key,
        )
        if existing_job is not None:
            existing_source_id = repository.get_source_id_by_job(
                vault_id,
                profile_id,
                existing_job.id,
            )
            if existing_source_id is not None:
                source = repository.get_source_summary(vault_id, profile_id, existing_source_id)
                duplicate_count = repository.get_source_duplicate_count(
                    vault_id, existing_source_id
                )
                return _receipt(source, duplicate_count=duplicate_count)

        prepared = self._with_local_ai(
            repository,
            vault_id=vault_id,
            prepared=prepared,
            semantic_enrichment_enabled=semantic_enrichment_enabled,
        )
        source_id: str
        with repository.engine.begin() as connection:
            job, _replayed = jobs.create(
                vault_id=vault_id,
                manifest=manifest,
                idempotency_key=job_idempotency_key,
                connection=connection,
            )
            existing_source_id = repository.get_source_id_by_job(
                vault_id,
                profile_id,
                job.id,
                connection=connection,
            )
            if existing_source_id is None:
                record = repository.persist_compilation(
                    vault_id=vault_id,
                    profile_id=profile_id,
                    source=_source_draft(
                        prepared,
                        retain_raw_source=retain_raw_source,
                        declared_media_type=declared_media_type,
                    ),
                    extraction=_extraction_draft(
                        job.id,
                        semantic_enabled=semantic_enrichment_enabled,
                        local_ai=prepared.local_ai,
                    ),
                    segments=_segments(prepared, retain_content=retain_raw_source),
                    quarantine=_quarantine(prepared),
                    entities_input=_entities(prepared),
                    edges=_edges(prepared),
                    enrichment_outcome=_enrichment_outcome_draft(prepared.local_ai),
                    connection=connection,
                )
                duplicate_count = record.duplicate_entity_count
                source_id = record.source_id
            else:
                source_id = existing_source_id
                duplicate_count = repository.get_source_duplicate_count(
                    vault_id,
                    source_id,
                    connection=connection,
                )
            jobs.complete_inline_intake(
                vault_id=vault_id,
                job_id=job.id,
                connection=connection,
            )
        source = repository.get_source_summary(vault_id, profile_id, source_id)
        return _receipt(source, duplicate_count=duplicate_count)

    def _with_local_ai(
        self,
        repository: IntakeIdentityRepository,
        *,
        vault_id: str,
        prepared: PreparedIntake,
        semantic_enrichment_enabled: bool,
    ) -> PreparedIntake:
        if not semantic_enrichment_enabled:
            return replace(
                prepared,
                local_ai=PreparedLocalAIOutcome(status=LocalAIIntakeStatus.NOT_REQUESTED),
            )
        settings = SettingsRepository(repository.engine).get(vault_id).values
        if not settings.local_ai_enabled or settings.local_ai_selected_model is None:
            return replace(
                prepared,
                local_ai=PreparedLocalAIOutcome(status=LocalAIIntakeStatus.DISABLED),
            )
        provider = settings.local_ai_provider
        model_id = settings.local_ai_selected_model
        attempted = PreparedLocalAIOutcome(
            status=LocalAIIntakeStatus.UNAVAILABLE,
            provider=provider.value,
            model_id=model_id,
            engine_version=LOCAL_AI_ENRICHMENT_ENGINE_VERSION,
        )
        try:
            enrichment = LocalAIClient(
                LocalAIConfig(
                    enabled=True,
                    provider=provider,
                    endpoint=settings.local_ai_endpoint,
                ),
                transport=self._local_ai_transport,
            ).enrich(
                EnrichmentRequest(redacted_text=prepared.deterministic.redacted_text),
                model_id=model_id,
            )
        except LocalAIError as error:
            status = {
                LocalAIErrorCode.TIMEOUT: LocalAIIntakeStatus.TIMEOUT,
                LocalAIErrorCode.INVALID_RESPONSE: LocalAIIntakeStatus.INVALID_RESPONSE,
                LocalAIErrorCode.RESPONSE_LIMIT: LocalAIIntakeStatus.INVALID_RESPONSE,
            }.get(error.code, LocalAIIntakeStatus.UNAVAILABLE)
            return replace(prepared, local_ai=replace(attempted, status=status))
        except ValueError:
            return replace(
                prepared,
                local_ai=replace(attempted, status=LocalAIIntakeStatus.INVALID_RESPONSE),
            )
        accepted = _accepted_local_ai_suggestions(prepared, enrichment.entities)
        return replace(
            prepared,
            local_ai=PreparedLocalAIOutcome(
                status=LocalAIIntakeStatus.SUCCEEDED,
                provider=enrichment.provider.value,
                model_id=enrichment.model_id,
                engine_version=enrichment.engine_version,
                suggestions=accepted,
            ),
        )

    def review_entities(self, body: EntityReviewRequest) -> EntityReviewResult:
        with self._repository() as (repository, _key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            if body.source_id is not None:
                try:
                    repository.get_source_summary(vault_id, body.profile_id, body.source_id)
                except LookupError as error:
                    raise Phase3NotFound("intake source is unavailable") from error
            entities = repository.list_entities(
                vault_id,
                body.profile_id,
                limit=body.limit + 1,
                source_id=body.source_id,
            )
            return EntityReviewResult(
                profile_id=body.profile_id,
                entities=tuple(_entity_summary(item) for item in entities[: body.limit]),
                quarantine_count=repository.count_quarantine(
                    vault_id,
                    body.profile_id,
                    source_id=body.source_id,
                ),
                has_more=len(entities) > body.limit,
            )

    def list_entity_origins(self, body: EntityOriginPageRequest) -> EntityOriginPageResult:
        with self._repository() as (repository, _key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            try:
                origins, total = repository.list_entity_origins(
                    vault_id,
                    body.profile_id,
                    body.entity_id,
                    offset=body.offset,
                    limit=body.limit,
                )
            except LookupError as error:
                raise Phase3NotFound("entity is unavailable in this profile") from error
            return EntityOriginPageResult(
                profile_id=body.profile_id,
                entity_id=body.entity_id,
                offset=body.offset,
                limit=body.limit,
                origins=tuple(_entity_origin(origin) for origin in origins),
                total=total,
                has_more=body.offset + len(origins) < total,
            )

    def decide_entity(self, body: EntityDecisionRequest) -> EntitySummary:
        with self._side_effect_lock, self._repository() as (repository, key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            digest = _request_digest(body.model_dump(mode="json", exclude={"idempotency_key"}))
            reservation = _IdempotencyReservation(
                repository,
                key,
                vault_id=vault_id,
                route_code="PHASE3_ENTITY_DECISION",
                idempotency_key=body.idempotency_key,
                request_digest=digest,
            )
            existing_id = reservation.reserve()
            if existing_id is not None:
                try:
                    historical = repository.get_entity_for_decision(
                        vault_id,
                        body.profile_id,
                        existing_id,
                    )
                    if historical is None:
                        raise LookupError("idempotency decision is unavailable")
                    return _entity_summary(historical)
                except (LookupError, RuntimeError) as error:
                    raise Phase3Conflict("idempotency result is unavailable") from error
            operation_id = reservation.operation_id
            recovered = repository.get_entity_for_decision(
                vault_id,
                body.profile_id,
                operation_id,
            )
            if recovered is not None:
                reservation.complete(
                    result_type="ENTITY_DECISION",
                    result_id=operation_id,
                )
                return _entity_summary(recovered)
            reason_code = (
                None
                if body.reason is None
                else (
                    "USER_REASON_"
                    + hmac.new(
                        key,
                        body.reason.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()[:16]
                )
            )
            try:
                repository.record_decision(
                    vault_id=vault_id,
                    profile_id=body.profile_id,
                    entity_id=body.entity_id,
                    expected_revision=body.expected_revision,
                    decision_type=body.decision_type.value,
                    review_state=body.review_state.value,
                    sensitivity=body.sensitivity.value,
                    temporal_state=body.temporal_state.value,
                    search_policy=_SEARCH_TO_STORAGE[body.search_policy],
                    transmission_policy=_TRANSMISSION_TO_STORAGE[body.transmission_policy],
                    reason_code=reason_code,
                    decision_id=operation_id,
                )
            except Exception:
                reservation.abort()
                raise
            historical = repository.get_entity_for_decision(
                vault_id,
                body.profile_id,
                operation_id,
            )
            if historical is None:
                raise Phase3Conflict("persisted decision result is unavailable")
            reservation.complete(
                result_type="ENTITY_DECISION",
                result_id=operation_id,
            )
            return _entity_summary(historical)

    def graph_snapshot(self, body: GraphSnapshotRequest) -> GraphSnapshot:
        with self._repository() as (repository, _key):
            vault_id = self._vault.manifest.vault_id
            _require_profile(repository, vault_id, body.profile_id)
            stored = repository.graph_snapshot(
                vault_id,
                body.profile_id,
                limit=body.max_nodes + 1,
                include_sensitive=body.include_sensitive,
                edge_node_limit=body.max_nodes,
                edge_limit=251,
            )
            selected = stored.nodes[: body.max_nodes]
            node_ids = {node.id for node in selected}
            edges = tuple(
                edge
                for edge in stored.edges
                if edge.from_node_id in node_ids and edge.to_node_id in node_ids
            )
            truncated = len(stored.nodes) > body.max_nodes or len(stored.edges) > 250
            return GraphSnapshot(
                profile_id=body.profile_id,
                nodes=tuple(
                    GraphNode(
                        node_id=node.id,
                        node_type=node.node_type,
                        display_label=node.display_label,
                        sensitivity=Sensitivity(node.sensitivity),
                        entity_id=node.entity_id,
                    )
                    for node in selected
                ),
                edges=tuple(
                    GraphEdge(
                        edge_id=edge.id,
                        from_node_id=edge.from_node_id,
                        to_node_id=edge.to_node_id,
                        edge_type=edge.edge_type,
                        confidence_micros=edge.confidence_micros,
                        origin_type=edge.origin_type,
                        explanation=edge.explanation[:160],
                        support_count=edge.support_count,
                        contradiction_count=edge.contradiction_count,
                        evidence=tuple(
                            GraphEdgeEvidence(
                                source_id=item.source_id,
                                segment_ordinal=item.segment_ordinal,
                                disposition=GraphEvidenceDisposition(item.disposition),
                                confidence_micros=item.confidence_micros,
                                visibility=GraphVisibility(item.visibility),
                                source_span_start=item.source_span_start,
                                source_span_end=item.source_span_end,
                                observed_at_us=item.observed_at_us,
                                origin_type=item.origin_type,
                                explanation=item.explanation,
                            )
                            for item in edge.evidence
                        ),
                        evidence_truncated=edge.evidence_truncated,
                    )
                    for edge in edges[:250]
                ),
                truncated=truncated,
            )


def _request_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _decode_selected_content(value: str) -> bytes:
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise Phase3InvalidRequest("selected file encoding is invalid") from None
    if base64.b64encode(content).decode("ascii") != value:
        raise Phase3InvalidRequest("selected file encoding is non-canonical")
    return content


def _normalise_local_ai_surface(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _local_ai_display_mask(entity_type: str, canonical: str) -> str:
    if entity_type == "PERSON":
        return " ".join(f"{part[0]}{'•' * min(5, len(part) - 1)}" for part in canonical.split())
    return f"[{entity_type.casefold().replace('_', ' ')}]"


def _accepted_local_ai_suggestions(
    prepared: PreparedIntake,
    suggestions: tuple[LocalEntitySuggestion, ...],
) -> tuple[LocalEntitySuggestion, ...]:
    existing = {
        (candidate.entity_type.value, candidate.canonical_value.casefold())
        for candidate in prepared.deterministic.candidates
    }
    existing.update(
        (item.candidate.entity_type.value, item.candidate.canonical_value.casefold())
        for item in prepared.structured_candidates
    )
    existing.update(
        (entity.entity_type.value, entity.canonical_value.casefold())
        for entity in prepared.semantic.entities
    )
    redacted_text = prepared.deterministic.redacted_text
    accepted: list[LocalEntitySuggestion] = []
    for suggestion in suggestions:
        if (
            suggestion.end > len(redacted_text)
            or redacted_text[suggestion.start : suggestion.end] != suggestion.surface
            or "█" in suggestion.surface
        ):
            continue
        canonical = _normalise_local_ai_surface(suggestion.surface)
        if not canonical:
            continue
        fingerprint = (suggestion.entity_type.value, canonical.casefold())
        if fingerprint in existing:
            continue
        existing.add(fingerprint)
        accepted.append(
            replace(
                suggestion,
                confidence_micros=min(850_000, suggestion.confidence_micros),
            )
        )
    return tuple(accepted)


def _enrichment_outcome_draft(outcome: PreparedLocalAIOutcome) -> EnrichmentOutcomeDraft:
    return EnrichmentOutcomeDraft(
        status=outcome.status.value,
        provider=outcome.provider,
        model_id=outcome.model_id,
        engine_version=outcome.engine_version,
        suggestion_count=len(outcome.suggestions),
    )


def _require_profile(
    repository: IntakeIdentityRepository,
    vault_id: str,
    profile_id: str,
) -> None:
    try:
        profile = repository.get_profile(vault_id, profile_id)
    except LookupError as error:
        raise Phase3NotFound("profile is unavailable") from error
    if profile.status != "ACTIVE":
        raise Phase3Conflict("profile is not active")


def _profile_summary(profile) -> ProfileSummary:  # type: ignore[no-untyped-def]
    return ProfileSummary(
        profile_id=profile.id,
        display_label=profile.display_label,
        purpose=profile.purpose,
        status=profile.status,
        revision=profile.revision,
    )


def _receipt(source: SourceSummary, *, duplicate_count: int = 0) -> IntakeReceipt:
    return IntakeReceipt(
        source_id=source.id,
        profile_id=source.profile_id,
        state="READY_FOR_REVIEW",
        source_kind=source.source_kind,
        segment_count=max(0, source.segment_count - 1),
        candidate_count=source.entity_count,
        duplicate_count=duplicate_count,
        quarantine_count=source.quarantine_count,
        revision=source.revision,
        local_ai_status=ApiLocalAIIntakeStatus(source.local_ai_status),
        local_ai_provider=(
            None if source.local_ai_provider is None else LocalAIProvider(source.local_ai_provider)
        ),
        local_ai_model=source.local_ai_model,
        local_ai_engine_version=source.local_ai_engine_version,
        local_ai_suggestion_count=source.local_ai_suggestion_count,
    )


def _entity_summary(entity: StoredEntitySummary) -> EntitySummary:
    try:
        search_policy = _SEARCH_FROM_STORAGE[entity.search_policy]
        transmission_policy = _TRANSMISSION_FROM_STORAGE[entity.transmission_policy]
    except KeyError as error:
        raise Phase3Conflict("stored entity policy is unsupported") from error
    return EntitySummary(
        entity_id=entity.id,
        entity_type=entity.entity_type,
        display_value=entity.display_mask,
        sensitivity=Sensitivity(entity.sensitivity),
        review_state=ReviewState(entity.review_state),
        temporal_state=TemporalState(entity.temporal_state),
        search_policy=search_policy,
        transmission_policy=transmission_policy,
        confidence_micros=entity.confidence_micros,
        provenance_label=entity.provenance_label,
        origins=tuple(_entity_origin(origin) for origin in entity.origins),
        origins_truncated=entity.origins_truncated,
        revision=entity.revision,
    )


def _entity_origin(origin: EntityOriginSummary) -> EntityOrigin:
    return EntityOrigin(
        source_id=origin.source_id,
        source_display_name=origin.source_display_name,
        source_sha256=origin.source_sha256,
        segment_id=origin.segment_id,
        segment_index=origin.segment_index,
        segment_locator=origin.segment_locator,
        source_span_start=origin.source_span_start,
        source_span_end=origin.source_span_end,
        extraction_run_id=origin.extraction_run_id,
        extractor_kind=origin.extractor_kind,
        extractor_name=origin.extractor_name,
        extractor_version=origin.extractor_version,
        origin_kind=origin.origin_kind,
        observed_at_us=origin.observed_at_us,
        confidence_micros=origin.confidence_micros,
        explanation=origin.explanation,
    )


def _source_draft(
    prepared: PreparedIntake,
    *,
    retain_raw_source: bool,
    declared_media_type: str | None,
) -> SourceDraft:
    timestamp = now_us()
    return SourceDraft(
        source_kind=prepared.source_kind,
        display_name=prepared.display_name,
        declared_mime=declared_media_type,
        detected_mime=prepared.detected_media_type,
        byte_size=prepared.byte_count,
        sha256=prepared.source_sha256,
        retention_state="RETAINED" if retain_raw_source else "TEMPORARY",
        retention_expires_at_us=None if retain_raw_source else timestamp + _RETENTION_US,
        consent_confirmed_at_us=timestamp,
    )


def _extraction_draft(
    job_id: str,
    *,
    semantic_enabled: bool,
    local_ai: PreparedLocalAIOutcome,
) -> ExtractionDraft:
    timestamp = now_us()
    configuration = canonical_json(
        {
            "compiler": _COMPILER_CONFIGURATION_PREFIX,
            "localAIEngineVersion": local_ai.engine_version,
            "localAIModel": local_ai.model_id,
            "localAIProvider": local_ai.provider,
            "localAIStatus": local_ai.status.value,
            "semantic": semantic_enabled,
        }
    )
    return ExtractionDraft(
        job_id=job_id,
        engine_kind="DETERMINISTIC",
        engine_name="bounded-local-rules",
        engine_version="1",
        configuration_hash=hashlib.sha256(configuration.encode("utf-8")).hexdigest(),
        state="SUCCEEDED",
        started_at_us=timestamp,
        finished_at_us=timestamp,
    )


def _segments(
    prepared: PreparedIntake,
    *,
    retain_content: bool,
) -> tuple[SegmentDraft, ...]:
    structured = prepared.parsed.source_format in {
        SourceFormat.CSV,
        SourceFormat.JSON,
        SourceFormat.VCARD,
    }
    master = SegmentDraft(
        ordinal=0,
        segment_kind="TEXT",
        locator_json='{"kind":"redacted_source"}',
        content_text=(
            prepared.deterministic.redacted_text if retain_content and not structured else None
        ),
    )
    parsed = tuple(
        SegmentDraft(
            ordinal=segment.index + 1,
            segment_kind=segment.kind.value,
            locator_json=json.dumps(
                {"locator": segment.locator},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            content_text=segment.text if retain_content else None,
        )
        for segment in prepared.parsed.segments
    )
    return (master, *parsed)


def _quarantine(prepared: PreparedIntake) -> tuple[QuarantineDraft, ...]:
    deadline = now_us() + _RETENTION_US
    count = len(prepared.deterministic.quarantine) + len(prepared.structured_quarantine)
    return tuple(
        QuarantineDraft(reason_code="RESTRICTED_VALUE", retention_expires_at_us=deadline)
        for _ in range(count)
    )


def _entities(prepared: PreparedIntake) -> tuple[EntityDraft, ...]:
    drafts: list[EntityDraft] = []
    keys: dict[tuple[str, str], str] = {}
    structured = prepared.parsed.source_format in {
        SourceFormat.CSV,
        SourceFormat.JSON,
        SourceFormat.VCARD,
    }

    def append(
        *,
        entity_type: str,
        canonical_value: str,
        display_mask: str,
        sensitivity: str,
        segment_ordinal: int,
        spans: tuple[SourceSpan, ...],
        confidence_micros: int,
        explanation: str,
        origin_kind: str = "DETERMINISTIC",
        search_policy: str | None = None,
        transmission_policy: str | None = None,
    ) -> None:
        fingerprint = (entity_type, canonical_value)
        origins = tuple(
            EntityOriginDraft(
                source_segment_ordinal=segment_ordinal,
                origin_kind=origin_kind,
                confidence_micros=confidence_micros,
                explanation=explanation,
                source_span_start=span.start,
                source_span_end=span.end,
            )
            for span in spans
        )
        local_key = keys.get(fingerprint)
        if local_key is not None:
            index = next(i for i, item in enumerate(drafts) if item.local_key == local_key)
            drafts[index] = replace(drafts[index], origins=(*drafts[index].origins, *origins))
            return
        local_key = f"entity-{len(drafts)}"
        keys[fingerprint] = local_key
        highly_sensitive = sensitivity == "HIGHLY_SENSITIVE"
        first_origin = origins[0]
        drafts.append(
            EntityDraft(
                local_key=local_key,
                source_segment_ordinal=segment_ordinal,
                entity_type=entity_type,
                canonical_value=canonical_value,
                display_mask=display_mask,
                sensitivity=sensitivity,
                review_state="UNREVIEWED",
                temporal_state="UNKNOWN",
                search_policy=(
                    search_policy
                    if search_policy is not None
                    else ("STORE_ONLY" if highly_sensitive else "APPROVAL_REQUIRED")
                ),
                transmission_policy=(
                    transmission_policy
                    if transmission_policy is not None
                    else ("TRANSMISSION_DENIED" if highly_sensitive else "LOCAL_ONLY")
                ),
                origin_kind=origin_kind,
                origin_confidence_micros=confidence_micros,
                origin_explanation=explanation,
                source_span_start=first_origin.source_span_start,
                source_span_end=first_origin.source_span_end,
                graph_node_type=entity_type,
                graph_visibility="PRIVATE_ONLY",
                origins=origins,
            )
        )

    if not structured:
        for candidate in prepared.deterministic.candidates:
            append(
                entity_type=candidate.entity_type.value,
                canonical_value=candidate.canonical_value,
                display_mask=candidate.display_mask,
                sensitivity=candidate.sensitivity.value,
                segment_ordinal=0,
                spans=candidate.spans,
                confidence_micros=candidate.confidence_micros,
                explanation=candidate.extractor,
            )
    for item in prepared.structured_candidates:
        candidate = item.candidate
        append(
            entity_type=candidate.entity_type.value,
            canonical_value=candidate.canonical_value,
            display_mask=candidate.display_mask,
            sensitivity=candidate.sensitivity.value,
            segment_ordinal=item.segment_index + 1,
            spans=candidate.spans,
            confidence_micros=candidate.confidence_micros,
            explanation=candidate.extractor,
        )
    if not structured:
        for entity in prepared.semantic.entities:
            append(
                entity_type=entity.entity_type.value,
                canonical_value=entity.canonical_value,
                display_mask=entity.display_mask,
                sensitivity=entity.sensitivity.value,
                segment_ordinal=0,
                spans=(entity.span,),
                confidence_micros=entity.confidence_micros,
                explanation=entity.rule_code,
            )

    for suggestion in prepared.local_ai.suggestions:
        canonical = _normalise_local_ai_surface(suggestion.surface)
        append(
            entity_type=suggestion.entity_type.value,
            canonical_value=canonical,
            display_mask=_local_ai_display_mask(suggestion.entity_type.value, canonical),
            sensitivity="SENSITIVE",
            segment_ordinal=0,
            spans=(SourceSpan(suggestion.start, suggestion.end),),
            confidence_micros=suggestion.confidence_micros,
            explanation=(
                f"local-ai:v{prepared.local_ai.engine_version}:probable:review-required:"
                f"provider={prepared.local_ai.provider}:model={prepared.local_ai.model_id}:"
                f"rule={suggestion.explanation_code}"
            ),
            origin_kind="LOCAL_MODEL",
            search_policy="STORE_ONLY",
            transmission_policy="LOCAL_ONLY",
        )

    if structured:
        return tuple(drafts)

    for relationship in prepared.semantic.relationships:
        if relationship.relationship_type.value not in {"PREVIOUS_USERNAME", "CURRENT_USERNAME"}:
            continue
        target_key = (
            relationship.target.entity_type,
            relationship.target.canonical_value,
        )
        local_key = keys.get(target_key)
        if local_key is None:
            continue
        index = next(i for i, item in enumerate(drafts) if item.local_key == local_key)
        drafts[index] = replace(
            drafts[index],
            temporal_state=(
                "HISTORICAL"
                if relationship.relationship_type.value == "PREVIOUS_USERNAME"
                else "CURRENT"
            ),
        )
    return tuple(drafts)


def _edges(prepared: PreparedIntake) -> tuple[EdgeDraft, ...]:
    if prepared.parsed.source_format in {
        SourceFormat.CSV,
        SourceFormat.JSON,
        SourceFormat.VCARD,
    }:
        return ()
    entity_keys = {
        (draft.entity_type, draft.canonical_value): draft.local_key for draft in _entities(prepared)
    }
    timestamp = now_us()
    edges: list[EdgeDraft] = []
    for relationship in prepared.semantic.relationships:
        source = entity_keys.get(
            (relationship.source.entity_type, relationship.source.canonical_value)
        )
        target = entity_keys.get(
            (relationship.target.entity_type, relationship.target.canonical_value)
        )
        if source is None or target is None or source == target:
            continue
        edges.append(
            EdgeDraft(
                from_entity_key=source,
                to_entity_key=target,
                edge_type=relationship.relationship_type.value,
                confidence_micros=relationship.confidence_micros,
                visibility="PRIVATE_ONLY",
                observed_at_us=timestamp,
                origin_type="DETERMINISTIC",
                explanation=relationship.explanation_code,
                source_segment_ordinal=0,
                disposition="CONTRADICTS" if relationship.contradictory else "SUPPORTS",
                source_span_start=relationship.span.start,
                source_span_end=relationship.span.end,
            )
        )
    return tuple(edges)


def translate_phase3_exception(
    error: Exception,
) -> Phase3Conflict | Phase3NotFound | Phase3InvalidRequest:
    """Collapse persistence/parser details into value-free route errors."""

    if isinstance(error, (Phase3Conflict, Phase3NotFound, Phase3InvalidRequest)):
        return error
    if isinstance(error, LookupError):
        return Phase3NotFound("profile resource is unavailable")
    if isinstance(error, (RevisionConflict, IdempotencyConflict, IntegrityError)):
        return Phase3Conflict("phase 3 state conflict")
    if isinstance(error, (ValueError, RuntimeError)):
        return Phase3InvalidRequest("phase 3 request is invalid")
    return Phase3Conflict("phase 3 operation failed")
