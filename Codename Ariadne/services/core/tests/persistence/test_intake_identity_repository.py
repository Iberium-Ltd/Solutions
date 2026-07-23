from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest
from alembic import command
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.intake_identity_repository import (
    EdgeDraft,
    EntityDraft,
    ExtractionDraft,
    IntakeIdentityRepository,
    QuarantineDraft,
    SegmentDraft,
    SourceDraft,
    VariantDraft,
)
from ariadne_core.infrastructure.db.migrate import migration_config, upgrade_to_head
from ariadne_core.infrastructure.db.models import (
    audit_events,
    entities,
    entity_decisions,
    entity_origins,
    entity_variant_decisions,
    entity_variants,
    event_outbox,
    graph_edge_decisions,
    graph_edge_origins,
    graph_edges,
    graph_nodes,
    intake_segments,
    intake_sources,
    quarantine_items,
)
from ariadne_core.infrastructure.db.repositories import (
    JobManifest,
    JobRepository,
    RevisionConflict,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian

FINGERPRINT_KEY = b"f" * 32


def test_persistence_drafts_hide_source_and_identity_values_from_repr() -> None:
    source = _source()
    segment = _segments()[0]
    entity = _entities()[0]

    assert source.display_name not in repr(source)
    assert segment.locator_json not in repr(segment)
    assert segment.content_text not in repr(segment)
    assert entity.canonical_value not in repr(entity)
    assert entity.display_mask not in repr(entity)
    assert entity.variants[0].value not in repr(entity.variants[0])


def _source() -> SourceDraft:
    return SourceDraft(
        source_kind="PASTE",
        display_name="Synthetic local paste",
        detected_mime="text/plain",
        byte_size=96,
        sha256=hashlib.sha256(b"synthetic compiler input").hexdigest(),
        retention_state="TEMPORARY",
        consent_confirmed_at_us=1_000,
        retention_expires_at_us=9_000,
    )


def _segments() -> tuple[SegmentDraft, ...]:
    return (
        SegmentDraft(
            ordinal=0,
            segment_kind="TEXT",
            locator_json='{"byteEnd":32,"byteStart":0}',
            content_text="Synthetic alias: river-otter",
            language="en",
        ),
        SegmentDraft(
            ordinal=1,
            segment_kind="TEXT",
            locator_json='{"byteEnd":64,"byteStart":33}',
            content_text="Synthetic project: glass-orchid",
            language="en",
        ),
    )


def _entities() -> tuple[EntityDraft, ...]:
    return (
        EntityDraft(
            local_key="alias",
            source_segment_ordinal=0,
            source_span_start=17,
            source_span_end=28,
            entity_type="USERNAME",
            canonical_value="river-otter",
            display_mask="riv••••tter",
            sensitivity="SENSITIVE",
            review_state="UNREVIEWED",
            temporal_state="CURRENT",
            search_policy="APPROVAL_REQUIRED",
            transmission_policy="LOCAL_ONLY",
            origin_kind="DETERMINISTIC",
            origin_confidence_micros=900_000,
            origin_explanation="Synthetic deterministic alias token",
            variants=(
                VariantDraft(
                    variant_type="EXACT",
                    value="river-otter",
                    generator="synthetic-rules",
                    generator_version="1",
                    rank=1,
                    estimated_risk="LOW",
                ),
            ),
            graph_node_type="USERNAME",
            graph_visibility="PRIVATE_ONLY",
        ),
        EntityDraft(
            local_key="project",
            source_segment_ordinal=1,
            source_span_start=19,
            source_span_end=31,
            entity_type="PROJECT",
            canonical_value="glass-orchid",
            display_mask="glass-orchid",
            sensitivity="PUBLIC",
            review_state="UNREVIEWED",
            temporal_state="UNKNOWN",
            search_policy="STORE_ONLY",
            transmission_policy="LOCAL_ONLY",
            origin_kind="DETERMINISTIC",
            origin_confidence_micros=800_000,
            origin_explanation="Synthetic deterministic project token",
            graph_node_type="PROJECT",
            graph_visibility="PUBLICLY_ATTRIBUTABLE",
        ),
    )


def _new_job(manager: VaultManager) -> str:
    record, created = JobRepository(
        manager.engine,
        idempotency_hmac_key=b"j" * 32,
    ).create(
        vault_id=manager.manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=f"synthetic-{uuid7()}",
    )
    assert created is False
    return record.id


def _persist(
    manager: VaultManager,
    repository: IntakeIdentityRepository,
    profile_id: str,
    *,
    edge_disposition: str = "SUPPORTS",
    source: SourceDraft | None = None,
):
    timestamp = 2_000
    return repository.persist_compilation(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        source=_source() if source is None else source,
        extraction=ExtractionDraft(
            job_id=_new_job(manager),
            engine_kind="DETERMINISTIC",
            engine_name="synthetic-compiler",
            engine_version="1.0.0",
            configuration_hash=hashlib.sha256(b"synthetic rules v1").hexdigest(),
            state="SUCCEEDED",
            started_at_us=timestamp,
            finished_at_us=timestamp + 100,
        ),
        segments=_segments(),
        quarantine=(
            QuarantineDraft(
                reason_code="RESTRICTED_VALUE",
                retention_expires_at_us=8_000,
                opaque_blob_key="quarantine/synthetic-object",
                byte_size_plaintext=24,
                byte_size_ciphertext=52,
                sha256_plaintext=hashlib.sha256(b"synthetic quarantined bytes").hexdigest(),
                sha256_ciphertext=hashlib.sha256(b"synthetic encrypted bytes").hexdigest(),
                encryption_version="AES_256_GCM_V1",
                key_version=1,
            ),
        ),
        entities_input=_entities(),
        edges=(
            EdgeDraft(
                from_entity_key="alias",
                to_entity_key="project",
                edge_type="CREATED",
                confidence_micros=700_000,
                visibility="PRIVATE_ONLY",
                observed_at_us=timestamp,
                origin_type="DETERMINISTIC",
                explanation="Synthetic co-occurrence rule",
                disposition=edge_disposition,
                source_span_start=4,
                source_span_end=40,
            ),
        ),
    )


def test_atomic_compilation_persists_keyed_fingerprints_provenance_and_redacted_event(
    tmp_path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic intake vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic subject",
        purpose="Authorised synthetic test",
    )

    result = _persist(manager, repository, profile.id)
    summaries = repository.list_entities(manager.manifest.vault_id, profile.id)
    graph = repository.graph_snapshot(manager.manifest.vault_id, profile.id)

    assert len(result.segment_ids) == 2
    assert len(result.quarantine_ids) == 1
    assert len(summaries) == 2
    assert {summary.display_mask for summary in summaries} == {"riv••••tter", "glass-orchid"}
    assert {(summary.confidence_micros, summary.provenance_label) for summary in summaries} == {
        (900_000, "Synthetic deterministic alias token"),
        (800_000, "Synthetic deterministic project token"),
    }
    assert not hasattr(summaries[0], "canonical_value")
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert all(summary.display_mask not in repr(summary) for summary in summaries)
    assert all(summary.provenance_label not in repr(summary) for summary in summaries)
    assert all(node.display_label not in repr(node) for node in graph.nodes)
    assert graph.edges[0].origin_type == "DETERMINISTIC"
    assert graph.edges[0].explanation == "Synthetic co-occurrence rule"
    assert graph.edges[0].explanation not in repr(graph.edges[0])
    assert graph.edges[0].support_count == 1
    assert graph.edges[0].contradiction_count == 0
    assert len(graph.edges[0].evidence) == 1
    assert graph.edges[0].evidence[0].source_id == result.source_id
    assert graph.edges[0].evidence[0].segment_ordinal == 0
    assert graph.edges[0].evidence[0].disposition == "SUPPORTS"
    assert graph.edges[0].evidence[0].explanation not in repr(graph.edges[0].evidence[0])

    alias_id = dict(result.entity_ids)["alias"]
    segment_id = dict(result.segment_ids)[0]
    expected_entity_hmac = hmac.new(
        FINGERPRINT_KEY,
        b"river-otter",
        hashlib.sha256,
    ).hexdigest()
    plain_entity_hash = hashlib.sha256(b"river-otter").hexdigest()
    with manager.engine.connect() as connection:
        entity_hmac = connection.execute(
            select(entities.c.value_hmac).where(entities.c.id == alias_id)
        ).scalar_one()
        variant_hmac = connection.execute(
            select(entity_variants.c.value_hmac).where(entity_variants.c.entity_id == alias_id)
        ).scalar_one()
        origin = (
            connection.execute(select(entity_origins).where(entity_origins.c.entity_id == alias_id))
            .mappings()
            .one()
        )
        edge_origin = (
            connection.execute(
                select(graph_edge_origins).where(
                    graph_edge_origins.c.graph_edge_id == result.graph_edge_ids[0]
                )
            )
            .mappings()
            .one()
        )
        payload = connection.execute(
            select(event_outbox.c.payload_json).where(
                event_outbox.c.event_type == "INTAKE_COMPILATION_PERSISTED"
            )
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count())
            .select_from(audit_events)
            .where(audit_events.c.event_type == "INTAKE_COMPILATION_PERSISTED")
        ).scalar_one()
    assert entity_hmac == expected_entity_hmac
    assert variant_hmac == expected_entity_hmac
    assert entity_hmac != plain_entity_hash
    assert origin["intake_segment_id"] == segment_id
    assert origin["extraction_run_id"] == result.extraction_run_id
    assert origin["raw_result_id"] is None
    assert origin["evidence_artifact_id"] is None
    assert origin["source_span_start"] == 17
    assert origin["source_span_end"] == 28
    assert edge_origin["intake_source_id"] == result.source_id
    assert edge_origin["intake_segment_id"] == segment_id
    assert edge_origin["extraction_run_id"] == result.extraction_run_id
    assert edge_origin["disposition"] == "SUPPORTS"
    assert (
        edge_origin["observation_hmac"]
        != hashlib.sha256(b"Synthetic co-occurrence rule").hexdigest()
    )
    assert json.loads(payload) == {
        "duplicateEdgeCount": 0,
        "duplicateEntityCount": 0,
        "duplicateVariantCount": 0,
        "edgeCount": 1,
        "entityCount": 2,
        "localAIEngineVersion": None,
        "localAIModel": None,
        "localAIProvider": None,
        "localAIStatus": "NOT_REQUESTED",
        "localAISuggestionCount": 0,
        "quarantineCount": 1,
        "segmentCount": 2,
    }
    assert "river-otter" not in payload
    assert audit_count == 1
    repository.close()
    manager.lock()


