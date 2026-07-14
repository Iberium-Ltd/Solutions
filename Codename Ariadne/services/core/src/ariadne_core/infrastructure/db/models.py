"""Phase 2 foundation schema expressed as SQLAlchemy Core metadata."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

vaults = Table(
    "vaults",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("state", String(24), nullable=False),
    Column("format_version", Integer, nullable=False),
    Column("auto_lock_seconds", Integer, nullable=False),
    Column("settings_revision", Integer, nullable=False, default=1),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False, default=1),
    CheckConstraint("state IN ('LOCKED','UNLOCKED','MIGRATING','RECOVERY_REQUIRED')"),
    CheckConstraint("auto_lock_seconds >= 30 AND auto_lock_seconds <= 86400"),
)

vault_crypto = Table(
    "vault_crypto",
    metadata,
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), primary_key=True),
    Column("key_version", Integer, nullable=False),
    Column("keychain_key_ref", Text, nullable=False, unique=True),
    Column("wrapped_dek", LargeBinary, nullable=True),
    Column("wrap_algorithm", String(48), nullable=False),
    Column("sqlcipher_profile", String(48), nullable=False),
    Column("evidence_cipher", String(48), nullable=False),
    Column("rotated_at_us", Integer, nullable=True),
)

profiles = Table(
    "profiles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("display_label", Text, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("status", String(24), nullable=False),
    Column("correlation_boundary", String(32), nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    UniqueConstraint("vault_id", "id"),
)

settings = Table(
    "settings",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("profile_id", String(36), nullable=True),
    Column("setting_key", String(64), nullable=False),
    Column("value_json", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("source", String(16), nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    CheckConstraint("source IN ('DEFAULT','USER','POLICY')"),
    ForeignKeyConstraint(
        ["vault_id", "profile_id"],
        ["profiles.vault_id", "profiles.id"],
        ondelete="RESTRICT",
    ),
)
Index(
    "uq_settings_vault_key",
    settings.c.vault_id,
    settings.c.setting_key,
    unique=True,
    sqlite_where=settings.c.profile_id.is_(None),
)
Index(
    "uq_settings_profile_key",
    settings.c.vault_id,
    settings.c.profile_id,
    settings.c.setting_key,
    unique=True,
    sqlite_where=settings.c.profile_id.is_not(None),
)

idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("route_code", String(96), nullable=False),
    Column("actor_class", String(32), nullable=False),
    Column("idempotency_key_hmac", String(64), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("result_type", String(64), nullable=True),
    Column("result_id", String(36), nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("expires_at_us", Integer, nullable=False),
    UniqueConstraint(
        "vault_id", "route_code", "actor_class", "idempotency_key_hmac", name="uq_idempotency_scope"
    ),
    UniqueConstraint("vault_id", "id"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("job_type", String(48), nullable=False),
    Column("state", String(32), nullable=False),
    Column("priority", Integer, nullable=False),
    Column("progress_micros", Integer, nullable=False),
    Column("progress_message_code", String(96), nullable=True),
    Column("scheduled_at_us", Integer, nullable=False),
    Column("lease_owner", String(64), nullable=True),
    Column("lease_expires_at_us", Integer, nullable=True),
    Column("retry_count", Integer, nullable=False),
    Column("retry_limit", Integer, nullable=False),
    Column("cancel_requested_at_us", Integer, nullable=True),
    Column("idempotency_record_id", String(36), nullable=True),
    Column("input_manifest_json", Text, nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    CheckConstraint("priority >= 0 AND priority <= 100"),
    CheckConstraint("progress_micros >= 0 AND progress_micros <= 1000000"),
    CheckConstraint("retry_count >= 0 AND retry_limit >= 0 AND retry_count <= retry_limit"),
    ForeignKeyConstraint(
        ["vault_id", "idempotency_record_id"],
        ["idempotency_records.vault_id", "idempotency_records.id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("vault_id", "id"),
)
Index("ix_jobs_ready", jobs.c.state, jobs.c.scheduled_at_us, jobs.c.priority)
Index("ix_jobs_lease", jobs.c.lease_expires_at_us)

job_dependencies = Table(
    "job_dependencies",
    metadata,
    Column("vault_id", String(36), nullable=False),
    Column("job_id", String(36), nullable=False),
    Column("depends_on_job_id", String(36), nullable=False),
    Column("required_state", String(16), nullable=False),
    Column("failure_policy", String(16), nullable=False),
    Column("created_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "job_id"],
        ["jobs.vault_id", "jobs.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "depends_on_job_id"],
        ["jobs.vault_id", "jobs.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("job_id <> depends_on_job_id"),
    CheckConstraint("required_state IN ('SUCCEEDED','TERMINAL')"),
    CheckConstraint("failure_policy IN ('BLOCK','CANCEL')"),
    UniqueConstraint("vault_id", "job_id", "depends_on_job_id"),
)
Index(
    "ix_job_dependencies_upstream",
    job_dependencies.c.vault_id,
    job_dependencies.c.depends_on_job_id,
)

job_attempts = Table(
    "job_attempts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("job_id", String(36), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("worker_kind", String(48), nullable=False),
    Column("started_at_us", Integer, nullable=False),
    Column("finished_at_us", Integer, nullable=True),
    Column("outcome_code", String(64), nullable=True),
    Column("result_metadata_json", Text, nullable=False),
    ForeignKeyConstraint(["vault_id", "job_id"], ["jobs.vault_id", "jobs.id"], ondelete="RESTRICT"),
    UniqueConstraint("vault_id", "job_id", "attempt_number"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("event_type", String(96), nullable=False),
    Column("actor_type", String(32), nullable=False),
    Column("target_type", String(64), nullable=False),
    Column("target_id", String(36), nullable=True),
    Column("before_digest", String(64), nullable=True),
    Column("after_digest", String(64), nullable=True),
    Column("metadata_json", Text, nullable=False),
    Column("occurred_at_us", Integer, nullable=False),
    Column("previous_event_hash", String(64), nullable=True),
    Column("event_hash", String(64), nullable=False),
)

event_stream_sessions = Table(
    "event_stream_sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("started_at_us", Integer, nullable=False),
    Column("closed_at_us", Integer, nullable=True),
    Column("next_sequence", Integer, nullable=False),
    Column("minimum_retained_sequence", Integer, nullable=False),
    Column("contract_version", Integer, nullable=False),
    UniqueConstraint("vault_id", "id"),
)

event_outbox = Table(
    "event_outbox",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("stream_session_id", String(36), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("event_type", String(96), nullable=False),
    Column("resource_type", String(64), nullable=True),
    Column("resource_id", String(36), nullable=True),
    Column("resource_revision", Integer, nullable=True),
    Column("payload_json", Text, nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("published_at_us", Integer, nullable=True),
    Column("expires_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "stream_session_id"],
        ["event_stream_sessions.vault_id", "event_stream_sessions.id"],
        ondelete="RESTRICT",
    ),
    UniqueConstraint("stream_session_id", "sequence"),
)

backup_records = Table(
    "backup_records",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), ForeignKey("vaults.id", ondelete="RESTRICT"), nullable=False),
    Column("bundle_version", Integer, nullable=False),
    Column("destination_class", String(32), nullable=False),
    Column("nonce_b64", String(16), nullable=False),
    Column("ciphertext_sha256", String(64), nullable=False),
    Column("key_version", Integer, nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("verified_at_us", Integer, nullable=True),
    Column("restored_at_us", Integer, nullable=True),
    Column("retention_expires_at_us", Integer, nullable=True),
    Column("state", String(32), nullable=False),
    UniqueConstraint("vault_id", "key_version", "nonce_b64", name="uq_backup_nonce"),
)

# Phase 3 deliberately starts with profile-scoped intake and identity data. Isolated
# audit-run scope and provider/evidence provenance are introduced by the migrations
# that own those parent tables, rather than leaving unverifiable polymorphic IDs.
intake_sources = Table(
    "intake_sources",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("source_kind", String(24), nullable=False),
    Column("display_name", Text, nullable=False),
    Column("broker_handle", String(128), nullable=True),
    Column("declared_mime", String(128), nullable=True),
    Column("detected_mime", String(128), nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("retention_state", String(24), nullable=False),
    Column("retention_expires_at_us", Integer, nullable=True),
    Column("consent_confirmed_at_us", Integer, nullable=False),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id"],
        ["profiles.vault_id", "profiles.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("source_kind IN ('PASTE','FILE','EXPORT','CONNECTOR','MANUAL_EVIDENCE')"),
    CheckConstraint("byte_size >= 0 AND byte_size <= 1073741824"),
    CheckConstraint("length(sha256) = 64 AND sha256 = lower(sha256)"),
    CheckConstraint("retention_state IN ('TEMPORARY','RETAINED','PURGE_PENDING')"),
    CheckConstraint("retention_state <> 'TEMPORARY' OR retention_expires_at_us IS NOT NULL"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
)
Index(
    "ix_intake_sources_profile",
    intake_sources.c.vault_id,
    intake_sources.c.profile_id,
    intake_sources.c.created_at_us,
)

intake_segments = Table(
    "intake_segments",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("intake_source_id", String(36), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("segment_kind", String(24), nullable=False),
    Column("content_text", Text, nullable=True),
    Column("content_hmac", String(64), nullable=False),
    Column("locator_json", Text, nullable=False),
    Column("language", String(35), nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id"],
        ["intake_sources.vault_id", "intake_sources.profile_id", "intake_sources.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("ordinal >= 0"),
    CheckConstraint("segment_kind IN ('TEXT','RECORD','CONTACT','JSON_VALUE','FILE_MEMBER')"),
    CheckConstraint("length(content_hmac) = 64 AND content_hmac = lower(content_hmac)"),
    CheckConstraint("json_valid(locator_json)"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "intake_source_id", "ordinal"),
)
Index(
    "uq_intake_segments_edge_origin_parent",
    intake_segments.c.vault_id,
    intake_segments.c.profile_id,
    intake_segments.c.intake_source_id,
    intake_segments.c.id,
    unique=True,
)

quarantine_items = Table(
    "quarantine_items",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("intake_source_id", String(36), nullable=False),
    Column("reason_code", String(32), nullable=False),
    Column("opaque_blob_key", String(128), nullable=True),
    Column("mime_type", String(128), nullable=True),
    Column("byte_size_plaintext", Integer, nullable=True),
    Column("byte_size_ciphertext", Integer, nullable=True),
    Column("sha256_plaintext", String(64), nullable=True),
    Column("sha256_ciphertext", String(64), nullable=True),
    Column("encryption_version", String(48), nullable=True),
    Column("key_version", Integer, nullable=True),
    Column("state", String(24), nullable=False),
    Column("retention_expires_at_us", Integer, nullable=False),
    Column("reviewed_at_us", Integer, nullable=True),
    Column("deletion_verified_at_us", Integer, nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id"],
        ["intake_sources.vault_id", "intake_sources.profile_id", "intake_sources.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "reason_code IN "
        "('RESTRICTED_VALUE','MIME_MISMATCH','ACTIVE_CONTENT','SIZE_LIMIT','MALFORMED',"
        "'UNSAFE_ARCHIVE')"
    ),
    CheckConstraint("state IN ('PENDING_REVIEW','DELETED','RELEASED_AS_SAFE')"),
    CheckConstraint("byte_size_plaintext IS NULL OR byte_size_plaintext >= 0"),
    CheckConstraint("byte_size_ciphertext IS NULL OR byte_size_ciphertext >= 0"),
    CheckConstraint(
        "sha256_plaintext IS NULL OR "
        "(length(sha256_plaintext) = 64 AND sha256_plaintext = lower(sha256_plaintext))"
    ),
    CheckConstraint(
        "sha256_ciphertext IS NULL OR "
        "(length(sha256_ciphertext) = 64 AND sha256_ciphertext = lower(sha256_ciphertext))"
    ),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
)

extraction_runs = Table(
    "extraction_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("intake_source_id", String(36), nullable=False),
    Column("job_id", String(36), nullable=False),
    Column("engine_kind", String(24), nullable=False),
    Column("engine_name", String(96), nullable=False),
    Column("engine_version", String(48), nullable=False),
    Column("configuration_hash", String(64), nullable=False),
    Column("state", String(24), nullable=False),
    Column("started_at_us", Integer, nullable=True),
    Column("finished_at_us", Integer, nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id"],
        ["intake_sources.vault_id", "intake_sources.profile_id", "intake_sources.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "job_id"],
        ["jobs.vault_id", "jobs.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("engine_kind IN ('DETERMINISTIC','LOCAL_MODEL')"),
    CheckConstraint(
        "state IN ('DRAFT','QUEUED','RUNNING','PAUSED','CANCELLED','SUCCEEDED','PARTIAL','FAILED')"
    ),
    CheckConstraint(
        "length(configuration_hash) = 64 AND configuration_hash = lower(configuration_hash)"
    ),
    CheckConstraint("finished_at_us IS NULL OR started_at_us IS NOT NULL"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint("vault_id", "job_id"),
)
Index(
    "uq_extraction_runs_edge_origin_parent",
    extraction_runs.c.vault_id,
    extraction_runs.c.profile_id,
    extraction_runs.c.intake_source_id,
    extraction_runs.c.id,
    unique=True,
)

entities = Table(
    "entities",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("canonical_value", Text, nullable=False),
    Column("display_mask", Text, nullable=False),
    Column("value_hmac", String(64), nullable=False),
    Column("sensitivity", String(24), nullable=False),
    Column("review_state", String(24), nullable=False),
    Column("temporal_state", String(16), nullable=False),
    Column("valid_from_us", Integer, nullable=True),
    Column("valid_to_us", Integer, nullable=True),
    Column("search_policy", String(24), nullable=False),
    Column("transmission_policy", String(24), nullable=False),
    Column("current_decision_id", String(36), nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id"],
        ["profiles.vault_id", "profiles.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "entity_type IN "
        "('PERSON','ALIAS','USERNAME','EMAIL','TELEPHONE','ADDRESS','LOCATION',"
        "'ORGANISATION','EMPLOYMENT','EDUCATION','DOMAIN','URL','PLATFORM_ACCOUNT',"
        "'COMPANY','PROJECT','IMAGE','DOCUMENT','DATE','IP_ADDRESS','COORDINATE',"
        "'COMPANY_NUMBER','PLATFORM_ID','POSTAL_CODE','WALLET_ADDRESS','OTHER')"
    ),
    # RESTRICTED is intentionally absent from every ordinary identity/graph check.
    CheckConstraint("sensitivity IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')"),
    CheckConstraint(
        "review_state IN "
        "('UNREVIEWED','CONFIRMED','PROBABLE','POSSIBLE','FALSE_POSITIVE','EXCLUDED')"
    ),
    CheckConstraint("temporal_state IN ('CURRENT','HISTORICAL','UNKNOWN')"),
    CheckConstraint(
        "search_policy IN ('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED')"
    ),
    CheckConstraint(
        "transmission_policy IN "
        "('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED')"
    ),
    CheckConstraint(
        "review_state NOT IN ('FALSE_POSITIVE','EXCLUDED') OR "
        "(search_policy = 'SEARCH_DENIED' AND transmission_policy = 'TRANSMISSION_DENIED')"
    ),
    CheckConstraint(
        "sensitivity <> 'HIGHLY_SENSITIVE' OR "
        "(search_policy <> 'SEARCH_ALLOWED' AND transmission_policy <> 'PROVIDER_ALLOWLIST')"
    ),
    CheckConstraint("valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us >= valid_from_us"),
    CheckConstraint("length(value_hmac) = 64 AND value_hmac = lower(value_hmac)"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "id", "sensitivity"),
)
Index(
    "uq_entities_live_value",
    entities.c.vault_id,
    entities.c.profile_id,
    entities.c.entity_type,
    entities.c.value_hmac,
    unique=True,
    sqlite_where=entities.c.deleted_at_us.is_(None),
)

entity_variants = Table(
    "entity_variants",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("entity_id", String(36), nullable=False),
    Column("sensitivity", String(24), nullable=False),
    Column("variant_type", String(24), nullable=False),
    Column("value", Text, nullable=False),
    Column("value_hmac", String(64), nullable=False),
    Column("generator", String(96), nullable=False),
    Column("generator_version", String(48), nullable=False),
    Column("rank", Integer, nullable=False),
    Column("estimated_risk", String(16), nullable=False),
    Column("approved_for_search", Integer, nullable=False),
    Column("current_decision_id", String(36), nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "entity_id", "sensitivity"],
        ["entities.vault_id", "entities.profile_id", "entities.id", "entities.sensitivity"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("sensitivity IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')"),
    CheckConstraint(
        "variant_type IN "
        "('EXACT','CASE','SEPARATOR','TRANSLITERATION','DIACRITIC','NATIONAL_FORMAT',"
        "'E164','LOCAL_PART','DOMAIN','CONTROLLED_TYPO','OTHER')"
    ),
    CheckConstraint("length(value_hmac) = 64 AND value_hmac = lower(value_hmac)"),
    CheckConstraint("rank >= 0 AND rank <= 1000000"),
    CheckConstraint("estimated_risk IN ('LOW','MEDIUM','HIGH')"),
    CheckConstraint("approved_for_search IN (0, 1)"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "entity_id", "id"),
)

entity_variant_decisions = Table(
    "entity_variant_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("variant_id", String(36), nullable=False),
    Column("decision_type", String(24), nullable=False),
    Column("before_approved", Integer, nullable=False),
    Column("after_approved", Integer, nullable=False),
    Column("before_rank", Integer, nullable=False),
    Column("after_rank", Integer, nullable=False),
    Column("actor_type", String(24), nullable=False),
    Column("actor_version", String(48), nullable=True),
    Column("reason_code", String(64), nullable=True),
    Column("before_revision", Integer, nullable=False),
    Column("after_revision", Integer, nullable=False),
    Column("supersedes_decision_id", String(36), nullable=True),
    Column("decided_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "variant_id"],
        ["entity_variants.vault_id", "entity_variants.profile_id", "entity_variants.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "variant_id", "supersedes_decision_id"],
        [
            "entity_variant_decisions.vault_id",
            "entity_variant_decisions.profile_id",
            "entity_variant_decisions.variant_id",
            "entity_variant_decisions.id",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint("decision_type IN ('APPROVE','REVOKE','RERANK','EXCLUDE')"),
    CheckConstraint("before_approved IN (0, 1) AND after_approved IN (0, 1)"),
    CheckConstraint("before_rank >= 0 AND after_rank >= 0"),
    CheckConstraint("actor_type IN ('LOCAL_USER','DETERMINISTIC_RULE','LOCAL_MODEL')"),
    CheckConstraint("after_revision = before_revision + 1"),
    UniqueConstraint("vault_id", "profile_id", "variant_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "variant_id", "after_revision"),
)

entity_origins = Table(
    "entity_origins",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("entity_id", String(36), nullable=False),
    Column("extraction_run_id", String(36), nullable=True),
    Column("intake_segment_id", String(36), nullable=True),
    Column("raw_result_id", String(36), nullable=True),
    Column("evidence_artifact_id", String(36), nullable=True),
    Column("source_span_start", Integer, nullable=True),
    Column("source_span_end", Integer, nullable=True),
    Column("origin_kind", String(24), nullable=False),
    Column("confidence_micros", Integer, nullable=False),
    Column("explanation", Text, nullable=False),
    Column("observed_at_us", Integer, nullable=False),
    Column("created_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "entity_id"],
        ["entities.vault_id", "entities.profile_id", "entities.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "extraction_run_id"],
        ["extraction_runs.vault_id", "extraction_runs.profile_id", "extraction_runs.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_segment_id"],
        ["intake_segments.vault_id", "intake_segments.profile_id", "intake_segments.id"],
        ondelete="RESTRICT",
    ),
    # Later source-owning migrations replace this temporary availability check
    # while retaining the exactly-one-pointer invariant.
    CheckConstraint(
        "intake_segment_id IS NOT NULL AND raw_result_id IS NULL AND evidence_artifact_id IS NULL"
    ),
    CheckConstraint(
        "(source_span_start IS NULL AND source_span_end IS NULL) OR "
        "(source_span_start >= 0 AND source_span_end > source_span_start)"
    ),
    CheckConstraint("origin_kind IN ('USER_INPUT','DETERMINISTIC','LOCAL_MODEL','MANUAL')"),
    CheckConstraint("confidence_micros >= 0 AND confidence_micros <= 1000000"),
    UniqueConstraint("vault_id", "profile_id", "id"),
)

entity_decisions = Table(
    "entity_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("entity_id", String(36), nullable=False),
    Column("decision_type", String(24), nullable=False),
    Column("before_review_state", String(24), nullable=False),
    Column("after_review_state", String(24), nullable=False),
    Column("before_sensitivity", String(24), nullable=False),
    Column("after_sensitivity", String(24), nullable=False),
    Column("before_temporal_state", String(16), nullable=False),
    Column("after_temporal_state", String(16), nullable=False),
    Column("before_search_policy", String(24), nullable=False),
    Column("after_search_policy", String(24), nullable=False),
    Column("before_transmission_policy", String(24), nullable=False),
    Column("after_transmission_policy", String(24), nullable=False),
    Column("actor_type", String(24), nullable=False),
    Column("actor_version", String(48), nullable=True),
    Column("reason_code", String(64), nullable=True),
    Column("before_revision", Integer, nullable=False),
    Column("after_revision", Integer, nullable=False),
    Column("supersedes_decision_id", String(36), nullable=True),
    Column("decided_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "entity_id"],
        ["entities.vault_id", "entities.profile_id", "entities.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "entity_id", "supersedes_decision_id"],
        [
            "entity_decisions.vault_id",
            "entity_decisions.profile_id",
            "entity_decisions.entity_id",
            "entity_decisions.id",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "decision_type IN "
        "('CONFIRM','REJECT','EXCLUDE','EDIT','MERGE','SPLIT','CLASSIFY','POLICY_CHANGE')"
    ),
    CheckConstraint(
        "before_review_state IN "
        "('UNREVIEWED','CONFIRMED','PROBABLE','POSSIBLE','FALSE_POSITIVE','EXCLUDED')"
    ),
    CheckConstraint(
        "after_review_state IN "
        "('UNREVIEWED','CONFIRMED','PROBABLE','POSSIBLE','FALSE_POSITIVE','EXCLUDED')"
    ),
    CheckConstraint(
        "before_sensitivity IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE') AND "
        "after_sensitivity IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')"
    ),
    CheckConstraint(
        "before_temporal_state IN ('CURRENT','HISTORICAL','UNKNOWN') AND "
        "after_temporal_state IN ('CURRENT','HISTORICAL','UNKNOWN')"
    ),
    CheckConstraint(
        "before_search_policy IN "
        "('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED') AND "
        "after_search_policy IN "
        "('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED')"
    ),
    CheckConstraint(
        "before_transmission_policy IN "
        "('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED') AND "
        "after_transmission_policy IN "
        "('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED')"
    ),
    CheckConstraint(
        "before_review_state NOT IN ('FALSE_POSITIVE','EXCLUDED') OR "
        "(before_search_policy = 'SEARCH_DENIED' AND "
        "before_transmission_policy = 'TRANSMISSION_DENIED')"
    ),
    CheckConstraint(
        "after_review_state NOT IN ('FALSE_POSITIVE','EXCLUDED') OR "
        "(after_search_policy = 'SEARCH_DENIED' AND "
        "after_transmission_policy = 'TRANSMISSION_DENIED')"
    ),
    CheckConstraint(
        "before_sensitivity <> 'HIGHLY_SENSITIVE' OR "
        "(before_search_policy <> 'SEARCH_ALLOWED' AND "
        "before_transmission_policy <> 'PROVIDER_ALLOWLIST')"
    ),
    CheckConstraint(
        "after_sensitivity <> 'HIGHLY_SENSITIVE' OR "
        "(after_search_policy <> 'SEARCH_ALLOWED' AND "
        "after_transmission_policy <> 'PROVIDER_ALLOWLIST')"
    ),
    CheckConstraint("actor_type IN ('LOCAL_USER','DETERMINISTIC_RULE','LOCAL_MODEL')"),
    CheckConstraint("after_revision = before_revision + 1"),
    UniqueConstraint("vault_id", "profile_id", "entity_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "entity_id", "after_revision"),
)

graph_nodes = Table(
    "graph_nodes",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("node_type", String(32), nullable=False),
    Column("display_label", Text, nullable=False),
    Column("sensitivity", String(24), nullable=False),
    Column("visibility", String(32), nullable=False),
    Column("entity_id", String(36), nullable=True),
    Column("position_json", Text, nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id"],
        ["profiles.vault_id", "profiles.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "entity_id", "sensitivity"],
        ["entities.vault_id", "entities.profile_id", "entities.id", "entities.sensitivity"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("sensitivity IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')"),
    CheckConstraint(
        "visibility IN "
        "('PUBLICLY_ATTRIBUTABLE','PUBLIC_PSEUDONYMOUS','PRIVATELY_LINKABLE',"
        "'HISTORICAL_RESIDUE','PRIVATE_ONLY','UNKNOWN')"
    ),
    CheckConstraint("position_json IS NULL OR json_valid(position_json)"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "id", "sensitivity"),
    UniqueConstraint("vault_id", "profile_id", "entity_id"),
)

graph_edges = Table(
    "graph_edges",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("from_node_id", String(36), nullable=False),
    Column("to_node_id", String(36), nullable=False),
    Column("edge_type", String(32), nullable=False),
    Column("confidence_micros", Integer, nullable=False),
    Column("visibility", String(32), nullable=False),
    Column("valid_from_us", Integer, nullable=True),
    Column("valid_to_us", Integer, nullable=True),
    Column("observed_at_us", Integer, nullable=False),
    Column("origin_type", String(24), nullable=False),
    Column("explanation", Text, nullable=False),
    Column("review_state", String(16), nullable=False),
    Column("current_decision_id", String(36), nullable=True),
    Column("created_at_us", Integer, nullable=False),
    Column("updated_at_us", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("deleted_at_us", Integer, nullable=True),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "from_node_id"],
        ["graph_nodes.vault_id", "graph_nodes.profile_id", "graph_nodes.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "to_node_id"],
        ["graph_nodes.vault_id", "graph_nodes.profile_id", "graph_nodes.id"],
        ondelete="RESTRICT",
    ),
    CheckConstraint("from_node_id <> to_node_id"),
    CheckConstraint(
        "edge_type IN "
        "('OWNS','USED','RECOVERY_FOR','EMPLOYED_BY','STUDIED_AT','LIVED_AT','LOCATED_IN',"
        "'LINKS_TO','MENTIONS','AUTHORED','CREATED','MIRRORS','REPOSTS','SAME_AS',"
        "'POSSIBLY_SAME_AS','NOT_SAME_AS','PREVIOUS_USERNAME','CURRENT_USERNAME','FOUND_BY',"
        "'SUPPORTED_BY','CONTRADICTED_BY','REMOVAL_REQUEST_FOR')"
    ),
    CheckConstraint("confidence_micros >= 0 AND confidence_micros <= 1000000"),
    CheckConstraint(
        "visibility IN "
        "('PUBLICLY_ATTRIBUTABLE','PUBLIC_PSEUDONYMOUS','PRIVATELY_LINKABLE',"
        "'HISTORICAL_RESIDUE','PRIVATE_ONLY','UNKNOWN')"
    ),
    CheckConstraint("valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us >= valid_from_us"),
    CheckConstraint("origin_type IN ('HUMAN','DETERMINISTIC','LOCAL_MODEL','PROVIDER')"),
    CheckConstraint("review_state IN ('UNREVIEWED','CONFIRMED','REJECTED','EXCLUDED')"),
    CheckConstraint("revision >= 1"),
    UniqueConstraint("vault_id", "profile_id", "id"),
)

graph_edge_origins = Table(
    "graph_edge_origins",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("graph_edge_id", String(36), nullable=False),
    Column("intake_source_id", String(36), nullable=False),
    Column("intake_segment_id", String(36), nullable=False),
    Column("extraction_run_id", String(36), nullable=False),
    Column("disposition", String(16), nullable=False),
    Column("confidence_micros", Integer, nullable=False),
    Column("visibility", String(32), nullable=False),
    Column("source_span_start", Integer, nullable=True),
    Column("source_span_end", Integer, nullable=True),
    Column("observed_at_us", Integer, nullable=False),
    Column("origin_type", String(24), nullable=False),
    Column("explanation", Text, nullable=False),
    Column("observation_hmac", String(64), nullable=False),
    Column("created_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "graph_edge_id"],
        ["graph_edges.vault_id", "graph_edges.profile_id", "graph_edges.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id"],
        ["intake_sources.vault_id", "intake_sources.profile_id", "intake_sources.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id", "intake_segment_id"],
        [
            "intake_segments.vault_id",
            "intake_segments.profile_id",
            "intake_segments.intake_source_id",
            "intake_segments.id",
        ],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "intake_source_id", "extraction_run_id"],
        [
            "extraction_runs.vault_id",
            "extraction_runs.profile_id",
            "extraction_runs.intake_source_id",
            "extraction_runs.id",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint("disposition IN ('SUPPORTS','CONTRADICTS')"),
    CheckConstraint("confidence_micros >= 0 AND confidence_micros <= 1000000"),
    CheckConstraint(
        "visibility IN "
        "('PUBLICLY_ATTRIBUTABLE','PUBLIC_PSEUDONYMOUS','PRIVATELY_LINKABLE',"
        "'HISTORICAL_RESIDUE','PRIVATE_ONLY','UNKNOWN')"
    ),
    CheckConstraint(
        "(source_span_start IS NULL AND source_span_end IS NULL) OR "
        "(source_span_start >= 0 AND source_span_end > source_span_start)"
    ),
    CheckConstraint("origin_type IN ('HUMAN','DETERMINISTIC','LOCAL_MODEL','PROVIDER')"),
    CheckConstraint("length(observation_hmac) = 64 AND observation_hmac = lower(observation_hmac)"),
    UniqueConstraint("vault_id", "profile_id", "id"),
    UniqueConstraint(
        "vault_id",
        "profile_id",
        "graph_edge_id",
        "observation_hmac",
        name="uq_graph_edge_origin_observation",
    ),
)
Index(
    "ix_graph_edge_origins_edge",
    graph_edge_origins.c.vault_id,
    graph_edge_origins.c.profile_id,
    graph_edge_origins.c.graph_edge_id,
    graph_edge_origins.c.created_at_us,
)

graph_edge_decisions = Table(
    "graph_edge_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("vault_id", String(36), nullable=False),
    Column("profile_id", String(36), nullable=False),
    Column("edge_id", String(36), nullable=False),
    Column("decision_type", String(24), nullable=False),
    Column("before_review_state", String(16), nullable=False),
    Column("after_review_state", String(16), nullable=False),
    Column("actor_type", String(24), nullable=False),
    Column("actor_version", String(48), nullable=True),
    Column("reason_code", String(64), nullable=True),
    Column("before_revision", Integer, nullable=False),
    Column("after_revision", Integer, nullable=False),
    Column("supersedes_decision_id", String(36), nullable=True),
    Column("decided_at_us", Integer, nullable=False),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "edge_id"],
        ["graph_edges.vault_id", "graph_edges.profile_id", "graph_edges.id"],
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["vault_id", "profile_id", "edge_id", "supersedes_decision_id"],
        [
            "graph_edge_decisions.vault_id",
            "graph_edge_decisions.profile_id",
            "graph_edge_decisions.edge_id",
            "graph_edge_decisions.id",
        ],
        ondelete="RESTRICT",
    ),
    CheckConstraint("decision_type IN ('CONFIRM','REJECT','CORRECT','EXCLUDE')"),
    CheckConstraint("before_review_state IN ('UNREVIEWED','CONFIRMED','REJECTED','EXCLUDED')"),
    CheckConstraint("after_review_state IN ('UNREVIEWED','CONFIRMED','REJECTED','EXCLUDED')"),
    CheckConstraint("actor_type IN ('LOCAL_USER','DETERMINISTIC_RULE','LOCAL_MODEL')"),
    CheckConstraint("after_revision = before_revision + 1"),
    UniqueConstraint("vault_id", "profile_id", "edge_id", "id"),
    UniqueConstraint("vault_id", "profile_id", "edge_id", "after_revision"),
)
