"""Add durable source-scoped graph edge evidence.

Revision ID: 0005_graph_edge_origins
Revises: 0004_decision_policy
"""

from __future__ import annotations

from alembic import op

from ariadne_core.infrastructure.db.models import graph_edge_origins

revision = "0005_graph_edge_origins"
down_revision = "0004_decision_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite unique parents let each origin prove that source, segment, and
    # extraction run belong to the same vault/profile before an edge cites them.
    op.create_index(
        "uq_intake_segments_edge_origin_parent",
        "intake_segments",
        ["vault_id", "profile_id", "intake_source_id", "id"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "uq_extraction_runs_edge_origin_parent",
        "extraction_runs",
        ["vault_id", "profile_id", "intake_source_id", "id"],
        unique=True,
        if_not_exists=True,
    )
    graph_edge_origins.create(bind=op.get_bind(), checkfirst=True)
    # Backfill only edges whose endpoints share a provable historical segment.
    # A later guard aborts the migration if any live edge remains unattributed.
    op.execute(
        """
        INSERT INTO graph_edge_origins (
            id, vault_id, profile_id, graph_edge_id, intake_source_id,
            intake_segment_id, extraction_run_id, disposition,
            confidence_micros, visibility, source_span_start, source_span_end,
            observed_at_us, origin_type, explanation, observation_hmac,
            created_at_us
        )
        SELECT
            lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' ||
            '4' || substr(lower(hex(randomblob(2))), 2) || '-' ||
            substr('89ab', abs(random()) % 4 + 1, 1) ||
            substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6))),
            edge.vault_id, edge.profile_id, edge.id, segment.intake_source_id,
            segment.id, source_origin.extraction_run_id, 'SUPPORTS',
            edge.confidence_micros, edge.visibility, NULL, NULL,
            max(source_origin.observed_at_us, target_origin.observed_at_us),
            edge.origin_type, edge.explanation, lower(hex(randomblob(32))),
            edge.created_at_us
        FROM graph_edges AS edge
        JOIN graph_nodes AS source_node
          ON source_node.vault_id = edge.vault_id
         AND source_node.profile_id = edge.profile_id
         AND source_node.id = edge.from_node_id
        JOIN graph_nodes AS target_node
          ON target_node.vault_id = edge.vault_id
         AND target_node.profile_id = edge.profile_id
         AND target_node.id = edge.to_node_id
        JOIN entity_origins AS source_origin
          ON source_origin.vault_id = edge.vault_id
         AND source_origin.profile_id = edge.profile_id
         AND source_origin.entity_id = source_node.entity_id
         AND source_origin.created_at_us = edge.created_at_us
        JOIN entity_origins AS target_origin
          ON target_origin.vault_id = edge.vault_id
         AND target_origin.profile_id = edge.profile_id
         AND target_origin.entity_id = target_node.entity_id
         AND target_origin.extraction_run_id = source_origin.extraction_run_id
         AND target_origin.intake_segment_id = source_origin.intake_segment_id
         AND target_origin.created_at_us = edge.created_at_us
        JOIN intake_segments AS segment
          ON segment.vault_id = edge.vault_id
         AND segment.profile_id = edge.profile_id
         AND segment.id = source_origin.intake_segment_id
        JOIN extraction_runs AS extraction
          ON extraction.vault_id = edge.vault_id
         AND extraction.profile_id = edge.profile_id
         AND extraction.intake_source_id = segment.intake_source_id
         AND extraction.id = source_origin.extraction_run_id
        GROUP BY edge.vault_id, edge.profile_id, edge.id, segment.intake_source_id,
                 segment.id, source_origin.extraction_run_id
        """
    )
    unbackfilled = (
        op.get_bind()
        .exec_driver_sql(
            """
        SELECT count(*)
        FROM graph_edges AS edge
        WHERE edge.deleted_at_us IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM graph_edge_origins AS origin
              WHERE origin.vault_id = edge.vault_id
                AND origin.profile_id = edge.profile_id
                AND origin.graph_edge_id = edge.id
          )
        """
        )
        .scalar_one()
    )
    if int(unbackfilled) != 0:
        raise RuntimeError(
            "graph edge provenance cannot be verified; restore the prior build and review the vault"
        )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
