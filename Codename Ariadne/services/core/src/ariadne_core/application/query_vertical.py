"""Authenticated, server-owned query planning and network-free dry-run execution.

The service compiles policy-bound checks and simulates dispatch eligibility;
neither operation contacts an external provider or consumes remote approval.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ariadne_core.api.query_schemas import (
    ProviderCatalogResult,
    QueryCheckState,
    QueryCoverageOutcome,
    QueryDryRunRequest,
    QueryPlanCell,
    QueryPlanRequest,
    QueryPlanResult,
    QueryPolicyMode,
    QueryProviderSummary,
)
from ariadne_core.application.query_policy import DryRunLocalAdapter, QueryPolicyService
from ariadne_core.application.vault import VaultManager, VaultSubkeyPurpose
from ariadne_core.domain.query_policy import (
    DRY_RUN_LOCAL_MANIFEST,
    MANUAL_LOCAL_MANIFEST,
    AccessBasis,
    ApprovedEntity,
    CheckState,
    CompiledCheck,
    CoverageOutcome,
    PolicyMode,
    ProviderMetadata,
    ProviderPolicy,
    ProviderRegistry,
    RunBudget,
    SearchPolicy,
    Sensitivity,
    TransmissionPolicy,
)
from ariadne_core.infrastructure.db.query_policy_repository import (
    QueryPolicyRepository,
    StoredCheck,
)


class QueryVerticalUnavailable(RuntimeError):
    pass


class QueryVerticalNotFound(RuntimeError):
    pass


class QueryVerticalConflict(RuntimeError):
    pass


LOCAL_DRY_RUN_PROVIDER = ProviderMetadata(
    provider_id="local-dry-run",
    display_name="Local dry-run evaluator",
    operator="Codename Ariadne on this Mac",
    adapter=DRY_RUN_LOCAL_MANIFEST,
    access_basis=AccessBasis.LOCAL_ONLY,
    processing_regions=frozenset(),
    external=False,
    enabled=True,
    retention_known=True,
)
MANUAL_IMPORT_PROVIDER = ProviderMetadata(
    provider_id="manual-import",
    display_name="Manual local import",
    operator="User-controlled file import",
    adapter=MANUAL_LOCAL_MANIFEST,
    access_basis=AccessBasis.LOCAL_ONLY,
    processing_regions=frozenset(),
    external=False,
    enabled=True,
    retention_known=True,
)
BUILTIN_PROVIDERS = ProviderRegistry((LOCAL_DRY_RUN_PROVIDER, MANUAL_IMPORT_PROVIDER))


class QueryVerticalCoordinator:
    def __init__(self, vault: VaultManager) -> None:
        self._vault = vault

    @contextmanager
    def _repository(self) -> Iterator[QueryPolicyRepository]:
        if not self._vault.is_unlocked:
            raise QueryVerticalUnavailable("query planning requires an unlocked vault")
        with self._vault.borrow_subkey(VaultSubkeyPurpose.QUERY_POLICY) as key:
            repository = QueryPolicyRepository(self._vault.engine, policy_hmac_key=key)
            try:
                yield repository
            finally:
                repository.close()

    def catalog(self, profile_id: str) -> ProviderCatalogResult:
        with self._repository() as repository:
            self._require_profile(repository, profile_id)
            providers = BUILTIN_PROVIDERS.all()
            return ProviderCatalogResult(
                profile_id=profile_id,
                providers=tuple(self._provider_summary(provider) for provider in providers),
                external_provider_count=sum(provider.external for provider in providers),
            )

    def create_plan(self, body: QueryPlanRequest) -> QueryPlanResult:
        with self._repository() as repository:
            self._require_profile(repository, body.profile_id)
            try:
                selected = tuple(BUILTIN_PROVIDERS.get(item) for item in body.provider_ids)
            except LookupError as error:
                raise QueryVerticalNotFound("selected provider is unavailable") from error
            entities = repository.list_confirmed_entities(
                vault_id=self._vault.manifest.vault_id,
                profile_id=body.profile_id,
                limit=100,
            )
            if not entities:
                raise QueryVerticalConflict("no confirmed entities are available for planning")
            policy = ProviderPolicy(
                mode=PolicyMode(body.policy_mode.value),
                revision=1,
                allowed_provider_ids=frozenset(body.allowed_provider_ids),
                allowed_regions=frozenset(body.allowed_regions),
                allowed_access_bases=frozenset({AccessBasis.LOCAL_ONLY}),
            )
            service = QueryPolicyService(repository)
            record = service.create_plan(
                vault_id=self._vault.manifest.vault_id,
                profile_id=body.profile_id,
                purpose_code=body.purpose_code,
                entities=entities,
                providers=ProviderRegistry(selected),
                policy=policy,
                budget=RunBudget(
                    maximum_checks=body.maximum_checks,
                    maximum_checks_per_provider=body.maximum_checks_per_provider,
                ),
            )
            entity_by_id = {entity.entity_id: entity for entity in entities}
            stored_by_id = {check.id: check for check in record.stored_checks}
            cells = tuple(
                self._cell(
                    stored_by_id[compiled.check_id],
                    entity_by_id[compiled.entity_id],
                )
                for compiled in record.plan.checks
            )
            return QueryPlanResult(
                run_id=record.run_id,
                profile_id=body.profile_id,
                policy_mode=QueryPolicyMode(body.policy_mode.value),
                cells=cells,
                planned_count=record.plan.planned_count,
                approval_required_count=record.plan.approval_required_count,
                not_checked_count=record.plan.not_checked_count,
                blocked_count=record.plan.blocked_count,
            )

    def execute_dry_run(self, body: QueryDryRunRequest) -> QueryPlanCell:
        with self._repository() as repository:
            self._require_profile(repository, body.profile_id)
            vault_id = self._vault.manifest.vault_id
            try:
                stored = repository.get_check(
                    vault_id,
                    body.profile_id,
                    body.run_id,
                    body.check_id,
                )
                entity = repository.get_confirmed_entity(
                    vault_id=vault_id,
                    profile_id=body.profile_id,
                    entity_id=stored.entity_id,
                )
                context = repository.get_run_context(
                    vault_id=vault_id,
                    profile_id=body.profile_id,
                    run_id=body.run_id,
                )
                provider = BUILTIN_PROVIDERS.get(stored.provider_id)
            except LookupError as error:
                raise QueryVerticalNotFound("query plan resource is unavailable") from error
            if stored.revision != body.expected_revision:
                raise QueryVerticalConflict("query check revision is stale")
            if provider.adapter is not DRY_RUN_LOCAL_MANIFEST:
                raise QueryVerticalConflict("selected check is not executable as a dry run")
            approval_token: str | None = None
            if stored.requires_approval and body.approve_once:
                approval_token = repository.issue_approval(
                    vault_id=vault_id,
                    profile_id=body.profile_id,
                    run_id=body.run_id,
                    check_id=body.check_id,
                    ttl_us=60_000_000,
                ).token
            compiled = self._compiled(stored, entity)
            result = QueryPolicyService(repository).execute(
                vault_id=vault_id,
                profile_id=body.profile_id,
                purpose_code=context.purpose_code,
                run_id=body.run_id,
                compiled=compiled,
                entity=entity,
                provider=provider,
                policy=context.policy,
                adapter=DryRunLocalAdapter(DRY_RUN_LOCAL_MANIFEST),
                approval_token=approval_token,
            )
            return self._cell(result, entity)

    def _require_profile(self, repository: QueryPolicyRepository, profile_id: str) -> None:
        if not repository.profile_is_active(
            vault_id=self._vault.manifest.vault_id,
            profile_id=profile_id,
        ):
            raise QueryVerticalNotFound("profile is unavailable")

    @staticmethod
    def _provider_summary(provider: ProviderMetadata) -> QueryProviderSummary:
        return QueryProviderSummary(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            operator=provider.operator,
            adapter_mode=provider.adapter.mode.value,
            access_basis=provider.access_basis.value,
            processing_regions=tuple(sorted(provider.processing_regions)),
            network_access=provider.adapter.network_access,
            sends_identifiers=provider.adapter.sends_identifiers,
            enabled=provider.enabled,
            retention_known=provider.retention_known,
        )

    @staticmethod
    def _cell(stored: StoredCheck, entity: ApprovedEntity) -> QueryPlanCell:
        return QueryPlanCell(
            check_id=stored.id,
            entity_id=stored.entity_id,
            provider_id=stored.provider_id,
            masked_value=stored.masked_query,
            entity_type=entity.entity_type,
            query_class=stored.query_class,
            state=QueryCheckState(stored.state.value),
            outcome=QueryCoverageOutcome(stored.outcome.value),
            reason_code=stored.reason_code,
            requires_approval=stored.requires_approval,
            revision=stored.revision,
        )

    @staticmethod
    def _compiled(stored: StoredCheck, entity: ApprovedEntity) -> CompiledCheck:
        return CompiledCheck(
            check_id=stored.id,
            entity_id=stored.entity_id,
            provider_id=stored.provider_id,
            query_class=stored.query_class,
            query_value=entity.query_value,
            masked_query=stored.masked_query,
            entity_revision=stored.entity_revision,
            sensitivity=Sensitivity(stored.sensitivity_snapshot),
            search_policy=SearchPolicy(stored.search_policy_snapshot),
            transmission_policy=TransmissionPolicy(stored.transmission_policy_snapshot),
            state=CheckState(stored.state.value),
            outcome=CoverageOutcome(stored.outcome.value),
            reason_code=stored.reason_code,
            requires_approval=stored.requires_approval,
        )
