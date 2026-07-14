from __future__ import annotations

import pytest

from ariadne_core.application.vault import (
    VaultLifecycleError,
    VaultManager,
    VaultSubkeyPurpose,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian


def test_vault_subkey_is_stable_purpose_bound_and_zeroized_after_borrow(tmp_path) -> None:
    custodian = MemoryKeyCustodian()
    manager = VaultManager(tmp_path / "vault", custodian)
    manager.create(display_name="Synthetic fingerprint vault")

    with manager.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as first:
        retained = first
        expected = bytes(first)
        assert len(first) == 32
        assert any(first)
    assert retained == bytearray(32)

    with manager.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as second:
        assert bytes(second) == expected

    with manager.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as active:
        manager.lock()
        assert active == bytearray(32)

    with (
        pytest.raises(VaultLifecycleError, match="locked"),
        manager.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT),
    ):
        pass

    reopened = VaultManager(tmp_path / "vault", custodian)
    reopened.unlock()
    with reopened.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as after_reopen:
        assert bytes(after_reopen) == expected
    reopened.lock()

    other = VaultManager(tmp_path / "other-vault", custodian)
    other.create(display_name="Synthetic isolated fingerprint vault")
    with other.borrow_subkey(VaultSubkeyPurpose.INTAKE_FINGERPRINT) as other_vault_key:
        assert bytes(other_vault_key) != expected
    other.lock()
