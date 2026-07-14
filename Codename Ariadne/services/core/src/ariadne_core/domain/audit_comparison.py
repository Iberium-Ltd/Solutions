"""Immutable audit snapshots and deterministic finding lifecycle comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Final

MAX_SNAPSHOTS: Final = 32
MAX_FINDINGS_PER_SNAPSHOT: Final = 2_000
MAX_PROVIDERS_PER_SNAPSHOT: Final = 256
MAX_UNIQUE_FINDINGS: Final = 5_000
MAX_COMPARISON_ITEMS: Final = 4_000
MAX_LIFECYCLE_EVENTS: Final = 128_000

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SnapshotRunState(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ProviderCoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    NOT_CHECKED = "NOT_CHECKED"
    BLOCKED = "BLOCKED"
    CHECK_FAILED = "CHECK_FAILED"


class FindingDiffState(StrEnum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    REMOVED = "REMOVED"
    UNCHANGED = "UNCHANGED"
    REAPPEARED = "REAPPEARED"


class ComparisonIncompleteReason(StrEnum):
    BASELINE_RUN_INCOMPLETE = "BASELINE_RUN_INCOMPLETE"
    CURRENT_RUN_INCOMPLETE = "CURRENT_RUN_INCOMPLETE"
    BASELINE_COVERAGE_INCOMPLETE = "BASELINE_COVERAGE_INCOMPLETE"
    CURRENT_COVERAGE_INCOMPLETE = "CURRENT_COVERAGE_INCOMPLETE"
    UNRESOLVED_ABSENCE = "UNRESOLVED_ABSENCE"
    HISTORY_GAP = "HISTORY_GAP"


def _validate_id(value: str, label: str) -> None:
    if _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


@dataclass(frozen=True, slots=True)
class FindingSnapshot:
    stable_id: str
    provider_id: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        _validate_id(self.stable_id, "stable finding id")
        _validate_id(self.provider_id, "provider id")
        if _SHA256.fullmatch(self.content_fingerprint) is None:
            raise ValueError("finding content fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class ProviderCoverage:
    provider_id: str
    state: ProviderCoverageState

    def __post_init__(self) -> None:
        _validate_id(self.provider_id, "provider id")
        if not isinstance(self.state, ProviderCoverageState):
            raise TypeError("provider coverage state is invalid")


@dataclass(frozen=True, slots=True)
class AuditRunSnapshot:
    run_id: str
    sequence: int
    captured_at_us: int
    run_state: SnapshotRunState
    findings: tuple[FindingSnapshot, ...]
    provider_coverage: tuple[ProviderCoverage, ...]

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "audit run id")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("audit run sequence is invalid")
        if type(self.captured_at_us) is not int or self.captured_at_us < 1:
            raise ValueError("audit snapshot time is invalid")
        if not isinstance(self.run_state, SnapshotRunState):
            raise TypeError("audit run state is invalid")
        if type(self.findings) is not tuple or len(self.findings) > MAX_FINDINGS_PER_SNAPSHOT:
            raise ValueError("audit snapshot findings are outside the allowed bounds")
        if (
            type(self.provider_coverage) is not tuple
            or not self.provider_coverage
            or len(self.provider_coverage) > MAX_PROVIDERS_PER_SNAPSHOT
        ):
            raise ValueError("audit snapshot provider coverage is outside the allowed bounds")
        finding_ids = tuple(finding.stable_id for finding in self.findings)
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("audit snapshot finding ids must be unique")
        coverage_ids = tuple(item.provider_id for item in self.provider_coverage)
        if len(set(coverage_ids)) != len(coverage_ids):
            raise ValueError("audit snapshot provider coverage must be unique")
        coverage_by_provider = {item.provider_id: item.state for item in self.provider_coverage}
        if any(finding.provider_id not in coverage_by_provider for finding in self.findings):
            raise ValueError("every finding requires provider coverage")
        if any(
            coverage_by_provider[finding.provider_id]
            in {ProviderCoverageState.NOT_CHECKED, ProviderCoverageState.BLOCKED}
            for finding in self.findings
        ):
            raise ValueError("observed findings require attempted provider coverage")


@dataclass(frozen=True, slots=True)
class FindingDiff:
    stable_id: str
    provider_id: str
    state: FindingDiffState
    previous_fingerprint: str | None
    current_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class UnresolvedAbsence:
    stable_id: str
    provider_id: str
    previous_fingerprint: str
    current_coverage: ProviderCoverageState | None


@dataclass(frozen=True, slots=True)
class ProviderCoverageComparison:
    provider_id: str
    baseline_state: ProviderCoverageState | None
    current_state: ProviderCoverageState | None


@dataclass(frozen=True, slots=True)
class FindingLifecycleEvent:
    run_id: str
    sequence: int
    run_state: SnapshotRunState
    provider_coverage: ProviderCoverageState | None
    observed: bool
    content_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class FindingLifecycle:
    stable_id: str
    provider_id: str
    events: tuple[FindingLifecycleEvent, ...]


@dataclass(frozen=True, slots=True)
class AuditComparison:
    baseline_run_id: str
    current_run_id: str
    diffs: tuple[FindingDiff, ...]
    unresolved_absences: tuple[UnresolvedAbsence, ...]
    coverage: tuple[ProviderCoverageComparison, ...]
    lifecycles: tuple[FindingLifecycle, ...]
    incomplete_comparison: bool
    incomplete_reasons: tuple[ComparisonIncompleteReason, ...]


def _snapshot_maps(
    snapshot: AuditRunSnapshot,
) -> tuple[dict[str, FindingSnapshot], dict[str, ProviderCoverageState]]:
    return (
        {finding.stable_id: finding for finding in snapshot.findings},
        {item.provider_id: item.state for item in snapshot.provider_coverage},
    )


def _validate_timeline(snapshots: tuple[AuditRunSnapshot, ...]) -> None:
    if type(snapshots) is not tuple or len(snapshots) < 2 or len(snapshots) > MAX_SNAPSHOTS:
        raise ValueError("audit comparison timeline is outside the allowed bounds")
    run_ids = tuple(snapshot.run_id for snapshot in snapshots)
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("audit run ids must be unique")
    sequences = tuple(snapshot.sequence for snapshot in snapshots)
    if any(current <= previous for previous, current in pairwise(sequences)):
        raise ValueError("audit snapshot sequences must increase")
    captured = tuple(snapshot.captured_at_us for snapshot in snapshots)
    if any(current <= previous for previous, current in pairwise(captured)):
        raise ValueError("audit snapshot times must increase")

    provider_by_finding: dict[str, str] = {}
    unique_findings: set[str] = set()
    for snapshot in snapshots:
        for finding in snapshot.findings:
            prior_provider = provider_by_finding.setdefault(finding.stable_id, finding.provider_id)
            if prior_provider != finding.provider_id:
                raise ValueError("stable finding identity changed provider")
            unique_findings.add(finding.stable_id)
    if len(unique_findings) > MAX_UNIQUE_FINDINGS:
        raise ValueError("audit comparison has too many unique findings")


def _last_observation_before_current(
    snapshot_maps: tuple[dict[str, FindingSnapshot], ...],
    stable_id: str,
) -> tuple[int, FindingSnapshot] | None:
    for index in range(len(snapshot_maps) - 2, -1, -1):
        finding = snapshot_maps[index].get(stable_id)
        if finding is not None:
            return index, finding
    return None


def _has_conclusive_absence(
    snapshots: tuple[AuditRunSnapshot, ...],
    finding_maps: tuple[dict[str, FindingSnapshot], ...],
    coverage_maps: tuple[dict[str, ProviderCoverageState], ...],
    *,
    stable_id: str,
    provider_id: str,
    after_index: int,
) -> bool:
    return any(
        snapshot.run_state is SnapshotRunState.COMPLETED
        and coverage_maps[index].get(provider_id) is ProviderCoverageState.COMPLETE
        and stable_id not in finding_maps[index]
        for index, snapshot in enumerate(snapshots[after_index + 1 : -1], start=after_index + 1)
    )


def _lifecycle(
    snapshots: tuple[AuditRunSnapshot, ...],
    finding_maps: tuple[dict[str, FindingSnapshot], ...],
    coverage_maps: tuple[dict[str, ProviderCoverageState], ...],
    *,
    stable_id: str,
    provider_id: str,
) -> FindingLifecycle:
    first_observed = next(
        index for index, finding_map in enumerate(finding_maps) if stable_id in finding_map
    )
    events = tuple(
        FindingLifecycleEvent(
            run_id=snapshot.run_id,
            sequence=snapshot.sequence,
            run_state=snapshot.run_state,
            provider_coverage=coverage_maps[index].get(provider_id),
            observed=(finding := finding_maps[index].get(stable_id)) is not None,
            content_fingerprint=None if finding is None else finding.content_fingerprint,
        )
        for index, snapshot in enumerate(snapshots[first_observed:], start=first_observed)
    )
    return FindingLifecycle(stable_id=stable_id, provider_id=provider_id, events=events)


def compare_audit_snapshots(
    snapshots: tuple[AuditRunSnapshot, ...],
    *,
    baseline_run_id: str | None = None,
    current_run_id: str | None = None,
) -> AuditComparison:
    """Compare two selected runs while retaining bounded lifecycle context."""

    _validate_timeline(snapshots)
    if (baseline_run_id is None) != (current_run_id is None):
        raise ValueError("audit comparison run selection is incomplete")
    if baseline_run_id is None:
        baseline_index = len(snapshots) - 2
        current_index = len(snapshots) - 1
    else:
        assert current_run_id is not None
        run_indexes = {snapshot.run_id: index for index, snapshot in enumerate(snapshots)}
        try:
            baseline_index = run_indexes[baseline_run_id]
            current_index = run_indexes[current_run_id]
        except KeyError as error:
            raise ValueError("selected audit comparison run is unavailable") from error
        if baseline_index >= current_index:
            raise ValueError("selected audit comparison runs are out of order")

    # Later snapshots are irrelevant to the requested comparison and must not
    # appear in its lifecycle projection.
    snapshots = snapshots[: current_index + 1]
    maps = tuple(_snapshot_maps(snapshot) for snapshot in snapshots)
    finding_maps = tuple(item[0] for item in maps)
    coverage_maps = tuple(item[1] for item in maps)
    baseline = snapshots[baseline_index]
    current = snapshots[-1]
    baseline_findings = finding_maps[baseline_index]
    current_findings = finding_maps[-1]
    current_coverage = coverage_maps[-1]

    item_ids = sorted(set(baseline_findings) | set(current_findings))
    if len(item_ids) > MAX_COMPARISON_ITEMS:
        raise ValueError("audit comparison output is outside the allowed bounds")

    diffs: list[FindingDiff] = []
    unresolved: list[UnresolvedAbsence] = []
    reasons: set[ComparisonIncompleteReason] = set()

    if baseline.run_state is not SnapshotRunState.COMPLETED:
        reasons.add(ComparisonIncompleteReason.BASELINE_RUN_INCOMPLETE)
    if current.run_state is not SnapshotRunState.COMPLETED:
        reasons.add(ComparisonIncompleteReason.CURRENT_RUN_INCOMPLETE)
    if any(
        state is not ProviderCoverageState.COMPLETE
        for state in coverage_maps[baseline_index].values()
    ):
        reasons.add(ComparisonIncompleteReason.BASELINE_COVERAGE_INCOMPLETE)
    if any(state is not ProviderCoverageState.COMPLETE for state in current_coverage.values()):
        reasons.add(ComparisonIncompleteReason.CURRENT_COVERAGE_INCOMPLETE)

    for stable_id in item_ids:
        previous = baseline_findings.get(stable_id)
        observed = current_findings.get(stable_id)
        if previous is not None and observed is not None:
            state = (
                FindingDiffState.UNCHANGED
                if previous.content_fingerprint == observed.content_fingerprint
                else FindingDiffState.CHANGED
            )
            diffs.append(
                FindingDiff(
                    stable_id,
                    observed.provider_id,
                    state,
                    previous.content_fingerprint,
                    observed.content_fingerprint,
                )
            )
            continue
        if observed is not None:
            prior = _last_observation_before_current(finding_maps, stable_id)
            if prior is None:
                state = FindingDiffState.NEW
                previous_fingerprint = None
            else:
                prior_index, prior_finding = prior
                previous_fingerprint = prior_finding.content_fingerprint
                reappeared = _has_conclusive_absence(
                    snapshots,
                    finding_maps,
                    coverage_maps,
                    stable_id=stable_id,
                    provider_id=observed.provider_id,
                    after_index=prior_index,
                )
                if reappeared:
                    state = FindingDiffState.REAPPEARED
                elif prior_index >= baseline_index:
                    # The finding first appeared after the selected baseline
                    # and remained observable through the current run.
                    state = FindingDiffState.NEW
                    previous_fingerprint = None
                else:
                    state = (
                        FindingDiffState.UNCHANGED
                        if previous_fingerprint == observed.content_fingerprint
                        else FindingDiffState.CHANGED
                    )
                    reasons.add(ComparisonIncompleteReason.HISTORY_GAP)
            diffs.append(
                FindingDiff(
                    stable_id,
                    observed.provider_id,
                    state,
                    previous_fingerprint,
                    observed.content_fingerprint,
                )
            )
            continue
        if previous is None:
            raise RuntimeError("audit comparison identity is unavailable")
        coverage_state = current_coverage.get(previous.provider_id)
        if (
            current.run_state is SnapshotRunState.COMPLETED
            and coverage_state is ProviderCoverageState.COMPLETE
        ):
            diffs.append(
                FindingDiff(
                    stable_id,
                    previous.provider_id,
                    FindingDiffState.REMOVED,
                    previous.content_fingerprint,
                    None,
                )
            )
        else:
            unresolved.append(
                UnresolvedAbsence(
                    stable_id,
                    previous.provider_id,
                    previous.content_fingerprint,
                    coverage_state,
                )
            )
            reasons.add(ComparisonIncompleteReason.UNRESOLVED_ABSENCE)

    provider_ids = sorted(set(coverage_maps[baseline_index]) | set(current_coverage))
    coverage = tuple(
        ProviderCoverageComparison(
            provider_id=provider_id,
            baseline_state=coverage_maps[baseline_index].get(provider_id),
            current_state=current_coverage.get(provider_id),
        )
        for provider_id in provider_ids
    )
    if any(item.baseline_state is None for item in coverage):
        reasons.add(ComparisonIncompleteReason.BASELINE_COVERAGE_INCOMPLETE)
    if any(item.current_state is None for item in coverage):
        reasons.add(ComparisonIncompleteReason.CURRENT_COVERAGE_INCOMPLETE)

    output_ids = {
        *(item.stable_id for item in diffs),
        *(item.stable_id for item in unresolved),
    }
    providers = {
        finding.stable_id: finding.provider_id
        for finding_map in finding_maps
        for finding in finding_map.values()
        if finding.stable_id in output_ids
    }
    lifecycles = tuple(
        _lifecycle(
            snapshots,
            finding_maps,
            coverage_maps,
            stable_id=stable_id,
            provider_id=providers[stable_id],
        )
        for stable_id in sorted(output_ids)
    )
    if sum(len(item.events) for item in lifecycles) > MAX_LIFECYCLE_EVENTS:
        raise ValueError("audit lifecycle output is outside the allowed bounds")

    incomplete_reasons = tuple(sorted(reasons, key=lambda item: item.value))
    return AuditComparison(
        baseline_run_id=baseline.run_id,
        current_run_id=current.run_id,
        diffs=tuple(sorted(diffs, key=lambda item: item.stable_id)),
        unresolved_absences=tuple(sorted(unresolved, key=lambda item: item.stable_id)),
        coverage=coverage,
        lifecycles=lifecycles,
        incomplete_comparison=bool(incomplete_reasons),
        incomplete_reasons=incomplete_reasons,
    )
