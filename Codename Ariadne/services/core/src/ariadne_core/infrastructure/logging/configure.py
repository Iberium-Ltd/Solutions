"""Configure JSON logs on stderr without request bodies or secrets."""

from __future__ import annotations

import io
import sys
from typing import TextIO, cast

import structlog


class _DynamicStderr(io.TextIOBase):
    """Delegate writes to the active stderr so test capture cannot leave a closed handle."""

    def write(self, value: str) -> int:
        return sys.stderr.write(value)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _DynamicStderr())),
        cache_logger_on_first_use=False,
    )
