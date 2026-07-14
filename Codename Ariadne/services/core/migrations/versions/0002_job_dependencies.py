"""Add the bounded durable-job dependency DAG.

Revision ID: 0002_job_dependencies
Revises: 0001_phase2_foundation
"""

from __future__ import annotations

from alembic import op

from ariadne_core.infrastructure.db.models import job_dependencies

revision = "0002_job_dependencies"
down_revision = "0001_phase2_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    job_dependencies.create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
