from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from ariadne_core.api.phase6_schemas import (
    Phase6AuditRunListResult,
    Phase6AuditRunSummary,
    Phase6CompareRunsRequest,
    Phase6ComparisonResult,
    Phase6FindingDiff,
    Phase6FindingLifecycle,
    Phase6LifecycleEvent,
    Phase6LocalCheckpointRequest,
    Phase6LocalCheckpointResult,
    Phase6RemediationCase,
    Phase6RemediationCaseSummary,
    Phase6RemediationCreateRequest,
    Phase6RemediationDeadlineUpdateRequest,
    Phase6RemediationDetailResult,
    Phase6RemediationDraftUpdateRequest,
    Phase6RemediationEvidenceLinkRequest,
    Phase6RemediationHistoryEntry,
    Phase6RemediationProviderResponseRequest,
    Phase6RemediationReappearanceRequest,
    Phase6RemediationRequireApprovalRequest,
    Phase6RemediationStatusTransitionRequest,
)


def _id(number: int) -> str:
    return str(UUID(f"00000000-0000-4000-8000-{number:012d}"))


PROFILE_ID = _id(1)
BASELINE_ID = _id(2)
CURRENT_ID = _id(3)
FINDING_ID = _id(4)
CASE_ID = _id(5)


def test_audit_run_list_requires_unique_newest_first_runs() -> None:
    result = Phase6AuditRunListResult(
        profile_id=PROFILE_ID,
        runs=(
            Phase6AuditRunSummary(
                run_id=CURRENT_ID,
                sequence=2,
                captured_at_us=2,
                run_state="COMPLETED",
                finding_count=1,
                provider_count=1,
            ),
            Phase6AuditRunSummary(
                run_id=BASELINE_ID,
                sequence=1,
                captured_at_us=1,
                run_state="COMPLETED",
                finding_count=0,
                provider_count=1,
            ),
        ),
        has_more=False,
    )

    assert result.model_dump(mode="json", by_alias=True)["runs"][0]["runId"] == CURRENT_ID

    with pytest.raises(ValidationError, match="newest first"):
        Phase6AuditRunListResult(
            profile_id=PROFILE_ID,
            runs=tuple(reversed(result.runs)),
            has_more=False,
        )


def test_local_checkpoint_contract_requires_explicit_unique_coverage() -> None:
    request = Phase6LocalCheckpointRequest(
        profile_id=PROFILE_ID,
        run_state="PARTIAL",
        provider_coverage=(
            {"providerId": "synthetic-a", "state": "COMPLETE"},
            {"providerId": "synthetic-b", "state": "CHECK_FAILED"},
        ),
    )
    result = Phase6LocalCheckpointResult(
        profile_id=PROFILE_ID,
        run_id=CURRENT_ID,
        sequence=1,
        captured_at_us=10,
        run_state=request.run_state,
        finding_count=1,
        provider_count=2,
        local_only=True,
    )

    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["localOnly"] is True
    assert payload["findingCount"] == 1
    assert payload["providerCount"] == 2

    with pytest.raises(ValidationError, match="duplicated"):
        Phase6LocalCheckpointRequest(
            profile_id=PROFILE_ID,
            run_state="COMPLETED",
            provider_coverage=(
                {"providerId": "synthetic-a", "state": "COMPLETE"},
                {"providerId": "synthetic-a", "state": "BLOCKED"},
            ),
        )

    with pytest.raises(ValidationError):
        Phase6LocalCheckpointResult(
            **{
                **result.model_dump(),
                "local_only": False,
            }
        )


def test_comparison_contract_preserves_lifecycle_and_incomplete_state() -> None:
    result = Phase6ComparisonResult(
        profile_id=PROFILE_ID,
        baseline_run_id=BASELINE_ID,
        current_run_id=CURRENT_ID,
        diffs=(
            Phase6FindingDiff(
                stable_id=FINDING_ID,
                provider_id="synthetic-provider",
                state="NEW",
                previous_fingerprint=None,
                current_fingerprint="a" * 64,
            ),
        ),
        unresolved_absences=(),
        coverage=(),
        lifecycles=(
            Phase6FindingLifecycle(
                stable_id=FINDING_ID,
                provider_id="synthetic-provider",
                events=(
                    Phase6LifecycleEvent(
                        run_id=CURRENT_ID,
                        sequence=2,
                        run_state="COMPLETED",
                        provider_coverage="COMPLETE",
                        observed=True,
                        content_fingerprint="a" * 64,
                    ),
                ),
            ),
        ),
        incomplete_comparison=False,
        incomplete_reasons=(),
    )

    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["diffs"][0]["state"] == "NEW"
    assert payload["incompleteComparison"] is False

    with pytest.raises(ValidationError, match="incomplete state"):
        Phase6ComparisonResult(
            **{
                **result.model_dump(),
                "incomplete_comparison": True,
            }
        )


def test_comparison_request_rejects_same_run_and_noncanonical_ids() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        Phase6CompareRunsRequest(
            profile_id=PROFILE_ID,
            baseline_run_id=BASELINE_ID,
            current_run_id=BASELINE_ID,
        )

    with pytest.raises(ValidationError):
        Phase6CompareRunsRequest(
            profile_id="profile-local",
            baseline_run_id=BASELINE_ID,
            current_run_id=CURRENT_ID,
        )


def _summary() -> Phase6RemediationCaseSummary:
    return Phase6RemediationCaseSummary(
        case_id=CASE_ID,
        finding_ids=(FINDING_ID,),
        action="REQUEST_CORRECTION",
        action_disposition="DRAFT",
        status="OPEN",
        deadline_at_us=None,
        reappearance_count=0,
        revision=1,
        updated_at_us=10,
    )