def test_entity_projection_preserves_exact_multi_source_origins_with_bounded_scope(
    tmp_path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic provenance vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic primary provenance profile",
        purpose="Authorised synthetic provenance test",
    )
    other_profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic isolated provenance profile",
        purpose="Synthetic profile isolation test",
    )
    first_source = replace(
        _source(),
        display_name="Synthetic source alpha",
        sha256=hashlib.sha256(b"synthetic source alpha").hexdigest(),
    )
    second_source = replace(
        _source(),
        display_name="Synthetic source beta",
        sha256=hashlib.sha256(b"synthetic source beta").hexdigest(),
    )
    first = _persist(manager, repository, profile.id, source=first_source)
    second = _persist(manager, repository, profile.id, source=second_source)
    isolated = _persist(
        manager,
        repository,
        other_profile.id,
        source=replace(
            _source(),
            display_name="Password: synthetic-provenance-secret",
            sha256=hashlib.sha256(b"synthetic isolated source").hexdigest(),
        ),
    )

    entity_id = dict(first.entity_ids)["alias"]
    first_segment_id = dict(first.segment_ids)[0]
    with manager.engine.begin() as connection:
        for ordinal in range(31):
            timestamp = 10_000 + ordinal
            connection.execute(
                insert(entity_origins).values(
                    id=str(uuid7()),
                    vault_id=manager.manifest.vault_id,
                    profile_id=profile.id,
                    entity_id=entity_id,
                    extraction_run_id=first.extraction_run_id,
                    intake_segment_id=first_segment_id,
                    raw_result_id=None,
                    evidence_artifact_id=None,
                    source_span_start=17,
                    source_span_end=28,
                    origin_kind="DETERMINISTIC",
                    confidence_micros=100_000 + ordinal,
                    explanation=f"Synthetic repeated observation {ordinal}",
                    observed_at_us=timestamp,
                    created_at_us=timestamp,
                )
            )

    profile_entities = repository.list_entities(manager.manifest.vault_id, profile.id)
    alias = next(item for item in profile_entities if item.id == entity_id)
    assert len(alias.origins) == 32
    assert alias.origins_truncated is True
    origin_page_selects: list[str] = []

    def record_origin_page_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            origin_page_selects.append(statement)

    event.listen(manager.engine, "before_cursor_execute", record_origin_page_sql)
    try:
        first_origin_page, total_origins = repository.list_entity_origins(
            manager.manifest.vault_id,
            profile.id,
            entity_id,
            offset=0,
            limit=10,
        )
    finally:
        event.remove(manager.engine, "before_cursor_execute", record_origin_page_sql)
    assert origin_page_selects
    assert all(
        forbidden not in statement.casefold()
        for statement in origin_page_selects
        for forbidden in (
            "entities.canonical_value",
            "entity_variants.value",
            "intake_segments.content_text",
        )
    )
    repeated_first_page, repeated_total = repository.list_entity_origins(
        manager.manifest.vault_id,
        profile.id,
        entity_id,
        offset=0,
        limit=10,
    )
    second_origin_page, _ = repository.list_entity_origins(
        manager.manifest.vault_id,
        profile.id,
        entity_id,
        offset=10,
        limit=10,
    )
    third_origin_page, _ = repository.list_entity_origins(
        manager.manifest.vault_id,
        profile.id,
        entity_id,
        offset=20,
        limit=10,
    )
    final_origin_page, final_total = repository.list_entity_origins(
        manager.manifest.vault_id,
        profile.id,
        entity_id,
        offset=30,
        limit=10,
    )
    assert total_origins == repeated_total == final_total == 33
    assert first_origin_page == repeated_first_page == alias.origins[:10]
    assert first_origin_page + second_origin_page + third_origin_page == alias.origins[:30]
    assert final_origin_page[:2] == alias.origins[30:32]
    assert len(final_origin_page) == 3
    assert all(not hasattr(origin, "content_text") for origin in final_origin_page)
    with pytest.raises(LookupError):
        repository.list_entity_origins(
            manager.manifest.vault_id,
            other_profile.id,
            entity_id,
            offset=0,
            limit=12,
        )
    assert {origin.source_id for origin in alias.origins[:2]} == {
        first.source_id,
        second.source_id,
    }
    by_source = {origin.source_id: origin for origin in alias.origins[:2]}
    first_origin = by_source[first.source_id]
    second_origin = by_source[second.source_id]
    assert (
        first_origin.source_display_name,
        first_origin.source_sha256,
        first_origin.segment_id,
        first_origin.segment_index,
        first_origin.segment_locator,
        first_origin.source_span_start,
        first_origin.source_span_end,
        first_origin.extraction_run_id,
        first_origin.extractor_kind,
        first_origin.extractor_name,
        first_origin.extractor_version,
        first_origin.origin_kind,
        first_origin.confidence_micros,
        first_origin.explanation,
    ) == (
        first_source.display_name,
        first_source.sha256,
        first_segment_id,
        0,
        _segments()[0].locator_json,
        17,
        28,
        first.extraction_run_id,
        "DETERMINISTIC",
        "synthetic-compiler",
        "1.0.0",
        "DETERMINISTIC",
        900_000,
        "Synthetic deterministic alias token",
    )
    assert second_origin.segment_id == dict(second.segment_ids)[0]
    assert second_origin.extraction_run_id == second.extraction_run_id
    assert isolated.source_id not in {origin.source_id for origin in alias.origins}

    first_scoped = repository.list_entities(
        manager.manifest.vault_id,
        profile.id,
        source_id=first.source_id,
    )
    scoped_alias = next(item for item in first_scoped if item.id == entity_id)
    assert len(scoped_alias.origins) == 32
    assert scoped_alias.origins_truncated is False
    assert {origin.source_id for origin in scoped_alias.origins} == {first.source_id}

    isolated_alias = next(
        item
        for item in repository.list_entities(manager.manifest.vault_id, other_profile.id)
        if item.id == dict(isolated.entity_ids)["alias"]
    )
    assert isolated_alias.origins[0].source_display_name == "Restricted source label"
    assert "synthetic-provenance-secret" not in repr(isolated_alias)
    assert not hasattr(first_origin, "content_text")
    assert "Synthetic alias: river-otter" not in repr(alias)

    repository.close()
    manager.lock()


