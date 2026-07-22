"""Profile-scoped projection and in-memory generation of one local report artifact.

The projection validates baseline/current ownership before collecting data and
returns bytes in memory so a separate file capability controls persistence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from uuid import UUID

from ariadne_core.api.reporting_schemas import (
    MAX_REPORT_API_RESPONSE_BYTES,
    ReportArtifactDescriptorResult,
    ReportArtifactFormat,
    ReportArtifactResult,
    ReportGenerateRequest,
    ReportGenerateResult,
    ReportManifestResult,
)
from ariadne_core.application.audit_comparison import AuditComparisonService
from ariadne_core.application.reporting import LocalReportGenerator, ReportSizeLimitExceeded
from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.audit_comparison import AuditComparison
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind, EvidenceCaptureMethod
from ariadne_core.domain.remediation import RemediationCase
from ariadne_core.domain.reporting import (
    MAX_REPORT_FINDINGS,
    MAX_REPORT_REMEDIATIONS,
    LocalReportInput,
    ReportAttributionSummary,
    ReportAuditComparison,
    ReportComparisonDiff,
    ReportEvidenceIntegrity,
    ReportEvidenceMetadata,
    ReportEvidenceMetadataEntry,
    ReportFindingOutcome,
    ReportFindingSeverity,
    ReportFindingSummary,
    ReportFindingVisibility,
    ReportNegativeSignalSource,
    ReportPositiveSignalSource,
    ReportProviderCoverage,
    ReportProviderResponse,
    ReportRemediationHistoryEntry,
    ReportRemediationSummary,
    ReportUnresolvedAbsence,
)
from ariadne_core.infrastructure.db.phase5_repository import (
    Phase5AttributionRepository,
    Phase5CheckpointEvidenceMaterial,
    Phase5CheckpointFindingMaterial,
    Phase5EvidenceRepository,
)
from ariadne_core.infrastructure.db.phase6_repository import (
    Phase6AuditRepository,
    Phase6RemediationRepository,
)
from ariadne_core.infrastructure.db.repositories import now_us


class ReportingUnavailable(RuntimeError):
    pass


class ReportingNotFound(LookupError):
    pass


class ReportingConflict(RuntimeError):
    pass


def _checkpoint_metadata(
    evidence: Phase5CheckpointEvidenceMaterial,
) -> tuple[ReportEvidenceMetadataEntry, ...]:
    values = [
        ("checkpoint.metadata_sha256", evidence.metadata_sha256),
        ("checkpoint.redirect_chain_sha256", evidence.redirect_chain_sha256),
    ]
    values.extend(
        (key, value)
        for key, value in (
            ("checkpoint.source_url_sha256", evidence.source_url_sha256),
            ("checkpoint.masked_query_sha256", evidence.masked_query_reference_sha256),
            ("checkpoint.viewport_sha256", evidence.viewport_sha256),
        )
        if value is not None
    )
    return tuple(ReportEvidenceMetadataEntry(key=key, value=value) for key, value in values)


def _evidence_projection(
    evidence: Phase5CheckpointEvidenceMaterial,
    *,
    source_url: str | None,
) -> ReportEvidenceMetadata:
    return ReportEvidenceMetadata(
        artifact_id=evidence.artifact_id,
        kind=EvidenceArtifactKind(evidence.kind),
        content_sha256=evidence.content_sha256,
        captured_at_us=evidence.captured_at_us,
        source_url=source_url,
        source_url_sha256=(
            None if source_url is None else hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        ),
        http_status=evidence.http_status,
        redirect_count=evidence.redirect_count,
        provider_id=evidence.provider_id,
        run_id=evidence.run_id,
        capture_method=EvidenceCaptureMethod(evidence.capture_method),
        integrity=ReportEvidenceIntegrity.NOT_VERIFIED,
        derivative_count=len(evidence.derivatives),
        metadata=_checkpoint_metadata(evidence),
    )


def _finding_projection(
    material: Phase5CheckpointFindingMaterial,
    source_urls: dict[str, str | None],
) -> ReportFindingSummary:
    finding = material.finding
    stored_assessment = material.latest_assessment
    if stored_assessment is None:
        raise ReportingConflict("report finding attribution is incomplete")
    assessment = stored_assessment.assessment
    decision = material.latest_decision
    evidence = tuple(
        _evidence_projection(item, source_url=source_urls[item.artifact_id])
        for item in material.evidence
    )
    updated_at_us = max(
        finding.updated_at_us,
        stored_assessment.assessed_at_us,
        0 if decision is None else decision.decision.decided_at_us,
    )
    return ReportFindingSummary(
        finding_id=finding.finding_id,
        provider_id=finding.provider_id,
        provider_label=finding.provider_label,
        provider_url=None,
        title=finding.title,
        summary=finding.summary,
        outcome=ReportFindingOutcome(finding.outcome.value),
        severity=ReportFindingSeverity(finding.severity.value),
        visibility=ReportFindingVisibility(finding.visibility.value),
        updated_at_us=updated_at_us,
        attribution=ReportAttributionSummary(
            weight_profile_version=assessment.weight_profile_version,
            score=assessment.score,
            confidence_band=assessment.confidence_band,
            human_state=None if decision is None else decision.decision.state,
            human_decided_at_us=(None if decision is None else decision.decision.decided_at_us),
            contributing_signals=tuple(item.signal for item in assessment.contributing_signals),
            contradiction_signals=tuple(item.signal for item in assessment.contradictions),
            contributing_signal_sources=tuple(
                ReportPositiveSignalSource(
                    signal=item.signal,
                    weight=item.weight,
                    evidence_references=item.evidence_references,
                )
                for item in assessment.contributing_signals
            ),
            contradiction_signal_sources=tuple(
                ReportNegativeSignalSource(
                    signal=item.signal,
                    penalty=item.penalty,
                    evidence_references=item.evidence_references,
                )
                for item in assessment.contradictions
            ),
            missing_evidence=tuple(item.signal for item in assessment.missing_evidence),
            recommended_next_evidence=assessment.recommended_next_evidence,
        ),
        evidence=evidence,
    )


def _comparison_projection(comparison: AuditComparison) -> ReportAuditComparison:
    return ReportAuditComparison(
        baseline_run_id=comparison.baseline_run_id,
        current_run_id=comparison.current_run_id,
        diffs=tuple(
            ReportComparisonDiff(
                finding_id=item.stable_id,
                provider_id=item.provider_id,
                state=item.state,
                previous_fingerprint=item.previous_fingerprint,
                current_fingerprint=item.current_fingerprint,
            )
            for item in comparison.diffs
        ),
        unresolved_absences=tuple(
            ReportUnresolvedAbsence(
                finding_id=item.stable_id,
                provider_id=item.provider_id,
                previous_fingerprint=item.previous_fingerprint,
                current_coverage=item.current_coverage,
            )
            for item in comparison.unresolved_absences
        ),
        coverage=tuple(
            ReportProviderCoverage(
                provider_id=item.provider_id,
                provider_url=None,
                baseline_state=item.baseline_state,
                current_state=item.current_state,
            )
            for item in comparison.coverage
        ),
        incomplete=comparison.incomplete_comparison,
        incomplete_reasons=comparison.incomplete_reasons,
    )


def _remediation_projection(case: RemediationCase) -> ReportRemediationSummary:
    return ReportRemediationSummary(
        case_id=case.case_id,
        finding_ids=case.finding_ids,
        action=case.action,
        action_disposition=case.action_disposition,
        status=case.status,
        deadline_at_us=case.deadline_at_us,
        draft_text=case.draft_text,
        evidence_references=case.evidence_references,
        provider_responses=tuple(
            ReportProviderResponse(
                provider_id=item.provider_id,
                response_code=item.response_code,
                summary=item.summary,
                received_at_us=item.received_at_us,
                evidence_references=item.evidence_references,
            )
            for item in case.provider_responses
        ),
        reappearance_count=case.reappearance_count,
        last_reappearance_at_us=case.last_reappearance_at_us,
        revision=case.revision,
        created_at_us=case.created_at_us,
        updated_at_us=case.updated_at_us,
        history=tuple(
            ReportRemediationHistoryEntry(
                revision=item.revision,
                event_type=item.event_type,
                actor_id=item.actor_id,
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


class ReportingProjectionCoordinator:
    """Generate a passive report from bounded encrypted profile state."""

    def __init__(
        self,
        vault: VaultManager,
        *,
        clock: Callable[[], int] = now_us,
        generator: LocalReportGenerator | None = None,
    ) -> None:
        self._vault = vault
        self._clock = clock
        self._generator = generator or LocalReportGenerator()

    def _repositories(
        self,
        profile_id: str,
    ) -> tuple[
        Phase5AttributionRepository,
        Phase5EvidenceRepository,
        Phase6AuditRepository,
        Phase6RemediationRepository,
    ]:
        if not self._vault.is_unlocked:
            raise ReportingUnavailable("report generation requires an unlocked vault")
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
            raise ReportingNotFound("report profile is unavailable") from error

    def generate(self, body: ReportGenerateRequest) -> ReportGenerateResult:
        phase5, evidence_repository, audits, remediation = self._repositories(body.profile_id)
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

            finding_count = phase5.count_findings()
            if finding_count > MAX_REPORT_FINDINGS:
                raise ReportingConflict("report finding capacity reached")
            stored_findings = phase5.list_findings(limit=MAX_REPORT_FINDINGS)
            if len(stored_findings) != finding_count:
                raise ReportingConflict("report finding projection is incomplete")
            provider_ids = tuple(sorted({item.provider_id for item in stored_findings}))
            materials = (
                ()
                if not provider_ids
                else phase5.local_checkpoint_materials(
                    provider_ids,
                    maximum_findings=MAX_REPORT_FINDINGS,
                )
            )
            if len(materials) != finding_count:
                raise ReportingConflict("report finding projection is incomplete")
            artifact_ids = tuple(
                sorted({item.artifact_id for material in materials for item in material.evidence})
            )
            source_urls = (
                {}
                if not artifact_ids
                else {
                    item.artifact_id: item.source_url
                    for item in evidence_repository.source_metadata_for_artifacts(artifact_ids)
                }
            )
            if set(source_urls) != set(artifact_ids):
                raise ReportingConflict("report evidence source projection is incomplete")

            remediation_count = remediation.count_cases()
            if remediation_count > MAX_REPORT_REMEDIATIONS:
                raise ReportingConflict("report remediation capacity reached")
            cases = remediation.list_cases(limit=MAX_REPORT_REMEDIATIONS)
            if len(cases) != remediation_count:
                raise ReportingConflict("report remediation projection is incomplete")

            generated_at_us = self._clock()
            source = LocalReportInput(
                profile_label=None,
                comparison=_comparison_projection(comparison),
                findings=tuple(_finding_projection(item, source_urls) for item in materials),
                remediations=tuple(_remediation_projection(item.case) for item in cases),
                generated_at_us=generated_at_us,
            )
            approval_id = (
                None if body.full_export_approval_id is None else UUID(body.full_export_approval_id)
            )
            bundle = self._generator.generate(
                source,
                mode=body.mode,
                full_export_approval_id=approval_id,
            )
            selected = (
                bundle.json_artifact
                if body.artifact_format is ReportArtifactFormat.JSON
                else bundle.markdown_artifact
            )
            result = ReportGenerateResult(
                profile_id=body.profile_id,
                baseline_run_id=body.baseline_run_id,
                current_run_id=body.current_run_id,
                local_only=True,
                artifact=ReportArtifactResult(
                    filename=selected.filename,
                    media_type=selected.media_type,
                    schema="ariadne.local-report",
                    version=1,
                    mode=selected.mode,
                    byte_count=selected.byte_count,
                    sha256=selected.sha256,
                    content=selected.text(),
                ),
                manifest=ReportManifestResult(
                    schema="ariadne.local-report",
                    version=1,
                    mode=bundle.manifest.mode,
                    generated_at_us=bundle.manifest.generated_at_us,
                    full_export_approval_id=(
                        None
                        if bundle.manifest.full_export_approval_id is None
                        else str(bundle.manifest.full_export_approval_id)
                    ),
                    artifacts=tuple(
                        ReportArtifactDescriptorResult(
                            filename=item.filename,
                            media_type=item.media_type,
                            byte_count=item.byte_count,
                            sha256=item.sha256,
                        )
                        for item in bundle.manifest.artifacts
                    ),
                ),
            )
            if len(result.model_dump_json(by_alias=True).encode("utf-8")) > (
                MAX_REPORT_API_RESPONSE_BYTES
            ):
                raise ReportingConflict("report API response capacity reached")
            return result
        except (ReportingConflict, ReportingNotFound, ReportingUnavailable):
            raise
        except LookupError as error:
            raise ReportingNotFound("report source record is unavailable") from error
        except ReportSizeLimitExceeded as error:
            raise ReportingConflict("report artifact capacity reached") from error
        except (RuntimeError, TypeError, ValueError) as error:
            raise ReportingConflict("report source data failed validation") from error
