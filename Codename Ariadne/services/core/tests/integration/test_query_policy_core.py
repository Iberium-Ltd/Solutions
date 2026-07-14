from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest
from alembic import command
from sqlalchemy import select

from ariadne_core.api.intake_schemas import PasteIntakeRequest, ProfileCreateRequest
from ariadne_core.application.phase3 import Phase3Coordinator
from ariadne_core.application.query_policy import (
    AdapterResult,
    DispatchEnvelope,
    DryRunLocalAdapter,
    QueryPolicyService,
)
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.query_policy import (
    DRY_RUN_LOCAL_MANIFEST,
    AccessBasis,
    AdapterManifest,
    AdapterMode,
    ApprovedEntity,
    CheckState,
    PolicyMode,
    ProviderMetadata,
    ProviderPolicy,
    ProviderRegistry,
    RunBudget,
    SearchPolicy,
    Sensitivity,
    TransmissionPolicy,
)
from ariadne_core.infrastructure.db.engine import SqlcipherEngineFactory
from ariadne_core.infrastructure.db.migrate import migration_config
from ariadne_core.infrastructure.db.query_policy_repository import QueryPolicyRepository
from ariadne_core.security.key_custody import MemoryKeyCustodian


@dataclass
class RecordingAdapter:
    manifest: AdapterManifest
    fail: bool = False
    values: list[str] = field(default_factory=list)

    def dispatch(self, envelope: DispatchEnvelope) -> AdapterResult:
        self.values.append(envelope.query_value)
        if self.fail:
            raise RuntimeError("synthetic adapter failure")
        return AdapterResult(True, "SYNTHETIC_RESULT")


def test_query_policy_schema_upgrades_forward_from_phase3_head(tmp_path) -> None:
    key = bytearray(b"m" * 32)
    engine = SqlcipherEngineFactory(tmp_path / "legacy" / "vault.db", key).create()
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0005_graph_edge_origins")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0006_query_policy_core")
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
        tables = {
            str(row[0])
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).all()
        }
    assert revision == "0006_query_policy_core"
    assert {
        "phase4_providers",
        "phase4_query_runs",
        "phase4_provider_budget_usage",
        "phase4_query_checks",
        "phase4_one_time_approvals",
        "phase4_transmission_ledger",
    } <= tables
    engine.dispose()
    key[:] = b"\x00" * len(key)


def _external_provider() -> ProviderMetadata:
    manifest = AdapterManifest(
        adapter_id="synthetic-eu-adapter",
        mode=AdapterMode.AUTOMATED,
        network_access=True,
        sends_identifiers=True,
        supported_query_classes=frozenset({"EXACT"}),
    )
    return ProviderMetadata(
        provider_id="synthetic-eu",
        display_name="Synthetic EU Public Index",
        operator="Synthetic Index Cooperative",
        adapter=manifest,
        access_basis=AccessBasis.PUBLIC,
        processing_regions=frozenset({"DE"}),
        external=True,
        enabled=True,
        retention_known=True,
    )


def _fixture(tmp_path):  # type: ignore[no-untyped-def]
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manager.create(display_name="Synthetic query policy vault")
    phase3 = Phase3Coordinator(manager)
    profile = phase3.create_profile(
        ProfileCreateRequest(
            idempotency_key="synthetic-query-profile-0001",
            display_label="Synthetic query profile",
            purpose="Synthetic Phase 4 policy test",
        )
    )
    phase3.ingest_paste(
        PasteIntakeRequest(
            idempotency_key="synthetic-query-intake-0001",
            profile_id=profile.profile_id,
            display_name="Synthetic approved identifiers",
            content=("Contact synthetic.one@example.invalid and synthetic.two@example.invalid"),
            consent_confirmed=True,
            retain_raw_source=False,
            semantic_enrichment_enabled=False,
        )
    )
    with manager.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE entities SET review_state = 'CONFIRMED', "
            "transmission_policy = 'APPROVAL_REQUIRED' "
            "WHERE profile_id = ? AND entity_type = 'EMAIL'",
            (profile.profile_id,),
        )
    with manager.engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id, canonical_value, display_mask FROM entities "
            "WHERE profile_id = ? AND entity_type = 'EMAIL' ORDER BY canonical_value",
            (profile.profile_id,),
        ).all()
    entities = tuple(
        ApprovedEntity(
            entity_id=str(row[0]),
            entity_type="EMAIL",
            query_value=str(row[1]),
            masked_display=str(row[2]),
            sensitivity=Sensitivity.SENSITIVE,
            search_policy=SearchPolicy.REQUIRE_APPROVAL,
            transmission_policy=TransmissionPolicy.REQUIRE_APPROVAL,
            revision=1,
        )
        for row in rows
    )
    repository = QueryPolicyRepository(manager.engine, policy_hmac_key=b"q" * 32)
    return manager, profile.profile_id, entities, repository


