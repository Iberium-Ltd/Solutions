from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from ariadne_core.application.import_export import ExportMode
from ariadne_core.application.reporting import (
    JSON_MEDIA_TYPE,
    MARKDOWN_MEDIA_TYPE,
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    LocalReportGenerator,
    ReportSizeLimitExceeded,
)
from ariadne_core.domain.attribution import (
    AttributionConfidenceBand,
    HumanAttributionState,
    NegativeAttributionSignal,
    PositiveAttributionSignal,
)
from ariadne_core.domain.audit_comparison import (
    FindingDiffState,
    ProviderCoverageState,
)
from ariadne_core.domain.evidence_artifacts import EvidenceArtifactKind, EvidenceCaptureMethod
from ariadne_core.domain.remediation import (
    ActionDisposition,
    RemediationAction,
    RemediationEventType,
    RemediationStatus,
)
from ariadne_core.domain.reporting import (
    MAX_REPORT_BYTES,
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
)

NOW_US = 1_750_000_000_000_000
APPROVAL_ID = UUID("10000000-0000-4000-8000-000000000001")


def _hash(label: str) -> str:
    return hashlib.sha256(f"synthetic:{label}".encode()).hexdigest()


def _evidence(index: int) -> ReportEvidenceMetadata:
    source_url = f"https://evidence-{index}.example/source"
    return ReportEvidenceMetadata(
        artifact_id=f"evidence-sensitive-{index}",
        kind=EvidenceArtifactKind.RAW_JSON,
        content_sha256=_hash(f"evidence-{index}"),
        captured_at_us=NOW_US + index,
        source_url=source_url,
        source_url_sha256=hashlib.sha256(source_url.encode()).hexdigest(),
        http_status=200,
        redirect_count=0,
        provider_id="provider-sensitive-primary",
        run_id="run-sensitive-current",
        capture_method=EvidenceCaptureMethod.PROVIDER_API,
        integrity=ReportEvidenceIntegrity.VERIFIED,
        derivative_count=index,
        metadata=(
            ReportEvidenceMetadataEntry(
                key="synthetic.note",
                value=f"Private metadata value {index}\r\nsecond line",
            ),
        ),
    )


def _finding() -> ReportFindingSummary:
    return ReportFindingSummary(
        finding_id="finding-sensitive-primary",
        provider_id="provider-sensitive-primary",
        provider_label="Sensitive Provider Label",
        provider_url="https://provider-sensitive.example/account",
        title="Sensitive synthetic finding title",
        summary="Sensitive synthetic finding summary\rwith another line",
        outcome=ReportFindingOutcome.FOUND,
        severity=ReportFindingSeverity.HIGH,
        visibility=ReportFindingVisibility.PUBLICLY_ATTRIBUTABLE,
        updated_at_us=NOW_US + 20,
        attribution=ReportAttributionSummary(
            weight_profile_version="ariadne-core-attribution-v1",
            score=420,
            confidence_band=AttributionConfidenceBand.HIGH,
            human_state=HumanAttributionState.PROBABLE,
            human_decided_at_us=NOW_US + 19,
            contributing_signals=(PositiveAttributionSignal.SAME_PROJECT,),
            contradiction_signals=(NegativeAttributionSignal.CONTRADICTORY_BIOGRAPHY,),
            contributing_signal_sources=(
                ReportPositiveSignalSource(
                    signal=PositiveAttributionSignal.SAME_PROJECT,
                    weight=50,
                    evidence_references=("evidence-sensitive-1",),
                ),
            ),
            contradiction_signal_sources=(
                ReportNegativeSignalSource(
                    signal=NegativeAttributionSignal.CONTRADICTORY_BIOGRAPHY,
                    penalty=120,
                    evidence_references=("evidence-sensitive-2",),
                ),
            ),
            missing_evidence=(PositiveAttributionSignal.SAME_LOCATION,),
            recommended_next_evidence=(PositiveAttributionSignal.SAME_LOCATION,),
        ),
        evidence=(_evidence(2), _evidence(1)),
    )


