from __future__ import annotations

import os
import sqlite3
import sys

import pytest
from alembic import command
from packaging.version import Version
from sqlalchemy.exc import IntegrityError

from ariadne_core.api.intake_schemas import PasteIntakeRequest, ProfileCreateRequest
from ariadne_core.application.phase3 import Phase3Coordinator
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import (
    MINIMUM_SQLITE,
    CipherUnavailable,
    SqlcipherEngineFactory,
)
from ariadne_core.infrastructure.db.migrate import migration_config, upgrade_to_head
from ariadne_core.security.key_custody import MemoryKeyCustodian

SYNTHETIC_CANARY = "SYNTHETIC_CANARY_ALPHA"


def test_vault_is_sqlcipher_encrypted_and_fails_closed_with_wrong_key(tmp_path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manifest = manager.create(display_name=SYNTHETIC_CANARY)

    database = tmp_path / "vault" / "vault.db"
    with custodian.borrow(manifest.database_key_ref) as database_key:
        runtime = SqlcipherEngineFactory(database, database_key).probe()
    assert Version(runtime.sqlite_version) >= MINIMUM_SQLITE
    assert runtime.cipher_version
    assert runtime.foreign_keys is True
    assert runtime.journal_mode == "delete"
    assert runtime.temp_store == 2
    assert runtime.fts5 is True
    assert runtime.json is True

    raw = database.read_bytes()
    assert not raw.startswith(b"SQLite format 3")
    assert SYNTHETIC_CANARY.encode() not in raw
    assert os.stat(database).st_mode & 0o777 == 0o600
    assert os.stat(database.parent).st_mode & 0o777 == 0o700
    assert not database.with_name("vault.db-wal").exists()
    assert not database.with_name("vault.db-shm").exists()

    with pytest.raises(sqlite3.DatabaseError):
        plain = sqlite3.connect(database)
        try:
            plain.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            plain.close()

    wrong_key = bytearray(b"w" * 32)
    before_wrong_key = database.read_bytes()
    with pytest.raises(CipherUnavailable):
        SqlcipherEngineFactory(database, wrong_key).probe()
    assert database.read_bytes() == before_wrong_key

    manager.lock()
    assert manager.is_unlocked is False
    assert manifest.database_key_ref in custodian.values


def test_migration_creates_phase3_intake_identity_schema(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic migration vault")
    with manager.engine.connect() as connection:
        table_names = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).all()
        }
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        entity_decision_columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(entity_decisions)").all()
        }
    assert revision == "0008_phase6_audit_remediation"
    assert {
        "vaults",
        "vault_crypto",
        "settings",
        "idempotency_records",
        "jobs",
        "job_dependencies",
        "job_attempts",
        "audit_events",
        "event_stream_sessions",
        "event_outbox",
        "backup_records",
        "intake_sources",
        "intake_segments",
        "quarantine_items",
        "extraction_runs",
        "entities",
        "entity_variants",
        "entity_variant_decisions",
        "entity_origins",
        "entity_decisions",
        "graph_nodes",
        "graph_edges",
        "graph_edge_origins",
        "graph_edge_decisions",
        "phase5_findings",
        "phase5_evidence_originals",
        "phase5_finding_evidence",
        "phase5_evidence_derivatives",
        "phase5_attribution_assessments",
        "phase5_attribution_signals",
        "phase5_attribution_signal_evidence",
        "phase5_attribution_missing_evidence",
        "phase5_attribution_decisions",
        "phase6_audit_snapshots",
        "phase6_audit_snapshot_findings",
        "phase6_audit_snapshot_coverage",
        "phase6_remediation_revisions",
        "phase6_remediation_findings",
        "phase6_remediation_evidence",
        "phase6_remediation_provider_responses",
        "phase6_remediation_provider_response_evidence",
        "phase6_remediation_history",
        "phase6_remediation_history_evidence",
    } <= table_names
    assert {
        "before_sensitivity",
        "after_sensitivity",
        "before_temporal_state",
        "after_temporal_state",
        "before_search_policy",
        "after_search_policy",
        "before_transmission_policy",
        "after_transmission_policy",
    } <= entity_decision_columns
    manager.lock()


