"""Wire schemas for deterministic, non-executing investigation plans."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator

from ariadne_core.api.schemas import ApiModel
from ariadne_core.domain.investigation_plan import (
    HARD_MAX_INVESTIGATION_IDENTIFIERS,
    HARD_MAX_INVESTIGATION_STEPS,
    MAX_INVESTIGATION_IDENTIFIER_VALUE_BYTES,
    InvestigationIdentifier,
    InvestigationIdentifierKind,
    InvestigationNotice,
    InvestigationOperation,
    InvestigationPlan,
    InvestigationPlanRequest,
    InvestigationPrerequisite,
    InvestigationProvider,
    InvestigationTransmission,
    normalise_investigation_identifier,
)


class InvestigationIdentifierInput(ApiModel):
    identifier_ref: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )
    kind: InvestigationIdentifierKind = Field(strict=False)
    value: str = Field(
        min_length=1,
        max_length=MAX_INVESTIGATION_IDENTIFIER_VALUE_BYTES,
        repr=False,
    )

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str, info: ValidationInfo) -> str:
        kind = info.data.get("kind")
        if not isinstance(kind, InvestigationIdentifierKind):
            raise ValueError("investigation identifier kind is invalid")
        return normalise_investigation_identifier(kind, value)

    def to_domain(self) -> InvestigationIdentifier:
        return InvestigationIdentifier(
            identifier_ref=self.identifier_ref,
            kind=self.kind,
            value=self.value,
        )


class InvestigationPlanCompileRequest(ApiModel):
    identifiers: tuple[InvestigationIdentifierInput, ...] = Field(
        min_length=1,
        max_length=HARD_MAX_INVESTIGATION_IDENTIFIERS,
        strict=False,
    )
    enabled_providers: tuple[Annotated[InvestigationProvider, Field(strict=False)], ...] = Field(
        default=(
            InvestigationProvider.DUCKDUCKGO_HTML,
            InvestigationProvider.GITHUB_USERS,
            InvestigationProvider.HAVE_I_BEEN_PWNED_V3,
        ),
        min_length=1,
        max_length=3,
        strict=False,
    )
    authorized_self_audit: bool
    hibp_api_key_available: bool = False
    hibp_k_anonymity_available: bool = False
    authorized_direct_email_transmission: bool = False

    def to_domain(self) -> InvestigationPlanRequest:
        return InvestigationPlanRequest(
            identifiers=tuple(item.to_domain() for item in self.identifiers),
            enabled_providers=self.enabled_providers,
            authorized_self_audit=self.authorized_self_audit,
            hibp_api_key_available=self.hibp_api_key_available,
            hibp_k_anonymity_available=self.hibp_k_anonymity_available,
            authorized_direct_email_transmission=self.authorized_direct_email_transmission,
        )


class InvestigationPlanStepItem(ApiModel):
    step_id: str = Field(pattern=r"^step-[0-9]{3}$")
    identifier_ref: str = Field(min_length=1, max_length=64)
    identifier_kind: InvestigationIdentifierKind = Field(strict=False)
    identifier_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    provider: InvestigationProvider = Field(strict=False)
    operation: InvestigationOperation = Field(strict=False)
    execution_route: Literal[
        "/v1/discovery/public/search",
        "/v1/discovery/hibp/account",
        "/v1/discovery/hibp/domain",
    ]
    transmission: InvestigationTransmission = Field(strict=False)
    prerequisites: tuple[InvestigationPrerequisite, ...] = Field(min_length=1, max_length=5)
    sequence: int = Field(ge=1, le=HARD_MAX_INVESTIGATION_STEPS)
    executes_during_compilation: Literal[False]
    human_review_required: Literal[True]


class InvestigationPlanResult(ApiModel):
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{24}$")
    steps: tuple[InvestigationPlanStepItem, ...] = Field(max_length=HARD_MAX_INVESTIGATION_STEPS)
    notices: tuple[InvestigationNotice, ...] = Field(max_length=3)
    authorization_confirmed: bool
    deterministic: Literal[True]
    executed: Literal[False]

    @classmethod
    def from_domain(cls, plan: InvestigationPlan) -> InvestigationPlanResult:
        return cls(
            plan_id=plan.plan_id,
            steps=tuple(
                InvestigationPlanStepItem(
                    step_id=item.step_id,
                    identifier_ref=item.identifier_ref,
                    identifier_kind=item.identifier_kind,
                    identifier_sha256=item.identifier_sha256,
                    provider=item.provider,
                    operation=item.operation,
                    execution_route=item.execution_route,
                    transmission=item.transmission,
                    prerequisites=item.prerequisites,
                    sequence=item.sequence,
                    executes_during_compilation=False,
                    human_review_required=True,
                )
                for item in plan.steps
            ),
            notices=plan.notices,
            authorization_confirmed=plan.authorization_confirmed,
            deterministic=True,
            executed=False,
        )
