from __future__ import annotations

import base64
import io
import json
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ariadne_core.bootstrap import (
    MAX_BOOTSTRAP_BYTES,
    BootstrapRejected,
    decode_session_token,
    read_bootstrap,
)


def _token() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()


def _line(**changes: object) -> bytes:
    payload: dict[str, object] = {
        "protocol_version": 1,
        "contract_version": 1,
        "session_token": _token(),
        "parent_pid": 42,
        "startup_nonce": str(uuid4()),
    }
    payload.update(changes)
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def test_reads_exact_bounded_bootstrap_and_masks_token() -> None:
    payload = read_bootstrap(io.BytesIO(_line()))

    assert payload.protocol_version == 1
    assert payload.contract_version == 1
    assert isinstance(payload.session_token, SecretStr)
    assert _token() not in repr(payload)
    assert decode_session_token(payload.session_token.get_secret_value()) == bytes(range(32))


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{}",
        b"{not-json}\n",
        b'[{"protocol_version":1}]\n',
        b'{"protocol_version":1,"protocol_version":1}\n',
        b"x" * MAX_BOOTSTRAP_BYTES + b"\n",
        _line(session_token="short"),
        _line(unexpected=True),
        _line(parent_pid=0),
    ],
)
def test_rejects_malformed_bootstrap_without_echo(content: bytes) -> None:
    with pytest.raises(BootstrapRejected) as captured:
        read_bootstrap(io.BytesIO(content))

    assert str(captured.value) == "bootstrap rejected"
    assert _token() not in str(captured.value)


def test_rejects_noncanonical_token_encoding() -> None:
    with pytest.raises(BootstrapRejected):
        decode_session_token("A" * 42 + "=")