def test_0005_backfills_only_verifiable_existing_graph_edge_origins(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic edge migration vault")
    coordinator = Phase3Coordinator(manager)
    profile = coordinator.create_profile(
        ProfileCreateRequest(
            idempotency_key="synthetic-profile-backfill-0001",
            display_label="Synthetic edge migration profile",
            purpose="Synthetic edge provenance backfill",
        )
    )
    coordinator.ingest_paste(
        PasteIntakeRequest(
            idempotency_key="synthetic-intake-backfill-0001",
            profile_id=profile.profile_id,
            display_name="Synthetic edge migration source",
            content=(
                "Morgan Vale uses the historical handle @night_orbit.\n"
                "Morgan Vale worked at Northbridge Systems."
            ),
            consent_confirmed=True,
            retain_raw_source=False,
            semantic_enrichment_enabled=True,
        )
    )
    with manager.engine.begin() as connection:
        edge_count = connection.exec_driver_sql("SELECT count(*) FROM graph_edges").scalar_one()
        assert edge_count > 0
        for drop_phase6_table in (
            "DROP TABLE phase6_remediation_history_evidence",
            "DROP TABLE phase6_remediation_history",
            "DROP TABLE phase6_remediation_provider_response_evidence",
            "DROP TABLE phase6_remediation_provider_responses",
            "DROP TABLE phase6_remediation_evidence",
            "DROP TABLE phase6_remediation_findings",
            "DROP TABLE phase6_remediation_revisions",
            "DROP TABLE phase6_audit_snapshot_findings",
            "DROP TABLE phase6_audit_snapshot_coverage",
            "DROP TABLE phase6_audit_snapshots",
        ):
            connection.exec_driver_sql(drop_phase6_table)
        for drop_phase5_table in (
            "DROP TABLE phase5_attribution_decisions",
            "DROP TABLE phase5_attribution_missing_evidence",
            "DROP TABLE phase5_attribution_signal_evidence",
            "DROP TABLE phase5_attribution_signals",
            "DROP TABLE phase5_attribution_assessments",
            "DROP TABLE phase5_evidence_derivatives",
            "DROP TABLE phase5_finding_evidence",
            "DROP TABLE phase5_evidence_originals",
            "DROP TABLE phase5_findings",
        ):
            connection.exec_driver_sql(drop_phase5_table)
        for drop_phase4_table in (
            "DROP TABLE phase4_transmission_ledger",
            "DROP TABLE phase4_one_time_approvals",
            "DROP TABLE phase4_query_checks",
            "DROP TABLE phase4_provider_budget_usage",
            "DROP TABLE phase4_query_runs",
            "DROP TABLE phase4_providers",
        ):
            connection.exec_driver_sql(drop_phase4_table)
        connection.exec_driver_sql("DROP TABLE graph_edge_origins")
        connection.exec_driver_sql(
            "UPDATE alembic_version SET version_num = '0004_decision_policy'"
        )

    upgrade_to_head(manager.engine)
    with manager.engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        origin_count = connection.exec_driver_sql(
            "SELECT count(*) FROM graph_edge_origins"
        ).scalar_one()
    assert revision == "0008_phase6_audit_remediation"
    assert origin_count == edge_count
    manager.lock()


def test_unlock_never_creates_a_missing_database(tmp_path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manager.create(display_name="Synthetic missing database vault")
    manager.lock()
    database = tmp_path / "vault" / "vault.db"
    database.unlink()

    with pytest.raises(CipherUnavailable, match="database is unavailable"):
        manager.unlock()

    assert manager.is_unlocked is False
    assert not database.exists()


def test_existing_phase2_foundation_upgrades_forward_to_intake_identity_head(tmp_path) -> None:
    key = bytearray(b"m" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001_phase2_foundation")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "0001_phase2_foundation"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='job_dependencies'"
            ).scalar_one()
            == 0
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='intake_sources'"
            ).scalar_one()
            == 0
        )

    upgrade_to_head(engine)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "0008_phase6_audit_remediation"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='job_dependencies'"
            ).scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='intake_sources'"
            ).scalar_one()
            == 1
        )
    engine.dispose()
    key[:] = b"\x00" * len(key)


def test_existing_query_policy_schema_upgrades_forward_to_current_head(tmp_path) -> None:
    key = bytearray(b"m" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy-phase4" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0006_query_policy_core")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "0006_query_policy_core"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'phase5_%'"
            ).scalar_one()
            == 0
        )

    upgrade_to_head(engine)
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        phase5_tables = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'phase5_%'"
            ).all()
        }
        phase6_tables = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'phase6_%'"
            ).all()
        }
    assert revision == "0008_phase6_audit_remediation"
    assert phase5_tables == {
        "phase5_findings",
        "phase5_evidence_originals",
        "phase5_finding_evidence",
        "phase5_evidence_derivatives",
        "phase5_attribution_assessments",
        "phase5_attribution_signals",
        "phase5_attribution_signal_evidence",
        "phase5_attribution_missing_evidence",
        "phase5_attribution_decisions",
    }
    assert phase6_tables == {
        "phase6_audit_snapshots",
        "phase6_audit_snapshot_findings",
        "phase6_audit_snapshot_coverage",
        "phase6_remediation_revisions",
        "phase6_remediation_findings",
        "phase6_remediation_evidence",
        "phase6_remediation_provider_responses",
        "phase6_remediation_provider_response_evidence",
        "phase6_remediation_history",
        "phase6_remediation_history_evidence",
    }
    engine.dispose()
    key[:] = b"\x00" * len(key)