def test_expired_temporary_content_is_scrubbed_without_breaking_provenance(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic retention vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic retention profile",
        purpose="Synthetic expiry test",
    )
    result = _persist(manager, repository, profile.id)

    assert (
        repository.purge_expired_temporary_content(
            vault_id=manager.manifest.vault_id,
            timestamp_us=8_999,
        )
        == 0
    )
    assert (
        repository.purge_expired_temporary_content(
            vault_id=manager.manifest.vault_id,
            timestamp_us=9_000,
        )
        == 1
    )
    assert (
        repository.purge_expired_temporary_content(
            vault_id=manager.manifest.vault_id,
            timestamp_us=9_001,
        )
        == 0
    )

    with manager.engine.connect() as connection:
        source = connection.execute(
            select(
                intake_sources.c.retention_state,
                intake_sources.c.retention_expires_at_us,
                intake_sources.c.revision,
            ).where(intake_sources.c.id == result.source_id)
        ).one()
        segments = (
            connection.execute(
                select(
                    intake_segments.c.content_text,
                    intake_segments.c.content_hmac,
                    intake_segments.c.locator_json,
                ).where(intake_segments.c.intake_source_id == result.source_id)
            )
            .mappings()
            .all()
        )
        purge_event_count = connection.execute(
            select(func.count())
            .select_from(audit_events)
            .where(audit_events.c.event_type == "INTAKE_SOURCE_CONTENT_PURGED")
        ).scalar_one()

    assert source == ("PURGE_PENDING", None, 2)
    assert segments
    assert all(segment["content_text"] is None for segment in segments)
    assert all(
        segment["content_hmac"]
        == hmac.new(
            FINGERPRINT_KEY,
            str(segment["locator_json"]).encode(),
            hashlib.sha256,
        ).hexdigest()
        for segment in segments
    )
    assert purge_event_count == 1
    assert len(repository.list_entities(manager.manifest.vault_id, profile.id)) == 2
    assert len(repository.graph_snapshot(manager.manifest.vault_id, profile.id).nodes) == 2
    repository.close()
    manager.lock()


