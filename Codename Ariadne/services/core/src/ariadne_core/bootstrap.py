"""Fail-closed parsing for the one-shot sidecar bootstrap channel.

The payload is read once from a bounded private pipe, has a closed schema, and
is discarded after establishing the launch session; it is never accepted via argv.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from typing import BinaryIO, Literal, NoReturn
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

MAX_BOOTSTRAP_BYTES = 4096
SESSION_TOKEN_BYTES = 32
SESSION_TOKEN_LENGTH = 43


class BootstrapRejected(ValueError):
    """Raised without retaining or exposing rejected bootstrap content."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapRejected("bootstrap rejected")
        result[key] = value
    return result


def decode_session_token(value: str) -> bytes:
    """Decode an unpadded base64url token and require exactly 256 bits."""
    if len(value) != SESSION_TOKEN_LENGTH:
        raise BootstrapRejected("bootstrap rejected")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise BootstrapRejected("bootstrap rejected") from error
    if len(decoded) != SESSION_TOKEN_BYTES:
        raise BootstrapRejected("bootstrap rejected")
    return decoded


class BootstrapPayload(BaseModel):
    """The only accepted Rust-to-core startup payload."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    protocol_version: Literal[1]
    contract_version: Literal[1]
    session_token: SecretStr
    parent_pid: int
    startup_nonce: UUID

    @field_validator("session_token")
    @classmethod
    def validate_session_token(cls, value: SecretStr) -> SecretStr:
        decode_session_token(value.get_secret_value())
        return value

    @field_validator("parent_pid")
    @classmethod
    def validate_parent_pid(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("parent pid is invalid")
        return value

    @field_validator("startup_nonce", mode="before")
    @classmethod
    def validate_startup_nonce(cls, value: object) -> UUID:
        if not isinstance(value, str):
            raise ValueError("startup nonce is invalid")
        try:
            parsed = UUID(value)
        except ValueError as error:
            raise ValueError("startup nonce is invalid") from error
        if str(parsed) != value:
            raise ValueError("startup nonce is invalid")
        return parsed


def read_bootstrap(stream: BinaryIO) -> BootstrapPayload:
    """Read exactly one bounded JSON line, suppressing all input details on failure."""
    line = stream.readline(MAX_BOOTSTRAP_BYTES + 1)
    if not line or len(line) > MAX_BOOTSTRAP_BYTES or not line.endswith(b"\n"):
        raise BootstrapRejected("bootstrap rejected")
    if b"\x00" in line:
        raise BootstrapRejected("bootstrap rejected")

    try:
        decoded = line[:-1].decode("utf-8", errors="strict")
        payload = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise BootstrapRejected("bootstrap rejected")
        return BootstrapPayload.model_validate(payload)
    except BootstrapRejected:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as error:
        raise BootstrapRejected("bootstrap rejected") from error


def fail_bootstrap() -> NoReturn:
    """Terminate with a generic message that cannot echo secrets or local paths."""
    raise SystemExit("Ariadne core bootstrap rejected.")
