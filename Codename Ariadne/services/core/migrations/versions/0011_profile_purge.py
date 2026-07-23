"""Permit explicit whole-profile purges without weakening normal immutability.

Revision ID: 0011_profile_purge
Revises: 0010_identity_ai_analysis
"""

from __future__ import annotations

from alembic import op

revision = "0011_profile_purge"
down_revision = "0010_identity_ai_analysis"
branch_labels = None
depends_on = None

_IMMUTABLE_TABLES = (
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
)


def upgrade() -> None:
    """Allow deletes only while the owning profile is explicitly purge-pending."""

    for table in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER trg_{table}_immutable_delete")
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable_delete "
            f"BEFORE DELETE ON {table} "
            "WHEN NOT EXISTS ("
            "SELECT 1 FROM profiles WHERE vault_id = OLD.vault_id "
            "AND id = OLD.profile_id AND status = 'PURGE_PENDING'"
            ") BEGIN "
            "SELECT RAISE(ABORT, 'immutable record outside profile purge'); END"
        )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
