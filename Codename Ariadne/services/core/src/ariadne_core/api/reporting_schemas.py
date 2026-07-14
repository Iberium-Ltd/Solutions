"""Strict wire contracts for bounded, in-memory local report generation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel, _canonical_uuid
from ariadne_core.application.import_export import ExportMode
from ariadne_core.domain.reporting import MAX_REPORT_BYTES

MAX_REPORT_API_REQUEST_BYTES = 1_024
MAX_REPORT_API_RESPONSE_BYTES = 1_000_000


class ReportArtifactFormat(StrEnum):
    JSON = "JSON"
    MARKDOWN = "MARKDOWN"


class ReportGenerateRequest(ApiModel):
    profile_id: str
    baseline_run_id: str
    current_run_id: str
    artifact_format: ReportArtifactFormat = Field(strict=False)
    mode: ExportMode = Field(strict=False)
    full_export_approval_id: str | None = None

    @field_validator(
        "profile_id",
        "baseline_run_id",
        "current_run_id",
        "full_export_approval_id",
    )
    @classmethod
    def validate_ids(cls, value: str | None, info) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_selection_and_approval(self) -> ReportGenerateRequest:
        if self.baseline_run_id == self.current_run_id:
            raise ValueError("report comparison runs must differ")
        if self.mode is ExportMode.FULL_EXPLICIT:
            if self.full_export_approval_id is None:
                raise ValueError("full report requires explicit manifest-bound approval")
        elif self.full_export_approval_id is not None:
            raise ValueError("redacted report cannot consume a full-export approval")
        return self


class ReportArtifactDescriptorResult(ApiModel):
    filename: str = Field(pattern=r"^report\.(json|md)$")
    media_type: str = Field(
        pattern=r"^(application/json|text/markdown; charset=utf-8)$",
    )
    byte_count: int = Field(ge=1, le=MAX_REPORT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportManifestResult(ApiModel):
    schema_: Literal["ariadne.local-report"] = Field(alias="schema")
    version: Literal[1]
    mode: ExportMode = Field(strict=False)
    generated_at_us: int = Field(ge=1, le=9_007_199_254_740_991)
    full_export_approval_id: str | None
    artifacts: tuple[ReportArtifactDescriptorResult, ...] = Field(min_length=2, max_length=2)

    @field_validator("full_export_approval_id")
    @classmethod
    def validate_approval_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_uuid(value, label="full export approval id")

    @model_validator(mode="after")
    def validate_approval_binding(self) -> ReportManifestResult:
        if self.mode is ExportMode.FULL_EXPLICIT:
            if self.full_export_approval_id is None:
                raise ValueError("full report manifest requires explicit approval")
        elif self.full_export_approval_id is not None:
            raise ValueError("redacted report manifest cannot contain full approval")
        if {item.filename for item in self.artifacts} != {"report.json", "report.md"}:
            raise ValueError("report manifest artifact set is invalid")
        return self


class ReportArtifactResult(ReportArtifactDescriptorResult):
    schema_: Literal["ariadne.local-report"] = Field(alias="schema")
    version: Literal[1]
    mode: ExportMode = Field(strict=False)
    content: str = Field(min_length=1, max_length=MAX_REPORT_BYTES, repr=False)


class ReportGenerateResult(ApiModel):
    profile_id: str
    baseline_run_id: str
    current_run_id: str
    local_only: Literal[True]
    artifact: ReportArtifactResult
    manifest: ReportManifestResult

    @field_validator("profile_id", "baseline_run_id", "current_run_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))

    @model_validator(mode="after")
    def validate_artifact_manifest_binding(self) -> ReportGenerateResult:
        if self.baseline_run_id == self.current_run_id:
            raise ValueError("report comparison runs must differ")
        if self.artifact.mode is not self.manifest.mode:
            raise ValueError("report artifact mode is inconsistent")
        descriptor = next(
            (item for item in self.manifest.artifacts if item.filename == self.artifact.filename),
            None,
        )
        if descriptor is None or (
            descriptor.media_type != self.artifact.media_type
            or descriptor.byte_count != self.artifact.byte_count
            or descriptor.sha256 != self.artifact.sha256
        ):
            raise ValueError("report artifact manifest descriptor is inconsistent")
        return self
