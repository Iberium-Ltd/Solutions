"""Harden entity decision history and policy invariants.

Revision ID: 0004_decision_policy
Revises: 0003_intake_identity_graph
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_decision_policy"
down_revision = "0003_intake_identity_graph"
branch_labels = None
depends_on = None

_AUDIT_COLUMNS = (
    ("before_sensitivity", 24),
    ("after_sensitivity", 24),
    ("before_temporal_state", 16),
    ("after_temporal_state", 16),
    ("before_search_policy", 24),
    ("after_search_policy", 24),
    ("before_transmission_policy", 24),
    ("after_transmission_policy", 24),
)

_ENTITY_POLICY_INVALID = """
    (NEW.review_state IN ('FALSE_POSITIVE','EXCLUDED') AND
        (NEW.search_policy <> 'SEARCH_DENIED' OR
         NEW.transmission_policy <> 'TRANSMISSION_DENIED'))
    OR
    (NEW.sensitivity = 'HIGHLY_SENSITIVE' AND
        (NEW.search_policy = 'SEARCH_ALLOWED' OR
         NEW.transmission_policy = 'PROVIDER_ALLOWLIST'))
"""

_DECISION_POLICY_INVALID = """
    NEW.before_review_state IS NULL OR
    NEW.before_review_state NOT IN
        ('UNREVIEWED','CONFIRMED','PROBABLE','POSSIBLE','FALSE_POSITIVE','EXCLUDED')
    OR NEW.after_review_state IS NULL OR
    NEW.after_review_state NOT IN
        ('UNREVIEWED','CONFIRMED','PROBABLE','POSSIBLE','FALSE_POSITIVE','EXCLUDED')
    OR NEW.before_sensitivity IS NULL OR
    NEW.before_sensitivity NOT IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')
    OR NEW.after_sensitivity IS NULL OR
    NEW.after_sensitivity NOT IN ('PUBLIC','SENSITIVE','HIGHLY_SENSITIVE')
    OR NEW.before_temporal_state IS NULL OR
    NEW.before_temporal_state NOT IN ('CURRENT','HISTORICAL','UNKNOWN')
    OR NEW.after_temporal_state IS NULL OR
    NEW.after_temporal_state NOT IN ('CURRENT','HISTORICAL','UNKNOWN')
    OR NEW.before_search_policy IS NULL OR
    NEW.before_search_policy NOT IN
        ('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED')
    OR NEW.after_search_policy IS NULL OR
    NEW.after_search_policy NOT IN
        ('SEARCH_ALLOWED','APPROVAL_REQUIRED','STORE_ONLY','SEARCH_DENIED')
    OR NEW.before_transmission_policy IS NULL OR
    NEW.before_transmission_policy NOT IN
        ('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED')
    OR NEW.after_transmission_policy IS NULL OR
    NEW.after_transmission_policy NOT IN
        ('LOCAL_ONLY','APPROVAL_REQUIRED','PROVIDER_ALLOWLIST','TRANSMISSION_DENIED')
    OR
    (NEW.before_review_state IN ('FALSE_POSITIVE','EXCLUDED') AND
        (NEW.before_search_policy <> 'SEARCH_DENIED' OR
         NEW.before_transmission_policy <> 'TRANSMISSION_DENIED'))
    OR
    (NEW.after_review_state IN ('FALSE_POSITIVE','EXCLUDED') AND
        (NEW.after_search_policy <> 'SEARCH_DENIED' OR
         NEW.after_transmission_policy <> 'TRANSMISSION_DENIED'))
    OR
    (NEW.before_sensitivity = 'HIGHLY_SENSITIVE' AND
        (NEW.before_search_policy = 'SEARCH_ALLOWED' OR
         NEW.before_transmission_policy = 'PROVIDER_ALLOWLIST'))
    OR
    (NEW.after_sensitivity = 'HIGHLY_SENSITIVE' AND
        (NEW.after_search_policy = 'SEARCH_ALLOWED' OR
         NEW.after_transmission_policy = 'PROVIDER_ALLOWLIST'))
"""


def _create_policy_trigger(*, name: str, timing: str, table: str, invalid: str) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER IF NOT EXISTS {name}
            BEFORE {timing} ON {table}
            FOR EACH ROW
            WHEN {invalid}
            BEGIN
                SELECT RAISE(ABORT, 'invalid entity policy');
            END
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    known_columns = {
        str(column["name"]) for column in sa.inspect(bind).get_columns("entity_decisions")
    }
    for name, length in _AUDIT_COLUMNS:
        if name in known_columns:
            continue
        op.add_column(
            "entity_decisions",
            sa.Column(
                name,
                sa.String(length),
                nullable=True,
            ),
        )

    for timing in ("INSERT", "UPDATE"):
        suffix = timing.lower()
        _create_policy_trigger(
            name=f"trg_entities_policy_{suffix}",
            timing=timing,
            table="entities",
            invalid=_ENTITY_POLICY_INVALID,
        )
        _create_policy_trigger(
            name=f"trg_entity_decisions_policy_{suffix}",
            timing=timing,
            table="entity_decisions",
            invalid=_DECISION_POLICY_INVALID,
        )


def downgrade() -> None:
    raise RuntimeError("release migrations are forward-only")
