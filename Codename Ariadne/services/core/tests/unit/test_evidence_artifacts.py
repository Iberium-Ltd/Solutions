from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ariadne_core.application.evidence_artifacts import (
    DuplicateEvidenceId,
    EvidenceArtifactService,
    EvidenceStorageFull,
    InMemoryEvidenceArtifactRepository,
    sha256_hex,
    url_reference_sha256,
)
from ariadne_core.domain.evidence_artifacts import (
    MAX_ARTIFACT_BYTES,
    MAX_METADATA_ENTRIES,
    MAX_REDIRECTS,
    EvidenceArtifactKind,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
    EvidenceViewport,
)

CAPTURED_AT_US = 1_750_000_000_000_000
SOURCE_URL = "https://source.example.invalid/synthetic-record"


def _service(
    *,
    maximum_originals: int = 1_000,
    maximum_derivatives: int = 2_000,
) -> tuple[EvidenceArtifactService, InMemoryEvidenceArtifactRepository]:
    repository = InMemoryEvidenceArtifactRepository(
        maximum_originals=maximum_originals,
        maximum_derivatives=maximum_derivatives,
    )
    return EvidenceArtifactService(repository), repository


def _capture_html(
    service: EvidenceArtifactService,
    *,
    artifact_id: str = "artifact-synthetic-html",
    content: bytes = b"<html><body>Synthetic evidence</body></html>",
):
    return service.capture_original(
        artifact_id=artifact_id,
        kind=EvidenceArtifactKind.HTML,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=CAPTURED_AT_US,
        source_url=SOURCE_URL,
        http_status=200,
        redirect_chain=("https://redirect.example.invalid/start",),
        masked_query_reference="mq_0123456789abcdef",
        provider_id="provider-synthetic",
        run_id="run-synthetic",
        finding_id="finding-synthetic",
        viewport=None,
        capture_method=EvidenceCaptureMethod.HTTP_FETCH,
        metadata=(EvidenceMetadataEntry("content_type", "text/html"),),
    )


def test_artifact_kind_catalog_and_screenshot_capture_are_immutable_and_verified() -> None:
    assert {kind.value for kind in EvidenceArtifactKind} == {
        "SCREENSHOT",
        "HTML",
        "PDF",
        "RAW_JSON",
        "URL_REFERENCE",
    }
    service, repository = _service()
    content = b"synthetic-png-placeholder"
    result = service.capture_original(
        artifact_id="artifact-synthetic-screenshot",
        kind=EvidenceArtifactKind.SCREENSHOT,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=CAPTURED_AT_US,
        source_url=SOURCE_URL,
        http_status=200,
        redirect_chain=(),
        masked_query_reference="mq_0123456789abcdef",
        provider_id="provider-synthetic",
        run_id="run-synthetic",
        finding_id="finding-synthetic",
        viewport=EvidenceViewport(1_440, 900, 2_000_000),
        capture_method=EvidenceCaptureMethod.BROWSER_CAPTURE,
    )

    assert result.deduplicated is False
    assert result.artifact.content_sha256 == sha256_hex(content)
    assert result.artifact.encryption_required is True
    assert result.artifact.viewport == EvidenceViewport(1_440, 900, 2_000_000)
    assert repository.original_count == 1
    assert service.uses_durable_encrypted_storage is False
    with pytest.raises(FrozenInstanceError):
        result.artifact.http_status = 404  # type: ignore[misc]


@pytest.mark.parametrize(
    "kind,content",
    [
        (EvidenceArtifactKind.HTML, b"<p>Synthetic</p>"),
        (EvidenceArtifactKind.PDF, b"%PDF-synthetic"),
        (EvidenceArtifactKind.RAW_JSON, b'{"synthetic":true}'),
    ],
)
def test_manual_local_import_has_no_network_claims(
    kind: EvidenceArtifactKind,
    content: bytes,
) -> None:
    service, _repository = _service()
    result = service.manual_local_import(
        artifact_id=f"artifact-synthetic-{kind.value.lower()}",
        kind=kind,
        content=content,
        content_sha256=sha256_hex(content),
        captured_at_us=CAPTURED_AT_US,
        provider_id="provider-local",
        run_id="run-synthetic",
        finding_id=None,
        metadata=(EvidenceMetadataEntry("source_class", "manual-local"),),
    )

    assert result.artifact.capture_method is EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT
    assert result.artifact.source_url is None
    assert result.artifact.http_status is None
    assert result.artifact.redirect_chain == ()


