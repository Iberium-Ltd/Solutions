"""Persist source-grounded AI analysis for identity audit runs.

Revision ID: 0010_identity_ai_analysis
Revises: 0009_identity_discovery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_identity_ai_analysis"
down_revision = "0009_identity_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add one immutable analysis plus proposal-to-entity provenance."""

    op.create_table(
        "identity_ai_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result_code", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(256), nullable=True),
        sa.Column("engine_version", sa.String(64), nullable=True),
        sa.Column("analysis_json", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "audit_id"),
        sa.CheckConstraint("status IN ('SUCCEEDED','FALLBACK','FAILED','EMPTY')"),
        sa.CheckConstraint("json_valid(analysis_json)"),
    )
    op.create_table(
        "identity_entity_origins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("audit_id", sa.String(36), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["identity_proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "proposal_id", "entity_id"),
    )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