def test_frozen_migration_assets_resolve_only_from_private_bundle_root(
    tmp_path, monkeypatch
) -> None:
    asset_root = tmp_path / "bundle" / "ariadne_core_migrations"
    (asset_root / "migrations").mkdir(parents=True)
    (asset_root / "alembic.ini").write_text("[alembic]\n")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    config = migration_config()
    assert config.config_file_name == str(asset_root / "alembic.ini")
    assert config.get_main_option("script_location") == str(asset_root / "migrations")


def test_existing_0003_decision_table_upgrades_without_double_adding_columns(tmp_path) -> None:
    key = bytearray(b"m" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy-0003" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003_intake_identity_graph")
        connection.exec_driver_sql("DROP TABLE entity_decisions")
        connection.exec_driver_sql(
            """
            CREATE TABLE entity_decisions (
                id TEXT PRIMARY KEY,
                vault_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                before_review_state TEXT NOT NULL,
                after_review_state TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_version TEXT,
                reason_code TEXT,
                before_revision INTEGER NOT NULL,
                after_revision INTEGER NOT NULL,
                supersedes_decision_id TEXT,
                decided_at_us INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO entity_decisions (
                id, vault_id, profile_id, entity_id, decision_type,
                before_review_state, after_review_state, actor_type,
                before_revision, after_revision, decided_at_us
            ) VALUES (
                'legacy-decision', 'legacy-vault', 'legacy-profile', 'legacy-entity',
                'CONFIRM', 'UNREVIEWED', 'CONFIRMED', 'LOCAL_USER', 1, 2, 1000
            )
            """
        )

    upgrade_to_head(engine)
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql("PRAGMA table_info(entity_decisions)").all()
        }
        triggers = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).all()
        }
        legacy_snapshots = connection.exec_driver_sql(
            """
            SELECT before_sensitivity, after_sensitivity,
                   before_temporal_state, after_temporal_state,
                   before_search_policy, after_search_policy,
                   before_transmission_policy, after_transmission_policy
            FROM entity_decisions WHERE id = 'legacy-decision'
            """
        ).one()
    assert revision == "0008_phase6_audit_remediation"
    assert {
        "before_sensitivity",
        "after_sensitivity",
        "before_temporal_state",
        "after_temporal_state",
        "before_search_policy",
        "after_search_policy",
        "before_transmission_policy",
        "after_transmission_policy",
    } <= columns
    assert {
        "trg_entities_policy_insert",
        "trg_entities_policy_update",
        "trg_entity_decisions_policy_insert",
        "trg_entity_decisions_policy_update",
    } <= triggers
    assert legacy_snapshots == (None, None, None, None, None, None, None, None)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO entity_decisions (
                id, vault_id, profile_id, entity_id, decision_type,
                before_review_state, after_review_state,
                before_sensitivity, after_sensitivity,
                before_temporal_state, after_temporal_state,
                before_search_policy, after_search_policy,
                before_transmission_policy, after_transmission_policy,
                actor_type, before_revision, after_revision, decided_at_us
            ) VALUES (
                'new-valid-decision', 'legacy-vault', 'legacy-profile', 'legacy-entity',
                'CONFIRM', 'UNREVIEWED', 'CONFIRMED',
                'SENSITIVE', 'SENSITIVE', 'UNKNOWN', 'UNKNOWN',
                'STORE_ONLY', 'STORE_ONLY', 'LOCAL_ONLY', 'LOCAL_ONLY',
                'LOCAL_USER', 2, 3, 2000
            )
            """
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO entity_decisions (
                id, vault_id, profile_id, entity_id, decision_type,
                before_review_state, after_review_state, actor_type,
                before_revision, after_revision, decided_at_us
            ) VALUES (
                'new-incomplete-decision', 'legacy-vault', 'legacy-profile', 'legacy-entity',
                'CONFIRM', 'UNREVIEWED', 'CONFIRMED', 'LOCAL_USER', 3, 4, 3000
            )
            """
        )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM entity_decisions").scalar_one() == 2
    engine.dispose()
    key[:] = b"\x00" * len(key)