def _remediation(index: int = 1, *, large: bool = False) -> ReportRemediationSummary:
    case_id = f"case-sensitive-{index}"
    finding_id = "finding-sensitive-primary" if index == 1 else f"finding-historical-{index}"
    evidence_id = "evidence-sensitive-1" if index == 1 else f"evidence-historical-{index}"
    created_at = NOW_US + 30 + (index * 10)
    if large:
        history = (
            ReportRemediationHistoryEntry(
                revision=1,
                event_type=RemediationEventType.CASE_CREATED,
                actor_id=f"actor-sensitive-{index}",
                occurred_at_us=created_at,
                previous_status=None,
                current_status=RemediationStatus.OPEN,
                detail_code="CASE_CREATED",
                subject_id=None,
                note="n" * 1_000,
            ),
        )
        return ReportRemediationSummary(
            case_id=case_id,
            finding_ids=(finding_id,),
            action=RemediationAction.CONTACT,
            action_disposition=ActionDisposition.DRAFT,
            status=RemediationStatus.OPEN,
            deadline_at_us=None,
            draft_text="d" * 10_000,
            evidence_references=(),
            provider_responses=(),
            reappearance_count=0,
            last_reappearance_at_us=None,
            revision=1,
            created_at_us=created_at,
            updated_at_us=created_at,
            history=history,
        )

    history = (
        ReportRemediationHistoryEntry(
            revision=1,
            event_type=RemediationEventType.CASE_CREATED,
            actor_id="actor-sensitive-local",
            occurred_at_us=created_at,
            previous_status=None,
            current_status=RemediationStatus.OPEN,
            detail_code="CASE_CREATED",
            subject_id=None,
            evidence_references=(evidence_id,),
            note="Sensitive private creation note",
        ),
        ReportRemediationHistoryEntry(
            revision=2,
            event_type=RemediationEventType.PROVIDER_RESPONSE_RECORDED,
            actor_id="actor-sensitive-local",
            occurred_at_us=created_at + 1,
            previous_status=RemediationStatus.OPEN,
            current_status=RemediationStatus.IN_PROGRESS,
            detail_code="REQUEST_ACKNOWLEDGED",
            subject_id="provider-sensitive-primary",
            evidence_references=(evidence_id,),
            note="Sensitive private follow-up note",
        ),
    )
    return ReportRemediationSummary(
        case_id=case_id,
        finding_ids=(finding_id,),
        action=RemediationAction.CONTACT,
        action_disposition=ActionDisposition.DRAFT,
        status=RemediationStatus.IN_PROGRESS,
        deadline_at_us=created_at + 100,
        draft_text="Sensitive outbound draft\r\nfor local review only.",
        evidence_references=(evidence_id,),
        provider_responses=(
            ReportProviderResponse(
                provider_id="provider-sensitive-primary",
                response_code="REQUEST_ACKNOWLEDGED",
                summary="Sensitive provider response summary",
                received_at_us=created_at + 1,
                evidence_references=(evidence_id,),
            ),
        ),
        reappearance_count=0,
        last_reappearance_at_us=None,
        revision=2,
        created_at_us=created_at,
        updated_at_us=created_at + 1,
        history=history,
    )


def _source() -> LocalReportInput:
    return LocalReportInput(
        profile_label="Sensitive Synthetic Profile",
        comparison=ReportAuditComparison(
            baseline_run_id="run-sensitive-baseline",
            current_run_id="run-sensitive-current",
            diffs=(
                ReportComparisonDiff(
                    finding_id="finding-sensitive-primary",
                    provider_id="provider-sensitive-primary",
                    state=FindingDiffState.CHANGED,
                    previous_fingerprint=_hash("before"),
                    current_fingerprint=_hash("after"),
                ),
            ),
            unresolved_absences=(),
            coverage=(
                ReportProviderCoverage(
                    provider_id="provider-sensitive-primary",
                    provider_url="https://provider-sensitive.example/account",
                    baseline_state=ProviderCoverageState.COMPLETE,
                    current_state=ProviderCoverageState.COMPLETE,
                ),
            ),
            incomplete=False,
            incomplete_reasons=(),
        ),
        findings=(_finding(),),
        remediations=(_remediation(),),
        generated_at_us=NOW_US + 100,
    )


