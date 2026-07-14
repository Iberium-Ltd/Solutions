"""Closed structured-log shapes that cannot accept request content or secrets."""

from __future__ import annotations

from typing import Literal, TypedDict

import structlog


class RequestLogFields(TypedDict):
    request_id: str
    route_template: str
    status: int
    latency_ms: int
    payload_bytes: int
    actor_class: Literal["SHELL", "UNKNOWN"]


def log_request(*, logger: structlog.stdlib.BoundLogger, fields: RequestLogFields) -> None:
    """Emit only the reviewed request metadata shape."""
    logger.info("local_api_request", **fields)