def test_url_reference_uses_safe_queryless_url_as_hash_material() -> None:
    service, _repository = _service()
    result = service.record_url_reference(
        artifact_id="artifact-synthetic-url",
        source_url=SOURCE_URL,
        content_sha256=url_reference_sha256(SOURCE_URL),
        captured_at_us=CAPTURED_AT_US,
        provider_id="provider-synthetic",
        run_id="run-synthetic",
        finding_id="finding-synthetic",
        masked_query_reference="mq_0123456789abcdef",
    )

    assert result.artifact.kind is EvidenceArtifactKind.URL_REFERENCE
    assert result.artifact.content == b""
    assert result.artifact.source_url == SOURCE_URL

    with pytest.raises(ValueError, match="not manual byte imports"):
        service.manual_local_import(
            artifact_id="artifact-synthetic-invalid-url-import",
            kind=EvidenceArtifactKind.URL_REFERENCE,
            content=b"",
            content_sha256=sha256_hex(b""),
            captured_at_us=CAPTURED_AT_US,
            provider_id="provider-local",
            run_id="run-synthetic",
            finding_id=None,
        )


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "file:///tmp/synthetic",
        "http://127.0.0.1/synthetic",
        "http://localhost/synthetic",
        "http://2130706433/synthetic",
        "http://0x7f000001/synthetic",
        "https://source.example.invalid/path?raw_query=synthetic",
        "https://user:secret@source.example.invalid/path",
    ],
)
def test_unsafe_urls_fail_closed(unsafe_url: str) -> None:
    service, _repository = _service()
    with pytest.raises(ValueError, match="evidence URL"):
        service.record_url_reference(
            artifact_id="artifact-synthetic-unsafe-url",
            source_url=unsafe_url,
            content_sha256=url_reference_sha256(unsafe_url),
            captured_at_us=CAPTURED_AT_US,
            provider_id="provider-synthetic",
            run_id="run-synthetic",
            finding_id=None,
        )