def test_redacted_report_remaps_identifiers_and_leaks_no_sensitive_text_or_urls() -> None:
    source = _source()
    bundle = LocalReportGenerator().generate(source)
    combined = bundle.json_artifact.text() + bundle.markdown_artifact.text()

    sensitive_values = {
        "Sensitive Synthetic Profile",
        "Sensitive Provider Label",
        "Sensitive synthetic finding title",
        "Sensitive synthetic finding summary",
        "Private metadata value",
        "Sensitive outbound draft",
        "Sensitive private creation note",
        "Sensitive private follow-up note",
        "Sensitive provider response summary",
        "https://provider-sensitive.example/account",
        "https://evidence-1.example/source",
        "finding-sensitive-primary",
        "provider-sensitive-primary",
        "run-sensitive-current",
        "evidence-sensitive-1",
        "case-sensitive-1",
        "actor-sensitive-local",
    }
    assert all(value not in combined for value in sensitive_values)
    assert "https://" not in combined
    assert _hash("evidence-1") in combined
    assert "HIGH" in combined
    assert "PROBABLE" in combined
    assert "REQUEST_ACKNOWLEDGED" in combined
    assert not hasattr(source.findings[0].evidence[0], "content")

    document = json.loads(bundle.json_artifact.content)
    finding_id = document["findings"][0]["finding_id"]
    assert finding_id.startswith("redacted-id-")
    assert document["comparison"]["diffs"][0]["finding_id"] == finding_id
    assert document["remediations"][0]["finding_ids"] == [finding_id]
    assert document["summary"] == {
        "comparison_diff_count": 1,
        "comparison_unresolved_count": 0,
        "evidence_metadata_count": 2,
        "finding_count": 1,
        "provider_coverage_count": 1,
        "remediation_count": 1,
    }
    assert document["constraints"]["evidence_bytes_included"] is False
    assert document["manifest"]["full_export_approval_id"] is None
    evidence = document["findings"][0]["evidence"][0]
    assert evidence["source_url"] is None
    assert evidence["source_url_redaction"] == "REMOVED_IN_REDACTED_REPORT"
    assert (
        evidence["source_url_sha256"]
        == hashlib.sha256(b"https://evidence-1.example/source").hexdigest()
    )
    source_id = evidence["artifact_id"]
    assert document["findings"][0]["attribution"]["contributing_signal_sources"] == [
        {
            "evidence_references": [source_id],
            "signal": "SAME_PROJECT",
            "weight": 50,
        }
    ]


