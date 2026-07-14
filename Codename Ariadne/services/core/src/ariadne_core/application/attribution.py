"""Application boundary for deterministic Ariadne Core attribution scoring."""

from __future__ import annotations

from ariadne_core.domain.attribution import (
    AttributionAssessment,
    AttributionCase,
    AttributionWeightProfile,
    default_attribution_weight_profile,
    score_attribution,
)


class AttributionScoringService:
    """Apply one explicit weight-profile version without persistence or side effects."""

    def __init__(self, profile: AttributionWeightProfile | None = None) -> None:
        self._profile = profile or default_attribution_weight_profile()

    @property
    def weight_profile_version(self) -> str:
        return self._profile.version

    def assess(self, case: AttributionCase) -> AttributionAssessment:
        return score_attribution(case, self._profile)
