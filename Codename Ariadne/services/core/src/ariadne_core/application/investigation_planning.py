"""Pure compiler for composable provider plans; this module performs no I/O.

A compiled step explains prerequisites and transmission mode but grants no
execution authority. Durable orchestration must re-resolve current person
knowledge and policy immediately before enqueue or dispatch.
"""

from __future__ import annotations

from ariadne_core.domain.investigation_plan import (
    InvestigationExecutionRoute,
    InvestigationIdentifier,
    InvestigationIdentifierKind,
    InvestigationNotice,
    InvestigationOperation,
    InvestigationPlan,
    InvestigationPlanRequest,
    InvestigationPlanStep,
    InvestigationPrerequisite,
    InvestigationProvider,
    InvestigationTransmission,
    deterministic_plan_id,
)


class InvestigationPlanCompiler:
    """Select lawful steps deterministically without dispatching a provider."""

    def compile(self, request: InvestigationPlanRequest) -> InvestigationPlan:
        if not request.authorized_self_audit:
            return InvestigationPlan(
                plan_id=deterministic_plan_id(request),
                steps=(),
                notices=(InvestigationNotice.SELF_AUDIT_AUTHORIZATION_REQUIRED,),
                authorization_confirmed=False,
            )

        steps: list[InvestigationPlanStep] = []
        notices: list[InvestigationNotice] = []
        enabled = frozenset(request.enabled_providers)
        for identifier in request.identifiers:
            if InvestigationProvider.DUCKDUCKGO_HTML in enabled:
                steps.append(
                    _step(
                        identifier=identifier,
                        provider=InvestigationProvider.DUCKDUCKGO_HTML,
                        operation=InvestigationOperation.PUBLIC_WEB_SEARCH,
                        route="/v1/discovery/public/search",
                        transmission=InvestigationTransmission.DIRECT_PUBLIC_QUERY,
                        prerequisites=(
                            InvestigationPrerequisite.EXPLICIT_SELF_AUDIT_AUTHORIZATION,
                        ),
                        sequence=len(steps) + 1,
                    )
                )
            if (
                identifier.kind is InvestigationIdentifierKind.USERNAME
                and InvestigationProvider.GITHUB_USERS in enabled
            ):
                steps.append(
                    _step(
                        identifier=identifier,
                        provider=InvestigationProvider.GITHUB_USERS,
                        operation=InvestigationOperation.GITHUB_USER_SEARCH,
                        route="/v1/discovery/public/search",
                        transmission=InvestigationTransmission.DIRECT_PUBLIC_QUERY,
                        prerequisites=(
                            InvestigationPrerequisite.EXPLICIT_SELF_AUDIT_AUTHORIZATION,
                        ),
                        sequence=len(steps) + 1,
                    )
                )
            if InvestigationProvider.HAVE_I_BEEN_PWNED_V3 not in enabled or identifier.kind not in {
                InvestigationIdentifierKind.EMAIL,
                InvestigationIdentifierKind.DOMAIN,
            }:
                continue
            if not request.hibp_api_key_available:
                _append_notice(notices, InvestigationNotice.HIBP_API_KEY_REQUIRED)
                continue
            if identifier.kind is InvestigationIdentifierKind.DOMAIN:
                steps.append(
                    _step(
                        identifier=identifier,
                        provider=InvestigationProvider.HAVE_I_BEEN_PWNED_V3,
                        operation=InvestigationOperation.HIBP_VERIFIED_DOMAIN_ENUMERATION,
                        route="/v1/discovery/hibp/domain",
                        transmission=InvestigationTransmission.PROVIDER_VERIFIED_DOMAIN,
                        prerequisites=(
                            InvestigationPrerequisite.EXPLICIT_SELF_AUDIT_AUTHORIZATION,
                            InvestigationPrerequisite.HIBP_API_KEY,
                            InvestigationPrerequisite.PROVIDER_VERIFIED_DOMAIN,
                        ),
                        sequence=len(steps) + 1,
                    )
                )
            elif request.hibp_k_anonymity_available:
                steps.append(
                    _step(
                        identifier=identifier,
                        provider=InvestigationProvider.HAVE_I_BEEN_PWNED_V3,
                        operation=InvestigationOperation.HIBP_EMAIL_K_ANONYMITY,
                        route="/v1/discovery/hibp/account",
                        transmission=InvestigationTransmission.PARTIAL_SHA1_PREFIX,
                        prerequisites=(
                            InvestigationPrerequisite.EXPLICIT_SELF_AUDIT_AUTHORIZATION,
                            InvestigationPrerequisite.HIBP_API_KEY,
                            InvestigationPrerequisite.HIBP_K_ANONYMITY_SUBSCRIPTION,
                        ),
                        sequence=len(steps) + 1,
                    )
                )
            elif request.authorized_direct_email_transmission:
                steps.append(
                    _step(
                        identifier=identifier,
                        provider=InvestigationProvider.HAVE_I_BEEN_PWNED_V3,
                        operation=InvestigationOperation.HIBP_EMAIL_DIRECT,
                        route="/v1/discovery/hibp/account",
                        transmission=InvestigationTransmission.DIRECT_EMAIL,
                        prerequisites=(
                            InvestigationPrerequisite.EXPLICIT_SELF_AUDIT_AUTHORIZATION,
                            InvestigationPrerequisite.HIBP_API_KEY,
                            (
                                InvestigationPrerequisite.DIRECT_IDENTIFIER_TRANSMISSION_AUTHORIZATION
                            ),
                        ),
                        sequence=len(steps) + 1,
                    )
                )
            else:
                _append_notice(notices, InvestigationNotice.HIBP_EMAIL_MODE_NOT_AUTHORIZED)

        return InvestigationPlan(
            plan_id=deterministic_plan_id(request),
            steps=tuple(steps),
            notices=tuple(notices),
            authorization_confirmed=True,
        )


def _step(
    *,
    identifier: InvestigationIdentifier,
    provider: InvestigationProvider,
    operation: InvestigationOperation,
    route: InvestigationExecutionRoute,
    transmission: InvestigationTransmission,
    prerequisites: tuple[InvestigationPrerequisite, ...],
    sequence: int,
) -> InvestigationPlanStep:
    return InvestigationPlanStep(
        step_id=f"step-{sequence:03d}",
        identifier_ref=identifier.identifier_ref,
        identifier_kind=identifier.kind,
        identifier_sha256=identifier.sha256,
        provider=provider,
        operation=operation,
        execution_route=route,
        transmission=transmission,
        prerequisites=prerequisites,
        sequence=sequence,
    )


def _append_notice(
    notices: list[InvestigationNotice],
    notice: InvestigationNotice,
) -> None:
    if notice not in notices:
        notices.append(notice)
