"""Durable profile-scoped evidence and explainable attribution persistence.

An original capture is immutable and content-addressed; redaction creates a
derivative rather than editing history. Findings, assessments, and human
decisions retain separate revisions so later interpretation cannot rewrite what
was captured or what supported an earlier conclusion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import MetaData, Table, and_, func, insert, select
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from ariadne_core.application.evidence_artifacts import (
    DuplicateEvidenceId,
    EvidenceStorageFull,
)
from ariadne_core.domain.attribution import (
    AttributionAssessment,
    AttributionConfidenceBand,
    HumanAttributionDecision,
    HumanAttributionState,
    MissingEvidence,
    NegativeAttributionSignal,
    NegativeSignalContribution,
    PositiveAttributionSignal,
    PositiveSignalContribution,
)
from ariadne_core.domain.evidence_artifacts import (
    MAX_DERIVATIVE_ARTIFACTS,
    MAX_ORIGINAL_ARTIFACTS,
    EvidenceArtifactKind,
    EvidenceArtifactOriginal,
    EvidenceCaptureMethod,
    EvidenceMetadataEntry,
    EvidenceViewport,
    RedactedEvidenceDerivative,
    validate_opaque_id,
    validate_timestamp,
)
from ariadne_core.infrastructure.db.repositories import now_us


class EvidenceIntegrityState(StrEnum):
    VERIFIED = "VERIFIED"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityResult:
    artifact_id: str
    state: EvidenceIntegrityState
    expected_sha256: str = field(repr=False)
    actual_sha256: str = field(repr=False)
    verified_at_us: int


@dataclass(frozen=True, slots=True)
class EvidenceSourceMetadata:
    """Traceable evidence identity loaded without selecting encrypted content bytes."""

    artifact_id: str
    source_url: str | None = field(repr=False)


def _require_encrypted_profile(engine: Engine, vault_id: str, profile_id: str) -> None:
    validate_opaque_id(vault_id, "vault id")
    validate_opaque_id(profile_id, "profile id")
    with engine.connect() as connection:
        cipher = connection.exec_driver_sql("PRAGMA cipher_version").scalar_one_or_none()
        if not cipher:
            raise RuntimeError("Phase 5 durable storage requires an encrypted vault")
        profile = connection.exec_driver_sql(
            "SELECT 1 FROM profiles WHERE vault_id = ? AND id = ?",
            (vault_id, profile_id),
        ).scalar_one_or_none()
    if profile is None:
        raise LookupError("Phase 5 profile is unavailable")


class Phase5EvidenceRepository:
    """Store immutable originals, derivatives, and links in one person's vault."""

    def __init__(
        self,
        engine: Engine,
        *,
        vault_id: str,
        profile_id: str,
        maximum_originals: int = MAX_ORIGINAL_ARTIFACTS,
        maximum_derivatives: int = MAX_DERIVATIVE_ARTIFACTS,
    ) -> None:
        if not 1 <= maximum_originals <= MAX_ORIGINAL_ARTIFACTS:
            raise ValueError("evidence original capacity is invalid")
        if not 1 <= maximum_derivatives <= MAX_DERIVATIVE_ARTIFACTS:
            raise ValueError("evidence derivative capacity is invalid")
        _require_encrypted_profile(engine, vault_id, profile_id)
        self.engine = engine
        self.vault_id = vault_id
        self.profile_id = profile_id
        self._maximum_originals = maximum_originals
        self._maximum_derivatives = maximum_derivatives
        metadata = MetaData()
        self.findings = Table("phase5_findings", metadata, autoload_with=engine)
        self.originals = Table("phase5_evidence_originals", metadata, autoload_with=engine)
        self.finding_evidence = Table("phase5_finding_evidence", metadata, autoload_with=engine)
        self.derivatives = Table("phase5_evidence_derivatives", metadata, autoload_with=engine)

    @property
    def durable_encryption(self) -> bool:
        return True

    def has_id(self, artifact_id: str) -> bool:
        validate_opaque_id(artifact_id, "evidence artifact id")
        with self.engine.connect() as connection:
            return self._has_id(connection, artifact_id)

    def _has_id(self, connection: Connection, artifact_id: str) -> bool:
        scope = (self.vault_id, self.profile_id, artifact_id)
        return bool(
            connection.exec_driver_sql(
                "SELECT EXISTS(SELECT 1 FROM phase5_evidence_originals "
                "WHERE vault_id = ? AND profile_id = ? AND id = ?) OR "
                "EXISTS(SELECT 1 FROM phase5_evidence_derivatives "
                "WHERE vault_id = ? AND profile_id = ? AND id = ?)",
                scope + scope,
            ).scalar_one()
        )

    def original_by_hash(self, content_sha256: str) -> EvidenceArtifactOriginal | None:
        with self.engine.connect() as connection:
            row = (
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
        return None if row is None else self._original(row)

    def derivative_by_hash(
        self,
        original_artifact_id: str,
        content_sha256: str,
    ) -> RedactedEvidenceDerivative | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.derivatives).where(
                        and_(
                            self.derivatives.c.vault_id == self.vault_id,
                            self.derivatives.c.profile_id == self.profile_id,
                            self.derivatives.c.original_artifact_id == original_artifact_id,
                            self.derivatives.c.content_sha256 == content_sha256,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._derivative(row)

    def insert_original(self, artifact: EvidenceArtifactOriginal) -> None:
        """Insert an original or accept only a byte-identical idempotent replay."""
        with self.engine.begin() as connection:
            if self._has_id(connection, artifact.artifact_id):
                raise DuplicateEvidenceId("evidence artifact id already exists")
            count = connection.execute(
                select(func.count())
                .select_from(self.originals)
                .where(
                    and_(
                        self.originals.c.vault_id == self.vault_id,
                        self.originals.c.profile_id == self.profile_id,
                    )
                )
            ).scalar_one()
            if count >= self._maximum_originals:
                raise EvidenceStorageFull("evidence original capacity is exhausted")
            if artifact.finding_id is not None:
                self._require_finding(connection, artifact.finding_id)
            try:
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
                        http_status=artifact.http_status,
                        redirect_chain_json=json.dumps(artifact.redirect_chain),
                        masked_query_reference=artifact.masked_query_reference,
                        provider_id=artifact.provider_id,
                        run_id=artifact.run_id,
                        finding_id=artifact.finding_id,
                        viewport_json=self._viewport_json(artifact.viewport),
                        capture_method=artifact.capture_method.value,
                        metadata_json=json.dumps(
                            [{"key": item.key, "value": item.value} for item in artifact.metadata],
                            separators=(",", ":"),
                        ),
                        encryption_required=1,
                    )
                )
                if artifact.finding_id is not None:
                    self._insert_link(connection, artifact.artifact_id, artifact.finding_id)
            except IntegrityError as error:
                if self._has_id(connection, artifact.artifact_id):
                    raise DuplicateEvidenceId("evidence artifact id already exists") from error
                raise ValueError(
                    "evidence content must be deduplicated before insertion"
                ) from error

    def insert_derivative(self, derivative: RedactedEvidenceDerivative) -> None:
        """Persist redaction as a child artifact; never modify the original."""
        with self.engine.begin() as connection:
            if self._has_id(connection, derivative.derivative_id):
                raise DuplicateEvidenceId("evidence artifact id already exists")
            if not self._original_exists(connection, derivative.original_artifact_id):
                raise LookupError("original evidence artifact is unavailable")
            count = connection.execute(
                select(func.count())
                .select_from(self.derivatives)
                .where(
                    and_(
                        self.derivatives.c.vault_id == self.vault_id,
                        self.derivatives.c.profile_id == self.profile_id,
                    )
                )
            ).scalar_one()
            if count >= self._maximum_derivatives:
                raise EvidenceStorageFull("evidence derivative capacity is exhausted")
            try:
                connection.execute(
                    insert(self.derivatives).values(
                        id=derivative.derivative_id,
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        original_artifact_id=derivative.original_artifact_id,
                        content=derivative.content,
                        content_sha256=derivative.content_sha256,
                        created_at_us=derivative.created_at_us,
                        redaction_policy_version=derivative.redaction_policy_version,
                        redaction_summary_code=derivative.redaction_summary_code,
                        encryption_required=1,
                    )
                )
            except IntegrityError as error:
                raise ValueError(
                    "evidence derivative must be deduplicated before insertion"
                ) from error

    def get_original(self, artifact_id: str) -> EvidenceArtifactOriginal:
        with self.engine.connect() as connection:
            row = self._original_row(connection, artifact_id)
        if row is None:
            raise LookupError("original evidence artifact is unavailable")
        return self._original(row)

    def list_originals(self, *, limit: int = 100) -> tuple[EvidenceArtifactOriginal, ...]:
        self._validate_limit(limit)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.originals)
                    .where(
                        and_(
                            self.originals.c.vault_id == self.vault_id,
                            self.originals.c.profile_id == self.profile_id,
                        )
                    )
                    .order_by(self.originals.c.captured_at_us.desc(), self.originals.c.id.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(self._original(row) for row in rows)

    def derivatives_for(self, artifact_id: str) -> tuple[RedactedEvidenceDerivative, ...]:
        if not self.has_id(artifact_id) or self.get_original(artifact_id) is None:
            raise LookupError("original evidence artifact is unavailable")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.derivatives)
                    .where(
                        and_(
                            self.derivatives.c.vault_id == self.vault_id,
                            self.derivatives.c.profile_id == self.profile_id,
                            self.derivatives.c.original_artifact_id == artifact_id,
                        )
                    )
                    .order_by(self.derivatives.c.created_at_us, self.derivatives.c.id)
                )
                .mappings()
                .all()
            )
        return tuple(self._derivative(row) for row in rows)

    def count_derivatives(self, artifact_id: str) -> int:
        with self.engine.connect() as connection:
            if not self._original_exists(connection, artifact_id):
                raise LookupError("original evidence artifact is unavailable")
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(self.derivatives)
                    .where(
                        and_(
                            self.derivatives.c.vault_id == self.vault_id,
                            self.derivatives.c.profile_id == self.profile_id,
                            self.derivatives.c.original_artifact_id == artifact_id,
                        )
                    )
                ).scalar_one()
            )

    def link_original_to_finding(self, artifact_id: str, finding_id: str) -> None:
        validate_opaque_id(artifact_id, "evidence artifact id")
        validate_opaque_id(finding_id, "evidence finding id")
        with self.engine.begin() as connection:
            if not self._original_exists(connection, artifact_id):
                raise LookupError("original evidence artifact is unavailable")
            self._require_finding(connection, finding_id)
            exists = connection.execute(
                select(self.finding_evidence.c.finding_id).where(
                    and_(
                        self.finding_evidence.c.vault_id == self.vault_id,
                        self.finding_evidence.c.profile_id == self.profile_id,
                        self.finding_evidence.c.finding_id == finding_id,
                        self.finding_evidence.c.evidence_artifact_id == artifact_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                self._insert_link(connection, artifact_id, finding_id)

    def originals_for_finding(
        self,
        finding_id: str,
        *,
        limit: int = 100,
    ) -> tuple[EvidenceArtifactOriginal, ...]:
        self._validate_limit(limit)
        with self.engine.connect() as connection:
            self._require_finding(connection, finding_id)
            rows = (
                connection.execute(
                    select(self.originals)
                    .join(
                        self.finding_evidence,
                        and_(
                            self.finding_evidence.c.vault_id == self.originals.c.vault_id,
                            self.finding_evidence.c.profile_id == self.originals.c.profile_id,
                            self.finding_evidence.c.evidence_artifact_id == self.originals.c.id,
                        ),
                    )
                    .where(
                        and_(
                            self.originals.c.vault_id == self.vault_id,
                            self.originals.c.profile_id == self.profile_id,
                            self.finding_evidence.c.finding_id == finding_id,
                        )
                    )
                    .order_by(self.originals.c.captured_at_us.desc(), self.originals.c.id.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(self._original(row) for row in rows)

    def source_metadata_for_artifacts(
        self,
        artifact_ids: tuple[str, ...],
    ) -> tuple[EvidenceSourceMetadata, ...]:
        if (
            type(artifact_ids) is not tuple
            or not artifact_ids
            or len(artifact_ids) > 1_000
            or len(set(artifact_ids)) != len(artifact_ids)
        ):
            raise ValueError("evidence source metadata selection is invalid")
        for artifact_id in artifact_ids:
            validate_opaque_id(artifact_id, "evidence artifact id")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.originals.c.id, self.originals.c.source_url)
                    .where(
                        and_(
                            self.originals.c.vault_id == self.vault_id,
                            self.originals.c.profile_id == self.profile_id,
                            self.originals.c.id.in_(artifact_ids),
                        )
                    )
                    .order_by(self.originals.c.id)
                )
                .mappings()
                .all()
            )
        return tuple(
            EvidenceSourceMetadata(
                artifact_id=str(row["id"]),
                source_url=None if row["source_url"] is None else str(row["source_url"]),
            )
            for row in rows
        )

    def count_originals_for_finding(self, finding_id: str) -> int:
        with self.engine.connect() as connection:
            self._require_finding(connection, finding_id)
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(self.finding_evidence)
                    .where(
                        and_(
                            self.finding_evidence.c.vault_id == self.vault_id,
                            self.finding_evidence.c.profile_id == self.profile_id,
                            self.finding_evidence.c.finding_id == finding_id,
                        )
                    )
                ).scalar_one()
            )

    def verify_original(self, artifact_id: str) -> EvidenceIntegrityResult:
        """Compare stored metadata and ciphertext hashes without changing evidence."""
        with self.engine.connect() as connection:
            row = self._original_row(connection, artifact_id)
        if row is None:
            raise LookupError("original evidence artifact is unavailable")
        material = (
            str(row["source_url"]).encode("utf-8")
            if str(row["kind"]) == EvidenceArtifactKind.URL_REFERENCE.value
            else bytes(row["content"])
        )
        actual = hashlib.sha256(material).hexdigest()
        expected = str(row["content_sha256"])
        return EvidenceIntegrityResult(
            artifact_id=artifact_id,
            state=(
                EvidenceIntegrityState.VERIFIED
                if actual == expected
                else EvidenceIntegrityState.CORRUPT
            ),
            expected_sha256=expected,
            actual_sha256=actual,
            verified_at_us=now_us(),
        )

    def _require_finding(self, connection: Connection, finding_id: str) -> None:
        exists = connection.execute(
            select(self.findings.c.id).where(
                and_(
                    self.findings.c.vault_id == self.vault_id,
                    self.findings.c.profile_id == self.profile_id,
                    self.findings.c.id == finding_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise LookupError("Phase 5 finding is unavailable")

    def _original_exists(self, connection: Connection, artifact_id: str) -> bool:
        return self._original_row(connection, artifact_id) is not None

    def _original_row(self, connection: Connection, artifact_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.originals).where(
                    and_(
                        self.originals.c.vault_id == self.vault_id,
                        self.originals.c.profile_id == self.profile_id,
                        self.originals.c.id == artifact_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    def _insert_link(self, connection: Connection, artifact_id: str, finding_id: str) -> None:
        connection.execute(
            insert(self.finding_evidence).values(
                vault_id=self.vault_id,
                profile_id=self.profile_id,
                finding_id=finding_id,
                evidence_artifact_id=artifact_id,
                linked_at_us=now_us(),
            )
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError("evidence artifact limit is invalid")

    @staticmethod
    def _viewport_json(viewport: EvidenceViewport | None) -> str | None:
        if viewport is None:
            return None
        return json.dumps(
            {
                "deviceScaleMicros": viewport.device_scale_micros,
                "height": viewport.height,
                "width": viewport.width,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _original(row: RowMapping) -> EvidenceArtifactOriginal:
        viewport_payload = (
            None if row["viewport_json"] is None else json.loads(row["viewport_json"])
        )
        metadata_payload = json.loads(str(row["metadata_json"]))
        return EvidenceArtifactOriginal(
            artifact_id=str(row["id"]),
            kind=EvidenceArtifactKind(str(row["kind"])),
            content=bytes(row["content"]),
            content_sha256=str(row["content_sha256"]),
            captured_at_us=int(row["captured_at_us"]),
            source_url=None if row["source_url"] is None else str(row["source_url"]),
            http_status=None if row["http_status"] is None else int(row["http_status"]),
            redirect_chain=tuple(json.loads(str(row["redirect_chain_json"]))),
            masked_query_reference=(
                None
                if row["masked_query_reference"] is None
                else str(row["masked_query_reference"])
            ),
            provider_id=str(row["provider_id"]),
            run_id=str(row["run_id"]),
            finding_id=None if row["finding_id"] is None else str(row["finding_id"]),
            viewport=(
                None
                if viewport_payload is None
                else EvidenceViewport(
                    width=int(viewport_payload["width"]),
                    height=int(viewport_payload["height"]),
                    device_scale_micros=int(viewport_payload["deviceScaleMicros"]),
                )
            ),
            capture_method=EvidenceCaptureMethod(str(row["capture_method"])),
            metadata=tuple(
                EvidenceMetadataEntry(str(item["key"]), str(item["value"]))
                for item in metadata_payload
            ),
        )

    @staticmethod
    def _derivative(row: RowMapping) -> RedactedEvidenceDerivative:
        return RedactedEvidenceDerivative(
            derivative_id=str(row["id"]),
            original_artifact_id=str(row["original_artifact_id"]),
            content=bytes(row["content"]),
            content_sha256=str(row["content_sha256"]),
            created_at_us=int(row["created_at_us"]),
            redaction_policy_version=str(row["redaction_policy_version"]),
            redaction_summary_code=str(row["redaction_summary_code"]),
        )


class FindingOutcome(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NOT_CHECKED = "NOT_CHECKED"
    CHECK_FAILED = "CHECK_FAILED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    AUTHORITATIVE_ABSENCE = "AUTHORITATIVE_ABSENCE"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingVisibility(StrEnum):
    PUBLICLY_ATTRIBUTABLE = "PUBLICLY_ATTRIBUTABLE"
    PUBLIC_PSEUDONYMOUS = "PUBLIC_PSEUDONYMOUS"
    PRIVATELY_LINKABLE = "PRIVATELY_LINKABLE"
    HISTORICAL_RESIDUE = "HISTORICAL_RESIDUE"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    UNKNOWN = "UNKNOWN"


def _valid_text(value: str, label: str, maximum: int) -> None:
    if (
        not value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise ValueError(f"{label} is invalid")


@dataclass(frozen=True, slots=True)
class FindingDraft:
    finding_id: str
    title: str = field(repr=False)
    summary: str = field(repr=False)
    outcome: FindingOutcome
    severity: FindingSeverity
    visibility: FindingVisibility
    provider_id: str
    provider_label: str
    observed_at_us: int

    def __post_init__(self) -> None:
        validate_opaque_id(self.finding_id, "finding id")
        validate_opaque_id(self.provider_id, "finding provider id")
        _valid_text(self.title, "finding title", 256)
        _valid_text(self.summary, "finding summary", 2_048)
        _valid_text(self.provider_label, "finding provider label", 128)
        if not isinstance(self.outcome, FindingOutcome):
            raise TypeError("finding outcome is invalid")
        if not isinstance(self.severity, FindingSeverity):
            raise TypeError("finding severity is invalid")
        if not isinstance(self.visibility, FindingVisibility):
            raise TypeError("finding visibility is invalid")
        validate_timestamp(self.observed_at_us, "finding observation time")


@dataclass(frozen=True, slots=True)
class StoredFinding:
    finding_id: str
    title: str = field(repr=False)
    summary: str = field(repr=False)
    outcome: FindingOutcome
    severity: FindingSeverity
    visibility: FindingVisibility
    provider_id: str
    provider_label: str
    observed_at_us: int
    created_at_us: int
    updated_at_us: int
    revision: int


@dataclass(frozen=True, slots=True)
class StoredAttributionAssessment:
    assessment_id: str
    finding_id: str
    assessment: AttributionAssessment
    assessed_at_us: int
    payload_sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class StoredAttributionDecision:
    decision_id: str
    assessment_id: str
    decision: HumanAttributionDecision
    supersedes_decision_id: str | None
    revision: int
    payload_sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Phase5CheckpointDerivativeMaterial:
    derivative_id: str
    content_sha256: str = field(repr=False)
    created_at_us: int
    redaction_policy_version: str
    redaction_summary_code: str


@dataclass(frozen=True, slots=True)
class Phase5CheckpointEvidenceMaterial:
    artifact_id: str
    kind: str
    content_sha256: str = field(repr=False)
    captured_at_us: int
    source_url_sha256: str | None = field(repr=False)
    http_status: int | None
    redirect_count: int
    redirect_chain_sha256: str = field(repr=False)
    masked_query_reference_sha256: str | None = field(repr=False)
    provider_id: str
    run_id: str
    primary_finding_id: str | None
    viewport_sha256: str | None = field(repr=False)
    capture_method: str
    metadata_sha256: str = field(repr=False)
    linked_at_us: int
    derivatives: tuple[Phase5CheckpointDerivativeMaterial, ...]


@dataclass(frozen=True, slots=True)
class Phase5CheckpointFindingMaterial:
    finding: StoredFinding
    evidence: tuple[Phase5CheckpointEvidenceMaterial, ...]
    latest_assessment: StoredAttributionAssessment | None
    latest_decision: StoredAttributionDecision | None


class DuplicatePhase5Id(ValueError):
    pass


class AttributionRevisionConflict(RuntimeError):
    pass


class Phase5AttributionRepository:
    """Persist findings and append-only, evidence-backed attribution history."""

    def __init__(self, engine: Engine, *, vault_id: str, profile_id: str) -> None:
        _require_encrypted_profile(engine, vault_id, profile_id)
        self.engine = engine
        self.vault_id = vault_id
        self.profile_id = profile_id
        metadata = MetaData()
        self.findings = Table("phase5_findings", metadata, autoload_with=engine)
        self.originals = Table("phase5_evidence_originals", metadata, autoload_with=engine)
        self.finding_evidence = Table("phase5_finding_evidence", metadata, autoload_with=engine)
        self.derivatives = Table("phase5_evidence_derivatives", metadata, autoload_with=engine)
        self.assessments = Table("phase5_attribution_assessments", metadata, autoload_with=engine)
        self.signals = Table("phase5_attribution_signals", metadata, autoload_with=engine)
        self.signal_evidence = Table(
            "phase5_attribution_signal_evidence", metadata, autoload_with=engine
        )
        self.missing = Table("phase5_attribution_missing_evidence", metadata, autoload_with=engine)
        self.decisions = Table("phase5_attribution_decisions", metadata, autoload_with=engine)

    def persist_finding(self, draft: FindingDraft) -> StoredFinding:
        with self.engine.begin() as connection:
            existing = self._finding_row(connection, draft.finding_id)
            if existing is not None:
                stored = self._stored_finding(existing)
                if self._draft_matches(stored, draft):
                    return stored
                raise DuplicatePhase5Id("finding id already exists with different content")
            timestamp = now_us()
            try:
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
            except IntegrityError as error:
                raise DuplicatePhase5Id("finding id already exists") from error
        return self.get_finding(draft.finding_id)

    def persist_manual_finding_with_initial_assessment(
        self,
        *,
        draft: FindingDraft,
        assessment_id: str,
        assessment: AttributionAssessment,
        assessed_at_us: int,
    ) -> tuple[StoredFinding, StoredAttributionAssessment]:
        """Create the first finding and neutral assessment in one transaction."""
        """Atomically create one manual finding and its neutral initial assessment."""

        validate_opaque_id(assessment_id, "attribution assessment id")
        validate_timestamp(assessed_at_us, "attribution assessment time")
        if assessment.case_id != draft.finding_id:
            raise ValueError("manual finding assessment does not match its finding")
        if assessed_at_us < draft.observed_at_us:
            raise ValueError("manual finding assessment precedes its observation")
        if (
            assessment.score != 0
            or assessment.confidence_band is not AttributionConfidenceBand.LOW
            or assessment.contributing_signals
            or assessment.contradictions
            or {item.signal for item in assessment.missing_evidence}
            != set(PositiveAttributionSignal)
        ):
            raise ValueError("manual finding initial assessment is not neutral")
        recommendation_ranks = {
            signal: rank
            for rank, signal in enumerate(assessment.recommended_next_evidence, start=1)
        }
        missing_signals = {item.signal for item in assessment.missing_evidence}
        if not set(recommendation_ranks) <= missing_signals:
            raise ValueError("attribution recommendations must reference missing evidence")
        payload_sha256 = self._payload_sha256(self._assessment_payload(assessment))

        with self.engine.begin() as connection:
            if self._finding_row(connection, draft.finding_id) is not None:
                raise DuplicatePhase5Id("finding id already exists")
            if self._assessment_row(connection, assessment_id) is not None:
                raise DuplicatePhase5Id("attribution assessment id already exists")
            timestamp = now_us()
            try:
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
                connection.execute(
                    insert(self.assessments).values(
                        id=assessment_id,
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        finding_id=assessment.case_id,
                        weight_profile_version=assessment.weight_profile_version,
                        score=assessment.score,
                        confidence_band=assessment.confidence_band.value,
                        human_review_required=int(assessment.human_review_required),
                        assessed_at_us=assessed_at_us,
                        payload_sha256=payload_sha256,
                    )
                )
                for missing_item in assessment.missing_evidence:
                    connection.execute(
                        insert(self.missing).values(
                            vault_id=self.vault_id,
                            profile_id=self.profile_id,
                            assessment_id=assessment_id,
                            signal_type=missing_item.signal.value,
                            potential_weight=missing_item.potential_weight,
                            recommended_rank=recommendation_ranks.get(missing_item.signal),
                        )
                    )
            except IntegrityError as error:
                raise DuplicatePhase5Id(
                    "manual finding or assessment could not be created"
                ) from error

        return self.get_finding(draft.finding_id), self.get_assessment(assessment_id)

    def get_finding(self, finding_id: str) -> StoredFinding:
        validate_opaque_id(finding_id, "finding id")
        with self.engine.connect() as connection:
            row = self._finding_row(connection, finding_id)
        if row is None:
            raise LookupError("Phase 5 finding is unavailable")
        return self._stored_finding(row)

    def list_findings(self, *, limit: int = 100) -> tuple[StoredFinding, ...]:
        self._validate_limit(limit)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.findings)
                    .where(
                        and_(
                            self.findings.c.vault_id == self.vault_id,
                            self.findings.c.profile_id == self.profile_id,
                        )
                    )
                    .order_by(self.findings.c.updated_at_us.desc(), self.findings.c.id.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return tuple(self._stored_finding(row) for row in rows)

    def count_findings(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(self.findings)
                    .where(
                        and_(
                            self.findings.c.vault_id == self.vault_id,
                            self.findings.c.profile_id == self.profile_id,
                        )
                    )
                ).scalar_one()
            )

    def local_checkpoint_materials(
        self,
        provider_ids: tuple[str, ...],
        *,
        maximum_findings: int,
    ) -> tuple[Phase5CheckpointFindingMaterial, ...]:
        """Load bounded, contentless Phase 5 state for a local audit checkpoint."""

        if (
            type(provider_ids) is not tuple
            or not provider_ids
            or len(provider_ids) > 256
            or len(set(provider_ids)) != len(provider_ids)
        ):
            raise ValueError("local checkpoint provider coverage is invalid")
        for provider_id in provider_ids:
            validate_opaque_id(provider_id, "local checkpoint provider id")
        if type(maximum_findings) is not int or not 1 <= maximum_findings <= 2_000:
            raise ValueError("local checkpoint finding bound is invalid")

        with self.engine.connect() as connection:
            finding_rows = (
                connection.execute(
                    select(self.findings)
                    .where(
                        and_(
                            self.findings.c.vault_id == self.vault_id,
                            self.findings.c.profile_id == self.profile_id,
                            self.findings.c.provider_id.in_(provider_ids),
                        )
                    )
                    .order_by(self.findings.c.provider_id, self.findings.c.id)
                    .limit(maximum_findings + 1)
                )
                .mappings()
                .all()
            )
            if len(finding_rows) > maximum_findings:
                raise RuntimeError("local checkpoint finding capacity reached")
            if not finding_rows:
                return ()

            findings = tuple(self._stored_finding(row) for row in finding_rows)
            finding_ids = tuple(item.finding_id for item in findings)
            evidence_by_finding = self._checkpoint_evidence(
                connection,
                finding_ids,
            )
            latest_assessments = self._latest_checkpoint_assessments(
                connection,
                finding_ids,
            )
            latest_decisions = self._latest_checkpoint_decisions(
                connection,
                finding_ids,
            )
            return tuple(
                Phase5CheckpointFindingMaterial(
                    finding=finding,
                    evidence=evidence_by_finding.get(finding.finding_id, ()),
                    latest_assessment=latest_assessments.get(finding.finding_id),
                    latest_decision=latest_decisions.get(finding.finding_id),
                )
                for finding in findings
            )

    def persist_assessment(
        self,
        *,
        assessment_id: str,
        assessment: AttributionAssessment,
        assessed_at_us: int,
    ) -> StoredAttributionAssessment:
        """Append an assessment only after every cited evidence link is verified."""
        validate_opaque_id(assessment_id, "attribution assessment id")
        validate_opaque_id(assessment.case_id, "attribution finding id")
        validate_timestamp(assessed_at_us, "attribution assessment time")
        payload = self._assessment_payload(assessment)
        payload_sha256 = self._payload_sha256(payload)
        with self.engine.begin() as connection:
            existing = self._assessment_row(connection, assessment_id)
            if existing is not None:
                stored = self._stored_assessment(connection, existing)
                if stored.assessment == assessment and stored.assessed_at_us == assessed_at_us:
                    return stored
                raise DuplicatePhase5Id(
                    "attribution assessment id already exists with different content"
                )
            if self._finding_row(connection, assessment.case_id) is None:
                raise LookupError("Phase 5 finding is unavailable")
            references = {
                reference
                for item in assessment.contributing_signals
                for reference in item.evidence_references
            } | {
                reference
                for item in assessment.contradictions
                for reference in item.evidence_references
            }
            for reference in references:
                if not self._evidence_is_linked(connection, reference, assessment.case_id):
                    raise LookupError("attribution evidence is not linked to this finding")
            connection.execute(
                insert(self.assessments).values(
                    id=assessment_id,
                    vault_id=self.vault_id,
                    profile_id=self.profile_id,
                    finding_id=assessment.case_id,
                    weight_profile_version=assessment.weight_profile_version,
                    score=assessment.score,
                    confidence_band=assessment.confidence_band.value,
                    human_review_required=int(assessment.human_review_required),
                    assessed_at_us=assessed_at_us,
                    payload_sha256=payload_sha256,
                )
            )
            for ordinal, positive in enumerate(assessment.contributing_signals):
                self._insert_signal(
                    connection,
                    assessment_id=assessment_id,
                    polarity="SUPPORTS",
                    ordinal=ordinal,
                    signal_type=positive.signal.value,
                    weight=positive.weight,
                    evidence_references=positive.evidence_references,
                )
            for ordinal, negative in enumerate(assessment.contradictions):
                self._insert_signal(
                    connection,
                    assessment_id=assessment_id,
                    polarity="CONTRADICTS",
                    ordinal=ordinal,
                    signal_type=negative.signal.value,
                    weight=negative.penalty,
                    evidence_references=negative.evidence_references,
                )
            recommendation_ranks = {
                signal: rank
                for rank, signal in enumerate(assessment.recommended_next_evidence, start=1)
            }
            missing_signals = {item.signal for item in assessment.missing_evidence}
            if not set(recommendation_ranks) <= missing_signals:
                raise ValueError("attribution recommendations must reference missing evidence")
            for missing_item in assessment.missing_evidence:
                connection.execute(
                    insert(self.missing).values(
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        assessment_id=assessment_id,
                        signal_type=missing_item.signal.value,
                        potential_weight=missing_item.potential_weight,
                        recommended_rank=recommendation_ranks.get(missing_item.signal),
                    )
                )
        return self.get_assessment(assessment_id)

    def get_assessment(self, assessment_id: str) -> StoredAttributionAssessment:
        validate_opaque_id(assessment_id, "attribution assessment id")
        with self.engine.connect() as connection:
            row = self._assessment_row(connection, assessment_id)
            if row is None:
                raise LookupError("attribution assessment is unavailable")
            return self._stored_assessment(connection, row)

    def latest_assessment(self, finding_id: str) -> StoredAttributionAssessment | None:
        validate_opaque_id(finding_id, "finding id")
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.assessments)
                    .where(
                        and_(
                            self.assessments.c.vault_id == self.vault_id,
                            self.assessments.c.profile_id == self.profile_id,
                            self.assessments.c.finding_id == finding_id,
                        )
                    )
                    .order_by(
                        self.assessments.c.assessed_at_us.desc(), self.assessments.c.id.desc()
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._stored_assessment(connection, row)

    def list_assessments(
        self,
        finding_id: str,
        *,
        limit: int = 100,
    ) -> tuple[StoredAttributionAssessment, ...]:
        self._validate_limit(limit)
        validate_opaque_id(finding_id, "finding id")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.assessments)
                    .where(
                        and_(
                            self.assessments.c.vault_id == self.vault_id,
                            self.assessments.c.profile_id == self.profile_id,
                            self.assessments.c.finding_id == finding_id,
                        )
                    )
                    .order_by(
                        self.assessments.c.assessed_at_us.desc(), self.assessments.c.id.desc()
                    )
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return tuple(self._stored_assessment(connection, row) for row in rows)

    def persist_decision(
        self,
        *,
        decision_id: str,
        assessment_id: str,
        decision: HumanAttributionDecision,
        expected_previous_decision_id: str | None,
    ) -> StoredAttributionDecision:
        """Append a human decision; never overwrite the assessment it reviewed."""
        validate_opaque_id(decision_id, "attribution decision id")
        validate_opaque_id(assessment_id, "attribution assessment id")
        if expected_previous_decision_id is not None:
            validate_opaque_id(expected_previous_decision_id, "previous attribution decision id")
        with self.engine.begin() as connection:
            existing = self._decision_row(connection, decision_id)
            if existing is not None:
                stored = self._stored_decision(existing)
                if (
                    stored.assessment_id == assessment_id
                    and stored.decision == decision
                    and stored.supersedes_decision_id == expected_previous_decision_id
                ):
                    return stored
                raise DuplicatePhase5Id(
                    "attribution decision id already exists with different content"
                )
            assessment_row = self._assessment_row(connection, assessment_id)
            if assessment_row is None:
                raise LookupError("attribution assessment is unavailable")
            if (
                decision.case_id != str(assessment_row["finding_id"])
                or decision.weight_profile_version != str(assessment_row["weight_profile_version"])
                or decision.decided_at_us < int(assessment_row["assessed_at_us"])
            ):
                raise ValueError("human attribution decision does not match its assessment")
            previous = self._latest_decision_row(connection, decision.case_id)
            previous_id = None if previous is None else str(previous["id"])
            if previous_id != expected_previous_decision_id:
                raise AttributionRevisionConflict("attribution decision revision conflict")
            revision = 1 if previous is None else int(previous["revision"]) + 1
            payload = self._decision_payload(
                assessment_id, decision, expected_previous_decision_id, revision
            )
            payload_sha256 = self._payload_sha256(payload)
            try:
                connection.execute(
                    insert(self.decisions).values(
                        id=decision_id,
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        finding_id=decision.case_id,
                        assessment_id=assessment_id,
                        state=decision.state.value,
                        actor_id=decision.actor_id,
                        decided_at_us=decision.decided_at_us,
                        weight_profile_version=decision.weight_profile_version,
                        supersedes_decision_id=expected_previous_decision_id,
                        revision=revision,
                        payload_sha256=payload_sha256,
                    )
                )
            except IntegrityError as error:
                raise AttributionRevisionConflict(
                    "attribution decision revision conflict"
                ) from error
        return self.get_decision(decision_id)

    def get_decision(self, decision_id: str) -> StoredAttributionDecision:
        validate_opaque_id(decision_id, "attribution decision id")
        with self.engine.connect() as connection:
            row = self._decision_row(connection, decision_id)
        if row is None:
            raise LookupError("attribution decision is unavailable")
        return self._stored_decision(row)

    def latest_decision(self, finding_id: str) -> StoredAttributionDecision | None:
        validate_opaque_id(finding_id, "finding id")
        with self.engine.connect() as connection:
            row = self._latest_decision_row(connection, finding_id)
        return None if row is None else self._stored_decision(row)

    def _checkpoint_evidence(
        self,
        connection: Connection,
        finding_ids: tuple[str, ...],
    ) -> dict[str, tuple[Phase5CheckpointEvidenceMaterial, ...]]:
        rows = (
            connection.execute(
                select(
                    self.finding_evidence.c.finding_id.label("linked_finding_id"),
                    self.finding_evidence.c.linked_at_us,
                    self.originals.c.id.label("artifact_id"),
                    self.originals.c.kind,
                    self.originals.c.content_sha256,
                    self.originals.c.captured_at_us,
                    self.originals.c.source_url,
                    self.originals.c.http_status,
                    self.originals.c.redirect_chain_json,
                    self.originals.c.masked_query_reference,
                    self.originals.c.provider_id,
                    self.originals.c.run_id,
                    self.originals.c.finding_id.label("primary_finding_id"),
                    self.originals.c.viewport_json,
                    self.originals.c.capture_method,
                    self.originals.c.metadata_json,
                )
                .join(
                    self.originals,
                    and_(
                        self.originals.c.vault_id == self.finding_evidence.c.vault_id,
                        self.originals.c.profile_id == self.finding_evidence.c.profile_id,
                        self.originals.c.id == self.finding_evidence.c.evidence_artifact_id,
                    ),
                )
                .where(
                    and_(
                        self.finding_evidence.c.vault_id == self.vault_id,
                        self.finding_evidence.c.profile_id == self.profile_id,
                        self.finding_evidence.c.finding_id.in_(finding_ids),
                    )
                )
                .order_by(
                    self.finding_evidence.c.finding_id,
                    self.originals.c.id,
                )
            )
            .mappings()
            .all()
        )
        artifact_ids = tuple(str(row["artifact_id"]) for row in rows)
        derivatives: dict[str, list[Phase5CheckpointDerivativeMaterial]] = {}
        if artifact_ids:
            derivative_rows = (
                connection.execute(
                    select(
                        self.derivatives.c.id,
                        self.derivatives.c.original_artifact_id,
                        self.derivatives.c.content_sha256,
                        self.derivatives.c.created_at_us,
                        self.derivatives.c.redaction_policy_version,
                        self.derivatives.c.redaction_summary_code,
                    )
                    .where(
                        and_(
                            self.derivatives.c.vault_id == self.vault_id,
                            self.derivatives.c.profile_id == self.profile_id,
                            self.derivatives.c.original_artifact_id.in_(artifact_ids),
                        )
                    )
                    .order_by(self.derivatives.c.original_artifact_id, self.derivatives.c.id)
                )
                .mappings()
                .all()
            )
            for row in derivative_rows:
                derivatives.setdefault(str(row["original_artifact_id"]), []).append(
                    Phase5CheckpointDerivativeMaterial(
                        derivative_id=str(row["id"]),
                        content_sha256=str(row["content_sha256"]),
                        created_at_us=int(row["created_at_us"]),
                        redaction_policy_version=str(row["redaction_policy_version"]),
                        redaction_summary_code=str(row["redaction_summary_code"]),
                    )
                )

        materials: dict[str, list[Phase5CheckpointEvidenceMaterial]] = {}
        for row in rows:
            artifact_id = str(row["artifact_id"])
            redirect_chain = json.loads(str(row["redirect_chain_json"]))
            viewport = (
                None if row["viewport_json"] is None else json.loads(str(row["viewport_json"]))
            )
            metadata = json.loads(str(row["metadata_json"]))
            if not isinstance(redirect_chain, list) or not isinstance(metadata, list):
                raise RuntimeError("stored checkpoint evidence metadata is invalid")
            try:
                sorted_metadata = sorted(
                    (str(item["key"]), str(item["value"])) for item in metadata
                )
            except (KeyError, TypeError) as error:
                raise RuntimeError("stored checkpoint evidence metadata is invalid") from error
            material = Phase5CheckpointEvidenceMaterial(
                artifact_id=artifact_id,
                kind=str(row["kind"]),
                content_sha256=str(row["content_sha256"]),
                captured_at_us=int(row["captured_at_us"]),
                source_url_sha256=self._checkpoint_optional_text_hash(row["source_url"]),
                http_status=None if row["http_status"] is None else int(row["http_status"]),
                redirect_count=len(redirect_chain),
                redirect_chain_sha256=self._checkpoint_hash(redirect_chain),
                masked_query_reference_sha256=self._checkpoint_optional_text_hash(
                    row["masked_query_reference"]
                ),
                provider_id=str(row["provider_id"]),
                run_id=str(row["run_id"]),
                primary_finding_id=(
                    None if row["primary_finding_id"] is None else str(row["primary_finding_id"])
                ),
                viewport_sha256=(None if viewport is None else self._checkpoint_hash(viewport)),
                capture_method=str(row["capture_method"]),
                metadata_sha256=self._checkpoint_hash(sorted_metadata),
                linked_at_us=int(row["linked_at_us"]),
                derivatives=tuple(derivatives.get(artifact_id, ())),
            )
            materials.setdefault(str(row["linked_finding_id"]), []).append(material)
        return {key: tuple(value) for key, value in materials.items()}

    def _latest_checkpoint_assessments(
        self,
        connection: Connection,
        finding_ids: tuple[str, ...],
    ) -> dict[str, StoredAttributionAssessment]:
        rows = (
            connection.execute(
                select(self.assessments)
                .where(
                    and_(
                        self.assessments.c.vault_id == self.vault_id,
                        self.assessments.c.profile_id == self.profile_id,
                        self.assessments.c.finding_id.in_(finding_ids),
                    )
                )
                .order_by(
                    self.assessments.c.finding_id,
                    self.assessments.c.assessed_at_us.desc(),
                    self.assessments.c.id.desc(),
                )
            )
            .mappings()
            .all()
        )
        latest: dict[str, StoredAttributionAssessment] = {}
        for row in rows:
            finding_id = str(row["finding_id"])
            if finding_id not in latest:
                latest[finding_id] = self._stored_assessment(connection, row)
        return latest

    def _latest_checkpoint_decisions(
        self,
        connection: Connection,
        finding_ids: tuple[str, ...],
    ) -> dict[str, StoredAttributionDecision]:
        rows = (
            connection.execute(
                select(self.decisions)
                .where(
                    and_(
                        self.decisions.c.vault_id == self.vault_id,
                        self.decisions.c.profile_id == self.profile_id,
                        self.decisions.c.finding_id.in_(finding_ids),
                    )
                )
                .order_by(
                    self.decisions.c.finding_id,
                    self.decisions.c.revision.desc(),
                )
            )
            .mappings()
            .all()
        )
        latest: dict[str, StoredAttributionDecision] = {}
        for row in rows:
            finding_id = str(row["finding_id"])
            if finding_id not in latest:
                latest[finding_id] = self._stored_decision(row)
        return latest

    @staticmethod
    def _checkpoint_hash(value: object) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _checkpoint_optional_text_hash(cls, value: object | None) -> str | None:
        return None if value is None else cls._checkpoint_hash(str(value))

    def _finding_row(self, connection: Connection, finding_id: str) -> RowMapping | None:
        return (
            connection.execute(
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

    def _assessment_row(self, connection: Connection, assessment_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.assessments).where(
                    and_(
                        self.assessments.c.vault_id == self.vault_id,
                        self.assessments.c.profile_id == self.profile_id,
                        self.assessments.c.id == assessment_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    def _decision_row(self, connection: Connection, decision_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.decisions).where(
                    and_(
                        self.decisions.c.vault_id == self.vault_id,
                        self.decisions.c.profile_id == self.profile_id,
                        self.decisions.c.id == decision_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    def _latest_decision_row(self, connection: Connection, finding_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.decisions)
                .where(
                    and_(
                        self.decisions.c.vault_id == self.vault_id,
                        self.decisions.c.profile_id == self.profile_id,
                        self.decisions.c.finding_id == finding_id,
                    )
                )
                .order_by(self.decisions.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def _evidence_is_linked(
        self,
        connection: Connection,
        artifact_id: str,
        finding_id: str,
    ) -> bool:
        return (
            connection.execute(
                select(self.finding_evidence.c.evidence_artifact_id).where(
                    and_(
                        self.finding_evidence.c.vault_id == self.vault_id,
                        self.finding_evidence.c.profile_id == self.profile_id,
                        self.finding_evidence.c.finding_id == finding_id,
                        self.finding_evidence.c.evidence_artifact_id == artifact_id,
                    )
                )
            ).scalar_one_or_none()
            is not None
        )

    def _insert_signal(
        self,
        connection: Connection,
        *,
        assessment_id: str,
        polarity: str,
        ordinal: int,
        signal_type: str,
        weight: int,
        evidence_references: tuple[str, ...],
    ) -> None:
        connection.execute(
            insert(self.signals).values(
                vault_id=self.vault_id,
                profile_id=self.profile_id,
                assessment_id=assessment_id,
                polarity=polarity,
                ordinal=ordinal,
                signal_type=signal_type,
                weight=weight,
            )
        )
        for evidence_ordinal, reference in enumerate(evidence_references):
            connection.execute(
                insert(self.signal_evidence).values(
                    vault_id=self.vault_id,
                    profile_id=self.profile_id,
                    assessment_id=assessment_id,
                    polarity=polarity,
                    signal_ordinal=ordinal,
                    evidence_ordinal=evidence_ordinal,
                    evidence_artifact_id=reference,
                )
            )

    def _stored_assessment(
        self,
        connection: Connection,
        row: RowMapping,
    ) -> StoredAttributionAssessment:
        signal_rows = (
            connection.execute(
                select(self.signals)
                .where(
                    and_(
                        self.signals.c.vault_id == self.vault_id,
                        self.signals.c.profile_id == self.profile_id,
                        self.signals.c.assessment_id == row["id"],
                    )
                )
                .order_by(self.signals.c.polarity, self.signals.c.ordinal)
            )
            .mappings()
            .all()
        )
        evidence_rows = (
            connection.execute(
                select(self.signal_evidence)
                .where(
                    and_(
                        self.signal_evidence.c.vault_id == self.vault_id,
                        self.signal_evidence.c.profile_id == self.profile_id,
                        self.signal_evidence.c.assessment_id == row["id"],
                    )
                )
                .order_by(
                    self.signal_evidence.c.polarity,
                    self.signal_evidence.c.signal_ordinal,
                    self.signal_evidence.c.evidence_ordinal,
                )
            )
            .mappings()
            .all()
        )
        references: dict[tuple[str, int], list[str]] = {}
        for evidence in evidence_rows:
            references.setdefault(
                (str(evidence["polarity"]), int(evidence["signal_ordinal"])), []
            ).append(str(evidence["evidence_artifact_id"]))
        contributing: list[PositiveSignalContribution] = []
        contradictions: list[NegativeSignalContribution] = []
        for signal in signal_rows:
            key = (str(signal["polarity"]), int(signal["ordinal"]))
            if key[0] == "SUPPORTS":
                contributing.append(
                    PositiveSignalContribution(
                        signal=PositiveAttributionSignal(str(signal["signal_type"])),
                        weight=int(signal["weight"]),
                        evidence_references=tuple(references.get(key, ())),
                    )
                )
            else:
                contradictions.append(
                    NegativeSignalContribution(
                        signal=NegativeAttributionSignal(str(signal["signal_type"])),
                        penalty=int(signal["weight"]),
                        evidence_references=tuple(references.get(key, ())),
                    )
                )
        missing_rows = (
            connection.execute(
                select(self.missing)
                .where(
                    and_(
                        self.missing.c.vault_id == self.vault_id,
                        self.missing.c.profile_id == self.profile_id,
                        self.missing.c.assessment_id == row["id"],
                    )
                )
                .order_by(self.missing.c.signal_type)
            )
            .mappings()
            .all()
        )
        missing = tuple(
            MissingEvidence(
                signal=PositiveAttributionSignal(str(item["signal_type"])),
                potential_weight=int(item["potential_weight"]),
            )
            for item in missing_rows
        )
        recommended = tuple(
            PositiveAttributionSignal(str(item["signal_type"]))
            for item in sorted(
                (item for item in missing_rows if item["recommended_rank"] is not None),
                key=lambda item: int(item["recommended_rank"]),
            )
        )
        assessment = AttributionAssessment(
            case_id=str(row["finding_id"]),
            weight_profile_version=str(row["weight_profile_version"]),
            score=int(row["score"]),
            contributing_signals=tuple(contributing),
            contradictions=tuple(contradictions),
            missing_evidence=missing,
            confidence_band=AttributionConfidenceBand(str(row["confidence_band"])),
            recommended_next_evidence=recommended,
            human_review_required=bool(row["human_review_required"]),
        )
        expected = str(row["payload_sha256"])
        if self._payload_sha256(self._assessment_payload(assessment)) != expected:
            raise RuntimeError("stored attribution assessment integrity check failed")
        return StoredAttributionAssessment(
            assessment_id=str(row["id"]),
            finding_id=str(row["finding_id"]),
            assessment=assessment,
            assessed_at_us=int(row["assessed_at_us"]),
            payload_sha256=expected,
        )

    def _stored_decision(self, row: RowMapping) -> StoredAttributionDecision:
        decision = HumanAttributionDecision(
            case_id=str(row["finding_id"]),
            state=HumanAttributionState(str(row["state"])),
            actor_id=str(row["actor_id"]),
            decided_at_us=int(row["decided_at_us"]),
            weight_profile_version=str(row["weight_profile_version"]),
        )
        expected = str(row["payload_sha256"])
        payload = self._decision_payload(
            str(row["assessment_id"]),
            decision,
            None if row["supersedes_decision_id"] is None else str(row["supersedes_decision_id"]),
            int(row["revision"]),
        )
        if self._payload_sha256(payload) != expected:
            raise RuntimeError("stored attribution decision integrity check failed")
        return StoredAttributionDecision(
            decision_id=str(row["id"]),
            assessment_id=str(row["assessment_id"]),
            decision=decision,
            supersedes_decision_id=(
                None
                if row["supersedes_decision_id"] is None
                else str(row["supersedes_decision_id"])
            ),
            revision=int(row["revision"]),
            payload_sha256=expected,
        )

    @staticmethod
    def _stored_finding(row: RowMapping) -> StoredFinding:
        return StoredFinding(
            finding_id=str(row["id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            outcome=FindingOutcome(str(row["outcome"])),
            severity=FindingSeverity(str(row["severity"])),
            visibility=FindingVisibility(str(row["visibility"])),
            provider_id=str(row["provider_id"]),
            provider_label=str(row["provider_label"]),
            observed_at_us=int(row["observed_at_us"]),
            created_at_us=int(row["created_at_us"]),
            updated_at_us=int(row["updated_at_us"]),
            revision=int(row["revision"]),
        )

    @staticmethod
    def _draft_matches(stored: StoredFinding, draft: FindingDraft) -> bool:
        return (
            stored.finding_id == draft.finding_id
            and stored.title == draft.title
            and stored.summary == draft.summary
            and stored.outcome is draft.outcome
            and stored.severity is draft.severity
            and stored.visibility is draft.visibility
            and stored.provider_id == draft.provider_id
            and stored.provider_label == draft.provider_label
            and stored.observed_at_us == draft.observed_at_us
        )

    @staticmethod
    def _assessment_payload(assessment: AttributionAssessment) -> dict[str, object]:
        return {
            "caseId": assessment.case_id,
            "confidenceBand": assessment.confidence_band.value,
            "contradictions": [
                {
                    "evidence": list(item.evidence_references),
                    "penalty": item.penalty,
                    "signal": item.signal.value,
                }
                for item in assessment.contradictions
            ],
            "contributingSignals": [
                {
                    "evidence": list(item.evidence_references),
                    "signal": item.signal.value,
                    "weight": item.weight,
                }
                for item in assessment.contributing_signals
            ],
            "humanReviewRequired": assessment.human_review_required,
            "missingEvidence": [
                {"potentialWeight": item.potential_weight, "signal": item.signal.value}
                for item in assessment.missing_evidence
            ],
            "recommendedNextEvidence": [
                item.value for item in assessment.recommended_next_evidence
            ],
            "score": assessment.score,
            "weightProfileVersion": assessment.weight_profile_version,
        }

    @staticmethod
    def _decision_payload(
        assessment_id: str,
        decision: HumanAttributionDecision,
        supersedes_decision_id: str | None,
        revision: int,
    ) -> dict[str, object]:
        return {
            "actorId": decision.actor_id,
            "assessmentId": assessment_id,
            "caseId": decision.case_id,
            "decidedAtUs": decision.decided_at_us,
            "revision": revision,
            "state": decision.state.value,
            "supersedesDecisionId": supersedes_decision_id,
            "weightProfileVersion": decision.weight_profile_version,
        }

    @staticmethod
    def _payload_sha256(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if type(limit) is not int or limit < 1 or limit > 100:
            raise ValueError("Phase 5 result limit is invalid")
