from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ariadne_core.api.investigation_plan_schemas import (
    InvestigationPlanCompileRequest,
    InvestigationPlanResult,
)
from ariadne_core.application.investigation_planning import InvestigationPlanCompiler
from ariadne_core.domain.investigation_plan import (
    InvestigationIdentifier,
    InvestigationIdentifierKind,
    InvestigationNotice,
    InvestigationOperation,
    InvestigationPlanRequest,
    InvestigationProvider,
)

EMAIL = "morgan.trace@ariadne-example.invalid"
USERNAME = "synthetic_night_orbit"
DOMAIN = "ariadne-example.invalid"


def _request(
    *,
    authorized: bool = True,
    key_available: bool = True,
    k_anonymity: bool = True,
    direct: bool = False,
    providers: tuple[InvestigationProvider, ...] = tuple(InvestigationProvider),
) -> InvestigationPlanRequest:
    return InvestigationPlanRequest(
        identifiers=(
            InvestigationIdentifier(
                identifier_ref="email-primary",
                kind=InvestigationIdentifierKind.EMAIL,
                value=EMAIL,
            ),
            InvestigationIdentifier(
                identifier_ref="username-primary",
                kind=InvestigationIdentifierKind.USERNAME,
                value=USERNAME,
            ),
            InvestigationIdentifier(
                identifier_ref="domain-primary",
                kind=InvestigationIdentifierKind.DOMAIN,
                value=DOMAIN,
            ),
        ),
        enabled_providers=providers,
        authorized_self_audit=authorized,
        hibp_api_key_available=key_available,
        hibp_k_anonymity_available=k_anonymity,
        authorized_direct_email_transmission=direct,
    )


def test_compiler_is_deterministic_and_never_executes() -> None:
    compiler = InvestigationPlanCompiler()

    first = compiler.compile(_request())
    second = compiler.compile(_request())

    assert first == second
    assert first.plan_id == second.plan_id
    assert first.deterministic is True
    assert first.executed is False
    assert first.authorization_confirmed is True
    assert all(not item.executes_during_compilation for item in first.steps)
    assert [item.sequence for item in first.steps] == list(range(1, len(first.steps) + 1))


def test_compiler_prefers_hibp_k_anonymity_and_composes_allowed_providers() -> None:
    plan = InvestigationPlanCompiler().compile(_request())

    operations = [item.operation for item in plan.steps]
    assert operations == [
        InvestigationOperation.PUBLIC_WEB_SEARCH,
        InvestigationOperation.HIBP_EMAIL_K_ANONYMITY,
        InvestigationOperation.PUBLIC_WEB_SEARCH,
        InvestigationOperation.GITHUB_USER_SEARCH,
        InvestigationOperation.PUBLIC_WEB_SEARCH,
        InvestigationOperation.HIBP_VERIFIED_DOMAIN_ENUMERATION,
    ]
    email_hibp = next(
        item
        for item in plan.steps
        if item.operation is InvestigationOperation.HIBP_EMAIL_K_ANONYMITY
    )
    assert email_hibp.transmission.value == "PARTIAL_SHA1_PREFIX"
    assert email_hibp.execution_route == "/v1/discovery/hibp/account"
    assert "HIBP_K_ANONYMITY_SUBSCRIPTION" in {item.value for item in email_hibp.prerequisites}
    domain_hibp = next(
        item
        for item in plan.steps
        if item.operation is InvestigationOperation.HIBP_VERIFIED_DOMAIN_ENUMERATION
    )
    assert "PROVIDER_VERIFIED_DOMAIN" in {item.value for item in domain_hibp.prerequisites}


def test_direct_email_is_only_a_fallback_when_separately_authorized() -> None:
    direct = InvestigationPlanCompiler().compile(_request(k_anonymity=False, direct=True))
    blocked = InvestigationPlanCompiler().compile(_request(k_anonymity=False, direct=False))

    assert InvestigationOperation.HIBP_EMAIL_DIRECT in {item.operation for item in direct.steps}
    assert InvestigationOperation.HIBP_EMAIL_DIRECT not in {
        item.operation for item in blocked.steps
    }
    assert blocked.notices == (InvestigationNotice.HIBP_EMAIL_MODE_NOT_AUTHORIZED,)


