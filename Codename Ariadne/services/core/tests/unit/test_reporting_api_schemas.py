from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ariadne_core.api.reporting_schemas import ReportGenerateRequest
from ariadne_core.application.import_export import ExportMode


def _request(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "profileId": str(uuid4()),
        "baselineRunId": str(uuid4()),
        "currentRunId": str(uuid4()),
        "artifactFormat": "JSON",
        "mode": "REDACTED",
        "fullExportApprovalId": None,
    }
    body.update(changes)
    return body


def test_report_request_schema_has_exact_camel_case_contract() -> None:
    body = _request()
    parsed = ReportGenerateRequest.model_validate(body)

    assert parsed.mode is ExportMode.REDACTED
    assert parsed.model_dump(mode="json", by_alias=True) == body


def test_report_request_binds_full_mode_to_one_canonical_approval_uuid() -> None:
    approval_id = str(uuid4())
    full = ReportGenerateRequest.model_validate(
        _request(mode="FULL_EXPLICIT", fullExportApprovalId=approval_id)
    )
    assert full.full_export_approval_id == approval_id

    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(_request(mode="FULL_EXPLICIT"))
    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(
            _request(fullExportApprovalId=approval_id),
        )
    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(
            _request(fullExportApprovalId="not-a-canonical-uuid"),
        )


def test_report_request_rejects_same_run_unknown_fields_and_unbounded_values() -> None:
    run_id = str(uuid4())
    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(
            _request(baselineRunId=run_id, currentRunId=run_id),
        )
    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(_request(unexpected=True))
    with pytest.raises(ValidationError):
        ReportGenerateRequest.model_validate(_request(artifactFormat="PDF"))
