from __future__ import annotations

import base64
from uuid import UUID

import pytest
from pydantic import ValidationError

from ariadne_core.api.phase5_schemas import (
    MAX_PHASE5_BASE64_CHARS,
    AttributionConfidenceBand,
    AttributionMissingEvidence,
    AttributionPositiveContribution,
    EvidenceIntegrityStatus,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionAssessment,
    Phase5AttributionDecisionRequest,
    Phase5EvidenceArtifact,
    Phase5FindingDetailResult,
    Phase5FindingSummary,
    Phase5HumanDecision,
    Phase5ManualEvidenceImportRequest,
    Phase5ManualFindingCreateRequest,
    Phase5RedactedDerivativeRequest,
)
from ariadne_core.domain.attribution import PositiveAttributionSignal
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
)

PROFILE_ID = str(UUID("00000000-0000-4000-8000-000000000001"))
FINDING_ID = str(UUID("00000000-0000-4000-8000-000000000002"))
ARTIFACT_ID = str(UUID("00000000-0000-4000-8000-000000000003"))
RUN_ID = str(UUID("00000000-0000-4000-8000-000000000004"))
ASSESSMENT_ID = str(UUID("00000000-0000-4000-8000-000000000005"))
DECISION_ID = str(UUID("00000000-0000-4000-8000-000000000006"))


def _assessment() -> Phase5AttributionAssessment:
    return Phase5AttributionAssessment(
        assessment_id=ASSESSMENT_ID,
        case_id=FINDING_ID,
        weight_profile_version="ariadne-core-attribution-v1",
        score=120,
        confidence_band=AttributionConfidenceBand.MEDIUM,
        contributing_signals=(
            AttributionPositiveContribution(
                signal=PositiveAttributionSignal.SAME_PROJECT,
                weight=50,
                evidence_artifact_ids=(ARTIFACT_ID,),
            ),
        ),
        contradictions=(),
        missing_evidence=(
            AttributionMissingEvidence(
                signal=PositiveAttributionSignal.USER_CONFIRMATION,
                potential_weight=200,
            ),
        ),
        recommended_next_evidence=(PositiveAttributionSignal.USER_CONFIRMATION,),
        human_review_required=True,
    )


def _artifact() -> Phase5EvidenceArtifact:
    return Phase5EvidenceArtifact(
        artifact_id=ARTIFACT_ID,
        kind=EvidenceArtifactKind.HTML,
        content_sha256="a" * 64,
        captured_at_us=1_750_000_000_000_000,
        source_url=None,
        http_status=None,
        redirect_count=0,
        provider_id="manual-import",
        run_id=RUN_ID,
        viewport=None,
        capture_method=EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT,
        encrypted_at_rest=True,
        integrity_status=EvidenceIntegrityStatus.VERIFIED,
        derivative_count=0,
    )


def _summary(*, state: str | None = None) -> Phase5FindingSummary:
    return Phase5FindingSummary(
        finding_id=FINDING_ID,
        title="Synthetic public record",
        summary="Synthetic evidence retained for a local attribution review.",
        outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
        severity=FindingSeverity.MEDIUM,
        visibility=FindingVisibility.PUBLIC_PSEUDONYMOUS,
        attribution_state=state,
        confidence_band=AttributionConfidenceBand.MEDIUM,
        score=120,
        human_review_required=True,
        provider_label="Manual import",
        artifact_count=1,
        updated_at_us=1_750_000_000_000_000,
    )


def test_phase5_detail_keeps_machine_assessment_separate_from_human_state() -> None:
    result = Phase5FindingDetailResult(
        profile_id=PROFILE_ID,
        finding=_summary(state="NEEDS_MORE_EVIDENCE"),
        assessment=_assessment(),
        artifacts=(_artifact(),),
        human_decision=Phase5HumanDecision(
            decision_id=DECISION_ID,
            assessment_id=ASSESSMENT_ID,
            state="NEEDS_MORE_EVIDENCE",
            actor_label="Local user",
            decided_at_us=1_750_000_000_000_001,
            weight_profile_version="ariadne-core-attribution-v1",
            supersedes_decision_id=None,
            revision=1,
        ),
    )

    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["finding"]["attributionState"] == "NEEDS_MORE_EVIDENCE"
    assert payload["assessment"]["humanReviewRequired"] is True
    assert payload["artifacts"][0]["encryptedAtRest"] is True
    assert payload["artifacts"][0]["integrityStatus"] == "VERIFIED"


def test_phase5_detail_rejects_inconsistent_counts_and_automatic_human_state() -> None:
    with pytest.raises(ValidationError, match="evidence count"):
        Phase5FindingDetailResult(
            profile_id=PROFILE_ID,
            finding=_summary(),
            assessment=_assessment(),
            artifacts=(),
            human_decision=None,
        )

    with pytest.raises(ValidationError, match="human attribution state"):
        Phase5FindingDetailResult(
            profile_id=PROFILE_ID,
            finding=_summary(state="CONFIRMED_MATCH"),
            assessment=_assessment(),
            artifacts=(_artifact(),),
            human_decision=None,
        )


def test_phase5_assessment_rejects_observed_missing_overlap() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        Phase5AttributionAssessment(
            assessment_id=ASSESSMENT_ID,
            case_id=FINDING_ID,
            weight_profile_version="ariadne-core-attribution-v1",
            score=50,
            confidence_band="LOW",
            contributing_signals=(
                AttributionPositiveContribution(
                    signal="SAME_PROJECT",
                    weight=50,
                    evidence_artifact_ids=(ARTIFACT_ID,),
                ),
            ),
            contradictions=(),
            missing_evidence=(
                AttributionMissingEvidence(signal="SAME_PROJECT", potential_weight=50),
            ),
            recommended_next_evidence=("SAME_PROJECT",),
            human_review_required=True,
        )