def test_profile_scope_is_structural_for_segments_entities_decisions_and_graph(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic scope vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    first = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic alpha",
        purpose="Synthetic scope A",
    )
    second = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic beta",
        purpose="Synthetic scope B",
    )
    first_result = _persist(manager, repository, first.id)
    second_result = _persist(manager, repository, second.id)

    assert len(repository.list_entities(manager.manifest.vault_id, first.id)) == 2
    assert len(repository.list_entities(manager.manifest.vault_id, second.id)) == 2
    assert dict(first_result.entity_ids)["alias"] != dict(second_result.entity_ids)["alias"]
    assert {
        node.id for node in repository.graph_snapshot(manager.manifest.vault_id, first.id).nodes
    } == set(dict(first_result.graph_node_ids).values())

    with pytest.raises(LookupError):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=second.id,
            entity_id=dict(first_result.entity_ids)["alias"],
            expected_revision=1,
            decision_type="CONFIRM",
            review_state="CONFIRMED",
        )

    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            insert(intake_segments).values(
                id=str(uuid7()),
                vault_id=manager.manifest.vault_id,
                profile_id=second.id,
                intake_source_id=first_result.source_id,
                ordinal=99,
                segment_kind="TEXT",
                content_text="Synthetic invalid cross-profile segment",
                content_hmac="a" * 64,
                locator_json="{}",
                language="en",
                created_at_us=1,
                deleted_at_us=None,
            )
        )

    with manager.engine.connect() as connection:
        first_edge_origin_id = connection.execute(
            select(graph_edge_origins.c.id).where(
                graph_edge_origins.c.graph_edge_id == first_result.graph_edge_ids[0]
            )
        ).scalar_one()
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            update(graph_edge_origins)
            .where(graph_edge_origins.c.id == first_edge_origin_id)
            .values(intake_source_id=second_result.source_id)
        )

    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            insert(graph_edges).values(
                id=str(uuid7()),
                vault_id=manager.manifest.vault_id,
                profile_id=first.id,
                from_node_id=dict(first_result.graph_node_ids)["alias"],
                to_node_id=dict(second_result.graph_node_ids)["project"],
                edge_type="LINKS_TO",
                confidence_micros=500_000,
                visibility="UNKNOWN",
                valid_from_us=None,
                valid_to_us=None,
                observed_at_us=1,
                origin_type="DETERMINISTIC",
                explanation="Synthetic invalid cross-profile edge",
                review_state="UNREVIEWED",
                current_decision_id=None,
                created_at_us=1,
                updated_at_us=1,
                revision=1,
                deleted_at_us=None,
            )
        )
    repository.close()
    manager.lock()


