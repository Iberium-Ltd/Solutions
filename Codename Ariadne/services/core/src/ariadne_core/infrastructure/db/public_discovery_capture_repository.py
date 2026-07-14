"""Atomic encrypted retention for reviewed public-discovery results."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import MetaData, Table, and_, func, insert, select
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from ariadne_core.domain.attribution import AttributionAssessment
from ariadne_core.domain.evidence_artifacts import (
    MAX_ORIGINAL_ARTIFACTS,
    EvidenceArtifactKind,
    EvidenceArtifactOriginal,
    validate_opaque_id,
)
from ariadne_core.infrastructure.db.phase5_repository import (
    FindingDraft,
    Phase5AttributionRepository,
)
from ariadne_core.infrastructure.db.repositories import now_us


class PublicDiscoveryCapturePersistenceError(RuntimeError):
    """A safe storage failure with no retained query or source content."""


@dataclass(frozen=True, slots=True)
class PublicDiscoveryCaptureRecord:
    finding: FindingDraft
    artifact: EvidenceArtifactOriginal
    assessment_id: str
    assessment: AttributionAssessment
    rank: int
    source_id: str | None
    capture_fingerprint: str

    def __post_init__(self) -> None:
        validate_opaque_id(self.assessment_id, "attribution assessment id")
        if (
            self.finding.finding_id != self.artifact.finding_id
            or self.finding.finding_id != self.assessment.case_id
            or self.finding.provider_id != self.artifact.provider_id
        ):
            raise ValueError("public discovery capture record binding is invalid")
        if self.artifact.kind is not EvidenceArtifactKind.URL_REFERENCE:
            raise ValueError("public discovery capture requires URL reference evidence")
        if self.artifact.captured_at_us != self.finding.observed_at_us:
            raise ValueError("public discovery capture time binding is invalid")
        if type(self.rank) is not int or not 1 <= self.rank <= 25:
            raise ValueError("public discovery capture rank is invalid")
        if self.source_id is not None and not self.source_id:
            raise ValueError("public discovery source id is invalid")
        if len(self.capture_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.capture_fingerprint
        ):
            raise ValueError("public discovery capture fingerprint is invalid")
        metadata = {item.key: item.value for item in self.artifact.metadata}
        if (
            self.artifact.masked_query_reference is None
            or metadata.get("discovery.authorized_self_audit") != "true"
            or metadata.get("discovery.capture_fingerprint") != self.capture_fingerprint
            or metadata.get("discovery.rank") != str(self.rank)
            or metadata.get("discovery.source_id") != self.source_id
        ):
            raise ValueError("public discovery structured provenance binding is invalid")


@dataclass(frozen=True, slots=True)
class StoredPublicDiscoveryCapture:
    finding_id: str
    artifact_id: str
    source_url: str
    url_sha256: str
    provider_id: str
    captured_at_us: int
    rank: int
    source_id: str | None
    deduplicated: bool


class PublicDiscoveryCaptureRepository:
    """Write a finding, neutral assessment, URL artifact, and link in one transaction."""

    def __init__(self, engine: Engine, *, vault_id: str, profile_id: str) -> None:
        validate_opaque_id(vault_id, "vault id")
        validate_opaque_id(profile_id, "profile id")
        with engine.connect() as connection:
            cipher = connection.exec_driver_sql("PRAGMA cipher_version").scalar_one_or_none()
            profile_exists = connection.exec_driver_sql(
                "SELECT 1 FROM profiles WHERE vault_id = ? AND id = ?",
                (vault_id, profile_id),
            ).scalar_one_or_none()
        if not cipher:
            raise RuntimeError("public discovery capture requires an encrypted vault")
        if profile_exists is None:
            raise LookupError("public discovery capture profile is unavailable")
        self.engine = engine
        self.vault_id = vault_id
        self.profile_id = profile_id
        metadata = MetaData()
        self.findings = Table("phase5_findings", metadata, autoload_with=engine)
        self.originals = Table("phase5_evidence_originals", metadata, autoload_with=engine)
        self.finding_evidence = Table("phase5_finding_evidence", metadata, autoload_with=engine)
        self.assessments = Table("phase5_attribution_assessments", metadata, autoload_with=engine)
        self.missing = Table("phase5_attribution_missing_evidence", metadata, autoload_with=engine)

    def persist(self, record: PublicDiscoveryCaptureRecord) -> StoredPublicDiscoveryCapture:
        """Persist all capture records atomically or return the exact prior capture."""

        try:
            with self.engine.begin() as connection:
                existing = self._existing_by_url_hash(
                    connection,
                    record.artifact.content_sha256,
                )
                if existing is not None:
                    return self._idempotent_result(connection, existing, record)
                original_count = connection.execute(
                    select(func.count())
                    .select_from(self.originals)
                    .where(
                        and_(
                            self.originals.c.vault_id == self.vault_id,
                            self.originals.c.profile_id == self.profile_id,
                        )
                    )
                ).scalar_one()
                if original_count >= MAX_ORIGINAL_ARTIFACTS:
                    raise PublicDiscoveryCapturePersistenceError(
                        "public discovery evidence capacity is exhausted"
                    )
                self._insert_finding(connection, record.finding)
                self._insert_assessment(connection, record)
                self._insert_artifact(connection, record.artifact)
                connection.execute(
                    insert(self.finding_evidence).values(
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        finding_id=record.finding.finding_id,
                        evidence_artifact_id=record.artifact.artifact_id,
                        linked_at_us=now_us(),
                    )
                )
            return StoredPublicDiscoveryCapture(
                finding_id=record.finding.finding_id,
                artifact_id=record.artifact.artifact_id,
                source_url=self._required_source_url(record.artifact),
                url_sha256=record.artifact.content_sha256,
                provider_id=record.artifact.provider_id,
                captured_at_us=record.artifact.captured_at_us,
                rank=record.rank,
                source_id=record.source_id,
                deduplicated=False,
            )
        except PublicDiscoveryCapturePersistenceError:
            raise
        except SQLAlchemyError as error:
            # The context manager has rolled back every preceding write here.
            try:
                with self.engine.connect() as connection:
                    existing = self._existing_by_url_hash(
                        connection,
                        record.artifact.content_sha256,
                    )
                    if existing is not None:
                        return self._idempotent_result(connection, existing, record)
            except (SQLAlchemyError, PublicDiscoveryCapturePersistenceError):
                pass
            raise PublicDiscoveryCapturePersistenceError(
                "public discovery capture transaction failed"
            ) from error

    def _insert_finding(self, connection: Connection, draft: FindingDraft) -> None:
        timestamp = now_us()
        connection.execute(
            insert(self.findings).values(
                id=draft.finding_id,
                vault_id=self.vault_id,
                profile_id=self.profile_id,
                title=draft.title,
                summary=draft.summary,
                outcome=draft.outcome.value,
                severity=draft.severity.value,
                visibility=draft.visibility.value,
                provider_id=draft.provider_id,
                provider_label=draft.provider_label,
                observed_at_us=draft.observed_at_us,
                created_at_us=timestamp,
                updated_at_us=timestamp,
                revision=1,
            )
        )

    def _insert_assessment(
        self,
        connection: Connection,
        record: PublicDiscoveryCaptureRecord,
    ) -> None:
        assessment = record.assessment
        payload = Phase5AttributionRepository._assessment_payload(assessment)
        payload_sha256 = Phase5AttributionRepository._payload_sha256(payload)
        connection.execute(
            insert(self.assessments).values(
                id=record.assessment_id,
                vault_id=self.vault_id,
                profile_id=self.profile_id,
                finding_id=record.finding.finding_id,
                weight_profile_version=assessment.weight_profile_version,
                score=assessment.score,
                confidence_band=assessment.confidence_band.value,
                human_review_required=1,
                assessed_at_us=record.artifact.captured_at_us,
                payload_sha256=payload_sha256,
            )
        )
        recommendation_ranks = {
            signal: rank
            for rank, signal in enumerate(assessment.recommended_next_evidence, start=1)
        }
        for item in assessment.missing_evidence:
            connection.execute(
                insert(self.missing).values(
                    vault_id=self.vault_id,
                    profile_id=self.profile_id,
                    assessment_id=record.assessment_id,
                    signal_type=item.signal.value,
                    potential_weight=item.potential_weight,
                    recommended_rank=recommendation_ranks.get(item.signal),
                )
            )

    def _insert_artifact(
        self,
        connection: Connection,
        artifact: EvidenceArtifactOriginal,
    ) -> None:
        connection.execute(
            insert(self.originals).values(
                id=artifact.artifact_id,
                vault_id=self.vault_id,
                profile_id=self.profile_id,
                kind=artifact.kind.value,
                content=artifact.content,
                content_sha256=artifact.content_sha256,
                captured_at_us=artifact.captured_at_us,
                source_url=artifact.source_url,
                http_status=None,
                redirect_chain_json="[]",
                masked_query_reference=artifact.masked_query_reference,
                provider_id=artifact.provider_id,
                run_id=artifact.run_id,
                finding_id=artifact.finding_id,
                viewport_json=None,
                capture_method=artifact.capture_method.value,
                metadata_json=self._metadata_json(artifact),
                encryption_required=1,
            )
        )

    def _existing_by_url_hash(
        self,
        connection: Connection,
        content_sha256: str,
    ) -> RowMapping | None:
        return (
            connection.execute(
                select(self.originals).where(
                    and_(
                        self.originals.c.vault_id == self.vault_id,
                        self.originals.c.profile_id == self.profile_id,
                        self.originals.c.content_sha256 == content_sha256,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    def _idempotent_result(
        self,
        connection: Connection,
        existing: RowMapping,
        record: PublicDiscoveryCaptureRecord,
    ) -> StoredPublicDiscoveryCapture:
        finding_id = None if existing["finding_id"] is None else str(existing["finding_id"])
        finding = (
            None
            if finding_id is None
            else connection.execute(
                select(self.findings).where(
                    and_(
                        self.findings.c.vault_id == self.vault_id,
                        self.findings.c.profile_id == self.profile_id,
                        self.findings.c.id == finding_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        linked = (
            False
            if finding_id is None
            else connection.execute(
                select(self.finding_evidence.c.evidence_artifact_id).where(
                    and_(
                        self.finding_evidence.c.vault_id == self.vault_id,
                        self.finding_evidence.c.profile_id == self.profile_id,
                        self.finding_evidence.c.finding_id == finding_id,
                        self.finding_evidence.c.evidence_artifact_id == existing["id"],
                    )
                )
            ).scalar_one_or_none()
            is not None
        )
        assessment_exists = (
            False
            if finding_id is None
            else connection.execute(
                select(self.assessments.c.id)
                .where(
                    and_(
                        self.assessments.c.vault_id == self.vault_id,
                        self.assessments.c.profile_id == self.profile_id,
                        self.assessments.c.finding_id == finding_id,
                        self.assessments.c.assessed_at_us == record.artifact.captured_at_us,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )
        expected_metadata = self._metadata_json(record.artifact)
        compatible = (
            finding is not None
            and linked
            and assessment_exists
            and str(existing["kind"]) == EvidenceArtifactKind.URL_REFERENCE.value
            and bytes(existing["content"]) == b""
            and str(existing["content_sha256"]) == record.artifact.content_sha256
            and str(existing["source_url"]) == self._required_source_url(record.artifact)
            and int(existing["captured_at_us"]) == record.artifact.captured_at_us
            and str(existing["masked_query_reference"]) == record.artifact.masked_query_reference
            and str(existing["provider_id"]) == record.artifact.provider_id
            and str(existing["capture_method"]) == record.artifact.capture_method.value
            and str(existing["metadata_json"]) == expected_metadata
            and str(finding["title"]) == record.finding.title
            and str(finding["summary"]) == record.finding.summary
            and str(finding["outcome"]) == record.finding.outcome.value
            and str(finding["severity"]) == record.finding.severity.value
            and str(finding["visibility"]) == record.finding.visibility.value
            and str(finding["provider_id"]) == record.finding.provider_id
            and str(finding["provider_label"]) == record.finding.provider_label
            and int(finding["observed_at_us"]) == record.finding.observed_at_us
        )
        if not compatible or finding_id is None:
            raise PublicDiscoveryCapturePersistenceError(
                "public discovery URL already exists with incompatible provenance"
            )
        return StoredPublicDiscoveryCapture(
            finding_id=finding_id,
            artifact_id=str(existing["id"]),
            source_url=str(existing["source_url"]),
            url_sha256=str(existing["content_sha256"]),
            provider_id=str(existing["provider_id"]),
            captured_at_us=int(existing["captured_at_us"]),
            rank=record.rank,
            source_id=record.source_id,
            deduplicated=True,
        )

    @staticmethod
    def _required_source_url(artifact: EvidenceArtifactOriginal) -> str:
        if artifact.source_url is None:
            raise ValueError("public discovery source URL is unavailable")
        return artifact.source_url

    @staticmethod
    def _metadata_json(artifact: EvidenceArtifactOriginal) -> str:
        return json.dumps(
            [{"key": item.key, "value": item.value} for item in artifact.metadata],
            separators=(",", ":"),
        )
