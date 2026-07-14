from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select, update

from ariadne_core.application.vault import VaultManager, VaultManifest
from ariadne_core.domain.settings import VaultSettingsPatch
from ariadne_core.infrastructure.db.models import event_outbox
from ariadne_core.infrastructure.db.repositories import (
    EventReplayRepository,
    SettingsRepository,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian


def _event_vault(tmp_path: Path) -> tuple[VaultManager, VaultManifest]:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic event replay vault")
    settings = SettingsRepository(manager.engine)
    settings.update(
        manifest.vault_id,
        VaultSettingsPatch(auto_lock_seconds=600),
        expected_revision=1,
    )
    settings.update(
        manifest.vault_id,
        VaultSettingsPatch(reveal_ttl_seconds=45),
        expected_revision=2,
    )
    settings.update(
        manifest.vault_id,
        VaultSettingsPatch(highly_sensitive_fts=True),
        expected_revision=3,
    )
    return manager, manifest


def test_replay_is_bounded_stable_and_payload_free(tmp_path: Path) -> None:
    manager, manifest = _event_vault(tmp_path)
    repository = EventReplayRepository(manager.engine)

    first = repository.replay(manifest.vault_id, cursor=None, limit=2)
    duplicate = repository.replay(manifest.vault_id, cursor=None, limit=2)
    remaining = repository.replay(
        manifest.vault_id,
        cursor=first.next_cursor,
        limit=2,
    )

    assert first.disposition == "OK"
    assert first.has_more is True
    assert first == duplicate
    assert len(first.events) == 2
    assert len(remaining.events) == 1
    assert remaining.events[0].sequence == first.events[-1].sequence + 1
    assert not hasattr(first.events[0], "payload")
    manager.lock()


def test_gap_and_expired_cursor_require_scoped_refetch(tmp_path: Path) -> None:
    manager, manifest = _event_vault(tmp_path)
    repository = EventReplayRepository(manager.engine)
    initial = repository.replay(manifest.vault_id, cursor=None, limit=1)
    first = initial.events[0]

    with manager.engine.begin() as connection:
        second_id = connection.execute(
            select(event_outbox.c.id).where(event_outbox.c.sequence == first.sequence + 1).limit(1)
        ).scalar_one()
        connection.execute(delete(event_outbox).where(event_outbox.c.id == second_id))

    gap = repository.replay(manifest.vault_id, cursor=first.event_id, limit=8)
    assert gap.disposition == "GAP"
    assert gap.events[0].sequence == first.sequence + 2

    with manager.engine.begin() as connection:
        connection.execute(
            update(event_outbox)
            .where(event_outbox.c.event_id == first.event_id)
            .values(expires_at_us=1)
        )
    expired = repository.replay(
        manifest.vault_id,
        cursor=first.event_id,
        limit=8,
        timestamp_us=2,
    )
    assert expired.disposition == "CURSOR_EXPIRED"
    assert expired.events == ()
    assert expired.next_cursor == gap.events[-1].event_id
    manager.lock()


def test_unknown_additive_variant_is_replayed_as_bounded_metadata(tmp_path: Path) -> None:
    manager, manifest = _event_vault(tmp_path)
    with manager.engine.begin() as connection:
        latest_id = connection.execute(
            select(event_outbox.c.id).order_by(event_outbox.c.sequence.desc()).limit(1)
        ).scalar_one()
        connection.execute(
            update(event_outbox)
            .where(event_outbox.c.id == latest_id)
            .values(event_type="FUTURE_ADDITIVE_VARIANT")
        )

    replay = EventReplayRepository(manager.engine).replay(
        manifest.vault_id,
        cursor=None,
        limit=8,
    )
    assert replay.events[-1].event_type == "FUTURE_ADDITIVE_VARIANT"
    assert len(replay.events[-1].event_type) <= 96
    manager.lock()