def test_hash_mismatch_raw_query_reference_and_artifact_bounds_fail_closed() -> None:
    service, _repository = _service()
    with pytest.raises(ValueError, match="hash does not match"):
        service.capture_original(
            artifact_id="artifact-synthetic-bad-hash",
            kind=EvidenceArtifactKind.HTML,
            content=b"synthetic",
            content_sha256=sha256_hex(b"different"),
            captured_at_us=CAPTURED_AT_US,
            source_url=SOURCE_URL,
            http_status=200,
            redirect_chain=(),
            masked_query_reference=None,
            provider_id="provider-synthetic",
            run_id="run-synthetic",
            finding_id=None,
            viewport=None,
            capture_method=EvidenceCaptureMethod.HTTP_FETCH,
        )
    with pytest.raises(ValueError, match="masked query reference"):
        service.capture_original(
            artifact_id="artifact-synthetic-raw-query",
            kind=EvidenceArtifactKind.HTML,
            content=b"synthetic",
            content_sha256=sha256_hex(b"synthetic"),
            captured_at_us=CAPTURED_AT_US,
            source_url=SOURCE_URL,
            http_status=200,
            redirect_chain=(),
            masked_query_reference="synthetic.user@example.invalid",
            provider_id="provider-synthetic",
            run_id="run-synthetic",
            finding_id=None,
            viewport=None,
            capture_method=EvidenceCaptureMethod.HTTP_FETCH,
        )
    oversized = b"x" * (MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(ValueError, match="bytes are outside"):
        service.manual_local_import(
            artifact_id="artifact-synthetic-oversized",
            kind=EvidenceArtifactKind.RAW_JSON,
            content=oversized,
            content_sha256=sha256_hex(oversized),
            captured_at_us=CAPTURED_AT_US,
            provider_id="provider-local",
            run_id="run-synthetic",
            finding_id=None,
        )


def test_content_hash_dedup_and_duplicate_ids_are_distinct_fail_closed_paths() -> None:
    service, repository = _service()
    first = _capture_html(service)
    duplicate = _capture_html(service, artifact_id="artifact-synthetic-html-duplicate")

    assert first.deduplicated is False
    assert duplicate.deduplicated is True
    assert duplicate.artifact.artifact_id == first.artifact.artifact_id
    assert repository.original_count == 1

    with pytest.raises(DuplicateEvidenceId, match="already exists"):
        _capture_html(service, artifact_id=first.artifact.artifact_id, content=b"new-content")


def test_redacted_derivatives_link_to_and_never_overwrite_originals() -> None:
    service, repository = _service()
    original_result = _capture_html(service)
    original_before = repository.get_original(original_result.artifact.artifact_id)
    redacted = b"<html><body>[redacted]</body></html>"
    derivative = service.create_redacted_derivative(
        derivative_id="derivative-synthetic-redacted",
        original_artifact_id=original_before.artifact_id,
        content=redacted,
        content_sha256=sha256_hex(redacted),
        created_at_us=CAPTURED_AT_US + 1,
        redaction_policy_version="synthetic-redaction-v1",
        redaction_summary_code="IDENTIFIERS_MASKED",
    )
    deduplicated = service.create_redacted_derivative(
        derivative_id="derivative-synthetic-redacted-duplicate",
        original_artifact_id=original_before.artifact_id,
        content=redacted,
        content_sha256=sha256_hex(redacted),
        created_at_us=CAPTURED_AT_US + 2,
        redaction_policy_version="synthetic-redaction-v1",
        redaction_summary_code="IDENTIFIERS_MASKED",
    )

    assert derivative.deduplicated is False
    assert derivative.derivative.original_artifact_id == original_before.artifact_id
    assert deduplicated.deduplicated is True
    assert repository.derivative_count == 1
    assert repository.get_original(original_before.artifact_id) == original_before
    assert repository.get_original(original_before.artifact_id).content != redacted
    assert repository.derivatives_for(original_before.artifact_id) == (derivative.derivative,)

    with pytest.raises(DuplicateEvidenceId, match="already exists"):
        service.create_redacted_derivative(
            derivative_id=original_before.artifact_id,
            original_artifact_id=original_before.artifact_id,
            content=b"different-redaction",
            content_sha256=sha256_hex(b"different-redaction"),
            created_at_us=CAPTURED_AT_US + 3,
            redaction_policy_version="synthetic-redaction-v1",
            redaction_summary_code="IDENTIFIERS_MASKED",
        )


def test_storage_count_redirect_and_metadata_bounds_are_enforced() -> None:
    service, _repository = _service(maximum_originals=1, maximum_derivatives=1)
    _capture_html(service)
    with pytest.raises(EvidenceStorageFull, match="capacity"):
        _capture_html(service, artifact_id="artifact-synthetic-capacity", content=b"unique")

    second_service, _second_repository = _service()
    content = b"synthetic"
    with pytest.raises(ValueError, match="redirect chain"):
        second_service.capture_original(
            artifact_id="artifact-synthetic-redirects",
            kind=EvidenceArtifactKind.HTML,
            content=content,
            content_sha256=sha256_hex(content),
            captured_at_us=CAPTURED_AT_US,
            source_url=SOURCE_URL,
            http_status=200,
            redirect_chain=tuple(
                f"https://redirect-{index}.example.invalid/path"
                for index in range(MAX_REDIRECTS + 1)
            ),
            masked_query_reference=None,
            provider_id="provider-synthetic",
            run_id="run-synthetic",
            finding_id=None,
            viewport=None,
            capture_method=EvidenceCaptureMethod.HTTP_FETCH,
        )
    with pytest.raises(ValueError, match="metadata is outside"):
        second_service.manual_local_import(
            artifact_id="artifact-synthetic-metadata",
            kind=EvidenceArtifactKind.HTML,
            content=content,
            content_sha256=sha256_hex(content),
            captured_at_us=CAPTURED_AT_US,
            provider_id="provider-local",
            run_id="run-synthetic",
            finding_id=None,
            metadata=tuple(
                EvidenceMetadataEntry(f"key_{index}", "synthetic")
                for index in range(MAX_METADATA_ENTRIES + 1)
            ),
        )