def test_sequential_overlapping_sources_reuse_identity_graph_and_preserve_reviews(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic overlap vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic overlap profile",
        purpose="Synthetic sequential provenance test",
    )
    first = _persist(manager, repository, profile.id)
    entity_id = dict(first.entity_ids)["alias"]
    edge_id = first.graph_edge_ids[0]
    with manager.engine.connect() as connection:
        variant_id = str(
            connection.execute(
                select(entity_variants.c.id).where(entity_variants.c.entity_id == entity_id)
            ).scalar_one()
        )

    with pytest.raises(ValueError, match="negatively reviewed"):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            entity_id=entity_id,
            expected_revision=1,
            decision_type="REJECT",
            review_state="FALSE_POSITIVE",
        )
    with pytest.raises(ValueError, match="highly sensitive"):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            entity_id=entity_id,
            expected_revision=1,
            decision_type="CONFIRM",
            review_state="CONFIRMED",
            sensitivity="HIGHLY_SENSITIVE",
            search_policy="SEARCH_ALLOWED",
            transmission_policy="PROVIDER_ALLOWLIST",
        )
    with manager.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(entity_decisions)).scalar_one() == 0
        )
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            update(entities).where(entities.c.id == entity_id).values(review_state="FALSE_POSITIVE")
        )
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            update(entities)
            .where(entities.c.id == entity_id)
            .values(
                sensitivity="HIGHLY_SENSITIVE",
                search_policy="SEARCH_ALLOWED",
                transmission_policy="PROVIDER_ALLOWLIST",
            )
        )

    with pytest.raises(ValueError, match="classification"):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            entity_id=entity_id,
            expected_revision=1,
            decision_type="CLASSIFY",
            review_state="CONFIRMED",
        )

    repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=entity_id,
        expected_revision=1,
        decision_type="CONFIRM",
        review_state="CONFIRMED",
    )
    repository.record_variant_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        variant_id=variant_id,
        expected_revision=1,
        decision_type="APPROVE",
        approved_for_search=True,
        rank=7,
    )
    repository.record_graph_edge_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        edge_id=edge_id,
        expected_revision=1,
        decision_type="CONFIRM",
        review_state="CONFIRMED",
    )

    second = _persist(manager, repository, profile.id)

    assert dict(second.entity_ids) == dict(first.entity_ids)
    assert dict(second.graph_node_ids) == dict(first.graph_node_ids)
    assert second.graph_edge_ids == first.graph_edge_ids
    assert second.duplicate_entity_count == 2
    assert second.duplicate_variant_count == 1
    assert second.duplicate_edge_count == 1
    assert len(repository.list_entities(manager.manifest.vault_id, profile.id)) == 2
    assert len(repository.graph_snapshot(manager.manifest.vault_id, profile.id).nodes) == 2
    assert len(repository.graph_snapshot(manager.manifest.vault_id, profile.id).edges) == 1

    with manager.engine.connect() as connection:
        origins = (
            connection.execute(
                select(entity_origins.c.intake_segment_id).where(
                    entity_origins.c.entity_id == entity_id
                )
            )
            .scalars()
            .all()
        )
        stored_entity = connection.execute(
            select(
                entities.c.review_state,
                entities.c.search_policy,
                entities.c.revision,
            ).where(entities.c.id == entity_id)
        ).one()
        stored_variant = connection.execute(
            select(
                entity_variants.c.approved_for_search,
                entity_variants.c.rank,
                entity_variants.c.revision,
            ).where(entity_variants.c.id == variant_id)
        ).one()
        stored_edge = connection.execute(
            select(graph_edges.c.review_state, graph_edges.c.revision).where(
                graph_edges.c.id == edge_id
            )
        ).one()
    assert len(origins) == 2
    assert set(origins) == {
        dict(first.segment_ids)[0],
        dict(second.segment_ids)[0],
    }
    assert stored_entity == ("CONFIRMED", "APPROVAL_REQUIRED", 2)
    assert stored_variant == (1, 7, 2)
    assert stored_edge == ("CONFIRMED", 2)
    third = _persist(
        manager,
        repository,
        profile.id,
        edge_disposition="CONTRADICTS",
    )
    assert third.graph_edge_ids == first.graph_edge_ids
    graph = repository.graph_snapshot(manager.manifest.vault_id, profile.id)
    assert graph.edges[0].support_count == 2
    assert graph.edges[0].contradiction_count == 1
    assert graph.edges[0].evidence_truncated is True
    assert {item.disposition for item in graph.edges[0].evidence} == {
        "SUPPORTS",
        "CONTRADICTS",
    }
    with manager.engine.connect() as connection:
        origin_dispositions = connection.execute(
            select(graph_edge_origins.c.disposition)
            .where(graph_edge_origins.c.graph_edge_id == edge_id)
            .order_by(graph_edge_origins.c.created_at_us, graph_edge_origins.c.id)
        ).scalars()
        assert sorted(origin_dispositions) == ["CONTRADICTS", "SUPPORTS", "SUPPORTS"]
    repository.close()
    manager.lock()


