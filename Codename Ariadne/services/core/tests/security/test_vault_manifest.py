from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from uuid6 import uuid7

from ariadne_core.application.vault import (
    DATABASE_KEY_VERSION,
    VAULT_FORMAT_VERSION,
    VaultLifecycleError,
    VaultManager,
    VaultManifest,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian


def _reference() -> str:
    return f"kc:v1:{uuid4()}"


def _manifest() -> VaultManifest:
    return VaultManifest(
        vault_id=str(uuid7()),
        format_version=VAULT_FORMAT_VERSION,
        database_key_ref=_reference(),
        backup_key_ref=_reference(),
        database_key_version=DATABASE_KEY_VERSION,
    )


def test_manifest_is_canonical_bound_and_uses_opaque_key_references(tmp_path) -> None:
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic manifest vault")
    manager.lock()

    encoded = (tmp_path / "vault" / "vault.json").read_bytes()
    assert encoded == manifest.to_json()
    assert len(manifest.digest()) == 32
    assert manifest.database_key_ref.startswith("kc:v1:")
    assert manifest.backup_key_ref.startswith("kc:v1:")
    assert manifest.database_key_ref != manifest.backup_key_ref
    assert VaultManifest.from_path(tmp_path / "vault" / "vault.json") == manifest


def test_manifest_rejects_noncanonical_content_and_unsafe_metadata(tmp_path) -> None:
    path = tmp_path / "vault.json"
    manifest = _manifest()
    noncanonical = json.dumps(json.loads(manifest.to_json()), indent=2).encode()
    path.write_bytes(noncanonical)
    path.chmod(0o600)

    with pytest.raises(VaultLifecycleError, match="manifest is invalid"):
        VaultManifest.from_path(path)

    path.write_bytes(manifest.to_json())
    path.chmod(0o644)
    with pytest.raises(VaultLifecycleError, match="manifest is invalid"):
        VaultManifest.from_path(path)

    path.chmod(0o600)
    link = tmp_path / "manifest-link.json"
    link.symlink_to(path)
    with pytest.raises(VaultLifecycleError, match="manifest is invalid"):
        VaultManifest.from_path(link)

    assert os.stat(path).st_uid == os.getuid()


@pytest.mark.parametrize(
    "changes",
    [
        {"database_key_ref": "not-a-key-reference"},
        {"database_key_ref": "kc:v1:00000000-0000-0000-0000-000000000000"},
        {"database_key_version": True},
        {"format_version": 2},
    ],
)
def test_manifest_rejects_invalid_binding_fields(changes: dict[str, object]) -> None:
    manifest = _manifest()
    values: dict[str, object] = {
        "vault_id": manifest.vault_id,
        "format_version": manifest.format_version,
        "database_key_ref": manifest.database_key_ref,
        "backup_key_ref": manifest.backup_key_ref,
        "database_key_version": manifest.database_key_version,
    }
    values.update(changes)

    with pytest.raises(VaultLifecycleError):
        VaultManifest(**values)  # type: ignore[arg-type]
