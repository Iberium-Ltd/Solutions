from __future__ import annotations

from ariadne_core.application.query_policy import QueryCompiler
from ariadne_core.domain.query_policy import (
    DRY_RUN_LOCAL_MANIFEST,
    AccessBasis,
    AdapterManifest,
    AdapterMode,
    ApprovedEntity,
    CheckState,
    PolicyMode,
    PolicyVerdict,
    ProviderMetadata,
    ProviderPolicy,
    ProviderRegistry,
    RunBudget,
    SearchPolicy,
    Sensitivity,
    TransmissionPolicy,
    evaluate_policy,
)


def _external_provider(provider_id: str, region: str) -> ProviderMetadata:
    return ProviderMetadata(
        provider_id=provider_id,
        display_name=f"Synthetic {provider_id}",
        operator="Synthetic Registry Cooperative",
        adapter=AdapterManifest(
            adapter_id=f"{provider_id}-adapter",
            mode=AdapterMode.AUTOMATED,
            network_access=True,
            sends_identifiers=True,
            supported_query_classes=frozenset({"EXACT"}),
        ),
        access_basis=AccessBasis.PUBLIC,
        processing_regions=frozenset({region}),
        external=True,
        enabled=True,
        retention_known=True,
    )


def _entity(
    value: str,
    *,
    sensitivity: Sensitivity = Sensitivity.SENSITIVE,
    search: SearchPolicy = SearchPolicy.ALLOW,
    transmission: TransmissionPolicy = TransmissionPolicy.PROVIDER_ALLOWLIST,
) -> ApprovedEntity:
    return ApprovedEntity(
        entity_id=f"entity-{value[-1]}",
        entity_type="EMAIL",
        query_value=value,
        masked_display="s••••••••@example.invalid",
        sensitivity=sensitivity,
        search_policy=search,
        transmission_policy=transmission,
        revision=1,
    )


def test_local_eu_and_custom_policy_verdicts_are_fail_closed() -> None:
    local = ProviderMetadata(
        provider_id="local-corpus",
        display_name="Synthetic Local Corpus",
        operator="On device",
        adapter=DRY_RUN_LOCAL_MANIFEST,
        access_basis=AccessBasis.LOCAL_ONLY,
        processing_regions=frozenset(),
        external=False,
        enabled=True,
        retention_known=True,
    )
    eu = _external_provider("eu-public", "DE")
    us = _external_provider("us-public", "US")
    entity = _entity("synthetic.one@example.invalid")

    local_only = ProviderPolicy(mode=PolicyMode.LOCAL_ONLY, revision=1)
    assert evaluate_policy(entity, local, local_only).verdict is PolicyVerdict.ALLOW_LOCAL
    assert evaluate_policy(entity, eu, local_only).reason_code == "LOCAL_ONLY_POLICY"

    eu_only = ProviderPolicy(mode=PolicyMode.EU_ONLY, revision=2)
    assert evaluate_policy(entity, eu, eu_only).verdict is PolicyVerdict.ALLOW_EXTERNAL
    assert evaluate_policy(entity, us, eu_only).reason_code == "JURISDICTION_BLOCKED"

    custom = ProviderPolicy(
        mode=PolicyMode.CUSTOM,
        revision=3,
        allowed_provider_ids=frozenset({"eu-public"}),
        allowed_regions=frozenset({"DE"}),
    )
    assert evaluate_policy(entity, eu, custom).verdict is PolicyVerdict.ALLOW_EXTERNAL
    assert evaluate_policy(entity, us, custom).reason_code == "PROVIDER_NOT_ALLOWLISTED"


def test_compiler_preserves_blocked_not_checked_and_hard_budget_cells() -> None:
    provider = _external_provider("eu-public", "DE")
    entities = (
        _entity("synthetic.one@example.invalid"),
        _entity("synthetic.two@example.invalid"),
        _entity("synthetic.three@example.invalid", sensitivity=Sensitivity.RESTRICTED),
    )
    plan = QueryCompiler().compile(
        entities=entities,
        providers=ProviderRegistry((provider,)),
        policy=ProviderPolicy(mode=PolicyMode.EU_ONLY, revision=1),
        budget=RunBudget(maximum_checks=1, maximum_checks_per_provider=1),
    )

    assert [check.state for check in plan.checks] == [
        CheckState.PLANNED,
        CheckState.NOT_CHECKED,
        CheckState.BLOCKED,
    ]
    assert [check.reason_code for check in plan.checks] == [
        "READY",
        "BUDGET_EXHAUSTED",
        "RESTRICTED_VALUE",
    ]
    assert plan.planned_count == plan.not_checked_count == plan.blocked_count == 1


def test_highly_sensitive_external_query_requires_one_time_approval() -> None:
    provider = _external_provider("eu-public", "DE")
    decision = evaluate_policy(
        _entity(
            "synthetic.one@example.invalid",
            sensitivity=Sensitivity.HIGHLY_SENSITIVE,
        ),
        provider,
        ProviderPolicy(mode=PolicyMode.EU_ONLY, revision=1),
    )
    assert decision.verdict is PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL
