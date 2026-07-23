"""Forward-only migrations over an already authenticated database handle."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine


def migration_config() -> Config:
    """Bind Alembic to the active encrypted database and frozen migration directory."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen_root, str):
        service_root = Path(frozen_root) / "ariadne_core_migrations"
    else:
        service_root = Path(__file__).resolve().parents[4]
    config_path = service_root / "alembic.ini"
    script_path = service_root / "migrations"
    if not config_path.is_file() or not script_path.is_dir():
        raise RuntimeError("the migration assets are unavailable")
    config = Config(str(config_path))
    config.set_main_option("script_location", str(script_path))
    return config


def upgrade_to_head(engine: Engine) -> None:
    # The caller supplies an already keyed and verified SQLCipher engine. Alembic
    # must never open an independent URL that could fall back to plaintext SQLite.
    """Advance an encrypted vault through reviewed forward-only migrations."""

    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def require_current_revision(engine: Engine) -> str:
    """Verify the existing vault is already at the one supported schema head."""

    config = migration_config()
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError("the migration graph has no single supported head")
    expected = heads[0]
    try:
        with engine.connect() as connection:
            revisions = tuple(
                str(row[0])
                for row in connection.execute(text("SELECT version_num FROM alembic_version")).all()
            )
    except Exception as error:
        raise RuntimeError("the vault schema revision is unavailable") from error
    if revisions != (expected,):
        raise RuntimeError("the vault schema revision is unsupported")
    return expected
