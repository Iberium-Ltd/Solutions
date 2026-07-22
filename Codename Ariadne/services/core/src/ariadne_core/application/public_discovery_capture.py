"""Application boundary for atomically retaining reviewed public results.

Search results remain transient until a user selects one; capture then stores
the finding, source receipt, artifact, and links in one transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

from ariadne_core.api.public_discovery_capture_schemas import (
    PublicDiscoveryCaptureRequest,
    PublicDiscoveryCaptureResult,
)
from ariadne_core.application.attribution import AttributionScoringService
from ariadne_core.application.evidence_artifacts import url_reference_sha256
from ariadne_core.application.vault import VaultManager, VaultSubkeyPurpose
from ariadne_core.domain.attribution import AttributionCase, PositiveAttributionSignal
from ariadne_core.domain.evidence_artifacts import (
    EvidenceArtifactKind,
    EvidenceArtifactOriginal,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
)
from ariadne_core.domain.public_discovery import (
    PublicDiscoveryProvider,
    public_discovery_provider_metadata,
)
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    FindingOutcome,
    FindingSeverity,
    FindingVisibility,
)
from ariadne_core.infrastructure.db.public_discovery_capture_repository import (
    PublicDiscoveryCapturePersistenceError,
    PublicDiscoveryCaptureRecord,
    PublicDiscoveryCaptureRepository,
)


class PublicDiscoveryCaptureUnavailable(RuntimeError):
    pass


class PublicDiscoveryCaptureNotFound(LookupError):
    pass


class PublicDiscoveryCaptureConflict(RuntimeError):
    pass


class PublicDiscoveryCaptureCoordinator:
    """Convert reviewed wire data into one encrypted, exact-source record."""

    def __init__(self, vault: VaultManager) -> None:
        self._vault = vault

    def capture(
        self,
        body: PublicDiscoveryCaptureRequest,
    ) -> PublicDiscoveryCaptureResult:
        if not self._vault.is_unlocked:
            raise PublicDiscoveryCaptureUnavailable(
                "public discovery capture requires an unlocked vault"
            )
        try:
            query_reference = self._query_reference(body.query)
            capture_fingerprint = self._capture_fingerprint(body, query_reference)
            finding_id = str(uuid4())
            artifact_id = str(uuid4())
            assessment_id = str(uuid4())
            provider = public_discovery_provider_metadata(body.provider)
            metadata = self._metadata(body, capture_fingerprint)
            artifact = EvidenceArtifactOriginal(
                artifact_id=artifact_id,
                kind=EvidenceArtifactKind.URL_REFERENCE,
                content=b"",
                content_sha256=url_reference_sha256(body.url),
                captured_at_us=body.captured_at_us,
                source_url=body.url,
                http_status=None,
                redirect_chain=(),
                masked_query_reference=query_reference,
                provider_id=body.provider.value,
                run_id=str(uuid4()),
                finding_id=finding_id,
                viewport=None,
                capture_method=self._capture_method(body.provider),
                metadata=metadata,
            )
            finding = FindingDraft(
                finding_id=finding_id,
                title=body.title,
                summary=(
                    body.snippet
                    if body.snippet is not None
                    else "No provider snippet was supplied for this reviewed public result."
                ),
                outcome=FindingOutcome.MANUAL_REVIEW_REQUIRED,
                severity=FindingSeverity.INFO,
                visibility=FindingVisibility.UNKNOWN,
                provider_id=body.provider.value,
                provider_label=provider.display_name,
                observed_at_us=body.captured_at_us,
            )
            assessment = AttributionScoringService().assess(
                AttributionCase(
                    case_id=finding_id,
                    missing_evidence=frozenset(PositiveAttributionSignal),
                )
            )
            repository = PublicDiscoveryCaptureRepository(
                self._vault.engine,
                vault_id=self._vault.manifest.vault_id,
                profile_id=body.profile_id,
            )
            stored = repository.persist(
                PublicDiscoveryCaptureRecord(
                    finding=finding,
                    artifact=artifact,
                    assessment_id=assessment_id,
                    assessment=assessment,
                    rank=body.rank,
                    source_id=body.source_id,
                    capture_fingerprint=capture_fingerprint,
                )
            )
        except LookupError as error:
            raise PublicDiscoveryCaptureNotFound(
                "public discovery capture profile is unavailable"
            ) from error
        except PublicDiscoveryCapturePersistenceError as error:
            raise PublicDiscoveryCaptureConflict(
                "public discovery result could not be retained"
            ) from error
        except (RuntimeError, ValueError) as error:
            raise PublicDiscoveryCaptureConflict(
                "public discovery capture failed validation"
            ) from error
        return PublicDiscoveryCaptureResult(
            profile_id=body.profile_id,
            finding_id=stored.finding_id,
            artifact_id=stored.artifact_id,
            provider=PublicDiscoveryProvider(stored.provider_id),
            rank=stored.rank,
            source_id=stored.source_id,
            url=stored.source_url,
            url_sha256=stored.url_sha256,
            query_reference=query_reference,
            captured_at_us=stored.captured_at_us,
            evidence_kind="URL_REFERENCE",
            encrypted_at_rest=True,
            local_only=True,
            deduplicated=stored.deduplicated,
        )

    def _query_reference(self, query: str) -> str:
        with self._vault.borrow_subkey(VaultSubkeyPurpose.PUBLIC_DISCOVERY_CAPTURE) as key:
            digest = hmac.new(
                key,
                b"public-discovery-query-v1\x00" + query.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        return f"mq_{digest}"

    @staticmethod
    def _capture_fingerprint(
        body: PublicDiscoveryCaptureRequest,
        query_reference: str,
    ) -> str:
        payload = json.dumps(
            {
                "authorizedSelfAudit": True,
                "capturedAtUs": body.captured_at_us,
                "provider": body.provider.value,
                "queryReference": query_reference,
                "rank": body.rank,
                "snippet": body.snippet,
                "sourceId": body.source_id,
                "title": body.title,
                "url": body.url,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _metadata(
        body: PublicDiscoveryCaptureRequest,
        capture_fingerprint: str,
    ) -> tuple[EvidenceMetadataEntry, ...]:
        entries = [
            EvidenceMetadataEntry("discovery.authorized_self_audit", "true"),
            EvidenceMetadataEntry("discovery.capture_fingerprint", capture_fingerprint),
            EvidenceMetadataEntry("discovery.rank", str(body.rank)),
            EvidenceMetadataEntry("discovery.schema", "v1"),
        ]
        if body.source_id is not None:
            entries.append(EvidenceMetadataEntry("discovery.source_id", body.source_id))
        return tuple(entries)

    @staticmethod
    def _capture_method(provider: PublicDiscoveryProvider) -> EvidenceCaptureMethod:
        if provider is PublicDiscoveryProvider.GITHUB_USERS:
            return EvidenceCaptureMethod.PROVIDER_API
        return EvidenceCaptureMethod.HTTP_FETCH