def test_remediation_detail_requires_exact_append_only_history() -> None:
    summary = _summary()
    case = Phase6RemediationCase(
        **summary.model_dump(),
        draft_text="Synthetic correction draft.",
        evidence_references=(),
        provider_responses=(),
        last_reappearance_at_us=None,
        created_at_us=10,
        history=(
            Phase6RemediationHistoryEntry(
                revision=1,
                event_type="CASE_CREATED",
                actor_label="Local user",
                occurred_at_us=10,
                previous_status=None,
                current_status="OPEN",
                detail_code="CASE_CREATED",
                subject_id=None,
                evidence_references=(),
                note=None,
            ),
        ),
    )
    result = Phase6RemediationDetailResult(profile_id=PROFILE_ID, case=case)

    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["case"]["draftText"] == "Synthetic correction draft."
    assert payload["case"]["history"][0]["actorLabel"] == "Local user"

    with pytest.raises(ValidationError, match="history timestamp"):
        Phase6RemediationCase(
            **{
                **case.model_dump(),
                "updated_at_us": 11,
            }
        )


def test_remediation_summary_rejects_local_action_with_draft_disposition() -> None:
    with pytest.raises(ValidationError, match="disposition"):
        Phase6RemediationCaseSummary(
            **{
                **_summary().model_dump(),
                "action": "MONITOR",
                "action_disposition": "DRAFT",
            }
        )


def test_remediation_mutation_requests_are_strict_bounded_and_redacted() -> None:
    evidence_id = _id(6)
    create = Phase6RemediationCreateRequest.model_validate(
        {
            "profileId": PROFILE_ID,
            "findingIds": [FINDING_ID],
            "action": "REQUEST_CORRECTION",
            "deadlineAtUs": None,
            "evidenceReferences": [evidence_id],
            "draftText": "Synthetic local draft.",
        }
    )
    assert create.finding_ids == (FINDING_ID,)
    assert "Synthetic local draft" not in repr(create)

    requests = (
        Phase6RemediationDraftUpdateRequest(
            profile_id=PROFILE_ID,
            case_id=CASE_ID,
            expected_revision=1,
            draft_text="Updated synthetic draft.",
        ),
        Phase6RemediationRequireApprovalRequest(
            profile_id=PROFILE_ID,
            case_id=CASE_ID,
            expected_revision=1,
        ),
        Phase6RemediationStatusTransitionRequest(
            profile_id=PROFILE_ID,
            case_id=CASE_ID,
            expected_revision=1,
            target_status="IN_PROGRESS",
            note=None,
        ),
        Phase6RemediationDeadlineUpdateRequest(
            profile_id=PROFILE_ID,
            case_id=CASE_ID,
            expected_revision=1,
            deadline_at_us=None,
        ),
        Phase6RemediationEvidenceLinkRequest.model_validate(
            {
                "profileId": PROFILE_ID,
                "caseId": CASE_ID,
                "expectedRevision": 1,
                "evidenceReferences": [evidence_id],
            }
        ),
        Phase6RemediationProviderResponseRequest.model_validate(
            {
                "profileId": PROFILE_ID,
                "caseId": CASE_ID,
                "expectedRevision": 1,
                "providerId": "synthetic-provider",
                "responseCode": "RECEIVED",
                "summary": "Synthetic response summary.",
                "evidenceReferences": [],
            }
        ),
        Phase6RemediationReappearanceRequest.model_validate(
            {
                "profileId": PROFILE_ID,
                "caseId": CASE_ID,
                "expectedRevision": 1,
                "findingId": FINDING_ID,
                "evidenceReferences": [evidence_id],
            }
        ),
    )
    assert all(item.expected_revision == 1 for item in requests)
    assert "Synthetic response summary" not in repr(requests[-2])


def test_remediation_mutations_require_nullable_fields_and_valid_cas() -> None:
    common = {
        "profileId": PROFILE_ID,
        "caseId": CASE_ID,
        "expectedRevision": 1,
    }
    with pytest.raises(ValidationError, match="deadlineAtUs"):
        Phase6RemediationCreateRequest.model_validate(
            {
                "profileId": PROFILE_ID,
                "findingIds": [FINDING_ID],
                "action": "REQUEST_CORRECTION",
                "evidenceReferences": [],
                "draftText": None,
            }
        )
    with pytest.raises(ValidationError, match="note"):
        Phase6RemediationStatusTransitionRequest.model_validate(
            {**common, "targetStatus": "IN_PROGRESS"}
        )
    with pytest.raises(ValidationError, match="deadlineAtUs"):
        Phase6RemediationDeadlineUpdateRequest.model_validate(common)
    with pytest.raises(ValidationError, match="less_than"):
        Phase6RemediationRequireApprovalRequest.model_validate({**common, "expectedRevision": 256})
    with pytest.raises(ValidationError, match="duplicated"):
        Phase6RemediationEvidenceLinkRequest.model_validate(
            {**common, "evidenceReferences": [FINDING_ID, FINDING_ID]}
        )
    with pytest.raises(ValidationError, match="outbound drafts"):
        Phase6RemediationCreateRequest.model_validate(
            {
                "profileId": PROFILE_ID,
                "findingIds": [FINDING_ID],
                "action": "MONITOR",
                "deadlineAtUs": None,
                "evidenceReferences": [],
                "draftText": "Not allowed for a local action.",
            }
        )
