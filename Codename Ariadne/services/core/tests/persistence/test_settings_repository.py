from __future__ import annotations

import json

import pytest
from sqlalchemy import and_, insert, select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.settings import TransmissionMode, VaultSettings, VaultSettingsPatch
from ariadne_core.infrastructure.db.models import audit_events, event_outbox, settings
from ariadne_core.infrastructure.db.repositories import RevisionConflict, SettingsRepository
from ariadne_core.security.key_custody import MemoryKeyCustodian


def test_settings_update_is_revisioned_and_emits_redacted_atomic_records(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic settings vault")
    repository = SettingsRepository(manager.engine)

    initial = repository.get(manifest.vault_id)
    assert initial.revision == 1
    assert initial.values.transmission_mode is TransmissionMode.LOCAL_ONLY
    assert initial.values.telemetry_enabled is False

    changed = repository.update(
        manifest.vault_id,
        VaultSettingsPatch(auto_lock_seconds=600),
        expected_revision=1,
    )
    assert changed.revision == 2
    assert changed.values.auto_lock_seconds == 600

    with pytest.raises(RevisionConflict):
        repository.update(
            manifest.vault_id,
            VaultSettingsPatch(reveal_ttl_seconds=45),
            expected_revision=1,
        )

    with manager.engine.connect() as connection:
        event = connection.execute(
            select(event_outbox.c.payload_json).where(
                and_(
                    event_outbox.c.vault_id == manifest.vault_id,
                    event_outbox.c.event_type == "SETTINGS_UPDATED",
                )
            )
        ).scalar_one()
        audit_count = connection.execute(
            select(audit_events.c.id).where(audit_events.c.event_type == "SETTINGS_UPDATED")
        ).all()
    assert json.loads(event) == {"changedKeys": ["auto_lock_seconds"]}
    assert "600" not in event
    assert len(audit_count) == 1
    manager.lock()


def test_privacy_invariants_cannot_be_disabled() -> None:
    with pytest.raises(ValueError):
        VaultSettingsPatch(telemetry_enabled=True).apply(VaultSettings())


def test_vault_wide_setting_partial_unique_index_enforces_null_scope(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic unique-setting vault")
    with pytest.raises(IntegrityError), manager.engine.begin() as connection:
        connection.execute(
            insert(settings).values(
                id=str(uuid7()),
                vault_id=manifest.vault_id,
                profile_id=None,
                setting_key="auto_lock_seconds",
                value_json="900",
                schema_version=1,
                source="USER",
                created_at_us=1,
                updated_at_us=1,
                revision=1,
            )
        )
    manager.lock()
