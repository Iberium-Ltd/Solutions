"""Typed import/export plans backed by shell-issued file capabilities.

Plans carry opaque, operation-scoped grants rather than paths. Possessing a
plan does not widen its capability or bypass native save/open mediation.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportMediaType(StrEnum):
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"
    CSV = "text/csv"
    JSON = "application/json"
    VCARD = "text/vcard"


class ImportScaffold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_broker_token: str = Field(min_length=32, max_length=256)
    declared_media_type: ImportMediaType
    expected_size_bytes: int = Field(ge=1, le=25 * 1024 * 1024)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: UUID | None = None


class ExportMode(StrEnum):
    REDACTED = "REDACTED"
    FULL_EXPLICIT = "FULL_EXPLICIT"


class ExportScaffold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_broker_token: str = Field(min_length=32, max_length=256)
    mode: ExportMode = ExportMode.REDACTED
    resource_ids: list[UUID] = Field(min_length=1, max_length=500)
    full_export_approval_id: UUID | None = None

    @model_validator(mode="after")
    def full_export_requires_manifest_bound_approval(self) -> ExportScaffold:
        if self.mode is ExportMode.FULL_EXPLICIT and not self.full_export_approval_id:
            raise ValueError("full export requires explicit manifest-bound approval")
        if self.mode is ExportMode.REDACTED and self.full_export_approval_id is not None:
            raise ValueError("redacted export does not consume a full-export approval")
        return self
