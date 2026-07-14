"""Pure generation of bounded local JSON and Markdown report artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from ariadne_core.application.import_export import ExportMode
from ariadne_core.domain.reporting import (
    MAX_REPORT_BYTES,
    LocalReportInput,
    ReportEvidenceMetadata,
    ReportFindingSummary,
    ReportRemediationHistoryEntry,
    ReportRemediationSummary,
)

REPORT_SCHEMA: Final = "ariadne.local-report"
REPORT_SCHEMA_VERSION: Final = 1
REDACTION_POLICY_VERSION: Final = "opaque-remap-exact-source-v2"
SENSITIVE_VALUE_REDACTION: Final = "REMOVED_IN_REDACTED_REPORT"
JSON_MEDIA_TYPE: Final = "application/json"
MARKDOWN_MEDIA_TYPE: Final = "text/markdown; charset=utf-8"


class ReportSizeLimitExceeded(ValueError):
    """One generated report artifact exceeded the fixed local size limit."""


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    filename: str
    media_type: str
    schema: str
    version: int
    mode: ExportMode
    byte_count: int
    sha256: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.filename not in {"report.json", "report.md"}:
            raise ValueError("report artifact filename is invalid")
        if self.media_type not in {JSON_MEDIA_TYPE, MARKDOWN_MEDIA_TYPE}:
            raise ValueError("report artifact media type is invalid")
        if self.schema != REPORT_SCHEMA or self.version != REPORT_SCHEMA_VERSION:
            raise ValueError("report artifact schema is invalid")
        if not isinstance(self.mode, ExportMode):
            raise TypeError("report artifact mode is invalid")
        if type(self.content) is not bytes or not self.content:
            raise ValueError("report artifact content is invalid")
        if self.byte_count != len(self.content) or self.byte_count > MAX_REPORT_BYTES:
            raise ValueError("report artifact byte count is invalid")
        if self.sha256 != hashlib.sha256(self.content).hexdigest():
            raise ValueError("report artifact hash is invalid")

    def text(self) -> str:
        return self.content.decode("utf-8")


@dataclass(frozen=True, slots=True)
class ReportArtifactDescriptor:
    filename: str
    media_type: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LocalReportManifest:
    schema: str
    version: int
    mode: ExportMode
    generated_at_us: int
    full_export_approval_id: UUID | None
    artifacts: tuple[ReportArtifactDescriptor, ...]


@dataclass(frozen=True, slots=True)
class LocalReportBundle:
    manifest: LocalReportManifest
    json_artifact: ReportArtifact
    markdown_artifact: ReportArtifact


@dataclass(frozen=True, slots=True)
class _RedactionMap:
    ids: dict[str, str]

    def opaque_id(self, value: str) -> str:
        return self.ids[value]


def _opaque_labels(values: set[str], prefix: str) -> dict[str, str]:
    """Assign deterministic, injective labels that never equal an input value."""

    labels: dict[str, str] = {}
    blocked = set(values)
    assigned: set[str] = set()
    next_index = 1
    for value in sorted(values):
        candidate = f"{prefix}-{next_index:06d}"
        while candidate in blocked or candidate in assigned:
            next_index += 1
            candidate = f"{prefix}-{next_index:06d}"
        labels[value] = candidate
        assigned.add(candidate)
        next_index += 1
    return labels


def _redaction_map(source: LocalReportInput) -> _RedactionMap:
    ids = {
        source.comparison.baseline_run_id,
        source.comparison.current_run_id,
    }
    for diff in source.comparison.diffs:
        ids.update((diff.finding_id, diff.provider_id))
    for absence in source.comparison.unresolved_absences:
        ids.update((absence.finding_id, absence.provider_id))
    for coverage in source.comparison.coverage:
        ids.add(coverage.provider_id)
    for finding in source.findings:
        ids.update((finding.finding_id, finding.provider_id))
        for evidence in finding.evidence:
            ids.update((evidence.artifact_id, evidence.provider_id, evidence.run_id))
    for case in source.remediations:
        ids.add(case.case_id)
        ids.update(case.finding_ids)
        ids.update(case.evidence_references)
        for response in case.provider_responses:
            ids.add(response.provider_id)
            ids.update(response.evidence_references)
        for entry in case.history:
            ids.add(entry.actor_id)
            ids.update(entry.evidence_references)
            if entry.subject_id is not None:
                ids.add(entry.subject_id)
    return _RedactionMap(ids=_opaque_labels(ids, "redacted-id"))


@dataclass(frozen=True, slots=True)
class _ProjectionPolicy:
    mode: ExportMode
    redactions: _RedactionMap

    @property
    def redacted(self) -> bool:
        return self.mode is ExportMode.REDACTED

    def opaque_id(self, value: str) -> str:
        return self.redactions.opaque_id(value) if self.redacted else value

    def url(self, value: str | None) -> str | None:
        if value is None:
            return None
        return None if self.redacted else value

    def url_redaction(self, value: str | None) -> str | None:
        if value is None or not self.redacted:
            return None
        return SENSITIVE_VALUE_REDACTION

    def sensitive(self, value: str | None, replacement: str) -> str | None:
        if value is None:
            return None
        return replacement if self.redacted else value


def _evidence_projection(
    evidence: ReportEvidenceMetadata,
    policy: _ProjectionPolicy,
) -> dict[str, object]:
    artifact_id = policy.opaque_id(evidence.artifact_id)
    metadata = []
    for item in sorted(evidence.metadata, key=lambda value: value.key):
        safe_hash = (
            item.key.endswith("_sha256")
            and len(item.value) == 64
            and all(character in "0123456789abcdef" for character in item.value)
        )
        metadata.append(
            {
                "key": item.key,
                "redaction": (
                    SENSITIVE_VALUE_REDACTION if policy.redacted and not safe_hash else None
                ),
                "value": None if policy.redacted and not safe_hash else item.value,
            }
        )
    return {
        "artifact_id": artifact_id,
        "capture_method": evidence.capture_method.value,
        "captured_at_us": evidence.captured_at_us,
        "content_sha256": evidence.content_sha256,
        "derivative_count": evidence.derivative_count,
        "http_status": evidence.http_status,
        "integrity": evidence.integrity.value,
        "kind": evidence.kind.value,
        "metadata": metadata,
        "provider_id": policy.opaque_id(evidence.provider_id),
        "redirect_count": evidence.redirect_count,
        "run_id": policy.opaque_id(evidence.run_id),
        "source_url": policy.url(evidence.source_url),
        "source_url_redaction": policy.url_redaction(evidence.source_url),
        "source_url_sha256": evidence.source_url_sha256,
    }


def _finding_projection(
    finding: ReportFindingSummary,
    policy: _ProjectionPolicy,
) -> dict[str, object]:
    finding_id = policy.opaque_id(finding.finding_id)
    attribution = finding.attribution
    return {
        "attribution": {
            "confidence_band": attribution.confidence_band.value,
            "contradiction_signals": sorted(
                item.value for item in attribution.contradiction_signals
            ),
            "contradiction_signal_sources": [
                {
                    "evidence_references": sorted(
                        policy.opaque_id(reference) for reference in item.evidence_references
                    ),
                    "penalty": item.penalty,
                    "signal": item.signal.value,
                }
                for item in sorted(
                    attribution.contradiction_signal_sources,
                    key=lambda value: value.signal.value,
                )
            ],
            "contributing_signals": sorted(item.value for item in attribution.contributing_signals),
            "contributing_signal_sources": [
                {
                    "evidence_references": sorted(
                        policy.opaque_id(reference) for reference in item.evidence_references
                    ),
                    "signal": item.signal.value,
                    "weight": item.weight,
                }
                for item in sorted(
                    attribution.contributing_signal_sources,
                    key=lambda value: value.signal.value,
                )
            ],
            "human_decided_at_us": attribution.human_decided_at_us,
            "human_review_required": attribution.human_review_required,
            "human_state": None
            if attribution.human_state is None
            else attribution.human_state.value,
            "missing_evidence": sorted(item.value for item in attribution.missing_evidence),
            "recommended_next_evidence": sorted(
                item.value for item in attribution.recommended_next_evidence
            ),
            "score": attribution.score,
            "weight_profile_version": attribution.weight_profile_version,
        },
        "evidence": [
            _evidence_projection(item, policy)
            for item in sorted(finding.evidence, key=lambda value: value.artifact_id)
        ],
        "finding_id": finding_id,
        "outcome": finding.outcome.value,
        "provider_id": policy.opaque_id(finding.provider_id),
        "provider_label": policy.sensitive(
            finding.provider_label,
            f"provider-label-for-{policy.opaque_id(finding.provider_id)}-redacted",
        ),
        "provider_url": policy.url(finding.provider_url),
        "provider_url_redaction": policy.url_redaction(finding.provider_url),
        "severity": finding.severity.value,
        "summary": policy.sensitive(
            finding.summary,
            f"summary-for-{finding_id}-redacted",
        ),
        "title": policy.sensitive(finding.title, f"title-for-{finding_id}-redacted"),
        "updated_at_us": finding.updated_at_us,
        "visibility": finding.visibility.value,
    }


def _history_projection(
    case_id: str,
    entry: ReportRemediationHistoryEntry,
    policy: _ProjectionPolicy,
) -> dict[str, object]:
    return {
        "actor_id": policy.opaque_id(entry.actor_id),
        "current_status": entry.current_status.value,
        "detail_code": entry.detail_code,
        "event_type": entry.event_type.value,
        "evidence_references": sorted(
            policy.opaque_id(value) for value in entry.evidence_references
        ),
        "note": policy.sensitive(
            entry.note,
            f"note-for-{case_id}-revision-{entry.revision}-redacted",
        ),
        "occurred_at_us": entry.occurred_at_us,
        "previous_status": None if entry.previous_status is None else entry.previous_status.value,
        "revision": entry.revision,
        "subject_id": None if entry.subject_id is None else policy.opaque_id(entry.subject_id),
    }


def _remediation_projection(
    remediation: ReportRemediationSummary,
    policy: _ProjectionPolicy,
) -> dict[str, object]:
    case_id = policy.opaque_id(remediation.case_id)
    responses = sorted(
        remediation.provider_responses,
        key=lambda value: (
            value.received_at_us,
            value.provider_id,
            value.response_code,
            value.summary,
            value.evidence_references,
        ),
    )
    return {
        "action": remediation.action.value,
        "action_disposition": remediation.action_disposition.value,
        "case_id": case_id,
        "created_at_us": remediation.created_at_us,
        "deadline_at_us": remediation.deadline_at_us,
        "draft_text": policy.sensitive(
            remediation.draft_text,
            f"draft-for-{case_id}-redacted",
        ),
        "evidence_references": sorted(
            policy.opaque_id(value) for value in remediation.evidence_references
        ),
        "finding_ids": sorted(policy.opaque_id(value) for value in remediation.finding_ids),
        "history": [
            _history_projection(case_id, item, policy)
            for item in sorted(remediation.history, key=lambda value: value.revision)
        ],
        "last_reappearance_at_us": remediation.last_reappearance_at_us,
        "provider_responses": [
            {
                "evidence_references": sorted(
                    policy.opaque_id(value) for value in item.evidence_references
                ),
                "provider_id": policy.opaque_id(item.provider_id),
                "received_at_us": item.received_at_us,
                "response_code": item.response_code,
                "summary": policy.sensitive(
                    item.summary,
                    f"response-for-{case_id}-{index:03d}-redacted",
                ),
            }
            for index, item in enumerate(responses, start=1)
        ],
        "reappearance_count": remediation.reappearance_count,
        "revision": remediation.revision,
        "status": remediation.status.value,
        "updated_at_us": remediation.updated_at_us,
    }


def _report_document(
    source: LocalReportInput,
    *,
    mode: ExportMode,
    full_export_approval_id: UUID | None,
) -> dict[str, object]:
    policy = _ProjectionPolicy(mode=mode, redactions=_redaction_map(source))
    comparison = source.comparison
    finding_count = len(source.findings)
    evidence_count = sum(len(item.evidence) for item in source.findings)
    remediation_count = len(source.remediations)
    return {
        "comparison": {
            "baseline_run_id": policy.opaque_id(comparison.baseline_run_id),
            "coverage": [
                {
                    "baseline_state": None
                    if item.baseline_state is None
                    else item.baseline_state.value,
                    "current_state": None
                    if item.current_state is None
                    else item.current_state.value,
                    "provider_id": policy.opaque_id(item.provider_id),
                    "provider_url": policy.url(item.provider_url),
                    "provider_url_redaction": policy.url_redaction(item.provider_url),
                }
                for item in sorted(comparison.coverage, key=lambda value: value.provider_id)
            ],
            "current_run_id": policy.opaque_id(comparison.current_run_id),
            "diffs": [
                {
                    "current_fingerprint": item.current_fingerprint,
                    "finding_id": policy.opaque_id(item.finding_id),
                    "previous_fingerprint": item.previous_fingerprint,
                    "provider_id": policy.opaque_id(item.provider_id),
                    "state": item.state.value,
                }
                for item in sorted(comparison.diffs, key=lambda value: value.finding_id)
            ],
            "incomplete": comparison.incomplete,
            "incomplete_reasons": sorted(item.value for item in comparison.incomplete_reasons),
            "unresolved_absences": [
                {
                    "current_coverage": None
                    if item.current_coverage is None
                    else item.current_coverage.value,
                    "finding_id": policy.opaque_id(item.finding_id),
                    "previous_fingerprint": item.previous_fingerprint,
                    "provider_id": policy.opaque_id(item.provider_id),
                }
                for item in sorted(
                    comparison.unresolved_absences,
                    key=lambda value: value.finding_id,
                )
            ],
        },
        "constraints": {
            "active_content_included": False,
            "evidence_bytes_included": False,
            "filesystem_writes_performed": False,
            "network_access_performed": False,
            "outbound_actions_performed": False,
        },
        "findings": [
            _finding_projection(item, policy)
            for item in sorted(source.findings, key=lambda value: value.finding_id)
        ],
        "manifest": {
            "full_export_approval_id": None
            if full_export_approval_id is None
            else str(full_export_approval_id),
            "generated_at_us": source.generated_at_us,
            "mode": mode.value,
            "redaction_policy_version": REDACTION_POLICY_VERSION
            if mode is ExportMode.REDACTED
            else None,
            "schema": REPORT_SCHEMA,
            "version": REPORT_SCHEMA_VERSION,
        },
        "profile": {
            "label": policy.sensitive(source.profile_label, "profile-label-redacted"),
        },
        "remediations": [
            _remediation_projection(item, policy)
            for item in sorted(source.remediations, key=lambda value: value.case_id)
        ],
        "summary": {
            "comparison_diff_count": len(comparison.diffs),
            "comparison_unresolved_count": len(comparison.unresolved_absences),
            "evidence_metadata_count": evidence_count,
            "finding_count": finding_count,
            "provider_coverage_count": len(comparison.coverage),
            "remediation_count": remediation_count,
        },
    }


def _canonical_json(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _markdown(document: dict[str, object], source: LocalReportInput, mode: ExportMode) -> bytes:
    pretty_json = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    lines = [
        "# Codename Ariadne Local Report",
        "",
        f"- Schema: `{REPORT_SCHEMA}`",
        f"- Version: `{REPORT_SCHEMA_VERSION}`",
        f"- Mode: `{mode.value}`",
        f"- Generated at (microseconds): `{source.generated_at_us}`",
        "",
        "## Summary",
        "",
        f"- Findings: `{len(source.findings)}`",
        f"- Evidence metadata records: `{sum(len(item.evidence) for item in source.findings)}`",
        f"- Remediation cases: `{len(source.remediations)}`",
        f"- Comparison incomplete: `{'yes' if source.comparison.incomplete else 'no'}`",
        "",
        "This is a passive local record. It contains no evidence bytes and performs no actions.",
        "",
        "## Report data",
        "",
        "The complete report document is shown as inert JSON data:",
        "",
        *(f"    {line}" for line in pretty_json.split("\n")),
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _artifact(
    *,
    filename: str,
    media_type: str,
    mode: ExportMode,
    content: bytes,
) -> ReportArtifact:
    if len(content) > MAX_REPORT_BYTES:
        raise ReportSizeLimitExceeded(
            f"{filename} exceeds the {MAX_REPORT_BYTES}-byte local report limit"
        )
    return ReportArtifact(
        filename=filename,
        media_type=media_type,
        schema=REPORT_SCHEMA,
        version=REPORT_SCHEMA_VERSION,
        mode=mode,
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


class LocalReportGenerator:
    """Generate report bytes in memory without filesystem, network, or outbound side effects."""

    def generate(
        self,
        source: LocalReportInput,
        *,
        mode: ExportMode = ExportMode.REDACTED,
        full_export_approval_id: UUID | None = None,
    ) -> LocalReportBundle:
        if not isinstance(source, LocalReportInput):
            raise TypeError("local report input is invalid")
        if not isinstance(mode, ExportMode):
            raise TypeError("local report mode is invalid")
        if mode is ExportMode.FULL_EXPLICIT:
            if not isinstance(full_export_approval_id, UUID):
                raise ValueError("full report requires a separate canonical approval UUID")
        elif full_export_approval_id is not None:
            raise ValueError("redacted report cannot consume a full-export approval")

        document = _report_document(
            source,
            mode=mode,
            full_export_approval_id=full_export_approval_id,
        )
        json_artifact = _artifact(
            filename="report.json",
            media_type=JSON_MEDIA_TYPE,
            mode=mode,
            content=_canonical_json(document),
        )
        markdown_artifact = _artifact(
            filename="report.md",
            media_type=MARKDOWN_MEDIA_TYPE,
            mode=mode,
            content=_markdown(document, source, mode),
        )
        descriptors = tuple(
            ReportArtifactDescriptor(
                filename=artifact.filename,
                media_type=artifact.media_type,
                byte_count=artifact.byte_count,
                sha256=artifact.sha256,
            )
            for artifact in (json_artifact, markdown_artifact)
        )
        return LocalReportBundle(
            manifest=LocalReportManifest(
                schema=REPORT_SCHEMA,
                version=REPORT_SCHEMA_VERSION,
                mode=mode,
                generated_at_us=source.generated_at_us,
                full_export_approval_id=full_export_approval_id,
                artifacts=descriptors,
            ),
            json_artifact=json_artifact,
            markdown_artifact=markdown_artifact,
        )
