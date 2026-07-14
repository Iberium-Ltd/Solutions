"""Evidence artifact service and non-durable in-memory conformance storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from ariadne_core.domain.evidence_artifacts import (
    MAX_DERIVATIVE_ARTIFACTS,
    MAX_ORIGINAL_ARTIFACTS,
    EvidenceArtifactKind,
    EvidenceArtifactOriginal,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
    EvidenceViewport,
    RedactedEvidenceDerivative,
)


class DuplicateEvidenceId(ValueError):
    pass


class EvidenceStorageFull(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OriginalSaveResult:
    artifact: EvidenceArtifactOriginal
    deduplicated: bool


@dataclass(frozen=True, slots=True)
class DerivativeSaveResult:
    derivative: RedactedEvidenceDerivative
    deduplicated: bool


class EvidenceArtifactStorage(Protocol):
    @property
    def durable_encryption(self) -> bool: ...

    def has_id(self, artifact_id: str) -> bool: ...

    def original_by_hash(self, content_sha256: str) -> EvidenceArtifactOriginal | None: ...

    def derivative_by_hash(
        self,
        original_artifact_id: str,
        content_sha256: str,
    ) -> RedactedEvidenceDerivative | None: ...

    def insert_original(self, artifact: EvidenceArtifactOriginal) -> None: ...

    def insert_derivative(self, derivative: RedactedEvidenceDerivative) -> None: ...

    def get_original(self, artifact_id: str) -> EvidenceArtifactOriginal: ...

    def derivatives_for(self, artifact_id: str) -> tuple[RedactedEvidenceDerivative, ...]: ...

    def link_original_to_finding(self, artifact_id: str, finding_id: str) -> None: ...

    def originals_for_finding(
        self, finding_id: str, *, limit: int = 100
    ) -> tuple[EvidenceArtifactOriginal, ...]: ...


class InMemoryEvidenceArtifactRepository:
    """Synthetic process-memory conformance store; not an encrypted durable vault."""

    def __init__(
        self,
        *,
        maximum_originals: int = MAX_ORIGINAL_ARTIFACTS,
        maximum_derivatives: int = MAX_DERIVATIVE_ARTIFACTS,
    ) -> None:
        if (
            type(maximum_originals) is not int
            or maximum_originals < 1
            or maximum_originals > MAX_ORIGINAL_ARTIFACTS
        ):
            raise ValueError("evidence original capacity is invalid")
        if (
            type(maximum_derivatives) is not int
            or maximum_derivatives < 1
            or maximum_derivatives > MAX_DERIVATIVE_ARTIFACTS
        ):
            raise ValueError("evidence derivative capacity is invalid")
        self._maximum_originals = maximum_originals
        self._maximum_derivatives = maximum_derivatives
        self._originals: dict[str, EvidenceArtifactOriginal] = {}
        self._original_hashes: dict[str, str] = {}
        self._derivatives: dict[str, RedactedEvidenceDerivative] = {}
        self._derivative_hashes: dict[tuple[str, str], str] = {}
        self._finding_links: set[tuple[str, str]] = set()

    @property
    def durable_encryption(self) -> bool:
        return False

    @property
    def original_count(self) -> int:
        return len(self._originals)

    @property
    def derivative_count(self) -> int:
        return len(self._derivatives)

    def has_id(self, artifact_id: str) -> bool:
        return artifact_id in self._originals or artifact_id in self._derivatives

    def original_by_hash(self, content_sha256: str) -> EvidenceArtifactOriginal | None:
        artifact_id = self._original_hashes.get(content_sha256)
        return None if artifact_id is None else self._originals[artifact_id]

    def derivative_by_hash(
        self,
        original_artifact_id: str,
        content_sha256: str,
    ) -> RedactedEvidenceDerivative | None:
        derivative_id = self._derivative_hashes.get((original_artifact_id, content_sha256))
        return None if derivative_id is None else self._derivatives[derivative_id]

    def insert_original(self, artifact: EvidenceArtifactOriginal) -> None:
        if self.has_id(artifact.artifact_id):
            raise DuplicateEvidenceId("evidence artifact id already exists")
        if len(self._originals) >= self._maximum_originals:
            raise EvidenceStorageFull("evidence original capacity is exhausted")
        if artifact.content_sha256 in self._original_hashes:
            raise ValueError("evidence content hash must be deduplicated before insertion")
        self._originals[artifact.artifact_id] = artifact
        self._original_hashes[artifact.content_sha256] = artifact.artifact_id

    def insert_derivative(self, derivative: RedactedEvidenceDerivative) -> None:
        if self.has_id(derivative.derivative_id):
            raise DuplicateEvidenceId("evidence artifact id already exists")
        if derivative.original_artifact_id not in self._originals:
            raise LookupError("original evidence artifact is unavailable")
        if len(self._derivatives) >= self._maximum_derivatives:
            raise EvidenceStorageFull("evidence derivative capacity is exhausted")
        key = (derivative.original_artifact_id, derivative.content_sha256)
        if key in self._derivative_hashes:
            raise ValueError("evidence derivative hash must be deduplicated before insertion")
        self._derivatives[derivative.derivative_id] = derivative
        self._derivative_hashes[key] = derivative.derivative_id

    def get_original(self, artifact_id: str) -> EvidenceArtifactOriginal:
        try:
            return self._originals[artifact_id]
        except KeyError as error:
            raise LookupError("original evidence artifact is unavailable") from error

    def derivatives_for(self, artifact_id: str) -> tuple[RedactedEvidenceDerivative, ...]:
        if artifact_id not in self._originals:
            raise LookupError("original evidence artifact is unavailable")
        return tuple(
            sorted(
                (
                    derivative
                    for derivative in self._derivatives.values()
                    if derivative.original_artifact_id == artifact_id
                ),
                key=lambda item: (item.created_at_us, item.derivative_id),
            )
        )

    def link_original_to_finding(self, artifact_id: str, finding_id: str) -> None:
        if artifact_id not in self._originals:
            raise LookupError("original evidence artifact is unavailable")
        if not finding_id:
            raise ValueError("evidence finding id is invalid")
        self._finding_links.add((finding_id, artifact_id))

    def originals_for_finding(
        self,
        finding_id: str,
        *,
        limit: int = 100,
    ) -> tuple[EvidenceArtifactOriginal, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("evidence artifact limit is invalid")
        artifact_ids = {
            artifact_id
            for linked_finding_id, artifact_id in self._finding_links
            if linked_finding_id == finding_id
        }
        return tuple(
            sorted(
                (self._originals[artifact_id] for artifact_id in artifact_ids),
                key=lambda item: (item.captured_at_us, item.artifact_id),
                reverse=True,
            )[:limit]
        )


class EvidenceArtifactService:
    def __init__(self, storage: EvidenceArtifactStorage) -> None:
        self._storage = storage

    @property
    def uses_durable_encrypted_storage(self) -> bool:
        return self._storage.durable_encryption

    def capture_original(
        self,
        *,
        artifact_id: str,
        kind: EvidenceArtifactKind,
        content: bytes,
        content_sha256: str,
        captured_at_us: int,
        source_url: str | None,
        http_status: int | None,
        redirect_chain: tuple[str, ...],
        masked_query_reference: str | None,
        provider_id: str,
        run_id: str,
        finding_id: str | None,
        viewport: EvidenceViewport | None,
        capture_method: EvidenceCaptureMethod,
        metadata: tuple[EvidenceMetadataEntry, ...] = (),
    ) -> OriginalSaveResult:
        if self._storage.has_id(artifact_id):
            raise DuplicateEvidenceId("evidence artifact id already exists")
        artifact = EvidenceArtifactOriginal(
            artifact_id=artifact_id,
            kind=kind,
            content=content,
            content_sha256=content_sha256,
            captured_at_us=captured_at_us,
            source_url=source_url,
            http_status=http_status,
            redirect_chain=redirect_chain,
            masked_query_reference=masked_query_reference,
            provider_id=provider_id,
            run_id=run_id,
            finding_id=finding_id,
            viewport=viewport,
            capture_method=capture_method,
            metadata=metadata,
        )
        existing = self._storage.original_by_hash(artifact.content_sha256)
        if existing is not None:
            if artifact.finding_id is not None:
                self._storage.link_original_to_finding(existing.artifact_id, artifact.finding_id)
            return OriginalSaveResult(existing, deduplicated=True)
        self._storage.insert_original(artifact)
        if artifact.finding_id is not None:
            self._storage.link_original_to_finding(artifact.artifact_id, artifact.finding_id)
        return OriginalSaveResult(artifact, deduplicated=False)

    def manual_local_import(
        self,
        *,
        artifact_id: str,
        kind: EvidenceArtifactKind,
        content: bytes,
        content_sha256: str,
        captured_at_us: int,
        provider_id: str,
        run_id: str,
        finding_id: str | None,
        viewport: EvidenceViewport | None = None,
        metadata: tuple[EvidenceMetadataEntry, ...] = (),
    ) -> OriginalSaveResult:
        if kind is EvidenceArtifactKind.URL_REFERENCE:
            raise ValueError("URL references are not manual byte imports")
        return self.capture_original(
            artifact_id=artifact_id,
            kind=kind,
            content=content,
            content_sha256=content_sha256,
            captured_at_us=captured_at_us,
            source_url=None,
            http_status=None,
            redirect_chain=(),
            masked_query_reference=None,
            provider_id=provider_id,
            run_id=run_id,
            finding_id=finding_id,
            viewport=viewport,
            capture_method=EvidenceCaptureMethod.MANUAL_LOCAL_IMPORT,
            metadata=metadata,
        )

    def record_url_reference(
        self,
        *,
        artifact_id: str,
        source_url: str,
        content_sha256: str,
        captured_at_us: int,
        provider_id: str,
        run_id: str,
        finding_id: str | None,
        masked_query_reference: str | None = None,
        metadata: tuple[EvidenceMetadataEntry, ...] = (),
    ) -> OriginalSaveResult:
        return self.capture_original(
            artifact_id=artifact_id,
            kind=EvidenceArtifactKind.URL_REFERENCE,
            content=b"",
            content_sha256=content_sha256,
            captured_at_us=captured_at_us,
            source_url=source_url,
            http_status=None,
            redirect_chain=(),
            masked_query_reference=masked_query_reference,
            provider_id=provider_id,
            run_id=run_id,
            finding_id=finding_id,
            viewport=None,
            capture_method=EvidenceCaptureMethod.BROWSER_CAPTURE,
            metadata=metadata,
        )

    def create_redacted_derivative(
        self,
        *,
        derivative_id: str,
        original_artifact_id: str,
        content: bytes,
        content_sha256: str,
        created_at_us: int,
        redaction_policy_version: str,
        redaction_summary_code: str,
    ) -> DerivativeSaveResult:
        if self._storage.has_id(derivative_id):
            raise DuplicateEvidenceId("evidence artifact id already exists")
        original = self._storage.get_original(original_artifact_id)
        if created_at_us <= original.captured_at_us:
            raise ValueError("evidence derivative must follow original capture")
        derivative = RedactedEvidenceDerivative(
            derivative_id=derivative_id,
            original_artifact_id=original_artifact_id,
            content=content,
            content_sha256=content_sha256,
            created_at_us=created_at_us,
            redaction_policy_version=redaction_policy_version,
            redaction_summary_code=redaction_summary_code,
        )
        existing = self._storage.derivative_by_hash(original_artifact_id, content_sha256)
        if existing is not None:
            return DerivativeSaveResult(existing, deduplicated=True)
        self._storage.insert_derivative(derivative)
        return DerivativeSaveResult(derivative, deduplicated=False)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def url_reference_sha256(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()
