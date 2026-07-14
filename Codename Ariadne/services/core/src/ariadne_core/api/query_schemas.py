"""Strict wire contracts for the network-free query-plan vertical."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ariadne_core.api.schemas import ApiModel, _canonical_uuid


class QueryPolicyMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    EU_ONLY = "EU_ONLY"
    CUSTOM = "CUSTOM"


class QueryCheckState(StrEnum):
    PLANNED = "PLANNED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    NOT_CHECKED = "NOT_CHECKED"
    BLOCKED = "BLOCKED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    CHECK_FAILED = "CHECK_FAILED"


class QueryCoverageOutcome(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    CHECK_FAILED = "CHECK_FAILED"


class ProviderCatalogRequest(ApiModel):
    profile_id: str

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")


class QueryProviderSummary(ApiModel):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=96)
    operator: str = Field(min_length=1, max_length=128)
    adapter_mode: str = Field(pattern=r"^(DRY_RUN|MANUAL_LOCAL)$")
    access_basis: str = Field(pattern=r"^LOCAL_ONLY$")
    processing_regions: tuple[str, ...] = Field(max_length=8)
    network_access: bool
    sends_identifiers: bool
    enabled: bool
    retention_known: bool


class ProviderCatalogResult(ApiModel):
    profile_id: str
    providers: tuple[QueryProviderSummary, ...] = Field(min_length=1, max_length=8)
    external_provider_count: int = Field(ge=0, le=8)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")


class QueryPlanRequest(ApiModel):
    profile_id: str
    purpose_code: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[A-Z][A-Z0-9_]{2,95}$",
    )
    provider_ids: list[str] = Field(min_length=1, max_length=2)
    policy_mode: QueryPolicyMode = Field(strict=False)
    allowed_provider_ids: list[str] = Field(default_factory=list, max_length=2)
    allowed_regions: list[str] = Field(default_factory=list, max_length=8)
    maximum_checks: int = Field(ge=1, le=200)
    maximum_checks_per_provider: int = Field(ge=1, le=100)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        return _canonical_uuid(value, label="profile id")

    @field_validator("provider_ids", "allowed_provider_ids")
    @classmethod
    def validate_provider_ids(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("provider ids are duplicated")
        if any(
            not value
            or len(value) > 64
            or not value[0].islower()
            or any(not (char.islower() or char.isdigit() or char in "_-") for char in value)
            for value in values
        ):
            raise ValueError("provider id is invalid")
        return values

    @field_validator("allowed_regions")
    @classmethod
    def validate_regions(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            len(value) != 2 or not value.isascii() or not value.isupper() for value in values
        ):
            raise ValueError("allowed region is invalid")
        return values

    @model_validator(mode="after")
    def validate_budget_and_custom_policy(self) -> QueryPlanRequest:
        if self.maximum_checks_per_provider > self.maximum_checks:
            raise ValueError("provider budget exceeds run budget")
        if self.policy_mode is QueryPolicyMode.CUSTOM and not self.allowed_provider_ids:
            raise ValueError("custom policy requires an explicit provider allowlist")
        if not set(self.allowed_provider_ids) <= set(self.provider_ids):
            raise ValueError("policy provider allowlist exceeds the selected providers")
        return self


class QueryPlanCell(ApiModel):
    check_id: str
    entity_id: str
    provider_id: str
    masked_value: str = Field(min_length=1, max_length=512, repr=False)
    entity_type: str = Field(min_length=1, max_length=32)
    query_class: str = Field(pattern=r"^EXACT$")
    state: QueryCheckState = Field(strict=False)
    outcome: QueryCoverageOutcome = Field(strict=False)
    reason_code: str = Field(min_length=1, max_length=96)
    requires_approval: bool
    revision: int = Field(ge=1)

    @field_validator("check_id", "entity_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))


class QueryPlanResult(ApiModel):
    run_id: str
    profile_id: str
    policy_mode: QueryPolicyMode = Field(strict=False)
    cells: tuple[QueryPlanCell, ...] = Field(max_length=200)
    planned_count: int = Field(ge=0, le=200)
    approval_required_count: int = Field(ge=0, le=200)
    not_checked_count: int = Field(ge=0, le=200)
    blocked_count: int = Field(ge=0, le=200)

    @field_validator("run_id", "profile_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))


class QueryDryRunRequest(ApiModel):
    profile_id: str
    run_id: str
    check_id: str
    expected_revision: int = Field(ge=1)
    approve_once: bool = False

    @field_validator("profile_id", "run_id", "check_id")
    @classmethod
    def validate_ids(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        return _canonical_uuid(value, label=info.field_name.replace("_", " "))
