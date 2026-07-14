from __future__ import annotations

import base64
import time
from uuid import uuid4

from pydantic import SecretStr

from ariadne_core.security.sessions import LaunchSession


def _raw_token(seed: int) -> bytes:
    return bytes((seed + index) % 256 for index in range(32))


def _token(seed: int) -> str:
    return base64.urlsafe_b64encode(_raw_token(seed)).rstrip(b"=").decode()


def test_stores_digest_and_authenticates_in_constant_shape() -> None:
    token = _token(7)
    session = LaunchSession.from_secret(SecretStr(token), ttl_seconds=None)

    assert session.authenticate(token)
    assert not session.authenticate(_token(8))
    assert not session.authenticate(None)
    assert token not in repr(session)
    assert not hasattr(session, "session_token")


def test_expiry_fails_closed() -> None:
    token = _token(4)
    session = LaunchSession.from_secret(SecretStr(token), ttl_seconds=0.001)
    time.sleep(0.01)

    assert session.is_expired()
    assert not session.authenticate(token)


def test_replay_cache_is_canonical_and_bounded() -> None:
    session = LaunchSession.from_token_bytes(
        _raw_token(1),
        ttl_seconds=None,
        replay_capacity=2,
        replay_ttl_seconds=60,
    )
    first = str(uuid4())
    second = str(uuid4())
    third = str(uuid4())

    assert session.accept_request_id(first)
    assert not session.accept_request_id(first)
    assert not session.accept_request_id(first.upper())
    assert session.accept_request_id(second)
    assert session.accept_request_id(third)
    assert session.replay_size == 2
    assert session.accept_request_id(first)
