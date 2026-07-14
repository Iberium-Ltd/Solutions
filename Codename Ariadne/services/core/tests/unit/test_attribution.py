from __future__ import annotations

from dataclasses import fields

import pytest

from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.domain.attribution import (
    SCORE_CEILING,
    SCORE_FLOOR,
    AttributionCase,
    AttributionConfidenceBand,
    AttributionWeightProfile,
    HumanAttributionDecision,
    HumanAttributionState,
    NegativeAttributionSignal,
    NegativeSignalObservation,
    PositiveAttributionSignal,
    PositiveSignalObservation,
    default_attribution_weight_profile,
)


def _positive(signal: PositiveAttributionSignal, suffix: str) -> PositiveSignalObservation:
    return PositiveSignalObservation(signal, (f"evidence-{suffix}",))


def _negative(signal: NegativeAttributionSignal, suffix: str) -> NegativeSignalObservation:
    return NegativeSignalObservation(signal, (f"evidence-{suffix}",))


def test_signal_and_human_state_catalogs_match_the_closed_master_contract() -> None:
    assert {signal.value for signal in PositiveAttributionSignal} == {
        "EXACT_EMAIL",
        "RECOVERY_RELATIONSHIP",
        "EXACT_LEGAL_NAME",
        "SAME_UNCOMMON_USERNAME",
        "SAME_PHOTOGRAPH",
        "SAME_ORGANISATION",
        "SAME_EDUCATION",
        "SAME_LOCATION",
        "SAME_PROJECT",
        "SAME_LINKED_DOMAIN",
        "SAME_WRITING_PROFILE_LINKS",
        "CHRONOLOGICAL_COMPATIBILITY",
        "USER_CONFIRMATION",
        "IMMUTABLE_PLATFORM_ID_CONTINUITY",
    }
    assert {signal.value for signal in NegativeAttributionSignal} == {
        "CONFLICTING_AGE",
        "CONFLICTING_PHOTOGRAPH",
        "INCOMPATIBLE_GEOGRAPHY",
        "ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP",
        "DIFFERENT_IMMUTABLE_ACCOUNT_ID",
        "CONTRADICTORY_BIOGRAPHY",
        "EXPLICIT_USER_EXCLUSION",
        "USERNAME_RECYCLING_EVIDENCE",
    }
    assert {state.value for state in HumanAttributionState} == {
        "CONFIRMED_MATCH",
        "CONFIRMED_NON_MATCH",
        "PROBABLE",
        "POSSIBLE",
        "UNRESOLVED",
        "NEEDS_MORE_EVIDENCE",
    }


def test_assessment_is_deterministic_explainable_and_never_assigns_human_state() -> None:
    positives = (
        _positive(PositiveAttributionSignal.SAME_UNCOMMON_USERNAME, "username"),
        PositiveSignalObservation(
            PositiveAttributionSignal.EXACT_EMAIL,
            ("evidence-email-b", "evidence-email-a"),
        ),
        _positive(
            PositiveAttributionSignal.IMMUTABLE_PLATFORM_ID_CONTINUITY,
            "platform-id",
        ),
    )
    contradictions = (_negative(NegativeAttributionSignal.CONFLICTING_AGE, "age"),)
    missing = frozenset(
        {
            PositiveAttributionSignal.USER_CONFIRMATION,
            PositiveAttributionSignal.RECOVERY_RELATIONSHIP,
            PositiveAttributionSignal.SAME_PHOTOGRAPH,
            PositiveAttributionSignal.SAME_EDUCATION,
        }
    )
    service = AttributionScoringService()

    first = service.assess(
        AttributionCase("case-synthetic-alpha", positives, contradictions, missing)
    )
    second = service.assess(
        AttributionCase(
            "case-synthetic-alpha",
            tuple(reversed(positives)),
            tuple(reversed(contradictions)),
            missing,
        )
    )

    assert first == second
    assert first.score == 440
    assert first.confidence_band is AttributionConfidenceBand.HIGH
    assert [item.signal for item in first.contributing_signals] == [
        PositiveAttributionSignal.EXACT_EMAIL,
        PositiveAttributionSignal.IMMUTABLE_PLATFORM_ID_CONTINUITY,
        PositiveAttributionSignal.SAME_UNCOMMON_USERNAME,
    ]
    assert first.contributing_signals[0].evidence_references == (
        "evidence-email-a",
        "evidence-email-b",
    )
    assert [item.signal for item in first.contradictions] == [
        NegativeAttributionSignal.CONFLICTING_AGE
    ]
    assert {item.signal for item in first.missing_evidence} == missing
    assert first.recommended_next_evidence == (
        PositiveAttributionSignal.USER_CONFIRMATION,
        PositiveAttributionSignal.RECOVERY_RELATIONSHIP,
        PositiveAttributionSignal.SAME_PHOTOGRAPH,
    )
    assert first.human_review_required is True
    assert "human_state" not in {item.name for item in fields(first)}


