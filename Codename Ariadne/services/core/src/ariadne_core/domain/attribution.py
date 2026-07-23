"""Deterministic, explainable identity-attribution scoring primitives."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

SCORE_FLOOR: Final = -1_000
SCORE_CEILING: Final = 1_000
MAX_WEIGHT: Final = 1_000
MAX_EVIDENCE_REFERENCES: Final = 16
MAX_RECOMMENDATIONS: Final = 5

_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PositiveAttributionSignal(StrEnum):
    EXACT_EMAIL = "EXACT_EMAIL"
    RECOVERY_RELATIONSHIP = "RECOVERY_RELATIONSHIP"
    EXACT_LEGAL_NAME = "EXACT_LEGAL_NAME"
    SAME_UNCOMMON_USERNAME = "SAME_UNCOMMON_USERNAME"
    SAME_PHOTOGRAPH = "SAME_PHOTOGRAPH"
    SAME_ORGANISATION = "SAME_ORGANISATION"
    SAME_EDUCATION = "SAME_EDUCATION"
    SAME_LOCATION = "SAME_LOCATION"
    SAME_PROJECT = "SAME_PROJECT"
    SAME_LINKED_DOMAIN = "SAME_LINKED_DOMAIN"
    SAME_WRITING_PROFILE_LINKS = "SAME_WRITING_PROFILE_LINKS"
    CHRONOLOGICAL_COMPATIBILITY = "CHRONOLOGICAL_COMPATIBILITY"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    IMMUTABLE_PLATFORM_ID_CONTINUITY = "IMMUTABLE_PLATFORM_ID_CONTINUITY"


class NegativeAttributionSignal(StrEnum):
    CONFLICTING_AGE = "CONFLICTING_AGE"
    CONFLICTING_PHOTOGRAPH = "CONFLICTING_PHOTOGRAPH"
    INCOMPATIBLE_GEOGRAPHY = "INCOMPATIBLE_GEOGRAPHY"
    ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP = "ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP"
    DIFFERENT_IMMUTABLE_ACCOUNT_ID = "DIFFERENT_IMMUTABLE_ACCOUNT_ID"
    CONTRADICTORY_BIOGRAPHY = "CONTRADICTORY_BIOGRAPHY"
    EXPLICIT_USER_EXCLUSION = "EXPLICIT_USER_EXCLUSION"
    USERNAME_RECYCLING_EVIDENCE = "USERNAME_RECYCLING_EVIDENCE"


class AttributionConfidenceBand(StrEnum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class HumanAttributionState(StrEnum):
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    CONFIRMED_NON_MATCH = "CONFIRMED_NON_MATCH"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


def _validate_opaque_id(value: str, label: str) -> None:
    if _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _validate_evidence_references(references: tuple[str, ...]) -> None:
    if not references or len(references) > MAX_EVIDENCE_REFERENCES:
        raise ValueError("evidence references are outside the allowed bounds")
    if len(set(references)) != len(references):
        raise ValueError("evidence references must be unique")
    for reference in references:
        _validate_opaque_id(reference, "evidence reference")


@dataclass(frozen=True, slots=True)
class PositiveSignalObservation:
    signal: PositiveAttributionSignal
    evidence_references: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, PositiveAttributionSignal):
            raise TypeError("positive signal is invalid")
        _validate_evidence_references(self.evidence_references)


@dataclass(frozen=True, slots=True)
class NegativeSignalObservation:
    signal: NegativeAttributionSignal
    evidence_references: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, NegativeAttributionSignal):
            raise TypeError("negative signal is invalid")
        _validate_evidence_references(self.evidence_references)


@dataclass(frozen=True, slots=True)
class AttributionCase:
    case_id: str
    positive_observations: tuple[PositiveSignalObservation, ...] = ()
    contradiction_observations: tuple[NegativeSignalObservation, ...] = ()
    missing_evidence: frozenset[PositiveAttributionSignal] = frozenset()

    def __post_init__(self) -> None:
        _validate_opaque_id(self.case_id, "attribution case id")
        positive_signals = tuple(observation.signal for observation in self.positive_observations)
        negative_signals = tuple(
            observation.signal for observation in self.contradiction_observations
        )
        if len(set(positive_signals)) != len(positive_signals):
            raise ValueError("positive attribution signals must be unique")
        if len(set(negative_signals)) != len(negative_signals):
            raise ValueError("negative attribution signals must be unique")
        if any(
            not isinstance(signal, PositiveAttributionSignal) for signal in self.missing_evidence
        ):
            raise TypeError("missing evidence signal is invalid")
        if set(positive_signals) & self.missing_evidence:
            raise ValueError("observed and missing attribution evidence overlap")


def _validated_weights[SignalT: StrEnum](
    weights: Mapping[SignalT, int],
    signal_type: type[SignalT],
    label: str,
) -> Mapping[SignalT, int]:
    expected = frozenset(signal_type)
    supplied = frozenset(weights)
    if supplied != expected or any(not isinstance(signal, signal_type) for signal in supplied):
        raise ValueError(f"{label} weights must cover the closed signal catalog exactly")
    copied: dict[SignalT, int] = {}
    for signal in signal_type:
        weight = weights[signal]
        if type(weight) is not int or weight < 0 or weight > MAX_WEIGHT:
            raise ValueError(f"{label} weight is outside the allowed bounds")
        copied[signal] = weight
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class AttributionWeightProfile:
    version: str
    positive_weights: Mapping[PositiveAttributionSignal, int] = field(repr=False)
    negative_weights: Mapping[NegativeAttributionSignal, int] = field(repr=False)
    very_low_maximum: int = -300
    medium_minimum: int = 100
    high_minimum: int = 300
    very_high_minimum: int = 600
    maximum_recommendations: int = 3

    def __post_init__(self) -> None:
        if _VERSION.fullmatch(self.version) is None:
            raise ValueError("attribution weight profile version is invalid")
        object.__setattr__(
            self,
            "positive_weights",
            _validated_weights(
                self.positive_weights,
                PositiveAttributionSignal,
                "positive",
            ),
        )
        object.__setattr__(
            self,
            "negative_weights",
            _validated_weights(
                self.negative_weights,
                NegativeAttributionSignal,
                "negative",
            ),
        )
        thresholds = (
            self.very_low_maximum,
            self.medium_minimum,
            self.high_minimum,
            self.very_high_minimum,
        )
        if any(type(value) is not int for value in thresholds):
            raise ValueError("attribution confidence thresholds must be integers")
        if not (
            SCORE_FLOOR
            <= self.very_low_maximum
            < self.medium_minimum
            < self.high_minimum
            < self.very_high_minimum
            <= SCORE_CEILING
        ):
            raise ValueError("attribution confidence thresholds are invalid")
        if (
            type(self.maximum_recommendations) is not int
            or self.maximum_recommendations < 1
            or self.maximum_recommendations > MAX_RECOMMENDATIONS
        ):
            raise ValueError("attribution recommendation limit is invalid")


@dataclass(frozen=True, slots=True)
class PositiveSignalContribution:
    signal: PositiveAttributionSignal
    weight: int
    evidence_references: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class NegativeSignalContribution:
    signal: NegativeAttributionSignal
    penalty: int
    evidence_references: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class MissingEvidence:
    signal: PositiveAttributionSignal
    potential_weight: int


@dataclass(frozen=True, slots=True)
class AttributionAssessment:
    case_id: str
    weight_profile_version: str
    score: int
    contributing_signals: tuple[PositiveSignalContribution, ...]
    contradictions: tuple[NegativeSignalContribution, ...]
    missing_evidence: tuple[MissingEvidence, ...]
    confidence_band: AttributionConfidenceBand
    recommended_next_evidence: tuple[PositiveAttributionSignal, ...]
    human_review_required: bool = True

    def __post_init__(self) -> None:
        if self.score < SCORE_FLOOR or self.score > SCORE_CEILING:
            raise ValueError("attribution score is outside the allowed bounds")
        if self.human_review_required is not True:
            raise ValueError("attribution assessments always require human review")


@dataclass(frozen=True, slots=True)
class HumanAttributionDecision:
    case_id: str
    state: HumanAttributionState
    actor_id: str
    decided_at_us: int
    weight_profile_version: str

    def __post_init__(self) -> None:
        _validate_opaque_id(self.case_id, "attribution case id")
        _validate_opaque_id(self.actor_id, "attribution actor id")
        if not isinstance(self.state, HumanAttributionState):
            raise TypeError("human attribution state is invalid")
        if type(self.decided_at_us) is not int or self.decided_at_us < 1:
            raise ValueError("human attribution decision time is invalid")
        if _VERSION.fullmatch(self.weight_profile_version) is None:
            raise ValueError("attribution weight profile version is invalid")


def _confidence_band(score: int, profile: AttributionWeightProfile) -> AttributionConfidenceBand:
    if score <= profile.very_low_maximum:
        return AttributionConfidenceBand.VERY_LOW
    if score < profile.medium_minimum:
        return AttributionConfidenceBand.LOW
    if score < profile.high_minimum:
        return AttributionConfidenceBand.MEDIUM
    if score < profile.very_high_minimum:
        return AttributionConfidenceBand.HIGH
    return AttributionConfidenceBand.VERY_HIGH


def score_attribution(
    case: AttributionCase,
    profile: AttributionWeightProfile,
) -> AttributionAssessment:
    """Score observed evidence without creating a human attribution state."""

    contributing = tuple(
        PositiveSignalContribution(
            signal=observation.signal,
            weight=profile.positive_weights[observation.signal],
            evidence_references=tuple(sorted(observation.evidence_references)),
        )
        for observation in sorted(
            case.positive_observations,
            key=lambda item: item.signal.value,
        )
    )
    contradictions = tuple(
        NegativeSignalContribution(
            signal=observation.signal,
            penalty=profile.negative_weights[observation.signal],
            evidence_references=tuple(sorted(observation.evidence_references)),
        )
        for observation in sorted(
            case.contradiction_observations,
            key=lambda item: item.signal.value,
        )
    )
    raw_score = sum(item.weight for item in contributing) - sum(
        item.penalty for item in contradictions
    )
    score = max(SCORE_FLOOR, min(SCORE_CEILING, raw_score))
    missing = tuple(
        MissingEvidence(signal=signal, potential_weight=profile.positive_weights[signal])
        for signal in sorted(case.missing_evidence, key=lambda item: item.value)
    )
    recommendations = tuple(
        item.signal
        for item in sorted(
            missing,
            key=lambda item: (-item.potential_weight, item.signal.value),
        )[: profile.maximum_recommendations]
    )
    return AttributionAssessment(
        case_id=case.case_id,
        weight_profile_version=profile.version,
        score=score,
        contributing_signals=contributing,
        contradictions=contradictions,
        missing_evidence=missing,
        confidence_band=_confidence_band(score, profile),
        recommended_next_evidence=recommendations,
    )


def default_attribution_weight_profile() -> AttributionWeightProfile:
    """Centralize conservative attribution weights so scoring is reproducible and reviewable."""

    return AttributionWeightProfile(
        version="ariadne-core-attribution-v1",
        positive_weights={
            PositiveAttributionSignal.EXACT_EMAIL: 180,
            PositiveAttributionSignal.RECOVERY_RELATIONSHIP: 160,
            PositiveAttributionSignal.EXACT_LEGAL_NAME: 60,
            PositiveAttributionSignal.SAME_UNCOMMON_USERNAME: 120,
            PositiveAttributionSignal.SAME_PHOTOGRAPH: 120,
            PositiveAttributionSignal.SAME_ORGANISATION: 45,
            PositiveAttributionSignal.SAME_EDUCATION: 35,
            PositiveAttributionSignal.SAME_LOCATION: 35,
            PositiveAttributionSignal.SAME_PROJECT: 50,
            PositiveAttributionSignal.SAME_LINKED_DOMAIN: 90,
            PositiveAttributionSignal.SAME_WRITING_PROFILE_LINKS: 55,
            PositiveAttributionSignal.CHRONOLOGICAL_COMPATIBILITY: 60,
            PositiveAttributionSignal.USER_CONFIRMATION: 200,
            PositiveAttributionSignal.IMMUTABLE_PLATFORM_ID_CONTINUITY: 240,
        },
        negative_weights={
            NegativeAttributionSignal.CONFLICTING_AGE: 100,
            NegativeAttributionSignal.CONFLICTING_PHOTOGRAPH: 180,
            NegativeAttributionSignal.INCOMPATIBLE_GEOGRAPHY: 90,
            NegativeAttributionSignal.ACTIVITY_BEFORE_PLAUSIBLE_OWNERSHIP: 180,
            NegativeAttributionSignal.DIFFERENT_IMMUTABLE_ACCOUNT_ID: 300,
            NegativeAttributionSignal.CONTRADICTORY_BIOGRAPHY: 120,
            NegativeAttributionSignal.EXPLICIT_USER_EXCLUSION: 1_000,
            NegativeAttributionSignal.USERNAME_RECYCLING_EVIDENCE: 250,
        },
    )
