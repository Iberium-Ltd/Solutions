from __future__ import annotations

from ariadne_core.application.auto_lock import AutoLockController


def test_auto_lock_resets_on_activity_and_locks_on_deadline() -> None:
    now = [100.0]
    calls: list[str] = []
    controller = AutoLockController(
        timeout_seconds=30,
        lock=lambda: calls.append("lock"),
        clock=lambda: now[0],
    )
    controller.arm()
    now[0] = 120.0
    controller.record_local_activity()
    now[0] = 140.0
    assert controller.check() is False
    now[0] = 151.0
    assert controller.check() is True
    assert calls == ["lock"]
    assert controller.check() is False


def test_system_sleep_obeys_policy() -> None:
    calls: list[str] = []
    controller = AutoLockController(timeout_seconds=30, lock=lambda: calls.append("lock"))
    controller.arm()
    assert controller.on_system_sleep() is True
    assert calls == ["lock"]
