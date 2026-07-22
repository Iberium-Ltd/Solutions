"""Add the Phase 4 query policy, approval, budget, and ledger core.

Plans bind policy snapshots to checks; approvals are scoped and consumable;
budget usage and dispatch receipts make every attempted provider action
recoverable and independently auditable.

Revision ID: 0006_query_policy_core
Revises: 0005_graph_edge_origins
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_query_policy_core"
down_revision = "0005_graph_edge_origins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the durable planning-to-dispatch chain and its database constraints."""

    op.create_table(
        "phase4_providers",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(96), nullable=False),
        sa.Column("operator_name", sa.String(128), nullable=False),
        sa.Column("adapter_id", sa.String(64), nullable=False),
        sa.Column("adapter_mode", sa.String(24), nullable=False),
        sa.Column("adapter_network_access", sa.Integer(), nullable=False),
        sa.Column("adapter_sends_identifiers", sa.Integer(), nullable=False),
        sa.Column("adapter_query_classes_json", sa.Text(), nullable=False),
        sa.Column("access_basis", sa.String(24), nullable=False),
        sa.Column("processing_regions_json", sa.Text(), nullable=False),
        sa.Column("external", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("retention_known", sa.Integer(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["vault_id"], ["vaults.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("vault_id", "id"),
        sa.CheckConstraint("json_valid(processing_regions_json)"),
        sa.CheckConstraint("json_valid(adapter_query_classes_json)"),
        sa.CheckConstraint(
            "adapter_network_access IN (0,1) AND adapter_sends_identifiers IN (0,1)"
        ),
        sa.CheckConstraint("external IN (0,1) AND enabled IN (0,1) AND retention_known IN (0,1)"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_table(
        "phase4_query_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("purpose_code", sa.String(96), nullable=False),
        sa.Column("policy_mode", sa.String(16), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("policy_hmac", sa.String(64), nullable=False),
        sa.Column("maximum_checks", sa.Integer(), nullable=False),
        sa.Column("maximum_checks_per_provider", sa.Integer(), nullable=False),
        sa.Column("used_checks", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.CheckConstraint("policy_mode IN ('LOCAL_ONLY','EU_ONLY','CUSTOM')"),
        sa.CheckConstraint("json_valid(policy_json)"),
        sa.CheckConstraint("length(policy_hmac) = 64 AND policy_hmac = lower(policy_hmac)"),
        sa.CheckConstraint("maximum_checks >= 1 AND maximum_checks <= 10000"),
        sa.CheckConstraint(
            "maximum_checks_per_provider >= 1 AND maximum_checks_per_provider <= maximum_checks"
        ),
        sa.CheckConstraint("used_checks >= 0 AND used_checks <= maximum_checks"),
        sa.CheckConstraint("state IN ('PLANNED','RUNNING','COMPLETE','FAILED','CANCELLED')"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_table(
        "phase4_provider_budget_usage",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("used_checks", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id"],
            ["phase4_query_runs.vault_id", "phase4_query_runs.profile_id", "phase4_query_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "provider_id"],
            ["phase4_providers.vault_id", "phase4_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "run_id", "provider_id"),
        sa.CheckConstraint("used_checks >= 0"),
    )
    op.create_table(
        "phase4_query_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("query_class", sa.String(32), nullable=False),
        sa.Column("masked_query", sa.String(512), nullable=False),
        sa.Column("query_hmac", sa.String(64), nullable=False),
        sa.Column("entity_revision", sa.Integer(), nullable=False),
        sa.Column("sensitivity_snapshot", sa.String(24), nullable=False),
        sa.Column("search_policy_snapshot", sa.String(24), nullable=False),
        sa.Column("transmission_policy_snapshot", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("requires_approval", sa.Integer(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id"],
            ["phase4_query_runs.vault_id", "phase4_query_runs.profile_id", "phase4_query_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "entity_id"],
            ["entities.vault_id", "entities.profile_id", "entities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "provider_id"],
            ["phase4_providers.vault_id", "phase4_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "run_id", "id"),
        sa.CheckConstraint("length(query_hmac) = 64 AND query_hmac = lower(query_hmac)"),
        sa.CheckConstraint("entity_revision >= 1"),
        sa.CheckConstraint(
            "sensitivity_snapshot IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE','RESTRICTED')"
        ),
        sa.CheckConstraint(
            "search_policy_snapshot IN "
            "('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED')"
        ),
        sa.CheckConstraint(
            "transmission_policy_snapshot IN "
            "('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED')"
        ),
        sa.CheckConstraint(
            "state IN ('PLANNED','APPROVAL_REQUIRED','NOT_CHECKED','BLOCKED','DISPATCHED',"
            "'SUCCEEDED','CHECK_FAILED')"
        ),
        sa.CheckConstraint(
            "outcome IN ('NOT_CHECKED','ACCESS_BLOCKED','DISPATCHED','SUCCEEDED','CHECK_FAILED')"
        ),
        sa.CheckConstraint("requires_approval IN (0,1)"),
        sa.CheckConstraint("revision >= 1"),
    )
    op.create_table(
        "phase4_one_time_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("check_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("token_hmac", sa.String(64), nullable=False),
        sa.Column("binding_hmac", sa.String(64), nullable=False),
        sa.Column("expires_at_us", sa.Integer(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("consumed_at_us", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id", "check_id"],
            [
                "phase4_query_checks.vault_id",
                "phase4_query_checks.profile_id",
                "phase4_query_checks.run_id",
                "phase4_query_checks.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "token_hmac"),
        sa.CheckConstraint("length(token_hmac) = 64 AND token_hmac = lower(token_hmac)"),
        sa.CheckConstraint("length(binding_hmac) = 64 AND binding_hmac = lower(binding_hmac)"),
    )
    op.create_table(
        "phase4_transmission_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("check_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("masked_display", sa.String(512), nullable=False),
        sa.Column("payload_hmac", sa.String(64), nullable=False),
        sa.Column("purpose_code", sa.String(96), nullable=False),
        sa.Column("jurisdiction", sa.String(32), nullable=False),
        sa.Column("access_basis", sa.String(24), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("result_code", sa.String(96), nullable=False),
        sa.Column("attempted_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id", "check_id"],
            [
                "phase4_query_checks.vault_id",
                "phase4_query_checks.profile_id",
                "phase4_query_checks.run_id",
                "phase4_query_checks.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(payload_hmac) = 64 AND payload_hmac = lower(payload_hmac)"),
        sa.UniqueConstraint("vault_id", "profile_id", "run_id", "check_id"),
    )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