def test_scores_are_integer_only_and_clamped_to_the_closed_range() -> None:
    profile = default_attribution_weight_profile()
    all_positive = AttributionCase(
        "case-synthetic-positive",
        tuple(
            _positive(signal, f"positive-{index}")
            for index, signal in enumerate(PositiveAttributionSignal)
        ),
    )
    all_negative = AttributionCase(
        "case-synthetic-negative",
        contradiction_observations=tuple(
            _negative(signal, f"negative-{index}")
            for index, signal in enumerate(NegativeAttributionSignal)
        ),
    )

    positive_result = AttributionScoringService(profile).assess(all_positive)
    negative_result = AttributionScoringService(profile).assess(all_negative)

    assert positive_result.score == SCORE_CEILING
    assert positive_result.confidence_band is AttributionConfidenceBand.VERY_HIGH
    assert negative_result.score == SCORE_FLOOR
    assert negative_result.confidence_band is AttributionConfidenceBand.VERY_LOW
    assert type(positive_result.score) is int
    assert type(negative_result.score) is int


def test_weight_profiles_are_versioned_configurable_complete_and_immutable() -> None:
    default = default_attribution_weight_profile()
    positive_weights = dict(default.positive_weights)
    negative_weights = dict(default.negative_weights)
    positive_weights[PositiveAttributionSignal.EXACT_EMAIL] = 7
    positive_weights[PositiveAttributionSignal.SAME_EDUCATION] = 900
    profile = AttributionWeightProfile(
        version="synthetic-attribution-v2",
        positive_weights=positive_weights,
        negative_weights=negative_weights,
        very_low_maximum=-10,
        medium_minimum=5,
        high_minimum=10,
        very_high_minimum=20,
        maximum_recommendations=1,
    )
    positive_weights[PositiveAttributionSignal.EXACT_EMAIL] = 999

    assessment = AttributionScoringService(profile).assess(
        AttributionCase(
            "case-synthetic-custom",
            (_positive(PositiveAttributionSignal.EXACT_EMAIL, "email"),),
            missing_evidence=frozenset(
                {
                    PositiveAttributionSignal.SAME_EDUCATION,
                    PositiveAttributionSignal.USER_CONFIRMATION,
                }
            ),
        )
    )

    assert assessment.weight_profile_version == "synthetic-attribution-v2"
    assert assessment.score == 7
    assert assessment.confidence_band is AttributionConfidenceBand.MEDIUM
    assert assessment.recommended_next_evidence == (PositiveAttributionSignal.SAME_EDUCATION,)

    incomplete = dict(default.positive_weights)
    incomplete.pop(PositiveAttributionSignal.EXACT_EMAIL)
    with pytest.raises(ValueError, match="closed signal catalog"):
        AttributionWeightProfile(
            version="synthetic-incomplete-v1",
            positive_weights=incomplete,
            negative_weights=default.negative_weights,
        )

    invalid_type = dict(default.negative_weights)
    invalid_type[NegativeAttributionSignal.CONFLICTING_AGE] = True
    with pytest.raises(ValueError, match="outside the allowed bounds"):
        AttributionWeightProfile(
            version="synthetic-invalid-v1",
            positive_weights=default.positive_weights,
            negative_weights=invalid_type,
        )


def test_invalid_evidence_and_profile_thresholds_fail_closed() -> None:
    duplicate = _positive(PositiveAttributionSignal.EXACT_EMAIL, "email")
    with pytest.raises(ValueError, match="must be unique"):
        AttributionCase("case-synthetic-duplicate", (duplicate, duplicate))
    with pytest.raises(ValueError, match="overlap"):
        AttributionCase(
            "case-synthetic-overlap",
            (duplicate,),
            missing_evidence=frozenset({PositiveAttributionSignal.EXACT_EMAIL}),
        )
    with pytest.raises(ValueError, match="evidence references"):
        PositiveSignalObservation(PositiveAttributionSignal.EXACT_EMAIL, ())

    default = default_attribution_weight_profile()
    with pytest.raises(ValueError, match="thresholds"):
        AttributionWeightProfile(
            version="synthetic-thresholds-v1",
            positive_weights=default.positive_weights,
            negative_weights=default.negative_weights,
            medium_minimum=300,
            high_minimum=300,
        )


def test_human_decisions_are_explicit_and_separate_from_scoring() -> None:
    assessment = AttributionScoringService().assess(AttributionCase("case-synthetic-human"))
    decision = HumanAttributionDecision(
        case_id=assessment.case_id,
        state=HumanAttributionState.NEEDS_MORE_EVIDENCE,
        actor_id="actor-local-reviewer",
        decided_at_us=1_750_000_000_000_000,
        weight_profile_version=assessment.weight_profile_version,
    )

    assert decision.state is HumanAttributionState.NEEDS_MORE_EVIDENCE
    assert assessment.score == 0
    assert assessment.human_review_required is True
    assert "state" not in {item.name for item in fields(assessment)}

    with pytest.raises(ValueError, match="decision time"):
        HumanAttributionDecision(
            case_id=assessment.case_id,
            state=HumanAttributionState.UNRESOLVED,
            actor_id="actor-local-reviewer",
            decided_at_us=0,
            weight_profile_version=assessment.weight_profile_version,
        )
