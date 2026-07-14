"""Alembic environment that accepts an already-keyed SQLCipher connection."""

from __future__ import annotations

from alembic import context

from ariadne_core.infrastructure.db.models import metadata


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("migrations require an already-keyed SQLCipher connection")
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