def test_missing_hibp_key_omits_hibp_steps_with_one_notice() -> None:
    plan = InvestigationPlanCompiler().compile(_request(key_available=False))

    assert all(
        item.provider is not InvestigationProvider.HAVE_I_BEEN_PWNED_V3 for item in plan.steps
    )
    assert plan.notices == (InvestigationNotice.HIBP_API_KEY_REQUIRED,)


def test_unauthorized_request_has_no_steps() -> None:
    plan = InvestigationPlanCompiler().compile(_request(authorized=False))

    assert plan.steps == ()
    assert plan.authorization_confirmed is False
    assert plan.notices == (InvestigationNotice.SELF_AUDIT_AUTHORIZATION_REQUIRED,)


def test_provider_selection_is_respected() -> None:
    plan = InvestigationPlanCompiler().compile(
        _request(providers=(InvestigationProvider.GITHUB_USERS,))
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].operation is InvestigationOperation.GITHUB_USER_SEARCH
    assert plan.steps[0].identifier_ref == "username-primary"


def test_raw_identifier_values_are_not_returned_or_represented() -> None:
    body = InvestigationPlanCompileRequest.model_validate(
        {
            "identifiers": [
                {
                    "identifierRef": "email-primary",
                    "kind": "EMAIL",
                    "value": EMAIL,
                }
            ],
            "enabledProviders": ["HAVE_I_BEEN_PWNED_V3"],
            "authorizedSelfAudit": True,
            "hibpApiKeyAvailable": True,
            "hibpKAnonymityAvailable": True,
        }
    )
    plan = InvestigationPlanCompiler().compile(body.to_domain())
    wire = InvestigationPlanResult.from_domain(plan)
    payload = wire.model_dump_json(by_alias=True)

    assert EMAIL not in repr(body)
    assert EMAIL not in repr(body.identifiers[0])
    assert EMAIL not in repr(body.to_domain())
    assert EMAIL not in repr(plan)
    assert EMAIL not in payload
    assert wire.steps[0].identifier_ref == "email-primary"
    assert len(wire.steps[0].identifier_sha256) == 64
    assert json.loads(payload)["executed"] is False


def test_plan_id_changes_when_provider_policy_changes() -> None:
    compiler = InvestigationPlanCompiler()
    k_anonymous = compiler.compile(_request(k_anonymity=True))
    direct = compiler.compile(_request(k_anonymity=False, direct=True))

    assert k_anonymous.plan_id != direct.plan_id


def test_duplicate_references_values_and_providers_are_rejected() -> None:
    identifier = InvestigationIdentifier(
        identifier_ref="duplicate",
        kind=InvestigationIdentifierKind.EMAIL,
        value=EMAIL,
    )
    with pytest.raises(ValueError, match="references"):
        InvestigationPlanRequest(
            identifiers=(identifier, identifier),
            enabled_providers=(InvestigationProvider.DUCKDUCKGO_HTML,),
            authorized_self_audit=True,
        )
    with pytest.raises(ValueError, match=r"providers|provider"):
        InvestigationPlanRequest(
            identifiers=(identifier,),
            enabled_providers=(
                InvestigationProvider.DUCKDUCKGO_HTML,
                InvestigationProvider.DUCKDUCKGO_HTML,
            ),
            authorized_self_audit=True,
        )


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("EMAIL", "not-an-email"),
        ("USERNAME", "synthetic username with spaces"),
        ("DOMAIN", "localhost"),
        ("URL", "file:///tmp/synthetic"),
    ],
)
def test_schema_rejects_unsupported_or_ambiguous_identifiers(
    kind: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        InvestigationPlanCompileRequest.model_validate(
            {
                "identifiers": [
                    {
                        "identifierRef": "synthetic",
                        "kind": kind,
                        "value": value,
                    }
                ],
                "authorizedSelfAudit": True,
            }
        )
