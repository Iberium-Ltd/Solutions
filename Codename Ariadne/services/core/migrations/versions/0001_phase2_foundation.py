"""Phase 2 encrypted local foundation.

Revision ID: 0001_phase2_foundation
Revises: None
"""

from __future__ import annotations

from alembic import op

from ariadne_core.infrastructure.db.models import metadata

revision = "0001_phase2_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This explicit list is the foundation boundary, not every table currently
    # present in shared metadata. Later features must remain owned by their own
    # forward migration and cannot appear in a fresh vault accidentally.
    bind = op.get_bind()
    foundation_tables = (
        "vaults",
        "vault_crypto",
        "profiles",
        "settings",
        "idempotency_records",
        "jobs",
        "job_attempts",
        "audit_events",
        "event_stream_sessions",
        "event_outbox",
        "backup_records",
    )
    metadata.create_all(
        bind=bind,
        tables=[metadata.tables[name] for name in foundation_tables],
        checkfirst=True,
    )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
