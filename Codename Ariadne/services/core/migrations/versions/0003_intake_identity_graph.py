"""Add profile-scoped intake, identity provenance, review, and graph storage.

Revision ID: 0003_intake_identity_graph
Revises: 0002_job_dependencies
"""

from __future__ import annotations

from alembic import op

from ariadne_core.infrastructure.db.models import (
    entities,
    entity_decisions,
    entity_origins,
    entity_variant_decisions,
    entity_variants,
    extraction_runs,
    graph_edge_decisions,
    graph_edges,
    graph_nodes,
    intake_segments,
    intake_sources,
    quarantine_items,
)

revision = "0003_intake_identity_graph"
down_revision = "0002_job_dependencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (
        intake_sources,
        intake_segments,
        quarantine_items,
        extraction_runs,
        entities,
        entity_variants,
        entity_variant_decisions,
        entity_origins,
        entity_decisions,
        graph_nodes,
        graph_edges,
        graph_edge_decisions,
    ):
        table.create(bind=bind, checkfirst=False)


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