def test_exact_email_canonical_values_do_not_casefold_merge(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic exact-value vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic exact-value profile",
        purpose="Synthetic canonical equality test",
    )
    template = _entities()[0]
    first = replace(
        template,
        local_key="email-upper",
        entity_type="EMAIL",
        canonical_value="Synthetic.User@example.invalid",
        display_mask="S•••••••••••@example.invalid",
        variants=(),
        graph_node_type="EMAIL",
    )
    second = replace(
        template,
        local_key="email-lower",
        entity_type="EMAIL",
        canonical_value="synthetic.user@example.invalid",
        display_mask="s•••••••••••@example.invalid",
        variants=(),
        graph_node_type="EMAIL",
    )
    result = repository.persist_compilation(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        source=_source(),
        extraction=ExtractionDraft(
            job_id=_new_job(manager),
            engine_kind="DETERMINISTIC",
            engine_name="synthetic-compiler",
            engine_version="1",
            configuration_hash="a" * 64,
        ),
        segments=_segments(),
        entities_input=(first, second),
    )

    assert len(set(dict(result.entity_ids).values())) == 2
    assert result.duplicate_entity_count == 0
    assert len(repository.list_entities(manager.manifest.vault_id, profile.id)) == 2
    repository.close()
    manager.lock()


def test_restricted_identity_paths_and_invalid_provenance_are_rejected_by_database(
    tmp_path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic privacy vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic privacy profile",
        purpose="Synthetic structural privacy test",
    )
    result = _persist(manager, repository, profile.id)
    entity_id = dict(result.entity_ids)["alias"]

    restricted = list(_entities())
    restricted[0] = replace(restricted[0], sensitivity="RESTRICTED")
    with pytest.raises(ValueError, match="sensitivity"):
        repository.persist_compilation(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            source=_source(),
            extraction=ExtractionDraft(
                job_id=_new_job(manager),
                engine_kind="DETERMINISTIC",
                engine_name="synthetic-compiler",
                engine_version="1",
                configuration_hash="a" * 64,
            ),
            segments=_segments(),
            entities_input=restricted,
        )

    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            insert(entity_variants).values(
                id=str(uuid7()),
                vault_id=manager.manifest.vault_id,
                profile_id=profile.id,
                entity_id=entity_id,
                sensitivity="RESTRICTED",
                variant_type="EXACT",
                value="synthetic restricted marker",
                value_hmac="b" * 64,
                generator="synthetic",
                generator_version="1",
                rank=1,
                estimated_risk="HIGH",
                approved_for_search=0,
                current_decision_id=None,
                created_at_us=1,
                updated_at_us=1,
                revision=1,
                deleted_at_us=None,
            )
        )

    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            insert(graph_nodes).values(
                id=str(uuid7()),
                vault_id=manager.manifest.vault_id,
                profile_id=profile.id,
                node_type="USERNAME",
                display_label="synthetic restricted marker",
                sensitivity="RESTRICTED",
                visibility="PRIVATE_ONLY",
                entity_id=None,
                position_json=None,
                created_at_us=1,
                updated_at_us=1,
                revision=1,
                deleted_at_us=None,
            )
        )

    origin = None
    with manager.engine.connect() as connection:
        origin = (
            connection.execute(
                select(entity_origins).where(entity_origins.c.entity_id == entity_id)
            )
            .mappings()
            .one()
        )
    invalid_origin = dict(origin)
    invalid_origin["id"] = str(uuid7())
    invalid_origin["raw_result_id"] = str(uuid7())
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(insert(entity_origins).values(**invalid_origin))
    invalid_origin["id"] = str(uuid7())
    invalid_origin["raw_result_id"] = None
    invalid_origin["source_span_end"] = invalid_origin["source_span_start"]
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(insert(entity_origins).values(**invalid_origin))

    assert {"raw_value", "content_text", "payload", "plaintext"}.isdisjoint(
        quarantine_items.c.keys()
    )
    repository.close()
    manager.lock()


