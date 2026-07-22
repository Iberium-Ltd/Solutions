"""Add durable Phase 6 audit snapshots and remediation history.

Revision ID: 0008_phase6_audit_remediation
Revises: 0007_phase5_evidence_attribution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_phase6_audit_remediation"
down_revision = "0007_phase5_evidence_attribution"
branch_labels = None
depends_on = None

_MAX_TIMESTAMP_US = 9_007_199_254_740_991


def _immutable(table: str) -> None:
    # Comparison correctness depends on historical snapshots and remediation
    # revisions never changing after a later run has referenced them.
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable_update "
        f"BEFORE UPDATE ON {table} BEGIN "
        "SELECT RAISE(ABORT, 'immutable Phase 6 record'); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable_delete "
        f"BEFORE DELETE ON {table} BEGIN "
        "SELECT RAISE(ABORT, 'immutable Phase 6 record'); END"
    )


def upgrade() -> None:
    op.create_table(
        "phase6_audit_snapshots",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("captured_at_us", sa.Integer(), nullable=False),
        sa.Column("run_state", sa.String(16), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "run_id"),
        sa.UniqueConstraint(
            "vault_id", "profile_id", "sequence", name="uq_phase6_audit_snapshot_sequence"
        ),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "captured_at_us",
            name="uq_phase6_audit_snapshot_captured_at",
        ),
        sa.CheckConstraint("sequence >= 1"),
        sa.CheckConstraint(f"captured_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US}"),
        sa.CheckConstraint("run_state IN ('COMPLETED','PARTIAL','CANCELLED','FAILED')"),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 = lower(payload_sha256)"
        ),
    )
    op.create_index(
        "ix_phase6_audit_snapshots_timeline",
        "phase6_audit_snapshots",
        ["vault_id", "profile_id", "sequence", "captured_at_us"],
    )

    op.create_table(
        "phase6_audit_snapshot_findings",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stable_id", sa.String(128), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id"],
            [
                "phase6_audit_snapshots.vault_id",
                "phase6_audit_snapshots.profile_id",
                "phase6_audit_snapshots.run_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "stable_id"],
            ["phase5_findings.vault_id", "phase5_findings.profile_id", "phase5_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "run_id", "stable_id"),
        sa.UniqueConstraint(
            "vault_id", "profile_id", "run_id", "ordinal", name="uq_phase6_audit_finding_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 2000"),
        sa.CheckConstraint(
            "length(content_fingerprint) = 64 AND content_fingerprint = lower(content_fingerprint)"
        ),
    )

    op.create_table(
        "phase6_audit_snapshot_coverage",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("coverage_state", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "run_id"],
            [
                "phase6_audit_snapshots.vault_id",
                "phase6_audit_snapshots.profile_id",
                "phase6_audit_snapshots.run_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "run_id", "provider_id"),
        sa.UniqueConstraint(
            "vault_id", "profile_id", "run_id", "ordinal", name="uq_phase6_audit_coverage_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 256"),
        sa.CheckConstraint("coverage_state IN ('COMPLETE','NOT_CHECKED','BLOCKED','CHECK_FAILED')"),
    )

    op.create_table(
        "phase6_remediation_revisions",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("action_disposition", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("deadline_at_us", sa.Integer(), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("reappearance_count", sa.Integer(), nullable=False),
        sa.Column("last_reappearance_at_us", sa.Integer(), nullable=True),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("updated_at_us", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "previous_revision"],
            [
                "phase6_remediation_revisions.vault_id",
                "phase6_remediation_revisions.profile_id",
                "phase6_remediation_revisions.case_id",
                "phase6_remediation_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "case_id", "revision"),
        sa.CheckConstraint("revision BETWEEN 1 AND 256"),
        sa.CheckConstraint(
            "(revision = 1 AND previous_revision IS NULL) OR "
            "(revision > 1 AND previous_revision = revision - 1)"
        ),
        sa.CheckConstraint(
            "action IN ('MONITOR','PRESERVE_EVIDENCE','DELETE_OWNED_ACCOUNT',"
            "'REQUEST_CORRECTION','DRAFT_ERASURE_OR_DEINDEX','DRAFT_IMPERSONATION_REPORT',"
            "'CONTACT','ESCALATE','MARK_LEGALLY_PERSISTENT')"
        ),
        sa.CheckConstraint(
            "action_disposition IN ('LOCAL_ONLY','DRAFT','REQUIRE_EXPLICIT_APPROVAL')"
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','AWAITING_EXPLICIT_APPROVAL','MONITORING',"
            "'RESOLVED','CLOSED')"
        ),
        sa.CheckConstraint(
            "((action IN ('MONITOR','PRESERVE_EVIDENCE')) AND "
            "action_disposition = 'LOCAL_ONLY') OR "
            "((action NOT IN ('MONITOR','PRESERVE_EVIDENCE')) AND "
            "action_disposition IN ('DRAFT','REQUIRE_EXPLICIT_APPROVAL'))"
        ),
        sa.CheckConstraint(
            "status <> 'AWAITING_EXPLICIT_APPROVAL' OR "
            "action_disposition = 'REQUIRE_EXPLICIT_APPROVAL'"
        ),
        sa.CheckConstraint(
            f"created_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US} AND "
            f"updated_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US} AND "
            "updated_at_us >= created_at_us"
        ),
        sa.CheckConstraint(
            f"deadline_at_us IS NULL OR deadline_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US}"
        ),
        sa.CheckConstraint("deadline_at_us IS NULL OR deadline_at_us > created_at_us"),
        sa.CheckConstraint("draft_text IS NULL OR length(draft_text) BETWEEN 1 AND 10000"),
        sa.CheckConstraint("reappearance_count >= 0"),
        sa.CheckConstraint(
            "(reappearance_count = 0 AND last_reappearance_at_us IS NULL) OR "
            "(reappearance_count > 0 AND last_reappearance_at_us IS NOT NULL)"
        ),
        sa.CheckConstraint(
            f"last_reappearance_at_us IS NULL OR "
            f"last_reappearance_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US}"
        ),
        sa.CheckConstraint(
            "last_reappearance_at_us IS NULL OR last_reappearance_at_us <= updated_at_us"
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 = lower(payload_sha256)"
        ),
    )
    op.create_index(
        "ix_phase6_remediation_latest",
        "phase6_remediation_revisions",
        ["vault_id", "profile_id", "case_id", "revision"],
    )
    op.create_index(
        "ix_phase6_remediation_status",
        "phase6_remediation_revisions",
        ["vault_id", "profile_id", "status", "updated_at_us"],
    )

    op.create_table(
        "phase6_remediation_findings",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision"],
            [
                "phase6_remediation_revisions.vault_id",
                "phase6_remediation_revisions.profile_id",
                "phase6_remediation_revisions.case_id",
                "phase6_remediation_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id"],
            ["phase5_findings.vault_id", "phase5_findings.profile_id", "phase5_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "case_id", "revision", "finding_id"),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "case_id",
            "revision",
            "ordinal",
            name="uq_phase6_remediation_finding_ordinal",
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 64"),
    )

    op.create_table(
        "phase6_remediation_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision"],
            [
                "phase6_remediation_revisions.vault_id",
                "phase6_remediation_revisions.profile_id",
                "phase6_remediation_revisions.case_id",
                "phase6_remediation_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "evidence_artifact_id"],
            [
                "phase5_evidence_originals.vault_id",
                "phase5_evidence_originals.profile_id",
                "phase5_evidence_originals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "vault_id", "profile_id", "case_id", "revision", "evidence_artifact_id"
        ),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "case_id",
            "revision",
            "ordinal",
            name="uq_phase6_remediation_evidence_ordinal",
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 64"),
    )

    op.create_table(
        "phase6_remediation_provider_responses",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("response_code", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("received_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision"],
            [
                "phase6_remediation_revisions.vault_id",
                "phase6_remediation_revisions.profile_id",
                "phase6_remediation_revisions.case_id",
                "phase6_remediation_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "case_id", "revision", "ordinal"),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 32"),
        sa.CheckConstraint("length(response_code) BETWEEN 2 AND 64"),
        sa.CheckConstraint("length(summary) BETWEEN 1 AND 2048"),
        sa.CheckConstraint(f"received_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US}"),
    )

    op.create_table(
        "phase6_remediation_provider_response_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("response_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision", "response_ordinal"],
            [
                "phase6_remediation_provider_responses.vault_id",
                "phase6_remediation_provider_responses.profile_id",
                "phase6_remediation_provider_responses.case_id",
                "phase6_remediation_provider_responses.revision",
                "phase6_remediation_provider_responses.ordinal",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "evidence_artifact_id"],
            [
                "phase5_evidence_originals.vault_id",
                "phase5_evidence_originals.profile_id",
                "phase5_evidence_originals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "vault_id",
            "profile_id",
            "case_id",
            "revision",
            "response_ordinal",
            "evidence_ordinal",
        ),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "case_id",
            "revision",
            "response_ordinal",
            "evidence_artifact_id",
            name="uq_phase6_response_evidence_artifact",
        ),
        sa.CheckConstraint("evidence_ordinal >= 0 AND evidence_ordinal < 64"),
    )

    op.create_table(
        "phase6_remediation_history",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("occurred_at_us", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("current_status", sa.String(32), nullable=False),
        sa.Column("detail_code", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision"],
            [
                "phase6_remediation_revisions.vault_id",
                "phase6_remediation_revisions.profile_id",
                "phase6_remediation_revisions.case_id",
                "phase6_remediation_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "case_id", "revision"),
        sa.CheckConstraint(
            "event_type IN ('CASE_CREATED','DRAFT_UPDATED','APPROVAL_REQUIRED','STATUS_CHANGED',"
            "'DEADLINE_CHANGED','EVIDENCE_LINKED','PROVIDER_RESPONSE_RECORDED',"
            "'REAPPEARANCE_RECORDED')"
        ),
        sa.CheckConstraint(f"occurred_at_us BETWEEN 1 AND {_MAX_TIMESTAMP_US}"),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('OPEN','IN_PROGRESS','AWAITING_EXPLICIT_APPROVAL','MONITORING','RESOLVED','CLOSED')"
        ),
        sa.CheckConstraint(
            "current_status IN ('OPEN','IN_PROGRESS','AWAITING_EXPLICIT_APPROVAL','MONITORING',"
            "'RESOLVED','CLOSED')"
        ),
        sa.CheckConstraint(
            "(revision = 1 AND previous_status IS NULL) OR "
            "(revision > 1 AND previous_status IS NOT NULL)"
        ),
        sa.CheckConstraint("length(detail_code) BETWEEN 2 AND 64"),
        sa.CheckConstraint("note IS NULL OR length(note) BETWEEN 1 AND 1000"),
    )

    op.create_table(
        "phase6_remediation_history_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "case_id", "revision"],
            [
                "phase6_remediation_history.vault_id",
                "phase6_remediation_history.profile_id",
                "phase6_remediation_history.case_id",
                "phase6_remediation_history.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "evidence_artifact_id"],
            [
                "phase5_evidence_originals.vault_id",
                "phase5_evidence_originals.profile_id",
                "phase5_evidence_originals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "vault_id", "profile_id", "case_id", "revision", "evidence_artifact_id"
        ),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "case_id",
            "revision",
            "ordinal",
            name="uq_phase6_history_evidence_ordinal",
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 64"),
    )

    op.execute(
        "CREATE TRIGGER trg_phase6_audit_snapshot_capacity "
        "BEFORE INSERT ON phase6_audit_snapshots WHEN ("
        "SELECT count(*) FROM phase6_audit_snapshots "
        "WHERE vault_id = NEW.vault_id AND profile_id = NEW.profile_id) >= 32 BEGIN "
        "SELECT RAISE(ABORT, 'audit snapshot capacity reached'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase6_audit_snapshot_order "
        "BEFORE INSERT ON phase6_audit_snapshots WHEN EXISTS ("
        "SELECT 1 FROM phase6_audit_snapshots "
        "WHERE vault_id = NEW.vault_id AND profile_id = NEW.profile_id AND "
        "(sequence >= NEW.sequence OR captured_at_us >= NEW.captured_at_us)) BEGIN "
        "SELECT RAISE(ABORT, 'audit snapshot order conflict'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase6_remediation_identity_continuity "
        "BEFORE INSERT ON phase6_remediation_revisions WHEN NEW.revision > 1 AND EXISTS ("
        "SELECT 1 FROM phase6_remediation_revisions previous WHERE "
        "previous.vault_id = NEW.vault_id AND previous.profile_id = NEW.profile_id AND "
        "previous.case_id = NEW.case_id AND previous.revision = NEW.previous_revision AND "
        "(previous.action <> NEW.action OR previous.created_at_us <> NEW.created_at_us)) BEGIN "
        "SELECT RAISE(ABORT, 'remediation identity changed'); END"
    )

    for table in (
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
    ):
        _immutable(table)


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
