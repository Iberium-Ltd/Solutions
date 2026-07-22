"""Add the bounded durable-job dependency DAG.

Dependencies are durable scheduling facts: a worker may claim a job only after
all prerequisite rows reach their required terminal state.

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
    """Install dependency storage after the job table created by revision 0001."""

    job_dependencies.create(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
