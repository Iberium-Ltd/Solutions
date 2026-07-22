"""Add persistent people metadata and recursive discovery execution state.

The schema records a complete person -> audit -> frontier -> result/lead ->
proposal chain. Composite foreign keys keep every row in one vault/profile
scope, while keyed fingerprints deduplicate sensitive values without using them
as indexes. Tool receipts and explicit terminal states make partial coverage and
restart recovery observable rather than implying that every check succeeded.

Revision ID: 0009_identity_discovery
Revises: 0008_phase6_audit_remediation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_identity_discovery"
down_revision = "0008_phase6_audit_remediation"
branch_labels = None
depends_on = None

_TASK_STATES = (
    "'PLANNED','READY','QUEUED','RUNNING','SUCCEEDED_EMPTY','SUCCEEDED_RESULTS',"
    "'BLOCKED','RATE_LIMITED','AUTH_REQUIRED','FAILED_RETRYABLE','FAILED_TERMINAL',"
    "'SKIPPED','CANCELLED','REVIEW_REQUIRED','REVIEWED','SAVED'"
)


def upgrade() -> None:
    """Install the durable identity workspace and its recursive audit ledger."""

    # Person metadata extends the existing profile without replacing Phase 3
    # identities or their exact intake origins.
    op.create_table(
        "identity_people",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id"),
        sa.CheckConstraint("length(notes) <= 20000"),
        sa.CheckConstraint("json_valid(tags_json)"),
        sa.CheckConstraint("revision >= 1"),
    )

    # Sources are profile knowledge. URL HMACs provide scoped idempotency while
    # canonical URLs remain available for explicit review and future checks.
    op.create_table(
        "identity_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hmac", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("relationship_state", sa.String(24), nullable=False),
        sa.Column("parent_source_id", sa.String(36), nullable=True),
        sa.Column("first_seen_at_us", sa.Integer(), nullable=False),
        sa.Column("last_checked_at_us", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "parent_source_id"],
            ["identity_sources.vault_id", "identity_sources.profile_id", "identity_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "url_hmac"),
        sa.CheckConstraint(
            "source_type IN ('WEBSITE','SUBPAGE','SOCIAL_PROFILE','FORUM_PROFILE','FORUM_THREAD',"
            "'COMMENT','MEMBER_PAGE','GIT_REPOSITORY','PACKAGE_REGISTRY','DOCUMENT','PDF',"
            "'PUBLIC_RECORD','ARCHIVE','SEARCH_RESULT','MEDIA','MANUAL_URL','OTHER')"
        ),
        sa.CheckConstraint("relationship_state IN ('UNREVIEWED','RELATED','UNRELATED','BLOCKED')"),
        sa.CheckConstraint("length(url_hmac) = 64 AND url_hmac = lower(url_hmac)"),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR "
            "(length(content_sha256) = 64 AND content_sha256 = lower(content_sha256))"
        ),
        sa.CheckConstraint("http_status IS NULL OR http_status BETWEEN 100 AND 599"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_index(
        "ix_identity_sources_person",
        "identity_sources",
        ["vault_id", "profile_id", "first_seen_at_us"],
    )

    # An audit snapshots mode, providers, model selection, and hard budgets so a
    # resumed run cannot silently inherit changed settings.
    op.create_table(
        "identity_audit_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("provider_ids_json", sa.Text(), nullable=False),
        sa.Column("use_local_ai", sa.Integer(), nullable=False),
        sa.Column("selected_model", sa.String(256), nullable=True),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("request_budget", sa.Integer(), nullable=False),
        sa.Column("time_budget_seconds", sa.Integer(), nullable=False),
        sa.Column("cost_budget_micros", sa.Integer(), nullable=False),
        sa.Column("total_tasks", sa.Integer(), nullable=False),
        sa.Column("terminal_tasks", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("lead_count", sa.Integer(), nullable=False),
        sa.Column("proposal_count", sa.Integer(), nullable=False),
        sa.Column("progress_micros", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("started_at_us", sa.Integer(), nullable=True),
        sa.Column("finished_at_us", sa.Integer(), nullable=True),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.CheckConstraint(
            "mode IN ('FULL_RESCAN','INCREMENTAL','NEW_IDENTIFIERS_ONLY',"
            "'FAILED_AND_BLOCKED_RETRY','SELECTED_IDENTITIES','SELECTED_PROVIDERS',"
            "'CHANGE_MONITORING','MAXIMUM_COVERAGE')"
        ),
        sa.CheckConstraint(
            "state IN "
            "('DRAFT','READY','RUNNING','PAUSED','COMPLETED','PARTIAL','CANCELLED','FAILED')"
        ),
        sa.CheckConstraint(
            "stage IN ('KNOWLEDGE','PLANNING','SEARCHING','EXTRACTING','CORRELATING',"
            "'AI_ANALYSIS','REVIEW','CHECKPOINT','COMPLETE')"
        ),
        sa.CheckConstraint("json_valid(provider_ids_json)"),
        sa.CheckConstraint("use_local_ai IN (0,1)"),
        sa.CheckConstraint("max_depth BETWEEN 0 AND 8"),
        sa.CheckConstraint("request_budget BETWEEN 1 AND 2000"),
        sa.CheckConstraint("time_budget_seconds BETWEEN 10 AND 86400"),
        sa.CheckConstraint("cost_budget_micros BETWEEN 0 AND 1000000000000"),
        sa.CheckConstraint(
            "total_tasks >= 0 AND terminal_tasks >= 0 AND terminal_tasks <= total_tasks"
        ),
        sa.CheckConstraint("result_count >= 0 AND lead_count >= 0 AND proposal_count >= 0"),
        sa.CheckConstraint("progress_micros BETWEEN 0 AND 1000000"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_index(
        "ix_identity_audit_person",
        "identity_audit_runs",
        ["vault_id", "profile_id", "created_at_us"],
    )

    # Leads form the recursive hypothesis chain; confidence and ownership state
    # remain separate from human review state.
    op.create_table(
        "identity_leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("parent_lead_id", sa.String(36), nullable=True),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("lead_type", sa.String(32), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("value_hmac", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("supporting_signals_json", sa.Text(), nullable=False),
        sa.Column("contradictions_json", sa.Text(), nullable=False),
        sa.Column("confidence_micros", sa.Integer(), nullable=False),
        sa.Column("ownership_state", sa.String(24), nullable=False),
        sa.Column("temporal_state", sa.String(16), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("expansion_state", sa.String(24), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "audit_id"],
            [
                "identity_audit_runs.vault_id",
                "identity_audit_runs.profile_id",
                "identity_audit_runs.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "parent_lead_id"],
            ["identity_leads.vault_id", "identity_leads.profile_id", "identity_leads.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "source_id"],
            ["identity_sources.vault_id", "identity_sources.profile_id", "identity_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id", "lead_type", "value_hmac"),
        sa.CheckConstraint("depth BETWEEN 0 AND 8"),
        sa.CheckConstraint(
            "json_valid(supporting_signals_json) AND json_valid(contradictions_json)"
        ),
        sa.CheckConstraint("confidence_micros BETWEEN 0 AND 1000000"),
        sa.CheckConstraint(
            "ownership_state IN ('UNKNOWN','POSSIBLE','PROBABLE','CONFIRMED','REJECTED')"
        ),
        sa.CheckConstraint("temporal_state IN ('CURRENT','HISTORICAL','UNKNOWN')"),
        sa.CheckConstraint("review_state IN ('UNREVIEWED','CONFIRMED','REJECTED','UNRELATED')"),
        sa.CheckConstraint(
            "expansion_state IN ('NEW','QUEUED','EXPANDING','EXHAUSTED','BLOCKED','REJECTED')"
        ),
    )

    # Frontier rows are the scheduler's source of truth. Parent links preserve
    # why work was generated, and the unique fingerprint prevents cycles.
    op.create_table(
        "identity_frontier_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=True),
        sa.Column("parent_task_id", sa.String(36), nullable=True),
        sa.Column("task_type", sa.String(48), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("payload_text", sa.Text(), nullable=False),
        sa.Column("payload_hmac", sa.String(64), nullable=False),
        sa.Column("masked_payload", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("information_gain_micros", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_limit", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at_us", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at_us", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("receipt_json", sa.Text(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "audit_id"],
            [
                "identity_audit_runs.vault_id",
                "identity_audit_runs.profile_id",
                "identity_audit_runs.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "lead_id"],
            ["identity_leads.vault_id", "identity_leads.profile_id", "identity_leads.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "parent_task_id"],
            [
                "identity_frontier_tasks.vault_id",
                "identity_frontier_tasks.profile_id",
                "identity_frontier_tasks.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id", "id"),
        sa.UniqueConstraint(
            "vault_id", "profile_id", "audit_id", "task_type", "provider_id", "payload_hmac"
        ),
        sa.CheckConstraint(
            "task_type IN ('SEARCH_WEB','SEARCH_PROVIDER','SEARCH_SITE','SEARCH_DOMAIN',"
            "'SEARCH_USERNAME','FETCH_URL','PARSE_HTML','EXTRACT_LINKS','EXTRACT_IDENTIFIERS',"
            "'QUERY_ARCHIVE','QUERY_GITHUB','QUERY_REGISTRY','QUERY_DNS',"
            "'QUERY_CERTIFICATE_TRANSPARENCY','RUN_USERNAME_ENUMERATION',"
            "'RUN_METADATA_EXTRACTION','RUN_OCR','HASH_IMAGE','COMPARE_IMAGES',"
            "'CAPTURE_SCREENSHOT','CAPTURE_HTML','CAPTURE_DOCUMENT',"
            "'GENERATE_QUERY_VARIANTS','ANALYSE_DOCUMENT','COMPARE_SOURCES')"
        ),
        sa.CheckConstraint(f"state IN ({_TASK_STATES})"),
        sa.CheckConstraint("priority BETWEEN 0 AND 100"),
        sa.CheckConstraint("information_gain_micros BETWEEN 0 AND 1000000"),
        sa.CheckConstraint("depth BETWEEN 0 AND 8"),
        sa.CheckConstraint("attempt_count >= 0 AND retry_limit BETWEEN 0 AND 10"),
        sa.CheckConstraint("result_count >= 0"),
        sa.CheckConstraint("json_valid(receipt_json)"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_index(
        "ix_identity_frontier_ready",
        "identity_frontier_tasks",
        ["vault_id", "profile_id", "audit_id", "state", "priority", "created_at_us"],
    )

    # Results retain the exact public URL and provider context returned by a
    # task; deduplication never erases the task/receipt chain.
    op.create_table(
        "identity_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hmac", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("observed_at_us", sa.Integer(), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "audit_id", "task_id"],
            [
                "identity_frontier_tasks.vault_id",
                "identity_frontier_tasks.profile_id",
                "identity_frontier_tasks.audit_id",
                "identity_frontier_tasks.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id", "url_hmac"),
        sa.CheckConstraint("rank BETWEEN 1 AND 10000"),
        sa.CheckConstraint(
            "category IN "
            "('SOCIAL','FORUM','CODE','DOCUMENT','ARCHIVE','PUBLIC_RECORD','WEBSITE','MEDIA','OTHER')"
        ),
        sa.CheckConstraint("review_state IN ('UNREVIEWED','RELATED','UNRELATED','SAVED')"),
    )

    # Extracted identifiers are proposals until reviewed. Exact source spans and
    # model attribution make deterministic and model-assisted origins explicit.
    op.create_table(
        "identity_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("value_hmac", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_span_start", sa.Integer(), nullable=True),
        sa.Column("source_span_end", sa.Integer(), nullable=True),
        sa.Column("supporting_signals_json", sa.Text(), nullable=False),
        sa.Column("contradictions_json", sa.Text(), nullable=False),
        sa.Column("confidence_micros", sa.Integer(), nullable=False),
        sa.Column("temporal_state", sa.String(16), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("recommended_actions_json", sa.Text(), nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(256), nullable=True),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("reviewed_at_us", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "audit_id"],
            [
                "identity_audit_runs.vault_id",
                "identity_audit_runs.profile_id",
                "identity_audit_runs.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "lead_id"],
            ["identity_leads.vault_id", "identity_leads.profile_id", "identity_leads.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id", "entity_type", "value_hmac"),
        sa.CheckConstraint("json_valid(supporting_signals_json)"),
        sa.CheckConstraint("json_valid(contradictions_json)"),
        sa.CheckConstraint("json_valid(recommended_actions_json)"),
        sa.CheckConstraint("confidence_micros BETWEEN 0 AND 1000000"),
        sa.CheckConstraint("temporal_state IN ('CURRENT','HISTORICAL','UNKNOWN')"),
        sa.CheckConstraint(
            "review_state IN "
            "('UNREVIEWED','CONFIRMED','CONFIRMED_HISTORICAL','PROBABLE','REJECTED',"
            "'UNRELATED','MERGED')"
        ),
        sa.CheckConstraint(
            "(source_span_start IS NULL AND source_span_end IS NULL) OR "
            "(source_span_start >= 0 AND source_span_end > source_span_start)"
        ),
        sa.CheckConstraint("revision >= 1"),
    )

    # Receipts describe every broker attempt independently from its findings,
    # including blocked, empty, failed, and not-yet-implemented outcomes.
    op.create_table(
        "identity_tool_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("tool_name", sa.String(48), nullable=False),
        sa.Column("arguments_sha256", sa.String(64), nullable=False),
        sa.Column("authorization_state", sa.String(24), nullable=False),
        sa.Column("execution_state", sa.String(24), nullable=False),
        sa.Column("result_code", sa.String(64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(256), nullable=True),
        sa.Column("started_at_us", sa.Integer(), nullable=False),
        sa.Column("finished_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "audit_id"],
            [
                "identity_audit_runs.vault_id",
                "identity_audit_runs.profile_id",
                "identity_audit_runs.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "task_id"],
            [
                "identity_frontier_tasks.vault_id",
                "identity_frontier_tasks.profile_id",
                "identity_frontier_tasks.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.CheckConstraint(
            "length(arguments_sha256) = 64 AND arguments_sha256 = lower(arguments_sha256)"
        ),
        sa.CheckConstraint("authorization_state IN ('APPROVED','DENIED','REVIEW_REQUIRED')"),
        sa.CheckConstraint(
            "execution_state IN ('SUCCEEDED','EMPTY','BLOCKED','FAILED','NOT_IMPLEMENTED')"
        ),
        sa.CheckConstraint("result_count >= 0"),
        sa.CheckConstraint("finished_at_us >= started_at_us"),
    )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