def test_denied_values_never_reach_dispatch_and_local_dry_run_is_ledgered(tmp_path) -> None:
    manager, profile_id, entities, repository = _fixture(tmp_path)
    service = QueryPolicyService(repository)
    external = _external_provider()
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
    policy = ProviderPolicy(mode=PolicyMode.LOCAL_ONLY, revision=1)
    record = service.create_plan(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_SELF_AUDIT",
        entities=(entities[0],),
        providers=ProviderRegistry((external, local)),
        policy=policy,
        budget=RunBudget(2, 1),
    )
    by_provider = {check.provider_id: check for check in record.plan.checks}
    external_adapter = RecordingAdapter(external.adapter)
    denied = service.execute(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_SELF_AUDIT",
        run_id=record.run_id,
        compiled=by_provider[external.provider_id],
        entity=entities[0],
        provider=external,
        policy=policy,
        adapter=external_adapter,
    )
    assert denied.state is CheckState.BLOCKED
    assert external_adapter.values == []

    dry_run = DryRunLocalAdapter(DRY_RUN_LOCAL_MANIFEST)
    local_grant = repository.issue_approval(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        run_id=record.run_id,
        check_id=by_provider[local.provider_id].check_id,
        ttl_us=60_000_000,
    )
    succeeded = service.execute(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_SELF_AUDIT",
        run_id=record.run_id,
        compiled=by_provider[local.provider_id],
        entity=entities[0],
        provider=local,
        policy=policy,
        adapter=dry_run,
        approval_token=local_grant.token,
    )
    assert succeeded.state is CheckState.SUCCEEDED
    assert dry_run.dispatch_count == 1

    with manager.engine.connect() as connection:
        phase4_text = " ".join(
            str(value)
            for table in (repository.checks, repository.approvals, repository.ledger)
            for row in connection.execute(select(table)).all()
            for value in row
            if value is not None
        )
        ledger_count = connection.execute(select(repository.ledger.c.id)).all()
    assert entities[0].query_value not in phase4_text
    assert len(ledger_count) == 1
    repository.close()
    manager.lock()


def test_restricted_or_unapproved_entity_cannot_enter_a_durable_plan(tmp_path) -> None:
    manager, profile_id, entities, repository = _fixture(tmp_path)
    service = QueryPolicyService(repository)
    provider = _external_provider()
    restricted = replace(entities[0], sensitivity=Sensitivity.RESTRICTED)
    with pytest.raises(ValueError, match="not currently approved"):
        service.create_plan(
            vault_id=manager.manifest.vault_id,
            profile_id=profile_id,
            purpose_code="SYNTHETIC_RESTRICTED_QUERY",
            entities=(restricted,),
            providers=ProviderRegistry((provider,)),
            policy=ProviderPolicy(mode=PolicyMode.EU_ONLY, revision=1),
            budget=RunBudget(1, 1),
        )
    with manager.engine.connect() as connection:
        assert connection.execute(select(repository.checks.c.id)).all() == []
    repository.close()
    manager.lock()


def test_one_time_approval_budget_and_failure_states_are_durable(tmp_path) -> None:
    manager, profile_id, entities, repository = _fixture(tmp_path)
    service = QueryPolicyService(repository)
    provider = _external_provider()
    policy = ProviderPolicy(mode=PolicyMode.EU_ONLY, revision=7)
    record = service.create_plan(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_APPROVED_QUERY",
        entities=entities,
        providers=ProviderRegistry((provider,)),
        policy=policy,
        budget=RunBudget(1, 1),
    )
    first, second = record.plan.checks
    assert first.state is CheckState.APPROVAL_REQUIRED
    assert second.state is CheckState.NOT_CHECKED
    grant = repository.issue_approval(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        run_id=record.run_id,
        check_id=first.check_id,
        ttl_us=60_000_000,
    )
    adapter = RecordingAdapter(provider.adapter, fail=True)
    failed = service.execute(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_APPROVED_QUERY",
        run_id=record.run_id,
        compiled=first,
        entity=entities[0],
        provider=provider,
        policy=policy,
        adapter=adapter,
        approval_token=grant.token,
    )
    assert failed.state is CheckState.CHECK_FAILED
    assert adapter.values == [entities[0].query_value]
    assert (
        repository.reserve_budget(
            vault_id=manager.manifest.vault_id,
            profile_id=profile_id,
            run_id=record.run_id,
            provider_id=provider.provider_id,
        )
        is False
    )
    assert (
        repository.consume_approval(
            vault_id=manager.manifest.vault_id,
            profile_id=profile_id,
            run_id=record.run_id,
            check_id=first.check_id,
            token=grant.token,
        )
        is False
    )

    second_result = service.execute(
        vault_id=manager.manifest.vault_id,
        profile_id=profile_id,
        purpose_code="SYNTHETIC_APPROVED_QUERY",
        run_id=record.run_id,
        compiled=second,
        entity=entities[1],
        provider=provider,
        policy=policy,
        adapter=adapter,
    )
    assert second_result.state is CheckState.NOT_CHECKED
    assert adapter.values == [entities[0].query_value]

    with manager.engine.connect() as connection:
        approval_rows = connection.execute(select(repository.approvals)).mappings().all()
        ledger_rows = connection.execute(select(repository.ledger)).mappings().all()
    assert len(approval_rows) == len(ledger_rows) == 1
    assert grant.token not in str(approval_rows)
    assert entities[0].query_value not in str(ledger_rows)
    repository.close()
    manager.lock()
