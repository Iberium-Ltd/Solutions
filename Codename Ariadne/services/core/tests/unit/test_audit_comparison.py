from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError

import pytest

from ariadne_core.application.audit_comparison import AuditComparisonService
from ariadne_core.domain.audit_comparison import (
    MAX_PROVIDERS_PER_SNAPSHOT,
    AuditRunSnapshot,
    ComparisonIncompleteReason,
    FindingDiffState,
    FindingSnapshot,
    ProviderCoverage,
    ProviderCoverageState,
    SnapshotRunState,
)


def _fingerprint(label: str) -> str:
    return hashlib.sha256(f"synthetic:{label}".encode()).hexdigest()


def _finding(stable_id: str, content: str, provider: str = "provider-synthetic") -> FindingSnapshot:
    return FindingSnapshot(stable_id, provider, _fingerprint(content))


def _coverage(
    state: ProviderCoverageState = ProviderCoverageState.COMPLETE,
    provider: str = "provider-synthetic",
) -> ProviderCoverage:
    return ProviderCoverage(provider, state)


def _snapshot(
    sequence: int,
    findings: tuple[FindingSnapshot, ...],
    *,
    coverage: tuple[ProviderCoverage, ...] = (_coverage(),),
    state: SnapshotRunState = SnapshotRunState.COMPLETED,
) -> AuditRunSnapshot:
    return AuditRunSnapshot(
        run_id=f"run-synthetic-{sequence}",
        sequence=sequence,
        captured_at_us=1_750_000_000_000_000 + sequence,
        run_state=state,
        findings=findings,
        provider_coverage=coverage,
    )


def test_complete_snapshots_classify_new_changed_removed_and_unchanged_deterministically() -> None:
    baseline = _snapshot(
        1,
        (
            _finding("finding-unchanged", "stable"),
            _finding("finding-changed", "before"),
            _finding("finding-removed", "gone"),
        ),
    )
    current = _snapshot(
        2,
        (
            _finding("finding-new", "first-observation"),
            _finding("finding-changed", "after"),
            _finding("finding-unchanged", "stable"),
        ),
    )

    result = AuditComparisonService().compare((baseline, current))

    assert [(item.stable_id, item.state) for item in result.diffs] == [
        ("finding-changed", FindingDiffState.CHANGED),
        ("finding-new", FindingDiffState.NEW),
        ("finding-removed", FindingDiffState.REMOVED),
        ("finding-unchanged", FindingDiffState.UNCHANGED),
    ]
    assert result.unresolved_absences == ()
    assert result.incomplete_comparison is False
    assert result.incomplete_reasons == ()
    assert result == AuditComparisonService().compare((baseline, current))


def test_reappearance_requires_prior_observation_and_conclusive_intervening_absence() -> None:
    first = _snapshot(1, (_finding("finding-returned", "original"),))
    absent = _snapshot(2, ())
    current = _snapshot(3, (_finding("finding-returned", "returned-content"),))

    result = AuditComparisonService().compare((first, absent, current))

    assert len(result.diffs) == 1
    assert result.diffs[0].state is FindingDiffState.REAPPEARED
    assert result.diffs[0].previous_fingerprint == _fingerprint("original")
    lifecycle = result.lifecycles[0]
    assert [event.observed for event in lifecycle.events] == [True, False, True]
    assert [event.provider_coverage for event in lifecycle.events] == [
        ProviderCoverageState.COMPLETE,
        ProviderCoverageState.COMPLETE,
        ProviderCoverageState.COMPLETE,
    ]
    assert result.incomplete_comparison is False


@pytest.mark.parametrize(
    "coverage_state",
    [ProviderCoverageState.NOT_CHECKED, ProviderCoverageState.BLOCKED],
)
def test_incomplete_provider_coverage_never_turns_absence_into_removal(
    coverage_state: ProviderCoverageState,
) -> None:
    baseline = _snapshot(1, (_finding("finding-uncertain", "observed"),))
    current = _snapshot(2, (), coverage=(_coverage(coverage_state),))

    result = AuditComparisonService().compare((baseline, current))

    assert result.diffs == ()
    assert len(result.unresolved_absences) == 1
    assert result.unresolved_absences[0].stable_id == "finding-uncertain"
    assert result.unresolved_absences[0].current_coverage is coverage_state
    assert result.coverage[0].current_state is coverage_state
    assert result.incomplete_comparison is True
    assert ComparisonIncompleteReason.CURRENT_COVERAGE_INCOMPLETE in result.incomplete_reasons
    assert ComparisonIncompleteReason.UNRESOLVED_ABSENCE in result.incomplete_reasons


