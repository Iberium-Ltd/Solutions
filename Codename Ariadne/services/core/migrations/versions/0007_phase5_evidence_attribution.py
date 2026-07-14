"""Add durable Phase 5 findings, evidence, and attribution persistence.

Revision ID: 0007_phase5_evidence_attribution
Revises: 0006_query_policy_core
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_phase5_evidence_attribution"
down_revision = "0006_query_policy_core"
branch_labels = None
depends_on = None


_POSITIVE_SIGNALS = (
    "'EXACT_EMAIL','RECOVERY_RELATIONSHIP','EXACT_LEGAL_NAME','SAME_UNCOMMON_USERNAME',"
    "'SAME_PHOTOGRAPH','SAME_ORGANISATION','SAME_EDUCATION','SAME_LOCATION','SAME_PROJECT',"
    "'SAME_LINKED_DOMAIN','SAME_WRITING_PROFILE_LINKS','CHRONOLOGICAL_COMPATIBILITY',"
    "'USER_CONFIRMATION','IMMUTABLE_PLATFORM_ID_CONTINUITY'"
)
_NEGATIVE_SIGNALS = (
    "'CONFLICTING_AGE','CONFLICTING_PHOTOGRAPH','INCOMPATIBLE_GEOGRAPHY',"
    "'ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP','DIFFERENT_IMMUTABLE_ACCOUNT_ID',"
    "'CONTRADICTORY_BIOGRAPHY','EXPLICIT_USER_EXCLUSION','USERNAME_RECYCLING_EVIDENCE'"
)


def _immutable(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable_update "
        f"BEFORE UPDATE ON {table} BEGIN "
        "SELECT RAISE(ABORT, 'immutable Phase 5 record'); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable_delete "
        f"BEFORE DELETE ON {table} BEGIN "
        "SELECT RAISE(ABORT, 'immutable Phase 5 record'); END"
    )


def upgrade() -> None:
    op.create_table(
        "phase5_findings",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("provider_label", sa.String(128), nullable=False),
        sa.Column("observed_at_us", sa.Integer(), nullable=False),
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
            "outcome IN ('FOUND','NOT_FOUND','NOT_CHECKED','CHECK_FAILED','ACCESS_BLOCKED',"
            "'AUTH_REQUIRED','RATE_LIMITED','PROVIDER_UNAVAILABLE','AMBIGUOUS',"
            "'MANUAL_REVIEW_REQUIRED','AUTHORITATIVE_ABSENCE')"
        ),
        sa.CheckConstraint("severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')"),
        sa.CheckConstraint(
            "visibility IN ('PUBLICLY_ATTRIBUTABLE','PUBLIC_PSEUDONYMOUS',"
            "'PRIVATELY_LINKABLE','HISTORICAL_RESIDUE','PRIVATE_ONLY','UNKNOWN')"
        ),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 256"),
        sa.CheckConstraint("length(summary) BETWEEN 1 AND 2048"),
        sa.CheckConstraint("length(provider_label) BETWEEN 1 AND 128"),
        sa.CheckConstraint("observed_at_us >= 1 AND created_at_us >= 1 AND updated_at_us >= 1"),
        sa.CheckConstraint("revision = 1"),
    )
    op.create_index(
        "ix_phase5_findings_profile_observed",
        "phase5_findings",
        ["vault_id", "profile_id", "observed_at_us", "id"],
    )

    op.create_table(
        "phase5_evidence_originals",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("captured_at_us", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("redirect_chain_json", sa.Text(), nullable=False),
        sa.Column("masked_query_reference", sa.String(67), nullable=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=True),
        sa.Column("viewport_json", sa.Text(), nullable=True),
        sa.Column("capture_method", sa.String(32), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("encryption_required", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id"],
            ["profiles.vault_id", "profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id"],
            ["phase5_findings.vault_id", "phase5_findings.profile_id", "phase5_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "content_sha256",
            name="uq_phase5_original_content",
        ),
        sa.CheckConstraint("kind IN ('SCREENSHOT','HTML','PDF','RAW_JSON','URL_REFERENCE')"),
        sa.CheckConstraint("length(content) <= 10485760"),
        sa.CheckConstraint(
            "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)"
        ),
        sa.CheckConstraint("captured_at_us >= 1"),
        sa.CheckConstraint("source_url IS NULL OR length(source_url) BETWEEN 1 AND 2048"),
        sa.CheckConstraint("http_status IS NULL OR http_status BETWEEN 100 AND 599"),
        sa.CheckConstraint("http_status IS NULL OR source_url IS NOT NULL"),
        sa.CheckConstraint("json_valid(redirect_chain_json)"),
        sa.CheckConstraint("viewport_json IS NULL OR json_valid(viewport_json)"),
        sa.CheckConstraint("json_valid(metadata_json)"),
        sa.CheckConstraint(
            "capture_method IN "
            "('BROWSER_CAPTURE','HTTP_FETCH','PROVIDER_API','MANUAL_LOCAL_IMPORT')"
        ),
        sa.CheckConstraint("encryption_required = 1"),
        sa.CheckConstraint(
            "(kind = 'URL_REFERENCE' AND length(content) = 0 AND source_url IS NOT NULL "
            "AND viewport_json IS NULL) OR (kind <> 'URL_REFERENCE' AND length(content) > 0)"
        ),
        sa.CheckConstraint("kind <> 'SCREENSHOT' OR viewport_json IS NOT NULL"),
        sa.CheckConstraint(
            "capture_method <> 'MANUAL_LOCAL_IMPORT' OR "
            "(source_url IS NULL AND http_status IS NULL AND redirect_chain_json = '[]')"
        ),
    )
    op.create_index(
        "ix_phase5_evidence_originals_finding",
        "phase5_evidence_originals",
        ["vault_id", "profile_id", "finding_id", "captured_at_us", "id"],
    )

    op.create_table(
        "phase5_finding_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(128), nullable=False),
        sa.Column("linked_at_us", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id"],
            ["phase5_findings.vault_id", "phase5_findings.profile_id", "phase5_findings.id"],
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
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "finding_id", "evidence_artifact_id"),
        sa.CheckConstraint("linked_at_us >= 1"),
    )
    op.create_index(
        "ix_phase5_finding_evidence_artifact",
        "phase5_finding_evidence",
        ["vault_id", "profile_id", "evidence_artifact_id", "finding_id"],
    )

    op.create_table(
        "phase5_evidence_derivatives",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("original_artifact_id", sa.String(128), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at_us", sa.Integer(), nullable=False),
        sa.Column("redaction_policy_version", sa.String(64), nullable=False),
        sa.Column("redaction_summary_code", sa.String(64), nullable=False),
        sa.Column("encryption_required", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "original_artifact_id"],
            [
                "phase5_evidence_originals.vault_id",
                "phase5_evidence_originals.profile_id",
                "phase5_evidence_originals.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "original_artifact_id",
            "content_sha256",
            name="uq_phase5_derivative_content",
        ),
        sa.CheckConstraint("length(content) BETWEEN 1 AND 10485760"),
        sa.CheckConstraint(
            "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)"
        ),
        sa.CheckConstraint("created_at_us >= 1"),
        sa.CheckConstraint("encryption_required = 1"),
    )

    op.create_table(
        "phase5_attribution_assessments",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("weight_profile_version", sa.String(64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence_band", sa.String(16), nullable=False),
        sa.Column("human_review_required", sa.Integer(), nullable=False),
        sa.Column("assessed_at_us", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id"],
            ["phase5_findings.vault_id", "phase5_findings.profile_id", "phase5_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "finding_id", "id"),
        sa.CheckConstraint("score BETWEEN -1000 AND 1000"),
        sa.CheckConstraint("confidence_band IN ('VERY_LOW','LOW','MEDIUM','HIGH','VERY_HIGH')"),
        sa.CheckConstraint("human_review_required = 1"),
        sa.CheckConstraint("assessed_at_us >= 1"),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 = lower(payload_sha256)"
        ),
    )
    op.create_index(
        "ix_phase5_assessments_finding",
        "phase5_attribution_assessments",
        ["vault_id", "profile_id", "finding_id", "assessed_at_us", "id"],
    )

    op.create_table(
        "phase5_attribution_signals",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "assessment_id"],
            [
                "phase5_attribution_assessments.vault_id",
                "phase5_attribution_assessments.profile_id",
                "phase5_attribution_assessments.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "assessment_id", "polarity", "ordinal"),
        sa.UniqueConstraint("vault_id", "profile_id", "assessment_id", "polarity", "signal_type"),
        sa.CheckConstraint("polarity IN ('SUPPORTS','CONTRADICTS')"),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 32"),
        sa.CheckConstraint("weight BETWEEN 0 AND 1000"),
        sa.CheckConstraint(
            f"(polarity = 'SUPPORTS' AND signal_type IN ({_POSITIVE_SIGNALS})) OR "
            f"(polarity = 'CONTRADICTS' AND signal_type IN ({_NEGATIVE_SIGNALS}))"
        ),
    )

    op.create_table(
        "phase5_attribution_signal_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("signal_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "assessment_id", "polarity", "signal_ordinal"],
            [
                "phase5_attribution_signals.vault_id",
                "phase5_attribution_signals.profile_id",
                "phase5_attribution_signals.assessment_id",
                "phase5_attribution_signals.polarity",
                "phase5_attribution_signals.ordinal",
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
            "assessment_id",
            "polarity",
            "signal_ordinal",
            "evidence_ordinal",
        ),
        sa.UniqueConstraint(
            "vault_id",
            "profile_id",
            "assessment_id",
            "polarity",
            "signal_ordinal",
            "evidence_artifact_id",
        ),
        sa.CheckConstraint("evidence_ordinal >= 0 AND evidence_ordinal < 16"),
    )

    op.create_table(
        "phase5_attribution_missing_evidence",
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("potential_weight", sa.Integer(), nullable=False),
        sa.Column("recommended_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "assessment_id"],
            [
                "phase5_attribution_assessments.vault_id",
                "phase5_attribution_assessments.profile_id",
                "phase5_attribution_assessments.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("vault_id", "profile_id", "assessment_id", "signal_type"),
        sa.UniqueConstraint("vault_id", "profile_id", "assessment_id", "recommended_rank"),
        sa.CheckConstraint(f"signal_type IN ({_POSITIVE_SIGNALS})"),
        sa.CheckConstraint("potential_weight BETWEEN 0 AND 1000"),
        sa.CheckConstraint("recommended_rank IS NULL OR recommended_rank BETWEEN 1 AND 5"),
    )

    op.create_table(
        "phase5_attribution_decisions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("vault_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("decided_at_us", sa.Integer(), nullable=False),
        sa.Column("weight_profile_version", sa.String(64), nullable=False),
        sa.Column("supersedes_decision_id", sa.String(128), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id", "assessment_id"],
            [
                "phase5_attribution_assessments.vault_id",
                "phase5_attribution_assessments.profile_id",
                "phase5_attribution_assessments.finding_id",
                "phase5_attribution_assessments.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vault_id", "profile_id", "finding_id", "supersedes_decision_id"],
            [
                "phase5_attribution_decisions.vault_id",
                "phase5_attribution_decisions.profile_id",
                "phase5_attribution_decisions.finding_id",
                "phase5_attribution_decisions.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("vault_id", "profile_id", "finding_id", "id"),
        sa.UniqueConstraint("vault_id", "profile_id", "finding_id", "revision"),
        sa.CheckConstraint(
            "state IN ('CONFIRMED_MATCH','CONFIRMED_NON_MATCH','PROBABLE','POSSIBLE',"
            "'UNRESOLVED','NEEDS_MORE_EVIDENCE')"
        ),
        sa.CheckConstraint("decided_at_us >= 1"),
        sa.CheckConstraint("revision >= 1"),
        sa.CheckConstraint(
            "(revision = 1 AND supersedes_decision_id IS NULL) OR "
            "(revision > 1 AND supersedes_decision_id IS NOT NULL)"
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 = lower(payload_sha256)"
        ),
    )
    op.create_index(
        "ix_phase5_decisions_finding",
        "phase5_attribution_decisions",
        ["vault_id", "profile_id", "finding_id", "revision"],
    )

    op.execute(
        "CREATE TRIGGER trg_phase5_original_id_namespace "
        "BEFORE INSERT ON phase5_evidence_originals WHEN EXISTS ("
        "SELECT 1 FROM phase5_evidence_derivatives WHERE id = NEW.id) BEGIN "
        "SELECT RAISE(ABORT, 'duplicate evidence id'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase5_derivative_id_namespace "
        "BEFORE INSERT ON phase5_evidence_derivatives WHEN EXISTS ("
        "SELECT 1 FROM phase5_evidence_originals WHERE id = NEW.id) BEGIN "
        "SELECT RAISE(ABORT, 'duplicate evidence id'); END"
    )

    for table in (
        "phase5_findings",
        "phase5_evidence_originals",
        "phase5_finding_evidence",
        "phase5_evidence_derivatives",
        "phase5_attribution_assessments",
        "phase5_attribution_signals",
        "phase5_attribution_signal_evidence",
        "phase5_attribution_missing_evidence",
        "phase5_attribution_decisions",
    ):
        _immutable(table)


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
