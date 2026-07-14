from __future__ import annotations

import pytest

from ariadne_core.application.import_export import (
    ExportMode,
    ExportScaffold,
    ImportMediaType,
    ImportScaffold,
)


def test_import_requires_broker_token_and_bounded_typed_metadata() -> None:
    plan = ImportScaffold(
        file_broker_token="t" * 43,
        declared_media_type=ImportMediaType.JSON,
        expected_size_bytes=128,
        expected_sha256="a" * 64,
    )
    assert not hasattr(plan, "path")
    with pytest.raises(ValueError):
        ImportScaffold.model_validate(
            {
                **plan.model_dump(),
                "path": "/tmp/not-accepted",
            }
        )


def test_export_is_redacted_by_default_and_full_requires_approval() -> None:
    resource_id = "01900000-0000-7000-8000-000000000001"
    plan = ExportScaffold(file_broker_token="t" * 43, resource_ids=[resource_id])
    assert plan.mode is ExportMode.REDACTED
    with pytest.raises(ValueError):
        ExportScaffold(
            file_broker_token="t" * 43,
            resource_ids=[resource_id],
            mode=ExportMode.FULL_EXPLICIT,
        )