def test_entity_decisions_use_cas_and_append_a_redacted_revision_chain(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic decision vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic decision profile",
        purpose="Synthetic review test",
    )
    result = _persist(manager, repository, profile.id)
    entity_id = dict(result.entity_ids)["alias"]
    edge_id = result.graph_edge_ids[0]
    with manager.engine.connect() as connection:
        variant_id = str(
            connection.execute(
                select(entity_variants.c.id).where(entity_variants.c.entity_id == entity_id)
            ).scalar_one()
        )

    confirmed = repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=entity_id,
        expected_revision=1,
        decision_type="CONFIRM",
        review_state="CONFIRMED",
        reason_code="SYNTHETIC_REVIEW",
    )
    assert confirmed.revision == 2
    assert confirmed.review_state == "CONFIRMED"
    with pytest.raises(RevisionConflict):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            entity_id=entity_id,
            expected_revision=1,
            decision_type="EXCLUDE",
            review_state="EXCLUDED",
        )
    excluded = repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=entity_id,
        expected_revision=2,
        decision_type="EXCLUDE",
        review_state="EXCLUDED",
        search_policy="SEARCH_DENIED",
        transmission_policy="TRANSMISSION_DENIED",
    )
    assert excluded.revision == 3
    with pytest.raises(ValueError, match="must alter"):
        repository.record_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            entity_id=entity_id,
            expected_revision=3,
            decision_type="POLICY_CHANGE",
            review_state="EXCLUDED",
        )

    approved = repository.record_variant_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        variant_id=variant_id,
        expected_revision=1,
        decision_type="APPROVE",
        approved_for_search=True,
        rank=2,
    )
    assert approved.revision == 2
    assert approved.approved_for_search is True
    with pytest.raises(RevisionConflict):
        repository.record_variant_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            variant_id=variant_id,
            expected_revision=1,
            decision_type="REVOKE",
            approved_for_search=False,
            rank=2,
        )

    confirmed_edge = repository.record_graph_edge_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        edge_id=edge_id,
        expected_revision=1,
        decision_type="CONFIRM",
        review_state="CONFIRMED",
    )
    assert confirmed_edge.revision == 2
    assert confirmed_edge.review_state == "CONFIRMED"
    with pytest.raises(RevisionConflict):
        repository.record_graph_edge_decision(
            vault_id=manager.manifest.vault_id,
            profile_id=profile.id,
            edge_id=edge_id,
            expected_revision=1,
            decision_type="REJECT",
            review_state="REJECTED",
        )

    with manager.engine.connect() as connection:
        decisions = (
            connection.execute(
                select(entity_decisions)
                .where(entity_decisions.c.entity_id == entity_id)
                .order_by(entity_decisions.c.after_revision)
            )
            .mappings()
            .all()
        )
        events = (
            connection.execute(
                select(event_outbox.c.payload_json).where(
                    event_outbox.c.event_type == "ENTITY_REVIEW_DECIDED"
                )
            )
            .scalars()
            .all()
        )
        variant_decision_count = connection.execute(
            select(func.count()).select_from(entity_variant_decisions)
        ).scalar_one()
        edge_decision_count = connection.execute(
            select(func.count()).select_from(graph_edge_decisions)
        ).scalar_one()
    assert [row["after_revision"] for row in decisions] == [2, 3]
    assert decisions[1]["supersedes_decision_id"] == decisions[0]["id"]
    assert (
        decisions[0]["before_sensitivity"],
        decisions[0]["after_sensitivity"],
        decisions[0]["before_temporal_state"],
        decisions[0]["after_temporal_state"],
        decisions[0]["before_search_policy"],
        decisions[0]["after_search_policy"],
        decisions[0]["before_transmission_policy"],
        decisions[0]["after_transmission_policy"],
    ) == (
        "SENSITIVE",
        "SENSITIVE",
        "CURRENT",
        "CURRENT",
        "APPROVAL_REQUIRED",
        "APPROVAL_REQUIRED",
        "LOCAL_ONLY",
        "LOCAL_ONLY",
    )
    assert all("river-otter" not in payload for payload in events)
    assert variant_decision_count == 1
    assert edge_decision_count == 1
    repository.close()
    manager.lock()


