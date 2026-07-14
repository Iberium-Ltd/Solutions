from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from uuid6 import uuid7

from ariadne_core.api.schemas import VaultCreateRequest, VaultUnlockRequest


def _reference() -> str:
    return f"kc:v1:{uuid4()}"


def _create_payload() -> dict[str, object]:
    return {
        "displayName": "Synthetic local vault",
        "transactionId": str(uuid4()),
        "vaultId": str(uuid7()),
        "manifestDigest": "ab" * 32,
        "databaseKeyRef": _reference(),
        "backupKeyRef": _reference(),
        "formatVersion": 1,
        "databaseKeyVersion": 1,
    }


def test_create_context_is_strict_canonical_and_secret_free() -> None:
    request = VaultCreateRequest.model_validate(_create_payload())

    assert request.manifest_digest == "ab" * 32
    assert request.database_key_ref != request.backup_key_ref
    assert set(request.model_dump(by_alias=True)) == {
        "displayName",
        "transactionId",
        "vaultId",
        "manifestDigest",
        "databaseKeyRef",
        "backupKeyRef",
        "formatVersion",
        "databaseKeyVersion",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifestDigest", "AB" * 32),
        ("manifestDigest", "ab" * 31),
        ("transactionId", str(uuid7())),
        ("databaseKeyRef", "kc:v1:not-a-uuid"),
        ("formatVersion", 2),
        ("databaseKeyVersion", True),
    ],
)
def test_create_context_rejects_noncanonical_fields(field: str, value: object) -> None:
    payload = _create_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        VaultCreateRequest.model_validate(payload)


def test_create_context_requires_distinct_key_references() -> None:
    payload = _create_payload()
    payload["backupKeyRef"] = payload["databaseKeyRef"]

    with pytest.raises(ValidationError):
        VaultCreateRequest.model_validate(payload)


def test_unlock_context_accepts_only_the_manifest_bound_database_reference() -> None:
    payload = _create_payload()
    request = VaultUnlockRequest.model_validate(
        {
            "transactionId": payload["transactionId"],
            "vaultId": payload["vaultId"],
            "manifestDigest": payload["manifestDigest"],
            "databaseKeyRef": payload["databaseKeyRef"],
            "databaseKeyVersion": 1,
        }
    )

    assert request.transaction_id == payload["transactionId"]
    assert request.database_key_ref == payload["databaseKeyRef"]