def test_manual_finding_request_is_bounded_content_safe_and_strict() -> None:
    request = Phase5ManualFindingCreateRequest(
        profile_id=PROFILE_ID,
        title="Synthetic manual result",
        summary="Synthetic local-only result awaiting evidence and human review.",
        outcome="MANUAL_REVIEW_REQUIRED",
        severity="MEDIUM",
        visibility="UNKNOWN",
        provider_id="manual.synthetic-local",
        provider_label="Synthetic manual source",
    )

    assert request.outcome is FindingOutcome.MANUAL_REVIEW_REQUIRED
    assert "Synthetic manual result" not in repr(request)
    assert "awaiting evidence" not in repr(request)
    assert "Synthetic manual source" not in repr(request)

    for invalid_title in (" Synthetic", "Synthetic\nresult", "Synthetic\u202eresult"):
        with pytest.raises(ValidationError, match="manual finding text"):
            Phase5ManualFindingCreateRequest(
                **{
                    **request.model_dump(),
                    "title": invalid_title,
                }
            )
    with pytest.raises(ValidationError):
        Phase5ManualFindingCreateRequest(
            **{
                **request.model_dump(),
                "provider_id": "manual provider",
            }
        )
    with pytest.raises(ValidationError):
        Phase5ManualFindingCreateRequest(
            **{
                **request.model_dump(),
                "summary": "S" * 2_049,
            }
        )
    with pytest.raises(ValidationError):
        Phase5ManualFindingCreateRequest.model_validate(
            {
                **request.model_dump(mode="json", by_alias=True),
                "unexpectedField": "rejected",
            }
        )


def test_manual_import_requires_canonical_bounded_content_and_safe_metadata() -> None:
    encoded = base64.b64encode(b'{"synthetic":"local evidence"}').decode("ascii")
    request = Phase5ManualEvidenceImportRequest(
        profile_id=PROFILE_ID,
        finding_id=FINDING_ID,
        kind="RAW_JSON",
        content_base64=encoded,
        viewport=None,
        metadata=({"key": "source.label", "value": "Synthetic import"},),
    )

    assert "synthetic" not in repr(request)
    assert request.content_base64 == encoded

    with pytest.raises(ValidationError, match="encoding"):
        Phase5ManualEvidenceImportRequest(
            profile_id=PROFILE_ID,
            finding_id=FINDING_ID,
            kind="RAW_JSON",
            content_base64="not-base64!",
            viewport=None,
            metadata=(),
        )
    with pytest.raises(ValidationError, match="duplicated"):
        Phase5ManualEvidenceImportRequest(
            profile_id=PROFILE_ID,
            finding_id=FINDING_ID,
            kind="RAW_JSON",
            content_base64=encoded,
            viewport=None,
            metadata=(
                {"key": "source.label", "value": "Synthetic one"},
                {"key": "source.label", "value": "Synthetic two"},
            ),
        )
    with pytest.raises(ValidationError, match="at most"):
        Phase5ManualEvidenceImportRequest(
            profile_id=PROFILE_ID,
            finding_id=FINDING_ID,
            kind="RAW_JSON",
            content_base64="A" * (MAX_PHASE5_BASE64_CHARS + 1),
            viewport=None,
            metadata=(),
        )


def test_manual_screenshot_and_redacted_derivative_are_explicit() -> None:
    encoded = base64.b64encode(b"synthetic-redacted-bytes").decode("ascii")
    with pytest.raises(ValidationError, match="viewport"):
        Phase5ManualEvidenceImportRequest(
            profile_id=PROFILE_ID,
            finding_id=FINDING_ID,
            kind="SCREENSHOT",
            content_base64=encoded,
            viewport=None,
            metadata=(),
        )
    with pytest.raises(ValidationError):
        Phase5RedactedDerivativeRequest(
            profile_id=PROFILE_ID,
            original_artifact_id=ARTIFACT_ID,
            redacted_content_base64=encoded,
            already_redacted=False,
            redaction_policy_version="manual-v1",
            redaction_summary_code="SYNTHETIC_MASK",
        )
    request = Phase5RedactedDerivativeRequest(
        profile_id=PROFILE_ID,
        original_artifact_id=ARTIFACT_ID,
        redacted_content_base64=encoded,
        already_redacted=True,
        redaction_policy_version="manual-v1",
        redaction_summary_code="SYNTHETIC_MASK",
    )
    assert "synthetic" not in repr(request)


def test_decision_request_binds_expected_id_and_revision() -> None:
    first = Phase5AttributionDecisionRequest(
        profile_id=PROFILE_ID,
        finding_id=FINDING_ID,
        assessment_id=ASSESSMENT_ID,
        state="UNRESOLVED",
        expected_previous_decision_id=None,
        expected_previous_revision=0,
    )
    assert first.expected_previous_revision == 0

    with pytest.raises(ValidationError, match="inconsistent"):
        Phase5AttributionDecisionRequest(
            profile_id=PROFILE_ID,
            finding_id=FINDING_ID,
            assessment_id=ASSESSMENT_ID,
            state="UNRESOLVED",
            expected_previous_decision_id=DECISION_ID,
            expected_previous_revision=0,
        )


def test_phase5_artifact_requires_canonical_ids_and_verified_encryption_flag() -> None:
    with pytest.raises(ValidationError):
        Phase5EvidenceArtifact(
            **{
                **_artifact().model_dump(),
                "artifact_id": "artifact-synthetic",
            }
        )
    with pytest.raises(ValidationError):
        Phase5EvidenceArtifact(
            **{
                **_artifact().model_dump(),
                "encrypted_at_rest": False,
            }
        )
