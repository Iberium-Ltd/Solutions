"""Inspectable query compilation and the final fail-closed dispatch boundary.

Compilation snapshots what would be disclosed. Execution revalidates that
snapshot, reserves budget, consumes approval, and records an outcome; no caller
may treat a successful plan as proof that a request occurred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from uuid6 import uuid7

from ariadne_core.domain.query_policy import (
    AdapterManifest,
    AdapterMode,
    ApprovedEntity,
    CheckState,
    CompiledCheck,
    CoverageOutcome,
    PolicyMode,
    PolicyVerdict,
    ProviderMetadata,
    ProviderPolicy,
    ProviderRegistry,
    QueryPlan,
    RunBudget,
    evaluate_policy,
)
from ariadne_core.infrastructure.db.query_policy_repository import (
    QueryPolicyRepository,
    StoredCheck,
)


@dataclass(frozen=True, slots=True)
class DispatchEnvelope:
    check_id: str
    provider_id: str
    query_class: str
    query_value: str = field(repr=False)
    masked_query: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    succeeded: bool
    result_code: str


class QueryAdapter(Protocol):
    manifest: AdapterManifest

    def dispatch(self, envelope: DispatchEnvelope) -> AdapterResult: ...


@dataclass(frozen=True, slots=True)
class PlanRecord:
    run_id: str
    plan: QueryPlan
    stored_checks: tuple[StoredCheck, ...]


class DryRunLocalAdapter:
    """A network-free adapter that proves dispatch without external effects."""

    def __init__(self, manifest: AdapterManifest) -> None:
        if manifest.mode is not AdapterMode.DRY_RUN or manifest.network_access:
            raise ValueError("dry-run adapter manifest is invalid")
        self.manifest = manifest
        self.dispatch_count = 0

    def dispatch(self, envelope: DispatchEnvelope) -> AdapterResult:
        del envelope
        self.dispatch_count += 1
        return AdapterResult(succeeded=True, result_code="DRY_RUN_COMPLETE")


class QueryCompiler:
    """Compile every entity/provider cell into an explicit coverage state."""

    def compile(
        self,
        *,
        entities: tuple[ApprovedEntity, ...],
        providers: ProviderRegistry,
        policy: ProviderPolicy,
        budget: RunBudget,
        query_class: str = "EXACT",
    ) -> QueryPlan:
        checks: list[CompiledCheck] = []
        used_total = 0
        used_by_provider: dict[str, int] = {}
        for provider in providers.all():
            for entity in entities:
                decision = evaluate_policy(entity, provider, policy)
                state = CheckState.BLOCKED
                outcome = CoverageOutcome.ACCESS_BLOCKED
                reason = decision.reason_code
                requires_approval = False
                if query_class not in provider.adapter.supported_query_classes:
                    reason = "QUERY_CLASS_UNSUPPORTED"
                elif decision.verdict in {
                    PolicyVerdict.ALLOW_LOCAL,
                    PolicyVerdict.ALLOW_EXTERNAL,
                    PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL,
                }:
                    if provider.adapter.mode is AdapterMode.MANUAL_LOCAL:
                        state = CheckState.NOT_CHECKED
                        outcome = CoverageOutcome.NOT_CHECKED
                        reason = "MANUAL_IMPORT_REQUIRED"
                        checks.append(
                            CompiledCheck(
                                check_id=str(uuid7()),
                                entity_id=entity.entity_id,
                                provider_id=provider.provider_id,
                                query_class=query_class,
                                query_value=entity.query_value,
                                masked_query=entity.masked_display,
                                entity_revision=entity.revision,
                                sensitivity=entity.sensitivity,
                                search_policy=entity.search_policy,
                                transmission_policy=entity.transmission_policy,
                                state=state,
                                outcome=outcome,
                                reason_code=reason,
                                requires_approval=False,
                            )
                        )
                        continue
                    provider_used = used_by_provider.get(provider.provider_id, 0)
                    if (
                        used_total >= budget.maximum_checks
                        or provider_used >= budget.maximum_checks_per_provider
                    ):
                        state = CheckState.NOT_CHECKED
                        outcome = CoverageOutcome.NOT_CHECKED
                        reason = "BUDGET_EXHAUSTED"
                    else:
                        used_total += 1
                        used_by_provider[provider.provider_id] = provider_used + 1
                        outcome = CoverageOutcome.NOT_CHECKED
                        if decision.verdict is PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL:
                            state = CheckState.APPROVAL_REQUIRED
                            requires_approval = True
                        else:
                            state = CheckState.PLANNED
                            reason = "READY"
                checks.append(
                    CompiledCheck(
                        check_id=str(uuid7()),
                        entity_id=entity.entity_id,
                        provider_id=provider.provider_id,
                        query_class=query_class,
                        query_value=entity.query_value,
                        masked_query=entity.masked_display,
                        entity_revision=entity.revision,
                        sensitivity=entity.sensitivity,
                        search_policy=entity.search_policy,
                        transmission_policy=entity.transmission_policy,
                        state=state,
                        outcome=outcome,
                        reason_code=reason,
                        requires_approval=requires_approval,
                    )
                )
        return QueryPlan(
            checks=tuple(checks),
            planned_count=sum(check.state is CheckState.PLANNED for check in checks),
            not_checked_count=sum(check.state is CheckState.NOT_CHECKED for check in checks),
            blocked_count=sum(check.state is CheckState.BLOCKED for check in checks),
            approval_required_count=sum(
                check.state is CheckState.APPROVAL_REQUIRED for check in checks
            ),
        )


class QueryPolicyService:
    """Coordinate final policy checks, accounting, and one typed adapter call."""

    def __init__(self, repository: QueryPolicyRepository) -> None:
        self.repository = repository
        self.compiler = QueryCompiler()

    def create_plan(
        self,
        *,
        vault_id: str,
        profile_id: str,
        purpose_code: str,
        entities: tuple[ApprovedEntity, ...],
        providers: ProviderRegistry,
        policy: ProviderPolicy,
        budget: RunBudget,
    ) -> PlanRecord:
        if not entities:
            raise ValueError("at least one approved entity is required")
        if not all(
            self.repository.approved_entity_is_current(
                vault_id=vault_id,
                profile_id=profile_id,
                entity=entity,
            )
            for entity in entities
        ):
            raise ValueError("query entity is not currently approved")
        for provider in providers.all():
            self.repository.register_provider(vault_id=vault_id, provider=provider)
        plan = self.compiler.compile(
            entities=entities,
            providers=providers,
            policy=policy,
            budget=budget,
        )
        run_id = self.repository.create_run(
            vault_id=vault_id,
            profile_id=profile_id,
            purpose_code=purpose_code,
            policy=policy,
            budget=budget,
        )
        stored = self.repository.persist_checks(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            checks=plan.checks,
        )
        return PlanRecord(run_id, plan, stored)

    def execute(
        self,
        *,
        vault_id: str,
        profile_id: str,
        purpose_code: str,
        run_id: str,
        compiled: CompiledCheck,
        entity: ApprovedEntity,
        provider: ProviderMetadata,
        policy: ProviderPolicy,
        adapter: QueryAdapter,
        approval_token: str | None = None,
    ) -> StoredCheck:
        """Dispatch once only after stale-plan, approval, and budget checks pass."""
        stored = self.repository.get_check(
            vault_id,
            profile_id,
            run_id,
            compiled.check_id,
        )
        if stored.entity_id != entity.entity_id or stored.provider_id != provider.provider_id:
            raise ValueError("query dispatch binding is invalid")
        if adapter.manifest.adapter_id != provider.adapter.adapter_id:
            raise ValueError("query adapter binding is invalid")
        if not self.repository.dispatch_binding_is_valid(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            check=stored,
            query_value=entity.query_value,
            provider=provider,
            policy=policy,
        ):
            raise ValueError("query policy binding is invalid")
        if stored.state in {
            CheckState.DISPATCHED,
            CheckState.SUCCEEDED,
            CheckState.CHECK_FAILED,
        }:
            return stored
        decision = evaluate_policy(entity, provider, policy)
        if decision.verdict is PolicyVerdict.DENY:
            return self.repository.update_check(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check_id=stored.id,
                state=CheckState.BLOCKED,
                outcome=CoverageOutcome.ACCESS_BLOCKED,
                reason_code=decision.reason_code,
            )
        if stored.state in {CheckState.BLOCKED, CheckState.NOT_CHECKED}:
            return stored
        if decision.verdict is PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL:
            approved = approval_token is not None and self.repository.consume_approval(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check_id=stored.id,
                token=approval_token,
            )
            if not approved:
                return self.repository.update_check(
                    vault_id=vault_id,
                    profile_id=profile_id,
                    run_id=run_id,
                    check_id=stored.id,
                    state=CheckState.APPROVAL_REQUIRED,
                    outcome=CoverageOutcome.NOT_CHECKED,
                    reason_code="ONE_TIME_APPROVAL_REQUIRED",
                )
        if not self.repository.reserve_budget(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            provider_id=provider.provider_id,
        ):
            return self.repository.update_check(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check_id=stored.id,
                state=CheckState.NOT_CHECKED,
                outcome=CoverageOutcome.NOT_CHECKED,
                reason_code="BUDGET_EXHAUSTED",
            )
        dispatched = self.repository.update_check(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            check_id=stored.id,
            state=CheckState.DISPATCHED,
            outcome=CoverageOutcome.DISPATCHED,
            reason_code="DISPATCH_STARTED",
        )
        envelope = DispatchEnvelope(
            check_id=stored.id,
            provider_id=provider.provider_id,
            query_class=stored.query_class,
            query_value=entity.query_value,
            masked_query=stored.masked_query,
        )
        try:
            result = adapter.dispatch(envelope)
        except Exception:
            self.repository.append_ledger(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check=dispatched,
                provider=provider,
                payload=entity.query_value,
                purpose_code=purpose_code,
                verdict=decision.verdict.value,
                result_code="ADAPTER_FAILURE",
            )
            return self.repository.update_check(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check_id=stored.id,
                state=CheckState.CHECK_FAILED,
                outcome=CoverageOutcome.CHECK_FAILED,
                reason_code="ADAPTER_FAILURE",
            )
        self.repository.append_ledger(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            check=dispatched,
            provider=provider,
            payload=entity.query_value,
            purpose_code=purpose_code,
            verdict=decision.verdict.value,
            result_code=result.result_code,
        )
        if not result.succeeded:
            return self.repository.update_check(
                vault_id=vault_id,
                profile_id=profile_id,
                run_id=run_id,
                check_id=stored.id,
                state=CheckState.CHECK_FAILED,
                outcome=CoverageOutcome.CHECK_FAILED,
                reason_code=result.result_code,
            )
        return self.repository.update_check(
            vault_id=vault_id,
            profile_id=profile_id,
            run_id=run_id,
            check_id=stored.id,
            state=CheckState.SUCCEEDED,
            outcome=CoverageOutcome.SUCCEEDED,
            reason_code=result.result_code,
        )


def local_policy(revision: int = 1) -> ProviderPolicy:
    return ProviderPolicy(mode=PolicyMode.LOCAL_ONLY, revision=revision)
