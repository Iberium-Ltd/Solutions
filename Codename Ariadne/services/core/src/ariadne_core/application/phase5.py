"""Application boundary for durable Phase 5 findings, evidence, and decisions.

It coordinates immutable evidence, append-only attribution history, and current
finding projections without treating a model or provider result as a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ariadne_core.api.phase5_schemas import (
    AttributionConfidenceBand as ApiAttributionConfidenceBand,
)
from ariadne_core.api.phase5_schemas import (
    AttributionMissingEvidence,
    AttributionNegativeContribution,
    AttributionPositiveContribution,
    EvidenceIntegrityStatus,
    EvidenceViewport,
    ManualEvidenceArtifactKind,
    Phase5AttributionAssessment,
    Phase5AttributionDecisionRequest,
    Phase5AttributionDecisionResult,
    Phase5EvidenceArtifact,
    Phase5EvidenceMetadata,
    Phase5FindingDetailRequest,
    Phase5FindingDetailResult,
    Phase5FindingListRequest,
    Phase5FindingListResult,
    Phase5FindingSummary,
    Phase5HumanDecision,
    Phase5ManualEvidenceImportRequest,
    Phase5ManualEvidenceImportResult,
    Phase5ManualFindingCreateRequest,
    Phase5RedactedDerivativeRequest,
    Phase5RedactedDerivativeResult,
    decode_phase5_content,
)
from ariadne_core.api.phase5_schemas import (
    FindingOutcome as ApiFindingOutcome,
)
from ariadne_core.api.phase5_schemas import (
    FindingSeverity as ApiFindingSeverity,
)
from ariadne_core.api.phase5_schemas import (
    FindingVisibility as ApiFindingVisibility,
)
from ariadne_core.api.phase5_schemas import (
    HumanAttributionState as ApiHumanAttributionState,
)
from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.application.evidence_artifacts import EvidenceArtifactService, sha256_hex
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.attribution import (
    AttributionCase,
    HumanAttributionDecision,
    HumanAttributionState,
    PositiveAttributionSignal,
)
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
)
from ariadne_core.domain.evidence_artifacts import (
    EvidenceViewport as DomainEvidenceViewport,
)
from ariadne_core.infrastructure.db.phase5_repository import (
    AttributionRevisionConflict,
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
    Phase5AttributionRepository,
    Phase5EvidenceRepository,
    StoredAttributionAssessment,
    StoredAttributionDecision,
    StoredFinding,
)
from ariadne_core.infrastructure.db.repositories import now_us


class Phase5Unavailable(RuntimeError):
    pass


class Phase5NotFound(LookupError):
    pass


class Phase5Conflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _FindingContext:
    finding: StoredFinding
    assessment: StoredAttributionAssessment
    decision: StoredAttributionDecision | None
    artifact_count: int


class Phase5Coordinator:
    """Project and append encrypted records without exposing evidence bytes."""

    def __init__(self, vault: VaultManager) -> None:
        self._vault = vault

    def _repositories(
        self,
        profile_id: str,
    ) -> tuple[Phase5AttributionRepository, Phase5EvidenceRepository]:
        if not self._vault.is_unlocked:
            raise Phase5Unavailable("Phase 5 requires an unlocked vault")
        try:
            vault_id = self._vault.manifest.vault_id
            return (
                Phase5AttributionRepository(
                    self._vault.engine,
                    vault_id=vault_id,
                    profile_id=profile_id,
                ),
                Phase5EvidenceRepository(
                    self._vault.engine,
                    vault_id=vault_id,
                    profile_id=profile_id,
                ),
            )
        except LookupError as error:
            raise Phase5NotFound("Phase 5 profile is unavailable") from error

    def create_manual_finding(
        self,
        body: Phase5ManualFindingCreateRequest,
    ) -> Phase5FindingDetailResult:
        attribution, _evidence = self._repositories(body.profile_id)
        timestamp = now_us()
        finding_id = str(uuid4())
        assessment_id = str(uuid4())
        assessment = AttributionScoringService().assess(
            AttributionCase(
                case_id=finding_id,
                missing_evidence=frozenset(PositiveAttributionSignal),
            )
        )
        try:
            attribution.persist_manual_finding_with_initial_assessment(
                draft=FindingDraft(
                    finding_id=finding_id,
                    title=body.title,
                    summary=body.summary,
                    outcome=FindingOutcome(body.outcome.value),
                    severity=FindingSeverity(body.severity.value),
                    visibility=FindingVisibility(body.visibility.value),
                    provider_id=body.provider_id,
                    provider_label=body.provider_label,
                    observed_at_us=timestamp,
                ),
                assessment_id=assessment_id,
                assessment=assessment,
                assessed_at_us=timestamp,
            )
        except LookupError as error:
            raise Phase5NotFound("Phase 5 profile is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 manual finding failed validation") from error
        return self.finding_detail(
            Phase5FindingDetailRequest(
                profile_id=body.profile_id,
                finding_id=finding_id,
            )
        )

    def list_findings(self, body: Phase5FindingListRequest) -> Phase5FindingListResult:
        attribution, evidence = self._repositories(body.profile_id)
        try:
            stored = attribution.list_findings(limit=body.limit)
            contexts = tuple(self._context(attribution, evidence, finding) for finding in stored)
            total = attribution.count_findings()
        except LookupError as error:
            raise Phase5NotFound("Phase 5 finding data is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 finding data failed validation") from error
        return Phase5FindingListResult(
            profile_id=body.profile_id,
            findings=tuple(self._summary(item) for item in contexts),
            has_more=total > len(contexts),
        )

    def finding_detail(self, body: Phase5FindingDetailRequest) -> Phase5FindingDetailResult:
        attribution, evidence = self._repositories(body.profile_id)
        try:
            finding = attribution.get_finding(body.finding_id)
            context = self._context(attribution, evidence, finding)
            if context.artifact_count > 64:
                raise Phase5Conflict("Phase 5 finding evidence exceeds the detail bound")
            artifacts = evidence.originals_for_finding(body.finding_id, limit=64)
            artifact_results = tuple(
                Phase5EvidenceArtifact(
                    artifact_id=artifact.artifact_id,
                    kind=artifact.kind,
                    content_sha256=artifact.content_sha256,
                    captured_at_us=artifact.captured_at_us,
                    source_url=artifact.source_url,
                    http_status=artifact.http_status,
                    redirect_count=len(artifact.redirect_chain),
                    provider_id=artifact.provider_id,
                    run_id=artifact.run_id,
                    viewport=(
                        None
                        if artifact.viewport is None
                        else EvidenceViewport(
                            width=artifact.viewport.width,
                            height=artifact.viewport.height,
                            device_scale_micros=artifact.viewport.device_scale_micros,
                        )
                    ),
                    capture_method=artifact.capture_method,
                    encrypted_at_rest=True,
                    # Reconstructing EvidenceArtifactOriginal verifies its SHA-256.
                    # Corrupt rows fail closed before this response is constructed.
                    integrity_status=EvidenceIntegrityStatus.VERIFIED,
                    derivative_count=evidence.count_derivatives(artifact.artifact_id),
                )
                for artifact in artifacts
            )
        except Phase5Conflict:
            raise
        except LookupError as error:
            raise Phase5NotFound("Phase 5 finding is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 finding data failed validation") from error

        assessment = context.assessment.assessment
        decision = context.decision
        return Phase5FindingDetailResult(
            profile_id=body.profile_id,
            finding=self._summary(context),
            assessment=Phase5AttributionAssessment(
                assessment_id=context.assessment.assessment_id,
                case_id=assessment.case_id,
                weight_profile_version=assessment.weight_profile_version,
                score=assessment.score,
                confidence_band=ApiAttributionConfidenceBand(assessment.confidence_band.value),
                contributing_signals=tuple(
                    AttributionPositiveContribution(
                        signal=item.signal,
                        weight=item.weight,
                        evidence_artifact_ids=item.evidence_references,
                    )
                    for item in assessment.contributing_signals
                ),
                contradictions=tuple(
                    AttributionNegativeContribution(
                        signal=item.signal,
                        penalty=item.penalty,
                        evidence_artifact_ids=item.evidence_references,
                    )
                    for item in assessment.contradictions
                ),
                missing_evidence=tuple(
                    AttributionMissingEvidence(
                        signal=item.signal,
                        potential_weight=item.potential_weight,
                    )
                    for item in assessment.missing_evidence
                ),
                recommended_next_evidence=assessment.recommended_next_evidence,
                human_review_required=True,
            ),
            artifacts=artifact_results,
            human_decision=(
                None
                if decision is None
                else Phase5HumanDecision(
                    decision_id=decision.decision_id,
                    assessment_id=decision.assessment_id,
                    state=ApiHumanAttributionState(decision.decision.state.value),
                    actor_label="Local user",
                    decided_at_us=decision.decision.decided_at_us,
                    weight_profile_version=decision.decision.weight_profile_version,
                    supersedes_decision_id=decision.supersedes_decision_id,
                    revision=decision.revision,
                )
            ),
        )

    def manual_evidence_import(
        self,
        body: Phase5ManualEvidenceImportRequest,
    ) -> Phase5ManualEvidenceImportResult:
        attribution, evidence = self._repositories(body.profile_id)
        try:
            # Resolve scope before decoding a potentially large local payload.
            attribution.get_finding(body.finding_id)
            content = decode_phase5_content(body.content_base64)
            content_sha256 = sha256_hex(content)
            viewport = self._domain_viewport(body.viewport)
            metadata = self._domain_metadata(body.metadata)
            existing = evidence.original_by_hash(content_sha256)
            if existing is not None and (
                existing.kind.value != body.kind.value
                or existing.capture_method.value != "MANUAL_LOCAL_IMPORT"
                or existing.viewport != viewport
                or existing.metadata != metadata
            ):
                raise Phase5Conflict(
                    "Phase 5 evidence content already exists with incompatible provenance"
                )
            result = EvidenceArtifactService(evidence).manual_local_import(
                artifact_id=str(uuid4()),
                kind=EvidenceArtifactKind(body.kind.value),
                content=content,
                content_sha256=content_sha256,
                captured_at_us=now_us(),
                provider_id="manual-import",
                run_id=str(uuid4()),
                finding_id=body.finding_id,
                viewport=viewport,
                metadata=metadata,
            )
        except Phase5Conflict:
            raise
        except LookupError as error:
            raise Phase5NotFound("Phase 5 finding is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 evidence import failed validation") from error
        artifact = result.artifact
        return Phase5ManualEvidenceImportResult(
            profile_id=body.profile_id,
            finding_id=body.finding_id,
            artifact_id=artifact.artifact_id,
            kind=ManualEvidenceArtifactKind(artifact.kind.value),
            content_sha256=artifact.content_sha256,
            captured_at_us=artifact.captured_at_us,
            capture_method=EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT,
            encrypted_at_rest=True,
            local_only=True,
            deduplicated=result.deduplicated,
        )

    def create_redacted_derivative(
        self,
        body: Phase5RedactedDerivativeRequest,
    ) -> Phase5RedactedDerivativeResult:
        _attribution, evidence = self._repositories(body.profile_id)
        try:
            # The bytes are supplied and explicitly attested as already redacted;
            # this boundary performs no inferred or automatic transformation.
            content = decode_phase5_content(body.redacted_content_base64)
            content_sha256 = sha256_hex(content)
            existing = evidence.derivative_by_hash(
                body.original_artifact_id,
                content_sha256,
            )
            if existing is not None and (
                existing.redaction_policy_version != body.redaction_policy_version
                or existing.redaction_summary_code != body.redaction_summary_code
            ):
                raise Phase5Conflict(
                    "Phase 5 derivative content already exists with incompatible redaction metadata"
                )
            result = EvidenceArtifactService(evidence).create_redacted_derivative(
                derivative_id=str(uuid4()),
                original_artifact_id=body.original_artifact_id,
                content=content,
                content_sha256=content_sha256,
                created_at_us=now_us(),
                redaction_policy_version=body.redaction_policy_version,
                redaction_summary_code=body.redaction_summary_code,
            )
        except Phase5Conflict:
            raise
        except LookupError as error:
            raise Phase5NotFound("Phase 5 original evidence is unavailable") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 evidence derivative failed validation") from error
        derivative = result.derivative
        return Phase5RedactedDerivativeResult(
            profile_id=body.profile_id,
            original_artifact_id=derivative.original_artifact_id,
            derivative_id=derivative.derivative_id,
            content_sha256=derivative.content_sha256,
            created_at_us=derivative.created_at_us,
            redaction_policy_version=derivative.redaction_policy_version,
            redaction_summary_code=derivative.redaction_summary_code,
            redaction_mode="CALLER_SUPPLIED",
            encrypted_at_rest=True,
            local_only=True,
            deduplicated=result.deduplicated,
        )

    def append_attribution_decision(
        self,
        body: Phase5AttributionDecisionRequest,
    ) -> Phase5AttributionDecisionResult:
        attribution, _evidence = self._repositories(body.profile_id)
        try:
            attribution.get_finding(body.finding_id)
            assessment = attribution.get_assessment(body.assessment_id)
            latest_assessment = attribution.latest_assessment(body.finding_id)
            if (
                assessment.finding_id != body.finding_id
                or latest_assessment is None
                or latest_assessment.assessment_id != assessment.assessment_id
            ):
                raise Phase5Conflict("Phase 5 attribution assessment is stale")
            previous = attribution.latest_decision(body.finding_id)
            previous_id = None if previous is None else previous.decision_id
            previous_revision = 0 if previous is None else previous.revision
            if (
                previous_id != body.expected_previous_decision_id
                or previous_revision != body.expected_previous_revision
            ):
                raise Phase5Conflict("Phase 5 attribution decision revision conflict")
            decided_at_us = now_us()
            if decided_at_us < assessment.assessed_at_us:
                raise Phase5Conflict("Phase 5 attribution assessment time is invalid")
            stored = attribution.persist_decision(
                decision_id=str(uuid4()),
                assessment_id=assessment.assessment_id,
                decision=HumanAttributionDecision(
                    case_id=body.finding_id,
                    state=HumanAttributionState(body.state.value),
                    actor_id="local-user",
                    decided_at_us=decided_at_us,
                    weight_profile_version=assessment.assessment.weight_profile_version,
                ),
                expected_previous_decision_id=body.expected_previous_decision_id,
            )
        except Phase5Conflict:
            raise
        except LookupError as error:
            raise Phase5NotFound("Phase 5 attribution data is unavailable") from error
        except AttributionRevisionConflict as error:
            raise Phase5Conflict("Phase 5 attribution decision revision conflict") from error
        except (RuntimeError, ValueError) as error:
            raise Phase5Conflict("Phase 5 attribution decision failed validation") from error
        return Phase5AttributionDecisionResult(
            profile_id=body.profile_id,
            finding_id=body.finding_id,
            assessment_id=stored.assessment_id,
            decision_id=stored.decision_id,
            state=ApiHumanAttributionState(stored.decision.state.value),
            actor_label="Local user",
            decided_at_us=stored.decision.decided_at_us,
            weight_profile_version=stored.decision.weight_profile_version,
            supersedes_decision_id=stored.supersedes_decision_id,
            revision=stored.revision,
        )

    @staticmethod
    def _domain_viewport(viewport: EvidenceViewport | None) -> DomainEvidenceViewport | None:
        if viewport is None:
            return None
        return DomainEvidenceViewport(
            width=viewport.width,
            height=viewport.height,
            device_scale_micros=viewport.device_scale_micros,
        )

    @staticmethod
    def _domain_metadata(
        metadata: tuple[Phase5EvidenceMetadata, ...],
    ) -> tuple[EvidenceMetadataEntry, ...]:
        return tuple(EvidenceMetadataEntry(item.key, item.value) for item in metadata)

    @staticmethod
    def _context(
        attribution: Phase5AttributionRepository,
        evidence: Phase5EvidenceRepository,
        finding: StoredFinding,
    ) -> _FindingContext:
        assessment = attribution.latest_assessment(finding.finding_id)
        if assessment is None:
            raise Phase5Conflict("Phase 5 finding attribution is incomplete")
        return _FindingContext(
            finding=finding,
            assessment=assessment,
            decision=attribution.latest_decision(finding.finding_id),
            artifact_count=evidence.count_originals_for_finding(finding.finding_id),
        )

    @staticmethod
    def _summary(context: _FindingContext) -> Phase5FindingSummary:
        assessment = context.assessment.assessment
        decision = context.decision
        updated_at_us = max(
            context.finding.updated_at_us,
            context.assessment.assessed_at_us,
            0 if decision is None else decision.decision.decided_at_us,
        )
        return Phase5FindingSummary(
            finding_id=context.finding.finding_id,
            title=context.finding.title,
            summary=context.finding.summary,
            outcome=ApiFindingOutcome(context.finding.outcome.value),
            severity=ApiFindingSeverity(context.finding.severity.value),
            visibility=ApiFindingVisibility(context.finding.visibility.value),
            attribution_state=(
                None
                if decision is None
                else ApiHumanAttributionState(decision.decision.state.value)
            ),
            confidence_band=ApiAttributionConfidenceBand(assessment.confidence_band.value),
            score=assessment.score,
            human_review_required=True,
            provider_label=context.finding.provider_label,
            artifact_count=context.artifact_count,
            updated_at_us=updated_at_us,
        )