def test_incomplete_intervening_run_does_not_create_false_reappearance() -> None:
    first = _snapshot(1, (_finding("finding-gap", "same"),))
    partial = _snapshot(
        2,
        (),
        coverage=(_coverage(ProviderCoverageState.NOT_CHECKED),),
        state=SnapshotRunState.PARTIAL,
    )
    current = _snapshot(3, (_finding("finding-gap", "same"),))

    result = AuditComparisonService().compare((first, partial, current))

    assert result.diffs[0].state is FindingDiffState.UNCHANGED
    assert FindingDiffState.REAPPEARED not in {item.state for item in result.diffs}
    assert result.incomplete_comparison is True
    assert ComparisonIncompleteReason.BASELINE_RUN_INCOMPLETE in result.incomplete_reasons
    assert ComparisonIncompleteReason.BASELINE_COVERAGE_INCOMPLETE in result.incomplete_reasons
    assert ComparisonIncompleteReason.HISTORY_GAP in result.incomplete_reasons


def test_new_means_first_observed_even_when_baseline_coverage_was_blocked() -> None:
    baseline = _snapshot(
        1,
        (),
        coverage=(_coverage(ProviderCoverageState.BLOCKED),),
    )
    current = _snapshot(2, (_finding("finding-first-seen", "visible"),))

    result = AuditComparisonService().compare((baseline, current))

    assert result.diffs[0].state is FindingDiffState.NEW
    assert result.incomplete_comparison is True
    assert ComparisonIncompleteReason.BASELINE_COVERAGE_INCOMPLETE in result.incomplete_reasons


def test_explicit_nonadjacent_runs_compare_selected_states_and_keep_intervening_lifecycle() -> None:
    baseline = _snapshot(1, (_finding("finding-selected", "baseline"),))
    intervening = _snapshot(
        2,
        (
            _finding("finding-selected", "intervening-change"),
            _finding("finding-after-baseline", "first-seen"),
        ),
    )
    current = _snapshot(
        3,
        (
            _finding("finding-selected", "baseline"),
            _finding("finding-after-baseline", "first-seen"),
        ),
    )

    result = AuditComparisonService().compare(
        (baseline, intervening, current),
        baseline_run_id=baseline.run_id,
        current_run_id=current.run_id,
    )

    assert [(item.stable_id, item.state) for item in result.diffs] == [
        ("finding-after-baseline", FindingDiffState.NEW),
        ("finding-selected", FindingDiffState.UNCHANGED),
    ]
    selected_lifecycle = next(
        item for item in result.lifecycles if item.stable_id == "finding-selected"
    )
    assert [event.run_id for event in selected_lifecycle.events] == [
        baseline.run_id,
        intervening.run_id,
        current.run_id,
    ]


def test_snapshots_are_immutable_bounded_and_reject_identity_drift() -> None:
    finding = _finding("finding-immutable", "one")
    snapshot = _snapshot(1, (finding,))
    with pytest.raises(FrozenInstanceError):
        snapshot.sequence = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="findings are outside"):
        AuditRunSnapshot(
            run_id="run-synthetic-list",
            sequence=1,
            captured_at_us=1,
            run_state=SnapshotRunState.COMPLETED,
            findings=[],  # type: ignore[arg-type]
            provider_coverage=(_coverage(),),
        )
    with pytest.raises(ValueError, match="provider coverage is outside"):
        AuditRunSnapshot(
            run_id="run-synthetic-providers",
            sequence=1,
            captured_at_us=1,
            run_state=SnapshotRunState.COMPLETED,
            findings=(),
            provider_coverage=tuple(
                _coverage(provider=f"provider-synthetic-{index}")
                for index in range(MAX_PROVIDERS_PER_SNAPSHOT + 1)
            ),
        )

    first = _snapshot(
        1,
        (_finding("finding-provider-bound", "one", "provider-one"),),
        coverage=(_coverage(provider="provider-one"),),
    )
    second = _snapshot(
        2,
        (_finding("finding-provider-bound", "two", "provider-two"),),
        coverage=(_coverage(provider="provider-two"),),
    )
    with pytest.raises(ValueError, match="changed provider"):
        AuditComparisonService().compare((first, second))


def test_timeline_order_and_fingerprint_validation_fail_closed() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        FindingSnapshot("finding-invalid", "provider-synthetic", "not-a-fingerprint")

    first = _snapshot(1, ())
    duplicate_sequence = AuditRunSnapshot(
        run_id="run-synthetic-other",
        sequence=1,
        captured_at_us=first.captured_at_us + 1,
        run_state=SnapshotRunState.COMPLETED,
        findings=(),
        provider_coverage=(_coverage(),),
    )
    with pytest.raises(ValueError, match="sequences must increase"):
        AuditComparisonService().compare((first, duplicate_sequence))

    with pytest.raises(ValueError, match="attempted provider coverage"):
        _snapshot(
            3,
            (_finding("finding-impossible", "observed"),),
            coverage=(_coverage(ProviderCoverageState.NOT_CHECKED),),
        )
