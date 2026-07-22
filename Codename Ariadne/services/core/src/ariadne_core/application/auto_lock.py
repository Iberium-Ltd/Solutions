"""Deterministic auto-lock policy; the shell owns sleep/background notifications.

This controller decides when to lock from monotonic activity timestamps; the
native shell performs key revocation and platform event integration.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class AutoLockController:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        lock: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
        lock_on_sleep: bool = True,
    ) -> None:
        if timeout_seconds < 30 or timeout_seconds > 86_400:
            raise ValueError("auto-lock timeout is outside the allowed range")
        self.timeout_seconds = timeout_seconds
        self.lock_on_sleep = lock_on_sleep
        self._lock = lock
        self._clock = clock
        self._deadline: float | None = None

    def arm(self) -> None:
        self._deadline = self._clock() + self.timeout_seconds

    def record_local_activity(self) -> None:
        if self._deadline is not None:
            self.arm()

    def on_system_sleep(self) -> bool:
        if not self.lock_on_sleep or self._deadline is None:
            return False
        self._lock_now()
        return True

    def check(self) -> bool:
        if self._deadline is None or self._clock() < self._deadline:
            return False
        self._lock_now()
        return True

    def disarm(self) -> None:
        self._deadline = None

    def _lock_now(self) -> None:
        self._deadline = None
        self._lock()
