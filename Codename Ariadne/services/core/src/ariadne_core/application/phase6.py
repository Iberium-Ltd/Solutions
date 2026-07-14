"""Application boundary for durable Phase 6 monitoring and local remediation."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from ariadne_core.api.phase6_schemas import (
    Phase6AuditRunListRequest,
    Phase6AuditRunListResult,
    Phase6AuditRunSummary,
    Phase6CompareRunsRequest,
    Phase6ComparisonResult,
    Phase6FindingDiff,
    Phase6FindingLifecycle,
    Phase6LifecycleEvent,
    Phase6LocalCheckpointRequest,
    Phase6LocalCheckpointResult,
    Phase6ProviderCoverageComparison,
    Phase6ProviderResponse,
    Phase6RemediationCase,
    Phase6RemediationCaseSummary,
    Phase6RemediationCreateRequest,
    Phase6RemediationDeadlineUpdateRequest,
    Phase6RemediationDetailRequest,
    Phase6RemediationDetailResult,
    Phase6RemediationDraftUpdateRequest,
    Phase6RemediationEvidenceLinkRequest,
    Phase6RemediationHistoryEntry,
    Phase6RemediationListRequest,
    Phase6RemediationListResult,
    Phase6RemediationProviderResponseRequest,
    Phase6RemediationReappearanceRequest,
    Phase6RemediationRequireApprovalRequest,
    Phase6RemediationStatusTransitionRequest,
    Phase6UnresolvedAbsence,
)
from ariadne_core.application.audit_comparison import AuditComparisonService
from ariadne_core.application.remediation import RemediationService
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.audit_comparison import (
    MAX_FINDINGS_PER_SNAPSHOT,
    AuditRunSnapshot,
    FindingSnapshot,
    ProviderCoverage,
    ProviderCoverageState,
)
from ariadne_core.domain.remediation import MAX_TIMESTAMP_US, RemediationCase
from ariadne_core.infrastructure.db.phase5_repository import (
    Phase5AttributionRepository,
    Phase5CheckpointFindingMaterial,
)
from ariadne_core.infrastructure.db.phase6_repository import (
    AuditSnapshotOrderConflict,
    Phase6AuditRepository,
    Phase6RemediationRepository,
)
from ariadne_core.infrastructure.db.repositories import now_us

LOCAL_ACTOR_ID = "local-user"
LOCAL_CHECKPOINT_FINGERPRINT_VERSION = "phase6-local-checkpoint-v1"


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _local_checkpoint_fingerprint(material: Phase5CheckpointFindingMaterial) -> str:
    finding = material.finding
    assessment_record = material.latest_assessment
    decision_record = material.latest_decision
    assessment = None
    if assessment_record is not None:
        assessment_value = assessment_record.assessment
        assessment = {
            "assessedAtUs": assessment_record.assessed_at_us,
            "assessmentId": assessment_record.assessment_id,
            "confidenceBand": assessment_value.confidence_band.value,
            "contradictions": [
                {
                    "evidenceReferences": sorted(item.evidence_references),
                    "penalty": item.penalty,
                    "signal": item.signal.value,
                }
                for item in sorted(
                    assessment_value.contradictions,
                    key=lambda item: (item.signal.value, item.penalty),
                )
            ],
            "contributingSignals": [
                {
                    "evidenceReferences": sorted(item.evidence_references),
                    "signal": item.signal.value,
                    "weight": item.weight,
                }
                for item in sorted(
                    assessment_value.contributing_signals,
                    key=lambda item: (item.signal.value, item.weight),
                )
            ],
            "humanReviewRequired": assessment_value.human_review_required,
            "missingEvidence": [
                {
                    "potentialWeight": item.potential_weight,
                    "signal": item.signal.value,
                }
                for item in sorted(
                    assessment_value.missing_evidence,
                    key=lambda item: (item.signal.value, item.potential_weight),
                )
            ],
            "payloadSha256": assessment_record.payload_sha256,
            "recommendedNextEvidence": [
                item.value for item in assessment_value.recommended_next_evidence
            ],
            "score": assessment_value.score,
            "weightProfileVersion": assessment_value.weight_profile_version,
        }
    decision = None
    if decision_record is not None:
        decision_value = decision_record.decision
        decision = {
            "assessmentId": decision_record.assessment_id,
            "decidedAtUs": decision_value.decided_at_us,
            "decisionId": decision_record.decision_id,
            "payloadSha256": decision_record.payload_sha256,
            "revision": decision_record.revision,
            "state": decision_value.state.value,
            "supersedesDecisionId": decision_record.supersedes_decision_id,
            "weightProfileVersion": decision_value.weight_profile_version,
        }
    evidence = [
        {
            "artifactId": item.artifact_id,
            "captureMethod": item.capture_method,
            "capturedAtUs": item.captured_at_us,
            "contentSha256": item.content_sha256,
            "derivatives": [
                {
                    "contentSha256": derivative.content_sha256,
                    "createdAtUs": derivative.created_at_us,
                    "derivativeId": derivative.derivative_id,
                    "redactionPolicyVersion": derivative.redaction_policy_version,
                    "redactionSummaryCode": derivative.redaction_summary_code,
                }
                for derivative in sorted(item.derivatives, key=lambda value: value.derivative_id)
            ],
            "httpStatus": item.http_status,
            "kind": item.kind,
            "linkedAtUs": item.linked_at_us,
            "maskedQueryReferenceSha256": item.masked_query_reference_sha256,
            "metadataSha256": item.metadata_sha256,
            "primaryFindingId": item.primary_finding_id,
            "providerId": item.provider_id,
            "redirectChainSha256": item.redirect_chain_sha256,
            "runId": item.run_id,
            "sourceUrlSha256": item.source_url_sha256,
            "viewportSha256": item.viewport_sha256,
        }
        for item in sorted(material.evidence, key=lambda value: value.artifact_id)
    ]
    return _canonical_sha256(
        {
            "assessment": assessment,
            "decision": decision,
            "evidence": evidence,
            "finding": {
                "createdAtUs": finding.created_at_us,
                "findingId": finding.finding_id,
                "observedAtUs": finding.observed_at_us,
                "outcome": finding.outcome.value,
                "providerId": finding.provider_id,
                "providerLabelSha256": _canonical_sha256(finding.provider_label),
                "revision": finding.revision,
                "severity": finding.severity.value,
                "summarySha256": _canonical_sha256(finding.summary),
                "titleSha256": _canonical_sha256(finding.title),
                "updatedAtUs": finding.updated_at_us,
                "visibility": finding.visibility.value,
            },
            "fingerprintVersion": LOCAL_CHECKPOINT_FINGERPRINT_VERSION,
        }
    )


class Phase6Unavailable(RuntimeError):
    pass


class Phase6NotFound(LookupError):
    pass


class Phase6Conflict(RuntimeError):
    pass


class Phase6Coordinator:
    """Project persisted snapshots and remediation history without outbound actions."""

    def __init__(self, vault: VaultManager) -> None:
        self._vault = vault

    def _repositories(
        self,
        profile_id: str,
    ) -> tuple[Phase6AuditRepository, Phase6RemediationRepository]:
        if not self._vault.is_unlocked:
            raise Phase6Unavailable("Phase 6 requires an unlocked vault")
        try:
            vault_id = self._vault.manifest.vault_id
            return (
                Phase6AuditRepository(
                    self._vault.engine,
                    vault_id=vault_id,
                    profile_id=profile_id,
                ),
                Phase6RemediationRepository(
                    self._vault.engine,
                    vault_id=vault_id,
                    profile_id=profile_id,
                ),
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 profile is unavailable") from error

    def list_audit_runs(self, body: Phase6AuditRunListRequest) -> Phase6AuditRunListResult:
        audits, _ = self._repositories(body.profile_id)
        try:
            summaries = audits.list_run_summaries(limit=body.limit)
            total = audits.count_snapshots()
            return Phase6AuditRunListResult(
                profile_id=body.profile_id,
                runs=tuple(
                    Phase6AuditRunSummary(
                        run_id=item.run_id,
                        sequence=item.sequence,
                        captured_at_us=item.captured_at_us,
                        run_state=item.run_state,
                        finding_count=item.finding_count,
                        provider_count=item.provider_count,
                    )
                    for item in summaries
                ),
                has_more=total > len(summaries),
            )
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 audit data failed validation") from error

    def create_local_checkpoint(
        self,
        body: Phase6LocalCheckpointRequest,
    ) -> Phase6LocalCheckpointResult:
        """Append a network-free snapshot of current durable Phase 5 state."""

        audits, _ = self._repositories(body.profile_id)
        coverage = tuple(
            ProviderCoverage(provider_id=item.provider_id, state=item.state)
            for item in sorted(body.provider_coverage, key=lambda item: item.provider_id)
        )
        provider_ids = tuple(item.provider_id for item in coverage)
        try:
            phase5 = Phase5AttributionRepository(
                self._vault.engine,
                vault_id=self._vault.manifest.vault_id,
                profile_id=body.profile_id,
            )
            materials = phase5.local_checkpoint_materials(
                provider_ids,
                maximum_findings=MAX_FINDINGS_PER_SNAPSHOT,
            )
            findings = tuple(
                FindingSnapshot(
                    stable_id=item.finding.finding_id,
                    provider_id=item.finding.provider_id,
                    content_fingerprint=_local_checkpoint_fingerprint(item),
                )
                for item in materials
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 local checkpoint profile is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 local checkpoint source failed validation") from error

        coverage_by_provider = {item.provider_id: item.state for item in coverage}
        forbidden = tuple(
            item.stable_id
            for item in findings
            if coverage_by_provider[item.provider_id]
            in {ProviderCoverageState.NOT_CHECKED, ProviderCoverageState.BLOCKED}
        )
        if forbidden:
            raise ValueError(
                "local checkpoint cannot include observed findings for unchecked "
                "or blocked providers"
            )

        last_order_conflict: AuditSnapshotOrderConflict | None = None
        for _attempt in range(3):
            try:
                sequence, captured_at_us = audits.next_snapshot_position(now_us())
                snapshot = AuditRunSnapshot(
                    run_id=str(uuid4()),
                    sequence=sequence,
                    captured_at_us=captured_at_us,
                    run_state=body.run_state,
                    findings=findings,
                    provider_coverage=coverage,
                )
                stored = audits.persist_snapshot(snapshot).snapshot
                return Phase6LocalCheckpointResult(
                    profile_id=body.profile_id,
                    run_id=stored.run_id,
                    sequence=stored.sequence,
                    captured_at_us=stored.captured_at_us,
                    run_state=stored.run_state,
                    finding_count=len(stored.findings),
                    provider_count=len(stored.provider_coverage),
                    local_only=True,
                )
            except AuditSnapshotOrderConflict as error:
                last_order_conflict = error
                continue
            except LookupError as error:
                raise Phase6NotFound("Phase 6 local checkpoint finding is unavailable") from error
            except (RuntimeError, ValueError) as error:
                raise Phase6Conflict("Phase 6 local checkpoint failed") from error
        raise Phase6Conflict("Phase 6 local checkpoint order conflict") from last_order_conflict

    def compare_runs(self, body: Phase6CompareRunsRequest) -> Phase6ComparisonResult:
        audits, _ = self._repositories(body.profile_id)
        try:
            timeline = audits.comparison_timeline(
                body.baseline_run_id,
                body.current_run_id,
            )
            comparison = AuditComparisonService().compare(
                timeline,
                baseline_run_id=body.baseline_run_id,
                current_run_id=body.current_run_id,
            )
            if (
                comparison.baseline_run_id != body.baseline_run_id
                or comparison.current_run_id != body.current_run_id
            ):
                raise Phase6Conflict("Phase 6 comparison identity is inconsistent")
            return Phase6ComparisonResult(
                profile_id=body.profile_id,
                baseline_run_id=comparison.baseline_run_id,
                current_run_id=comparison.current_run_id,
                diffs=tuple(
                    Phase6FindingDiff(
                        stable_id=item.stable_id,
                        provider_id=item.provider_id,
                        state=item.state,
                        previous_fingerprint=item.previous_fingerprint,
                        current_fingerprint=item.current_fingerprint,
                    )
                    for item in comparison.diffs
                ),
                unresolved_absences=tuple(
                    Phase6UnresolvedAbsence(
                        stable_id=item.stable_id,
                        provider_id=item.provider_id,
                        previous_fingerprint=item.previous_fingerprint,
                        current_coverage=item.current_coverage,
                    )
                    for item in comparison.unresolved_absences
                ),
                coverage=tuple(
                    Phase6ProviderCoverageComparison(
                        provider_id=item.provider_id,
                        baseline_state=item.baseline_state,
                        current_state=item.current_state,
                    )
                    for item in comparison.coverage
                ),
                lifecycles=tuple(
                    Phase6FindingLifecycle(
                        stable_id=item.stable_id,
                        provider_id=item.provider_id,
                        events=tuple(
                            Phase6LifecycleEvent(
                                run_id=event.run_id,
                                sequence=event.sequence,
                                run_state=event.run_state,
                                provider_coverage=event.provider_coverage,
                                observed=event.observed,
                                content_fingerprint=event.content_fingerprint,
                            )
                            for event in item.events
                        ),
                    )
                    for item in comparison.lifecycles
                ),
                incomplete_comparison=comparison.incomplete_comparison,
                incomplete_reasons=comparison.incomplete_reasons,
            )
        except Phase6Conflict:
            raise
        except LookupError as error:
            raise Phase6NotFound("Phase 6 audit run is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 comparison failed validation") from error

    def list_remediation_cases(
        self,
        body: Phase6RemediationListRequest,
    ) -> Phase6RemediationListResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            summaries = remediation.list_case_summaries(limit=body.limit)
            total = remediation.count_cases()
            return Phase6RemediationListResult(
                profile_id=body.profile_id,
                cases=tuple(
                    Phase6RemediationCaseSummary(
                        case_id=item.case_id,
                        finding_ids=item.finding_ids,
                        action=item.action,
                        action_disposition=item.action_disposition,
                        status=item.status,
                        deadline_at_us=item.deadline_at_us,
                        reappearance_count=item.reappearance_count,
                        revision=item.revision,
                        updated_at_us=item.updated_at_us,
                    )
                    for item in summaries
                ),
                has_more=total > len(summaries),
            )
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation data failed validation") from error

    def remediation_detail(
        self,
        body: Phase6RemediationDetailRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            return self._remediation_result(body.profile_id, case)
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation case is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation data failed validation") from error

    def create_remediation_case(
        self,
        body: Phase6RemediationCreateRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = RemediationService().create_case(
                case_id=str(uuid4()),
                finding_ids=body.finding_ids,
                action=body.action,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=now_us(),
                deadline_at_us=body.deadline_at_us,
                evidence_references=body.evidence_references,
                draft_text=body.draft_text,
            )
            stored = remediation.persist_case(
                case,
                expected_previous_revision=None,
            ).case
            return self._remediation_result(body.profile_id, stored)
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation references are unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation case creation failed") from error

    def update_remediation_draft(
        self,
        body: Phase6RemediationDraftUpdateRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().update_draft(
                case,
                expected_revision=body.expected_revision,
                draft_text=body.draft_text,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation case is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation draft update failed") from error

    def require_remediation_approval(
        self,
        body: Phase6RemediationRequireApprovalRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().require_explicit_approval(
                case,
                expected_revision=body.expected_revision,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation case is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation approval requirement failed") from error

    def transition_remediation_status(
        self,
        body: Phase6RemediationStatusTransitionRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().transition_status(
                case,
                expected_revision=body.expected_revision,
                target_status=body.target_status,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
                note=body.note,
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation case is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation status transition failed") from error

    def update_remediation_deadline(
        self,
        body: Phase6RemediationDeadlineUpdateRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().set_deadline(
                case,
                expected_revision=body.expected_revision,
                deadline_at_us=body.deadline_at_us,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation case is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation deadline update failed") from error

    def link_remediation_evidence(
        self,
        body: Phase6RemediationEvidenceLinkRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().link_evidence(
                case,
                expected_revision=body.expected_revision,
                evidence_references=body.evidence_references,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation evidence is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation evidence link failed") from error

    def record_remediation_provider_response(
        self,
        body: Phase6RemediationProviderResponseRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().record_provider_response(
                case,
                expected_revision=body.expected_revision,
                provider_id=body.provider_id,
                response_code=body.response_code,
                summary=body.summary,
                evidence_references=body.evidence_references,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation references are unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 provider response record failed") from error

    def record_remediation_reappearance(
        self,
        body: Phase6RemediationReappearanceRequest,
    ) -> Phase6RemediationDetailResult:
        _, remediation = self._repositories(body.profile_id)
        try:
            case = remediation.get_case(body.case_id).case
            updated = RemediationService().record_reappearance(
                case,
                expected_revision=body.expected_revision,
                finding_id=body.finding_id,
                evidence_references=body.evidence_references,
                actor_id=LOCAL_ACTOR_ID,
                occurred_at_us=self._next_event_time(case),
            )
            return self._persist_update(
                body.profile_id, remediation, updated, body.expected_revision
            )
        except LookupError as error:
            raise Phase6NotFound("Phase 6 remediation references are unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase6Conflict("Phase 6 remediation reappearance record failed") from error

    @classmethod
    def _persist_update(
        cls,
        profile_id: str,
        repository: Phase6RemediationRepository,
        case: RemediationCase,
        expected_revision: int,
    ) -> Phase6RemediationDetailResult:
        stored = repository.persist_case(
            case,
            expected_previous_revision=expected_revision,
        ).case
        return cls._remediation_result(profile_id, stored)

    @staticmethod
    def _next_event_time(case: RemediationCase) -> int:
        if case.updated_at_us >= MAX_TIMESTAMP_US:
            raise Phase6Conflict("Phase 6 remediation timestamp is exhausted")
        return max(now_us(), case.updated_at_us + 1)

    @staticmethod
    def _remediation_result(
        profile_id: str,
        case: RemediationCase,
    ) -> Phase6RemediationDetailResult:
        summary = Phase6RemediationCaseSummary(
            case_id=case.case_id,
            finding_ids=case.finding_ids,
            action=case.action,
            action_disposition=case.action_disposition,
            status=case.status,
            deadline_at_us=case.deadline_at_us,
            reappearance_count=case.reappearance_count,
            revision=case.revision,
            updated_at_us=case.updated_at_us,
        )
        result = Phase6RemediationCase(
            **summary.model_dump(),
            draft_text=case.draft_text,
            evidence_references=case.evidence_references,
            provider_responses=tuple(
                Phase6ProviderResponse(
                    provider_id=item.provider_id,
                    response_code=item.response_code,
                    summary=item.summary,
                    received_at_us=item.received_at_us,
                    evidence_references=item.evidence_references,
                )
                for item in case.provider_responses
            ),
            last_reappearance_at_us=case.last_reappearance_at_us,
            created_at_us=case.created_at_us,
            history=tuple(
                Phase6RemediationHistoryEntry(
                    revision=item.revision,
                    event_type=item.event_type,
                    actor_label="Local user",
                    occurred_at_us=item.occurred_at_us,
                    previous_status=item.previous_status,
                    current_status=item.current_status,
                    detail_code=item.detail_code,
                    subject_id=item.subject_id,
                    evidence_references=item.evidence_references,
                    note=item.note,
                )
                for item in case.history
            ),
        )
        return Phase6RemediationDetailResult(profile_id=profile_id, case=result)
