"""Encrypted persistence for Phase 4 query policy state and disclosure accounting."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field

from sqlalchemy import MetaData, Table, and_, insert, select, update
from sqlalchemy.engine import Engine, RowMapping
from uuid6 import uuid7

from ariadne_core.domain.query_policy import (
    AccessBasis,
    ApprovedEntity,
    CheckState,
    CompiledCheck,
    CoverageOutcome,
    PolicyMode,
    ProviderMetadata,
    ProviderPolicy,
    RunBudget,
    SearchPolicy,
    Sensitivity,
    TransmissionPolicy,
)
from ariadne_core.infrastructure.db.repositories import now_us


@dataclass(frozen=True, slots=True)
class StoredCheck:
    id: str
    run_id: str
    entity_id: str
    provider_id: str
    query_class: str
    masked_query: str = field(repr=False)
    query_hmac: str = field(repr=False)
    entity_revision: int
    sensitivity_snapshot: str
    search_policy_snapshot: str
    transmission_policy_snapshot: str
    state: CheckState
    outcome: CoverageOutcome
    reason_code: str
    requires_approval: bool
    revision: int


@dataclass(frozen=True, slots=True)
class OneTimeApproval:
    approval_id: str
    token: str = field(repr=False)
    expires_at_us: int


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    id: str
    check_id: str
    provider_id: str
    masked_display: str = field(repr=False)
    payload_hmac: str = field(repr=False)
    verdict: str
    result_code: str


@dataclass(frozen=True, slots=True)
class RunContext:
    purpose_code: str
    policy: ProviderPolicy


class QueryPolicyRepository:
    """Profile-scoped state whose HMAC key is held only in mutable memory."""

    def __init__(self, engine: Engine, *, policy_hmac_key: bytes | bytearray) -> None:
        if len(policy_hmac_key) != 32:
            raise ValueError("query policy HMAC key must contain exactly 256 bits")
        self.engine = engine
        self._key = bytearray(policy_hmac_key)
        metadata = MetaData()
        self.providers = Table("phase4_providers", metadata, autoload_with=engine)
        self.profiles = Table("profiles", metadata, autoload_with=engine)
        self.entities = Table("entities", metadata, autoload_with=engine)
        self.runs = Table("phase4_query_runs", metadata, autoload_with=engine)
        self.usage = Table("phase4_provider_budget_usage", metadata, autoload_with=engine)
        self.checks = Table("phase4_query_checks", metadata, autoload_with=engine)
        self.approvals = Table("phase4_one_time_approvals", metadata, autoload_with=engine)
        self.ledger = Table("phase4_transmission_ledger", metadata, autoload_with=engine)
        self._closed = False

    def close(self) -> None:
        self._key[:] = b"\x00" * len(self._key)
        self._closed = True

    def _hmac(self, purpose: str, value: str) -> str:
        if self._closed:
            raise RuntimeError("query policy HMAC key is unavailable")
        return hmac.new(
            self._key,
            f"ariadne:{purpose}:v1:{value}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def register_provider(self, *, vault_id: str, provider: ProviderMetadata) -> None:
        timestamp = now_us()
        values = {
            "display_name": provider.display_name,
            "operator_name": provider.operator,
            "adapter_id": provider.adapter.adapter_id,
            "adapter_mode": provider.adapter.mode.value,
            "adapter_network_access": int(provider.adapter.network_access),
            "adapter_sends_identifiers": int(provider.adapter.sends_identifiers),
            "adapter_query_classes_json": json.dumps(
                sorted(provider.adapter.supported_query_classes)
            ),
            "access_basis": provider.access_basis.value,
            "processing_regions_json": json.dumps(sorted(provider.processing_regions)),
            "external": int(provider.external),
            "enabled": int(provider.enabled),
            "retention_known": int(provider.retention_known),
            "updated_at_us": timestamp,
        }
        with self.engine.begin() as connection:
            current = (
                connection.execute(
                    select(self.providers).where(
                        and_(
                            self.providers.c.vault_id == vault_id,
                            self.providers.c.id == provider.provider_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if current is None:
                connection.execute(
                    insert(self.providers).values(
                        vault_id=vault_id,
                        id=provider.provider_id,
                        created_at_us=timestamp,
                        revision=1,
                        **values,
                    )
                )
                return
            comparable = {key: current[key] for key in values if key != "updated_at_us"}
            expected = {key: value for key, value in values.items() if key != "updated_at_us"}
            if comparable == expected:
                return
            referenced = connection.execute(
                select(self.checks.c.id)
                .where(
                    and_(
                        self.checks.c.vault_id == vault_id,
                        self.checks.c.provider_id == provider.provider_id,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            if referenced is not None:
                raise ValueError("provider metadata is immutable after query planning")
            connection.execute(
                update(self.providers)
                .where(
                    and_(
                        self.providers.c.vault_id == vault_id,
                        self.providers.c.id == provider.provider_id,
                    )
                )
                .values(**values, revision=self.providers.c.revision + 1)
            )

    def create_run(
        self,
        *,
        vault_id: str,
        profile_id: str,
        purpose_code: str,
        policy: ProviderPolicy,
        budget: RunBudget,
    ) -> str:
        if (
            not purpose_code
            or len(purpose_code) > 96
            or any(ord(character) < 32 for character in purpose_code)
        ):
            raise ValueError("query purpose code is invalid")
        run_id = str(uuid7())
        timestamp = now_us()
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.runs).values(
                    id=run_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    purpose_code=purpose_code,
                    policy_mode=policy.mode.value,
                    policy_revision=policy.revision,
                    policy_json=self._policy_payload(policy),
                    policy_hmac=self._policy_hmac(policy),
                    maximum_checks=budget.maximum_checks,
                    maximum_checks_per_provider=budget.maximum_checks_per_provider,
                    used_checks=0,
                    state="PLANNED",
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                )
            )
        return run_id

    def profile_is_active(self, *, vault_id: str, profile_id: str) -> bool:
        with self.engine.connect() as connection:
            status = connection.execute(
                select(self.profiles.c.status).where(
                    and_(
                        self.profiles.c.vault_id == vault_id,
                        self.profiles.c.id == profile_id,
                    )
                )
            ).scalar_one_or_none()
        return status == "ACTIVE"

    def get_run_context(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
    ) -> RunContext:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.runs).where(
                        and_(
                            self.runs.c.vault_id == vault_id,
                            self.runs.c.profile_id == profile_id,
                            self.runs.c.id == run_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError("query run is unavailable")
        try:
            payload = json.loads(str(row["policy_json"]))
            policy = ProviderPolicy(
                mode=PolicyMode(str(payload["mode"])),
                revision=int(payload["revision"]),
                allowed_provider_ids=frozenset(payload["allowedProviderIds"]),
                blocked_provider_ids=frozenset(payload["blockedProviderIds"]),
                allowed_regions=frozenset(payload["allowedRegions"]),
                allowed_access_bases=frozenset(
                    AccessBasis(item) for item in payload["allowedAccessBases"]
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise RuntimeError("stored query policy is invalid") from None
        if not hmac.compare_digest(str(row["policy_hmac"]), self._policy_hmac(policy)):
            raise RuntimeError("stored query policy binding is invalid")
        return RunContext(purpose_code=str(row["purpose_code"]), policy=policy)

    def approved_entity_is_current(
        self,
        *,
        vault_id: str,
        profile_id: str,
        entity: ApprovedEntity,
    ) -> bool:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.entities).where(
                        and_(
                            self.entities.c.vault_id == vault_id,
                            self.entities.c.profile_id == profile_id,
                            self.entities.c.id == entity.entity_id,
                            self.entities.c.deleted_at_us.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return row is not None and (
            str(row["canonical_value"]) == entity.query_value
            and str(row["display_mask"]) == entity.masked_display
            and str(row["sensitivity"]) == entity.sensitivity.value
            and str(row["review_state"]) == "CONFIRMED"
            and str(row["search_policy"]) == entity.search_policy.value
            and str(row["transmission_policy"]) == entity.transmission_policy.value
            and int(row["revision"]) == entity.revision
        )

    def list_confirmed_entities(
        self,
        *,
        vault_id: str,
        profile_id: str,
        limit: int = 100,
    ) -> tuple[ApprovedEntity, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("confirmed entity limit is invalid")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.entities)
                    .where(
                        and_(
                            self.entities.c.vault_id == vault_id,
                            self.entities.c.profile_id == profile_id,
                            self.entities.c.review_state == "CONFIRMED",
                            self.entities.c.deleted_at_us.is_(None),
                        )
                    )
                    .order_by(self.entities.c.created_at_us, self.entities.c.id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(
            ApprovedEntity(
                entity_id=str(row["id"]),
                entity_type=str(row["entity_type"]),
                query_value=str(row["canonical_value"]),
                masked_display=str(row["display_mask"]),
                sensitivity=Sensitivity(str(row["sensitivity"])),
                search_policy=SearchPolicy(str(row["search_policy"])),
                transmission_policy=TransmissionPolicy(str(row["transmission_policy"])),
                revision=int(row["revision"]),
            )
            for row in rows
        )

    def get_confirmed_entity(
        self,
        *,
        vault_id: str,
        profile_id: str,
        entity_id: str,
    ) -> ApprovedEntity:
        matches = tuple(
            entity
            for entity in self.list_confirmed_entities(
                vault_id=vault_id,
                profile_id=profile_id,
                limit=100,
            )
            if entity.entity_id == entity_id
        )
        if len(matches) != 1:
            raise LookupError("confirmed query entity is unavailable")
        return matches[0]

    def persist_checks(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        checks: tuple[CompiledCheck, ...],
    ) -> tuple[StoredCheck, ...]:
        timestamp = now_us()
        with self.engine.begin() as connection:
            for check in checks:
                connection.execute(
                    insert(self.checks).values(
                        id=check.check_id,
                        vault_id=vault_id,
                        profile_id=profile_id,
                        run_id=run_id,
                        entity_id=check.entity_id,
                        provider_id=check.provider_id,
                        query_class=check.query_class,
                        masked_query=check.masked_query,
                        query_hmac=self._hmac("query", check.query_value),
                        entity_revision=check.entity_revision,
                        sensitivity_snapshot=check.sensitivity.value,
                        search_policy_snapshot=check.search_policy.value,
                        transmission_policy_snapshot=check.transmission_policy.value,
                        state=check.state.value,
                        outcome=check.outcome.value,
                        reason_code=check.reason_code,
                        requires_approval=int(check.requires_approval),
                        created_at_us=timestamp,
                        updated_at_us=timestamp,
                        revision=1,
                    )
                )
        return tuple(
            self.get_check(vault_id, profile_id, run_id, check.check_id) for check in checks
        )

    def get_check(
        self,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check_id: str,
    ) -> StoredCheck:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.checks).where(
                        and_(
                            self.checks.c.vault_id == vault_id,
                            self.checks.c.profile_id == profile_id,
                            self.checks.c.run_id == run_id,
                            self.checks.c.id == check_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise LookupError("query check is unavailable")
        return self._stored_check(row)

    def dispatch_binding_is_valid(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check: StoredCheck,
        query_value: str,
        provider: ProviderMetadata,
        policy: ProviderPolicy,
    ) -> bool:
        with self.engine.connect() as connection:
            run = (
                connection.execute(
                    select(self.runs).where(
                        and_(
                            self.runs.c.vault_id == vault_id,
                            self.runs.c.profile_id == profile_id,
                            self.runs.c.id == run_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            provider_row = (
                connection.execute(
                    select(self.providers).where(
                        and_(
                            self.providers.c.vault_id == vault_id,
                            self.providers.c.id == provider.provider_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            entity_row = (
                connection.execute(
                    select(self.entities).where(
                        and_(
                            self.entities.c.vault_id == vault_id,
                            self.entities.c.profile_id == profile_id,
                            self.entities.c.id == check.entity_id,
                            self.entities.c.deleted_at_us.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if run is None or provider_row is None or entity_row is None:
            return False
        expected_provider = {
            "adapter_id": provider.adapter.adapter_id,
            "adapter_mode": provider.adapter.mode.value,
            "adapter_network_access": int(provider.adapter.network_access),
            "adapter_sends_identifiers": int(provider.adapter.sends_identifiers),
            "adapter_query_classes_json": json.dumps(
                sorted(provider.adapter.supported_query_classes)
            ),
            "access_basis": provider.access_basis.value,
            "processing_regions_json": json.dumps(sorted(provider.processing_regions)),
            "external": int(provider.external),
            "enabled": int(provider.enabled),
            "retention_known": int(provider.retention_known),
        }
        return (
            hmac.compare_digest(check.query_hmac, self._hmac("query", query_value))
            and str(run["policy_mode"]) == policy.mode.value
            and int(run["policy_revision"]) == policy.revision
            and hmac.compare_digest(str(run["policy_hmac"]), self._policy_hmac(policy))
            and all(provider_row[key] == value for key, value in expected_provider.items())
            and str(entity_row["canonical_value"]) == query_value
            and str(entity_row["display_mask"]) == check.masked_query
            and str(entity_row["review_state"]) == "CONFIRMED"
            and int(entity_row["revision"]) == check.entity_revision
            and str(entity_row["sensitivity"]) == check.sensitivity_snapshot
            and str(entity_row["search_policy"]) == check.search_policy_snapshot
            and str(entity_row["transmission_policy"]) == check.transmission_policy_snapshot
        )

    def reserve_budget(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        provider_id: str,
    ) -> bool:
        """Atomically reserve both run and provider budgets before dispatch."""

        timestamp = now_us()
        with self.engine.connect() as connection:
            try:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                run = (
                    connection.execute(
                        select(self.runs).where(
                            and_(
                                self.runs.c.vault_id == vault_id,
                                self.runs.c.profile_id == profile_id,
                                self.runs.c.id == run_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if run is None:
                    raise LookupError("query run is unavailable")
                usage = (
                    connection.execute(
                        select(self.usage).where(
                            and_(
                                self.usage.c.vault_id == vault_id,
                                self.usage.c.profile_id == profile_id,
                                self.usage.c.run_id == run_id,
                                self.usage.c.provider_id == provider_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                provider_used = 0 if usage is None else int(usage["used_checks"])
                if int(run["used_checks"]) >= int(run["maximum_checks"]) or provider_used >= int(
                    run["maximum_checks_per_provider"]
                ):
                    connection.rollback()
                    return False
                connection.execute(
                    update(self.runs)
                    .where(
                        and_(
                            self.runs.c.vault_id == vault_id,
                            self.runs.c.profile_id == profile_id,
                            self.runs.c.id == run_id,
                            self.runs.c.used_checks == int(run["used_checks"]),
                        )
                    )
                    .values(
                        used_checks=int(run["used_checks"]) + 1,
                        state="RUNNING",
                        updated_at_us=timestamp,
                        revision=self.runs.c.revision + 1,
                    )
                )
                if usage is None:
                    connection.execute(
                        insert(self.usage).values(
                            vault_id=vault_id,
                            profile_id=profile_id,
                            run_id=run_id,
                            provider_id=provider_id,
                            used_checks=1,
                            updated_at_us=timestamp,
                        )
                    )
                else:
                    connection.execute(
                        update(self.usage)
                        .where(
                            and_(
                                self.usage.c.vault_id == vault_id,
                                self.usage.c.profile_id == profile_id,
                                self.usage.c.run_id == run_id,
                                self.usage.c.provider_id == provider_id,
                            )
                        )
                        .values(used_checks=provider_used + 1, updated_at_us=timestamp)
                    )
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

    def issue_approval(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check_id: str,
        ttl_us: int,
    ) -> OneTimeApproval:
        if not 1_000_000 <= ttl_us <= 3_600_000_000:
            raise ValueError("approval lifetime is outside the allowed range")
        check = self.get_check(vault_id, profile_id, run_id, check_id)
        if not check.requires_approval:
            raise ValueError("query check does not require approval")
        token = secrets.token_urlsafe(32)
        approval_id = str(uuid7())
        timestamp = now_us()
        expires_at = timestamp + ttl_us
        binding = self._approval_binding(check)
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.approvals).values(
                    id=approval_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    run_id=run_id,
                    check_id=check.id,
                    entity_id=check.entity_id,
                    provider_id=check.provider_id,
                    token_hmac=self._hmac("approval-token", token),
                    binding_hmac=binding,
                    expires_at_us=expires_at,
                    created_at_us=timestamp,
                    consumed_at_us=None,
                )
            )
        return OneTimeApproval(approval_id, token, expires_at)

    def consume_approval(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check_id: str,
        token: str,
    ) -> bool:
        check = self.get_check(vault_id, profile_id, run_id, check_id)
        timestamp = now_us()
        token_hmac = self._hmac("approval-token", token)
        binding_hmac = self._approval_binding(check)
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(self.approvals)
                .where(
                    and_(
                        self.approvals.c.vault_id == vault_id,
                        self.approvals.c.profile_id == profile_id,
                        self.approvals.c.run_id == run_id,
                        self.approvals.c.check_id == check_id,
                        self.approvals.c.token_hmac == token_hmac,
                        self.approvals.c.binding_hmac == binding_hmac,
                        self.approvals.c.expires_at_us > timestamp,
                        self.approvals.c.consumed_at_us.is_(None),
                    )
                )
                .values(consumed_at_us=timestamp)
            )
        return changed.rowcount == 1

    def update_check(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check_id: str,
        state: CheckState,
        outcome: CoverageOutcome,
        reason_code: str,
    ) -> StoredCheck:
        timestamp = now_us()
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(self.checks)
                .where(
                    and_(
                        self.checks.c.vault_id == vault_id,
                        self.checks.c.profile_id == profile_id,
                        self.checks.c.run_id == run_id,
                        self.checks.c.id == check_id,
                    )
                )
                .values(
                    state=state.value,
                    outcome=outcome.value,
                    reason_code=reason_code,
                    updated_at_us=timestamp,
                    revision=self.checks.c.revision + 1,
                )
            )
        if changed.rowcount != 1:
            raise LookupError("query check is unavailable")
        return self.get_check(vault_id, profile_id, run_id, check_id)

    def append_ledger(
        self,
        *,
        vault_id: str,
        profile_id: str,
        run_id: str,
        check: StoredCheck,
        provider: ProviderMetadata,
        payload: str,
        purpose_code: str,
        verdict: str,
        result_code: str,
    ) -> LedgerRecord:
        record_id = str(uuid7())
        jurisdiction = (
            "LOCAL" if not provider.external else ",".join(sorted(provider.processing_regions))
        )
        payload_hmac = self._hmac("ledger-payload", payload)
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.ledger).values(
                    id=record_id,
                    vault_id=vault_id,
                    profile_id=profile_id,
                    run_id=run_id,
                    check_id=check.id,
                    provider_id=provider.provider_id,
                    masked_display=check.masked_query,
                    payload_hmac=payload_hmac,
                    purpose_code=purpose_code,
                    jurisdiction=jurisdiction,
                    access_basis=provider.access_basis.value,
                    verdict=verdict,
                    result_code=result_code,
                    attempted_at_us=now_us(),
                )
            )
        return LedgerRecord(
            record_id,
            check.id,
            provider.provider_id,
            check.masked_query,
            payload_hmac,
            verdict,
            result_code,
        )

    def _approval_binding(self, check: StoredCheck) -> str:
        value = json.dumps(
            {
                "checkId": check.id,
                "entityId": check.entity_id,
                "providerId": check.provider_id,
                "queryHmac": check.query_hmac,
                "runId": check.run_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return self._hmac("approval-binding", value)

    def _policy_hmac(self, policy: ProviderPolicy) -> str:
        return self._hmac("provider-policy", self._policy_payload(policy))

    @staticmethod
    def _policy_payload(policy: ProviderPolicy) -> str:
        return json.dumps(
            {
                "allowedAccessBases": sorted(item.value for item in policy.allowed_access_bases),
                "allowedProviderIds": sorted(policy.allowed_provider_ids),
                "allowedRegions": sorted(policy.allowed_regions),
                "blockedProviderIds": sorted(policy.blocked_provider_ids),
                "mode": policy.mode.value,
                "revision": policy.revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _stored_check(row: RowMapping) -> StoredCheck:
        return StoredCheck(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            entity_id=str(row["entity_id"]),
            provider_id=str(row["provider_id"]),
            query_class=str(row["query_class"]),
            masked_query=str(row["masked_query"]),
            query_hmac=str(row["query_hmac"]),
            entity_revision=int(row["entity_revision"]),
            sensitivity_snapshot=str(row["sensitivity_snapshot"]),
            search_policy_snapshot=str(row["search_policy_snapshot"]),
            transmission_policy_snapshot=str(row["transmission_policy_snapshot"]),
            state=CheckState(str(row["state"])),
            outcome=CoverageOutcome(str(row["outcome"])),
            reason_code=str(row["reason_code"]),
            requires_approval=bool(row["requires_approval"]),
            revision=int(row["revision"]),
        )
