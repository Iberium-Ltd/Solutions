"""Fail-closed query planning and transmission policy primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_REGION = re.compile(r"^[A-Z]{2}$")
EU_EEA_REGIONS = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    }
)


def _identifier(value: str, label: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _bounded(value: str, label: str, maximum: int) -> str:
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} is invalid")
    return value


class AccessBasis(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    PUBLIC = "PUBLIC"
    USER_AUTHORISED = "USER_AUTHORISED"


class PolicyMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    EU_ONLY = "EU_ONLY"
    CUSTOM = "CUSTOM"


class Sensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    SENSITIVE = "SENSITIVE"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE"
    RESTRICTED = "RESTRICTED"


class SearchPolicy(StrEnum):
    ALLOW = "SEARCH_ALLOWED"
    REQUIRE_APPROVAL = "APPROVAL_REQUIRED"
    STORE_ONLY = "STORE_ONLY"
    DENY = "SEARCH_DENIED"


class TransmissionPolicy(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    REQUIRE_APPROVAL = "APPROVAL_REQUIRED"
    PROVIDER_ALLOWLIST = "PROVIDER_ALLOWLIST"
    DENY = "TRANSMISSION_DENIED"


class PolicyVerdict(StrEnum):
    ALLOW_LOCAL = "ALLOW_LOCAL"
    ALLOW_EXTERNAL = "ALLOW_EXTERNAL"
    REQUIRE_ONE_TIME_APPROVAL = "REQUIRE_ONE_TIME_APPROVAL"
    DENY = "DENY"


class CheckState(StrEnum):
    PLANNED = "PLANNED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    NOT_CHECKED = "NOT_CHECKED"
    BLOCKED = "BLOCKED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    CHECK_FAILED = "CHECK_FAILED"


class CoverageOutcome(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    CHECK_FAILED = "CHECK_FAILED"


class AdapterMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    MANUAL_LOCAL = "MANUAL_LOCAL"
    AUTOMATED = "AUTOMATED"


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    adapter_id: str
    mode: AdapterMode
    network_access: bool
    sends_identifiers: bool
    supported_query_classes: frozenset[str]

    def __post_init__(self) -> None:
        _identifier(self.adapter_id, "adapter id")
        if not self.supported_query_classes:
            raise ValueError("adapter query classes are required")
        if self.mode in {AdapterMode.DRY_RUN, AdapterMode.MANUAL_LOCAL} and (
            self.network_access or self.sends_identifiers
        ):
            raise ValueError("local adapter manifests cannot transmit identifiers")


DRY_RUN_LOCAL_MANIFEST = AdapterManifest(
    adapter_id="dry-run-local",
    mode=AdapterMode.DRY_RUN,
    network_access=False,
    sends_identifiers=False,
    supported_query_classes=frozenset({"EXACT", "VARIANT"}),
)
MANUAL_LOCAL_MANIFEST = AdapterManifest(
    adapter_id="manual-local",
    mode=AdapterMode.MANUAL_LOCAL,
    network_access=False,
    sends_identifiers=False,
    supported_query_classes=frozenset({"EXACT"}),
)


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    operator: str
    adapter: AdapterManifest
    access_basis: AccessBasis
    processing_regions: frozenset[str]
    external: bool
    enabled: bool
    retention_known: bool

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider id")
        _bounded(self.display_name, "provider display name", 96)
        _bounded(self.operator, "provider operator", 128)
        if any(_REGION.fullmatch(region) is None for region in self.processing_regions):
            raise ValueError("provider processing region is invalid")
        if self.external and not self.processing_regions:
            raise ValueError("external provider processing regions are required")
        if self.external != self.adapter.sends_identifiers:
            raise ValueError("provider and adapter transmission metadata disagree")
        if not self.external and self.access_basis is not AccessBasis.LOCAL_ONLY:
            raise ValueError("local provider requires a local-only access basis")


class ProviderRegistry:
    def __init__(self, providers: tuple[ProviderMetadata, ...]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        by_id = {provider.provider_id: provider for provider in providers}
        if len(by_id) != len(providers):
            raise ValueError("provider ids must be unique")
        self._providers = by_id

    def get(self, provider_id: str) -> ProviderMetadata:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise LookupError("provider is unavailable") from error

    def all(self) -> tuple[ProviderMetadata, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    mode: PolicyMode
    revision: int
    allowed_provider_ids: frozenset[str] = frozenset()
    blocked_provider_ids: frozenset[str] = frozenset()
    allowed_regions: frozenset[str] = frozenset()
    allowed_access_bases: frozenset[AccessBasis] = frozenset(
        {AccessBasis.LOCAL_ONLY, AccessBasis.PUBLIC}
    )

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("policy revision must be positive")
        if self.allowed_provider_ids & self.blocked_provider_ids:
            raise ValueError("provider policy allow/block lists overlap")
        if any(_IDENTIFIER.fullmatch(item) is None for item in self.allowed_provider_ids):
            raise ValueError("provider allowlist is invalid")
        if any(_IDENTIFIER.fullmatch(item) is None for item in self.blocked_provider_ids):
            raise ValueError("provider blocklist is invalid")
        if any(_REGION.fullmatch(item) is None for item in self.allowed_regions):
            raise ValueError("provider region allowlist is invalid")
        if self.mode is PolicyMode.CUSTOM and not self.allowed_provider_ids:
            raise ValueError("custom provider policy requires an explicit allowlist")


@dataclass(frozen=True, slots=True)
class ApprovedEntity:
    entity_id: str
    entity_type: str
    query_value: str = field(repr=False)
    masked_display: str = field(repr=False)
    sensitivity: Sensitivity
    search_policy: SearchPolicy
    transmission_policy: TransmissionPolicy
    revision: int

    def __post_init__(self) -> None:
        _bounded(self.query_value, "entity query value", 2_048)
        _bounded(self.masked_display, "entity display mask", 512)
        _bounded(self.entity_type, "entity type", 32)
        if self.revision < 1:
            raise ValueError("entity revision must be positive")


@dataclass(frozen=True, slots=True)
class RunBudget:
    maximum_checks: int
    maximum_checks_per_provider: int

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_checks <= 10_000:
            raise ValueError("run check budget is invalid")
        if not 1 <= self.maximum_checks_per_provider <= self.maximum_checks:
            raise ValueError("provider check budget is invalid")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    verdict: PolicyVerdict
    reason_code: str


@dataclass(frozen=True, slots=True)
class CompiledCheck:
    check_id: str
    entity_id: str
    provider_id: str
    query_class: str
    query_value: str = field(repr=False)
    masked_query: str = field(repr=False)
    entity_revision: int
    sensitivity: Sensitivity
    search_policy: SearchPolicy
    transmission_policy: TransmissionPolicy
    state: CheckState
    outcome: CoverageOutcome
    reason_code: str
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class QueryPlan:
    checks: tuple[CompiledCheck, ...]
    planned_count: int
    not_checked_count: int
    blocked_count: int
    approval_required_count: int


def evaluate_policy(
    entity: ApprovedEntity,
    provider: ProviderMetadata,
    policy: ProviderPolicy,
) -> PolicyDecision:
    """Evaluate metadata only; never hand a denied query value to an adapter."""

    if entity.sensitivity is Sensitivity.RESTRICTED:
        return PolicyDecision(PolicyVerdict.DENY, "RESTRICTED_VALUE")
    if entity.search_policy in {SearchPolicy.DENY, SearchPolicy.STORE_ONLY}:
        return PolicyDecision(PolicyVerdict.DENY, "ENTITY_SEARCH_DENIED")
    if not provider.enabled:
        return PolicyDecision(PolicyVerdict.DENY, "PROVIDER_DISABLED")
    if entity.query_value == "":
        return PolicyDecision(PolicyVerdict.DENY, "EMPTY_QUERY")
    if not provider.external:
        if (
            entity.search_policy is SearchPolicy.REQUIRE_APPROVAL
            or entity.sensitivity is Sensitivity.HIGHLY_SENSITIVE
        ):
            return PolicyDecision(
                PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL,
                "ONE_TIME_APPROVAL_REQUIRED",
            )
        return PolicyDecision(PolicyVerdict.ALLOW_LOCAL, "LOCAL_NO_TRANSMISSION")
    if provider.provider_id in policy.blocked_provider_ids:
        return PolicyDecision(PolicyVerdict.DENY, "PROVIDER_BLOCKED")
    if provider.access_basis not in policy.allowed_access_bases:
        return PolicyDecision(PolicyVerdict.DENY, "ACCESS_BASIS_BLOCKED")
    if policy.mode is PolicyMode.LOCAL_ONLY:
        return PolicyDecision(PolicyVerdict.DENY, "LOCAL_ONLY_POLICY")
    if policy.mode is PolicyMode.EU_ONLY and not provider.processing_regions <= EU_EEA_REGIONS:
        return PolicyDecision(PolicyVerdict.DENY, "JURISDICTION_BLOCKED")
    if policy.mode is PolicyMode.CUSTOM:
        if provider.provider_id not in policy.allowed_provider_ids:
            return PolicyDecision(PolicyVerdict.DENY, "PROVIDER_NOT_ALLOWLISTED")
        if policy.allowed_regions and not provider.processing_regions <= policy.allowed_regions:
            return PolicyDecision(PolicyVerdict.DENY, "JURISDICTION_BLOCKED")
    if entity.transmission_policy in {
        TransmissionPolicy.LOCAL_ONLY,
        TransmissionPolicy.DENY,
    }:
        return PolicyDecision(PolicyVerdict.DENY, "ENTITY_TRANSMISSION_DENIED")
    if (
        entity.search_policy is SearchPolicy.REQUIRE_APPROVAL
        or entity.transmission_policy is TransmissionPolicy.REQUIRE_APPROVAL
        or entity.sensitivity is Sensitivity.HIGHLY_SENSITIVE
    ):
        return PolicyDecision(
            PolicyVerdict.REQUIRE_ONE_TIME_APPROVAL,
            "ONE_TIME_APPROVAL_REQUIRED",
        )
    return PolicyDecision(PolicyVerdict.ALLOW_EXTERNAL, "POLICY_ALLOWED")