def test_entity_sensitivity_decision_updates_graph_and_variants_atomically(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic classification vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic classification profile",
        purpose="Synthetic sensitivity propagation test",
    )
    result = _persist(manager, repository, profile.id)
    entity_id = dict(result.entity_ids)["alias"]

    updated = repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=entity_id,
        expected_revision=1,
        decision_type="POLICY_CHANGE",
        review_state="UNREVIEWED",
        sensitivity="HIGHLY_SENSITIVE",
        temporal_state="HISTORICAL",
        search_policy="STORE_ONLY",
        transmission_policy="TRANSMISSION_DENIED",
    )

    with manager.engine.connect() as connection:
        variant_rows = connection.execute(
            select(entity_variants.c.sensitivity, entity_variants.c.revision).where(
                entity_variants.c.entity_id == entity_id
            )
        ).all()
        node = connection.execute(
            select(graph_nodes.c.sensitivity, graph_nodes.c.revision).where(
                graph_nodes.c.entity_id == entity_id
            )
        ).one()
        decision = (
            connection.execute(
                select(entity_decisions).where(entity_decisions.c.entity_id == entity_id)
            )
            .mappings()
            .one()
        )
    assert updated.sensitivity == "HIGHLY_SENSITIVE"
    assert updated.temporal_state == "HISTORICAL"
    assert updated.search_policy == "STORE_ONLY"
    assert updated.transmission_policy == "TRANSMISSION_DENIED"
    assert variant_rows == [("HIGHLY_SENSITIVE", 2)]
    assert node == ("HIGHLY_SENSITIVE", 2)
    assert (
        decision["before_sensitivity"],
        decision["after_sensitivity"],
        decision["before_temporal_state"],
        decision["after_temporal_state"],
        decision["before_search_policy"],
        decision["after_search_policy"],
        decision["before_transmission_policy"],
        decision["after_transmission_policy"],
    ) == (
        "SENSITIVE",
        "HIGHLY_SENSITIVE",
        "CURRENT",
        "HISTORICAL",
        "APPROVAL_REQUIRED",
        "STORE_ONLY",
        "LOCAL_ONLY",
        "TRANSMISSION_DENIED",
    )
    repository.close()
    manager.lock()


def test_rejected_and_excluded_entities_and_incident_edges_are_hidden_from_graph(
    tmp_path,
) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic graph suppression vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic graph suppression profile",
        purpose="Synthetic negative-review graph test",
    )
    result = _persist(manager, repository, profile.id)
    alias_id = dict(result.entity_ids)["alias"]
    project_id = dict(result.entity_ids)["project"]

    repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=alias_id,
        expected_revision=1,
        decision_type="REJECT",
        review_state="FALSE_POSITIVE",
        search_policy="SEARCH_DENIED",
        transmission_policy="TRANSMISSION_DENIED",
    )
    rejected_snapshot = repository.graph_snapshot(manager.manifest.vault_id, profile.id)
    assert {node.entity_id for node in rejected_snapshot.nodes} == {project_id}
    assert rejected_snapshot.edges == ()

    repository.record_decision(
        vault_id=manager.manifest.vault_id,
        profile_id=profile.id,
        entity_id=project_id,
        expected_revision=1,
        decision_type="EXCLUDE",
        review_state="EXCLUDED",
        search_policy="SEARCH_DENIED",
        transmission_policy="TRANSMISSION_DENIED",
    )
    excluded_snapshot = repository.graph_snapshot(manager.manifest.vault_id, profile.id)
    assert excluded_snapshot.nodes == ()
    assert excluded_snapshot.edges == ()

    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(graph_nodes)).scalar_one() == 2
        assert connection.execute(select(func.count()).select_from(graph_edges)).scalar_one() == 1
        assert (
            connection.execute(select(func.count()).select_from(entity_decisions)).scalar_one() == 2
        )
    repository.close()
    manager.lock()


def test_compilation_rolls_back_if_atomic_event_append_fails(tmp_path, monkeypatch) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic rollback vault")
    repository = IntakeIdentityRepository(manager.engine, fingerprint_key=FINGERPRINT_KEY)
    profile = repository.create_profile(
        vault_id=manager.manifest.vault_id,
        display_label="Synthetic rollback profile",
        purpose="Synthetic atomicity test",
    )

    def fail_event(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(
        "ariadne_core.infrastructure.db.intake_identity_repository._append_event",
        fail_event,
    )
    with pytest.raises(RuntimeError, match="synthetic event failure"):
        _persist(manager, repository, profile.id)

    with manager.engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(intake_sources)).scalar_one() == 0
        )
        assert connection.execute(select(func.count()).select_from(entities)).scalar_one() == 0
        assert connection.execute(select(func.count()).select_from(graph_edges)).scalar_one() == 0
    repository.close()
    manager.lock()


def test_dependency_schema_upgrades_forward_to_intake_identity_graph_head(tmp_path) -> None:
    key = bytearray(b"m" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002_job_dependencies")
    upgrade_to_head(engine)

    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).all()
        }
    assert revision == "0011_profile_purge"
    assert {
        "intake_sources",
        "intake_segments",
        "quarantine_items",
        "extraction_runs",
        "entities",
        "entity_variants",
        "entity_origins",
        "entity_decisions",
        "graph_nodes",
        "graph_edges",
    } <= table_names
    engine.dispose()
    key[:] = b"\x00" * len(key)
