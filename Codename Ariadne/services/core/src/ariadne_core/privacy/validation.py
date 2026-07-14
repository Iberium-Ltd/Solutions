"""Safe validation helpers that deliberately discard rejected values."""

from __future__ import annotations

from collections.abc import Iterable


def safe_field_path(location: Iterable[object]) -> str:
    """Render only schema field/index locations, never rejected input values."""
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            parts.append(str(item))
        elif isinstance(item, str) and item.isidentifier():
            parts.append(item)
        else:
            parts.append("field")
    return ".".join(parts) or "request"