def test_generation_is_canonical_deterministic_ordered_and_newline_normalized() -> None:
    source = _source()
    reordered_finding = replace(
        source.findings[0], evidence=tuple(reversed(source.findings[0].evidence))
    )
    reordered_source = replace(source, findings=(reordered_finding,))

    first = LocalReportGenerator().generate(source)
    second = LocalReportGenerator().generate(reordered_source)

    assert first == second
    assert b"\r" not in first.json_artifact.content
    assert b"\r" not in first.markdown_artifact.content
    parsed = json.loads(first.json_artifact.content)
    assert (
        json.dumps(
            parsed,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        == first.json_artifact.content
    )
    assert [item["artifact_id"] for item in parsed["findings"][0]["evidence"]] == sorted(
        item["artifact_id"] for item in parsed["findings"][0]["evidence"]
    )


def test_finding_report_accepts_manual_or_corroborating_evidence_provider() -> None:
    source = _source()
    manual_evidence = replace(
        source.findings[0].evidence[1],
        provider_id="manual-import",
        source_url=None,
        source_url_sha256=None,
        http_status=None,
        redirect_count=0,
        capture_method=EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT,
    )
    finding = replace(
        source.findings[0],
        evidence=(manual_evidence, source.findings[0].evidence[0]),
    )

    bundle = LocalReportGenerator().generate(replace(source, findings=(finding,)))
    document = json.loads(bundle.json_artifact.content)

    projected = {item["artifact_id"]: item for item in document["findings"][0]["evidence"]}
    manual_id = document["findings"][0]["attribution"]["contributing_signal_sources"][0][
        "evidence_references"
    ][0]
    assert projected[manual_id]["provider_id"].startswith("redacted-id-")


def test_redaction_labels_cannot_collide_with_an_original_opaque_id() -> None:
    source = _source()
    collision_candidate = "redacted-id-000001"
    source = replace(
        source,
        comparison=replace(source.comparison, baseline_run_id=collision_candidate),
    )

    bundle = LocalReportGenerator().generate(source)
    document = json.loads(bundle.json_artifact.content)

    assert collision_candidate not in bundle.json_artifact.text()
    assert document["comparison"]["baseline_run_id"] != collision_candidate


def test_artifact_manifest_hashes_media_types_and_bounds_are_exact() -> None:
    bundle = LocalReportGenerator().generate(_source())

    assert bundle.manifest.schema == REPORT_SCHEMA
    assert bundle.manifest.version == REPORT_SCHEMA_VERSION
    assert bundle.manifest.mode is ExportMode.REDACTED
    assert [item.media_type for item in bundle.manifest.artifacts] == [
        JSON_MEDIA_TYPE,
        MARKDOWN_MEDIA_TYPE,
    ]
    for descriptor, artifact in zip(
        bundle.manifest.artifacts,
        (bundle.json_artifact, bundle.markdown_artifact),
        strict=True,
    ):
        assert descriptor.byte_count == artifact.byte_count == len(artifact.content)
        assert descriptor.sha256 == artifact.sha256
        assert artifact.sha256 == hashlib.sha256(artifact.content).hexdigest()
        assert artifact.byte_count <= MAX_REPORT_BYTES
        assert artifact.schema == REPORT_SCHEMA
        assert artifact.version == REPORT_SCHEMA_VERSION


def test_full_explicit_requires_separate_uuid_and_binds_it_into_both_artifacts() -> None:
    generator = LocalReportGenerator()
    source = _source()

    with pytest.raises(ValueError, match="separate canonical approval UUID"):
        generator.generate(source, mode=ExportMode.FULL_EXPLICIT)
    with pytest.raises(ValueError, match="separate canonical approval UUID"):
        generator.generate(
            source,
            mode=ExportMode.FULL_EXPLICIT,
            full_export_approval_id=str(APPROVAL_ID),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="cannot consume"):
        generator.generate(
            source,
            mode=ExportMode.REDACTED,
            full_export_approval_id=APPROVAL_ID,
        )

    bundle = generator.generate(
        source,
        mode=ExportMode.FULL_EXPLICIT,
        full_export_approval_id=APPROVAL_ID,
    )
    assert bundle.manifest.full_export_approval_id == APPROVAL_ID
    assert str(APPROVAL_ID) in bundle.json_artifact.text()
    assert str(APPROVAL_ID) in bundle.markdown_artifact.text()
    assert "Sensitive Synthetic Profile" in bundle.json_artifact.text()
    document = json.loads(bundle.json_artifact.content)
    assert (
        document["remediations"][0]["draft_text"]
        == "Sensitive outbound draft\nfor local review only."
    )
    assert "finding-sensitive-primary" in bundle.json_artifact.text()
    exact_source = document["findings"][0]["evidence"][0]
    assert exact_source["artifact_id"] == "evidence-sensitive-1"
    assert exact_source["provider_id"] == "provider-sensitive-primary"
    assert exact_source["source_url"] == "https://evidence-1.example/source"
    assert exact_source["source_url_redaction"] is None
    assert document["findings"][0]["attribution"]["contributing_signal_sources"] == [
        {
            "evidence_references": ["evidence-sensitive-1"],
            "signal": "SAME_PROJECT",
            "weight": 50,
        }
    ]

    another = generator.generate(
        source,
        mode=ExportMode.FULL_EXPLICIT,
        full_export_approval_id=UUID("10000000-0000-4000-8000-000000000002"),
    )
    assert another.json_artifact.sha256 != bundle.json_artifact.sha256
    assert another.markdown_artifact.sha256 != bundle.markdown_artifact.sha256


def test_full_report_over_one_mebibyte_fails_closed_without_partial_bundle() -> None:
    source = replace(
        _source(),
        remediations=tuple(_remediation(index, large=True) for index in range(1, 101)),
    )

    with pytest.raises(ReportSizeLimitExceeded, match="1048576-byte"):
        LocalReportGenerator().generate(
            source,
            mode=ExportMode.FULL_EXPLICIT,
            full_export_approval_id=APPROVAL_ID,
        )


def test_generator_surface_has_no_write_send_or_active_report_method() -> None:
    generator = LocalReportGenerator()
    assert not hasattr(generator, "save")
    assert not hasattr(generator, "write")
    assert not hasattr(generator, "send")
    assert not hasattr(generator, "submit")
    assert not hasattr(generator, "render_html")
