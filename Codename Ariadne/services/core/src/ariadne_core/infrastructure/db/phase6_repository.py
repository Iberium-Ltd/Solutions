"""Durable immutable audit checkpoints and revisioned remediation history.

Audit snapshots are comparison projections of findings and coverage at a point
in time; they are not mutable execution records. Remediation changes append a
complete revision plus one matching history event so state cannot drift away
from the event that explains it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import MetaData, Table, and_, func, insert, select
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from ariadne_core.domain.audit_comparison import (
    MAX_SNAPSHOTS,
    AuditRunSnapshot,
    FindingSnapshot,
    ProviderCoverage,
    ProviderCoverageState,
    SnapshotRunState,
)
from ariadne_core.domain.remediation import (
    MAX_HISTORY_ENTRIES,
    ActionDisposition,
    ProviderResponse,
    RemediationAction,
    RemediationCase,
    RemediationEventType,
    RemediationHistoryEntry,
    RemediationStatus,
    validate_opaque_id,
)


class DuplicatePhase6Id(ValueError):
    """An immutable Phase 6 identity was replayed with different content."""


class AuditSnapshotCapacity(RuntimeError):
    """The bounded audit snapshot timeline has reached capacity."""


class AuditSnapshotOrderConflict(RuntimeError):
    """An audit snapshot does not append monotonically to its timeline."""


class RemediationPersistenceConflict(RuntimeError):
    """The expected remediation revision is no longer current."""


class Phase6IntegrityError(RuntimeError):
    """Persisted Phase 6 content does not match its integrity digest."""


@dataclass(frozen=True, slots=True)
class AuditSnapshotRecord:
    snapshot: AuditRunSnapshot
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class RemediationCaseRecord:
    case: RemediationCase
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class AuditRunSummary:
    run_id: str
    sequence: int
    captured_at_us: int
    run_state: SnapshotRunState
    finding_count: int
    provider_count: int


@dataclass(frozen=True, slots=True)
class RemediationCaseSummary:
    case_id: str
    finding_ids: tuple[str, ...]
    action: RemediationAction
    action_disposition: ActionDisposition
    status: RemediationStatus
    deadline_at_us: int | None
    reappearance_count: int
    revision: int
    created_at_us: int
    updated_at_us: int
    finding_count: int
    evidence_count: int
    provider_response_count: int


def _require_encrypted_profile(engine: Engine, vault_id: str, profile_id: str) -> None:
    validate_opaque_id(vault_id, "vault id")
    validate_opaque_id(profile_id, "profile id")
    with engine.connect() as connection:
        cipher = connection.exec_driver_sql("PRAGMA cipher_version").scalar_one_or_none()
        if not cipher:
            raise RuntimeError("Phase 6 durable storage requires an encrypted vault")
        profile = connection.exec_driver_sql(
            "SELECT 1 FROM profiles WHERE vault_id = ? AND id = ?",
            (vault_id, profile_id),
        ).scalar_one_or_none()
    if profile is None:
        raise LookupError("Phase 6 profile is unavailable")


def _payload_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_limit(limit: int, *, maximum: int = 100) -> None:
    if type(limit) is not int or limit < 1 or limit > maximum:
        raise ValueError("Phase 6 result limit is invalid")


class Phase6AuditRepository:
    """Append and replay bounded, person-scoped comparison checkpoints."""

    def __init__(
        self,
        engine: Engine,
        *,
        vault_id: str,
        profile_id: str,
        maximum_snapshots: int = MAX_SNAPSHOTS,
    ) -> None:
        if type(maximum_snapshots) is not int or not 2 <= maximum_snapshots <= MAX_SNAPSHOTS:
            raise ValueError("audit snapshot capacity is invalid")
        _require_encrypted_profile(engine, vault_id, profile_id)
        self.engine = engine
        self.vault_id = vault_id
        self.profile_id = profile_id
        self._maximum_snapshots = maximum_snapshots
        metadata = MetaData()
        self.snapshots = Table("phase6_audit_snapshots", metadata, autoload_with=engine)
        self.findings = Table("phase6_audit_snapshot_findings", metadata, autoload_with=engine)
        self.coverage = Table("phase6_audit_snapshot_coverage", metadata, autoload_with=engine)
        self.phase5_findings = Table("phase5_findings", metadata, autoload_with=engine)

    def persist_snapshot(self, snapshot: AuditRunSnapshot) -> AuditSnapshotRecord:
        """Append a snapshot or accept only an identical idempotent replay."""
        payload_sha256 = _payload_sha256(self._snapshot_payload(snapshot))
        with self.engine.begin() as connection:
            existing = self._snapshot_row(connection, snapshot.run_id)
            if existing is not None:
                record = self._record(connection, existing)
                if record.snapshot == snapshot:
                    return record
                raise DuplicatePhase6Id(
                    "audit run id already exists with different snapshot content"
                )

            count = int(
                connection.execute(
                    select(func.count()).select_from(self.snapshots).where(self._snapshot_scope())
                ).scalar_one()
            )
            if count >= self._maximum_snapshots:
                raise AuditSnapshotCapacity("audit snapshot capacity reached")

            last = (
                connection.execute(
                    select(self.snapshots.c.sequence, self.snapshots.c.captured_at_us)
                    .where(self._snapshot_scope())
                    .order_by(self.snapshots.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if last is not None and (
                snapshot.sequence <= int(last["sequence"])
                or snapshot.captured_at_us <= int(last["captured_at_us"])
            ):
                raise AuditSnapshotOrderConflict("audit snapshots must append in timeline order")

            self._require_finding_providers(connection, snapshot)
            try:
                connection.execute(
                    insert(self.snapshots).values(
                        vault_id=self.vault_id,
                        profile_id=self.profile_id,
                        run_id=snapshot.run_id,
                        sequence=snapshot.sequence,
                        captured_at_us=snapshot.captured_at_us,
                        run_state=snapshot.run_state.value,
                        payload_sha256=payload_sha256,
                    )
                )
                for ordinal, finding in enumerate(snapshot.findings):
                    connection.execute(
                        insert(self.findings).values(
                            vault_id=self.vault_id,
                            profile_id=self.profile_id,
                            run_id=snapshot.run_id,
                            ordinal=ordinal,
                            stable_id=finding.stable_id,
                            provider_id=finding.provider_id,
                            content_fingerprint=finding.content_fingerprint,
                        )
                    )
                for ordinal, coverage in enumerate(snapshot.provider_coverage):
                    connection.execute(
                        insert(self.coverage).values(
                            vault_id=self.vault_id,
                            profile_id=self.profile_id,
                            run_id=snapshot.run_id,
                            ordinal=ordinal,
                            provider_id=coverage.provider_id,
                            coverage_state=coverage.state.value,
                        )
                    )
            except IntegrityError as error:
                message = str(error).lower()
                if "capacity" in message:
                    raise AuditSnapshotCapacity("audit snapshot capacity reached") from error
                if "order conflict" in message or "snapshot_sequence" in message:
                    raise AuditSnapshotOrderConflict(
                        "audit snapshots must append in timeline order"
                    ) from error
                raise DuplicatePhase6Id("audit snapshot identity conflict") from error
        return self.get_snapshot(snapshot.run_id)

    def get_snapshot(self, run_id: str) -> AuditSnapshotRecord:
        validate_opaque_id(run_id, "audit run id")
        with self.engine.connect() as connection:
            row = self._snapshot_row(connection, run_id)
            if row is None:
                raise LookupError("audit snapshot is unavailable")
            return self._record(connection, row)

    def list_timeline(self, *, limit: int = MAX_SNAPSHOTS) -> tuple[AuditRunSnapshot, ...]:
        _validate_limit(limit, maximum=MAX_SNAPSHOTS)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.snapshots)
                    .where(self._snapshot_scope())
                    .order_by(self.snapshots.c.sequence.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            records = tuple(self._record(connection, row).snapshot for row in reversed(rows))
        return records

    def list_run_summaries(self, *, limit: int = MAX_SNAPSHOTS) -> tuple[AuditRunSummary, ...]:
        _validate_limit(limit, maximum=MAX_SNAPSHOTS)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.snapshots)
                    .where(self._snapshot_scope())
                    .order_by(self.snapshots.c.sequence.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return tuple(self._summary(connection, row) for row in rows)

    def list_timeline_through(
        self,
        run_id: str,
        *,
        limit: int = MAX_SNAPSHOTS,
    ) -> tuple[AuditRunSnapshot, ...]:
        validate_opaque_id(run_id, "audit run id")
        _validate_limit(limit, maximum=MAX_SNAPSHOTS)
        with self.engine.connect() as connection:
            target = self._snapshot_row(connection, run_id)
            if target is None:
                raise LookupError("audit snapshot is unavailable")
            rows = (
                connection.execute(
                    select(self.snapshots)
                    .where(
                        and_(
                            self._snapshot_scope(),
                            self.snapshots.c.sequence <= int(target["sequence"]),
                        )
                    )
                    .order_by(self.snapshots.c.sequence.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return tuple(self._record(connection, row).snapshot for row in reversed(rows))

    def comparison_timeline(
        self,
        baseline_run_id: str,
        current_run_id: str,
    ) -> tuple[AuditRunSnapshot, ...]:
        """Return the complete persisted interval needed for lifecycle analysis."""
        validate_opaque_id(baseline_run_id, "baseline audit run id")
        validate_opaque_id(current_run_id, "current audit run id")
        if baseline_run_id == current_run_id:
            raise ValueError("audit comparison run ids must differ")
        with self.engine.connect() as connection:
            baseline = self._snapshot_row(connection, baseline_run_id)
            current = self._snapshot_row(connection, current_run_id)
            if baseline is None or current is None:
                raise LookupError("audit comparison snapshot is unavailable")
            if int(baseline["sequence"]) >= int(current["sequence"]) or int(
                baseline["captured_at_us"]
            ) >= int(current["captured_at_us"]):
                raise ValueError("audit comparison run order is invalid")
            rows = (
                connection.execute(
                    select(self.snapshots)
                    .where(
                        and_(
                            self._snapshot_scope(),
                            self.snapshots.c.sequence <= int(current["sequence"]),
                        )
                    )
                    .order_by(self.snapshots.c.sequence)
                    .limit(MAX_SNAPSHOTS)
                )
                .mappings()
                .all()
            )
            timeline = tuple(self._record(connection, row).snapshot for row in rows)
            if baseline_run_id not in {item.run_id for item in timeline}:
                raise AuditSnapshotCapacity("audit comparison history is outside capacity")
            return timeline

    def count_snapshots(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count()).select_from(self.snapshots).where(self._snapshot_scope())
                ).scalar_one()
            )

    def next_snapshot_position(self, wall_time_us: int) -> tuple[int, int]:
        """Return the next bounded sequence and a monotonic capture time.

        Wall clocks can repeat or move backwards. Ordering therefore advances
        from the last durable timestamp instead of trusting the current clock.
        """

        if (
            type(wall_time_us) is not int
            or wall_time_us < 1
            or wall_time_us > 9_007_199_254_740_991
        ):
            raise ValueError("audit snapshot wall time is invalid")
        with self.engine.connect() as connection:
            count = int(
                connection.execute(
                    select(func.count()).select_from(self.snapshots).where(self._snapshot_scope())
                ).scalar_one()
            )
            if count >= self._maximum_snapshots:
                raise AuditSnapshotCapacity("audit snapshot capacity reached")
            last = (
                connection.execute(
                    select(self.snapshots.c.sequence, self.snapshots.c.captured_at_us)
                    .where(self._snapshot_scope())
                    .order_by(self.snapshots.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if last is None:
            return 1, wall_time_us
        sequence = int(last["sequence"]) + 1
        captured_at_us = max(wall_time_us, int(last["captured_at_us"]) + 1)
        if captured_at_us > 9_007_199_254_740_991:
            raise AuditSnapshotOrderConflict("audit snapshot time capacity reached")
        return sequence, captured_at_us

    def _snapshot_scope(self) -> ColumnElement[bool]:
        return and_(
            self.snapshots.c.vault_id == self.vault_id,
            self.snapshots.c.profile_id == self.profile_id,
        )

    def _snapshot_row(self, connection: Connection, run_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.snapshots).where(
                    and_(self._snapshot_scope(), self.snapshots.c.run_id == run_id)
                )
            )
            .mappings()
            .one_or_none()
        )

    def _require_finding_providers(
        self,
        connection: Connection,
        snapshot: AuditRunSnapshot,
    ) -> None:
        if not snapshot.findings:
            return
        stable_ids = tuple(item.stable_id for item in snapshot.findings)
        rows = connection.execute(
            select(self.phase5_findings.c.id, self.phase5_findings.c.provider_id).where(
                and_(
                    self.phase5_findings.c.vault_id == self.vault_id,
                    self.phase5_findings.c.profile_id == self.profile_id,
                    self.phase5_findings.c.id.in_(stable_ids),
                )
            )
        ).all()
        providers = {str(row[0]): str(row[1]) for row in rows}
        if any(providers.get(item.stable_id) != item.provider_id for item in snapshot.findings):
            raise LookupError("audit snapshot finding is unavailable in this profile")

    def _record(self, connection: Connection, row: RowMapping) -> AuditSnapshotRecord:
        run_id = str(row["run_id"])
        finding_rows = (
            connection.execute(
                select(self.findings)
                .where(
                    and_(
                        self.findings.c.vault_id == self.vault_id,
                        self.findings.c.profile_id == self.profile_id,
                        self.findings.c.run_id == run_id,
                    )
                )
                .order_by(self.findings.c.ordinal)
            )
            .mappings()
            .all()
        )
        coverage_rows = (
            connection.execute(
                select(self.coverage)
                .where(
                    and_(
                        self.coverage.c.vault_id == self.vault_id,
                        self.coverage.c.profile_id == self.profile_id,
                        self.coverage.c.run_id == run_id,
                    )
                )
                .order_by(self.coverage.c.ordinal)
            )
            .mappings()
            .all()
        )
        snapshot = AuditRunSnapshot(
            run_id=run_id,
            sequence=int(row["sequence"]),
            captured_at_us=int(row["captured_at_us"]),
            run_state=SnapshotRunState(str(row["run_state"])),
            findings=tuple(
                FindingSnapshot(
                    stable_id=str(item["stable_id"]),
                    provider_id=str(item["provider_id"]),
                    content_fingerprint=str(item["content_fingerprint"]),
                )
                for item in finding_rows
            ),
            provider_coverage=tuple(
                ProviderCoverage(
                    provider_id=str(item["provider_id"]),
                    state=ProviderCoverageState(str(item["coverage_state"])),
                )
                for item in coverage_rows
            ),
        )
        expected = str(row["payload_sha256"])
        if _payload_sha256(self._snapshot_payload(snapshot)) != expected:
            raise Phase6IntegrityError("audit snapshot integrity verification failed")
        return AuditSnapshotRecord(snapshot=snapshot, payload_sha256=expected)

    def _summary(self, connection: Connection, row: RowMapping) -> AuditRunSummary:
        run_id = str(row["run_id"])
        child_scope = and_(
            self.findings.c.vault_id == self.vault_id,
            self.findings.c.profile_id == self.profile_id,
            self.findings.c.run_id == run_id,
        )
        coverage_scope = and_(
            self.coverage.c.vault_id == self.vault_id,
            self.coverage.c.profile_id == self.profile_id,
            self.coverage.c.run_id == run_id,
        )
        finding_count = int(
            connection.execute(
                select(func.count()).select_from(self.findings).where(child_scope)
            ).scalar_one()
        )
        provider_count = int(
            connection.execute(
                select(func.count()).select_from(self.coverage).where(coverage_scope)
            ).scalar_one()
        )
        return AuditRunSummary(
            run_id=run_id,
            sequence=int(row["sequence"]),
            captured_at_us=int(row["captured_at_us"]),
            run_state=SnapshotRunState(str(row["run_state"])),
            finding_count=finding_count,
            provider_count=provider_count,
        )

    @staticmethod
    def _snapshot_payload(snapshot: AuditRunSnapshot) -> dict[str, object]:
        return {
            "capturedAtUs": snapshot.captured_at_us,
            "findings": [
                {
                    "contentFingerprint": item.content_fingerprint,
                    "providerId": item.provider_id,
                    "stableId": item.stable_id,
                }
                for item in snapshot.findings
            ],
            "providerCoverage": [
                {"providerId": item.provider_id, "state": item.state.value}
                for item in snapshot.provider_coverage
            ],
            "runId": snapshot.run_id,
            "runState": snapshot.run_state.value,
            "sequence": snapshot.sequence,
        }


class Phase6RemediationRepository:
    """Persist complete remediation revisions and one immutable history event per revision."""

    def __init__(self, engine: Engine, *, vault_id: str, profile_id: str) -> None:
        _require_encrypted_profile(engine, vault_id, profile_id)
        self.engine = engine
        self.vault_id = vault_id
        self.profile_id = profile_id
        metadata = MetaData()
        self.revisions = Table("phase6_remediation_revisions", metadata, autoload_with=engine)
        self.findings = Table("phase6_remediation_findings", metadata, autoload_with=engine)
        self.evidence = Table("phase6_remediation_evidence", metadata, autoload_with=engine)
        self.responses = Table(
            "phase6_remediation_provider_responses", metadata, autoload_with=engine
        )
        self.response_evidence = Table(
            "phase6_remediation_provider_response_evidence", metadata, autoload_with=engine
        )
        self.history = Table("phase6_remediation_history", metadata, autoload_with=engine)
        self.history_evidence = Table(
            "phase6_remediation_history_evidence", metadata, autoload_with=engine
        )
        self.phase5_findings = Table("phase5_findings", metadata, autoload_with=engine)
        self.phase5_evidence = Table("phase5_evidence_originals", metadata, autoload_with=engine)

    def persist_case(
        self,
        case: RemediationCase,
        *,
        expected_previous_revision: int | None,
    ) -> RemediationCaseRecord:
        """Append exactly one CAS-checked case revision and its history event."""
        if expected_previous_revision is not None and (
            type(expected_previous_revision) is not int
            or expected_previous_revision < 1
            or expected_previous_revision >= MAX_HISTORY_ENTRIES
        ):
            raise ValueError("expected remediation revision is invalid")
        payload_sha256 = _payload_sha256(self._case_payload(case))
        with self.engine.begin() as connection:
            existing = self._revision_row(connection, case.case_id, case.revision)
            if existing is not None:
                record = self._record(connection, existing)
                if record.case == case:
                    return record
                raise DuplicatePhase6Id("remediation case revision exists with different content")

            latest_row = self._latest_revision_row(connection, case.case_id)
            if latest_row is None:
                if case.revision != 1 or expected_previous_revision is not None:
                    raise RemediationPersistenceConflict(
                        "remediation case creation revision conflict"
                    )
            else:
                latest = self._record(connection, latest_row).case
                if (
                    expected_previous_revision != latest.revision
                    or case.revision != latest.revision + 1
                ):
                    raise RemediationPersistenceConflict("remediation case revision conflict")
                if (
                    case.case_id != latest.case_id
                    or case.action is not latest.action
                    or case.created_at_us != latest.created_at_us
                    or case.history[:-1] != latest.history
                ):
                    raise RemediationPersistenceConflict(
                        "remediation case history continuity conflict"
                    )
                self._require_revision_delta(latest, case)

            self._require_profile_references(connection, case)
            try:
                self._insert_revision(connection, case, payload_sha256)
            except IntegrityError as error:
                raise RemediationPersistenceConflict(
                    "remediation case revision conflict"
                ) from error
        return self.get_case(case.case_id, revision=case.revision)

    def get_case(
        self,
        case_id: str,
        *,
        revision: int | None = None,
    ) -> RemediationCaseRecord:
        validate_opaque_id(case_id, "remediation case id")
        if revision is not None and (
            type(revision) is not int or revision < 1 or revision > MAX_HISTORY_ENTRIES
        ):
            raise ValueError("remediation revision is invalid")
        with self.engine.connect() as connection:
            row = (
                self._latest_revision_row(connection, case_id)
                if revision is None
                else self._revision_row(connection, case_id, revision)
            )
            if row is None:
                raise LookupError("remediation case is unavailable")
            return self._record(connection, row)

    def list_cases(self, *, limit: int = 100) -> tuple[RemediationCaseRecord, ...]:
        _validate_limit(limit)
        latest = (
            select(
                self.revisions.c.case_id.label("case_id"),
                func.max(self.revisions.c.revision).label("revision"),
            )
            .where(self._revision_scope())
            .group_by(self.revisions.c.case_id)
            .subquery()
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.revisions)
                    .join(
                        latest,
                        and_(
                            self.revisions.c.case_id == latest.c.case_id,
                            self.revisions.c.revision == latest.c.revision,
                        ),
                    )
                    .where(self._revision_scope())
                    .order_by(
                        self.revisions.c.updated_at_us.desc(), self.revisions.c.case_id.desc()
                    )
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return tuple(self._record(connection, row) for row in rows)

    def list_case_summaries(self, *, limit: int = 100) -> tuple[RemediationCaseSummary, ...]:
        _validate_limit(limit)
        with self.engine.connect() as connection:
            rows = self._latest_rows(connection, limit)
            return tuple(self._summary(connection, row) for row in rows)

    def count_cases(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count(func.distinct(self.revisions.c.case_id))).where(
                        self._revision_scope()
                    )
                ).scalar_one()
            )

    def _revision_scope(self) -> ColumnElement[bool]:
        return and_(
            self.revisions.c.vault_id == self.vault_id,
            self.revisions.c.profile_id == self.profile_id,
        )

    def _revision_row(
        self,
        connection: Connection,
        case_id: str,
        revision: int,
    ) -> RowMapping | None:
        return (
            connection.execute(
                select(self.revisions).where(
                    and_(
                        self._revision_scope(),
                        self.revisions.c.case_id == case_id,
                        self.revisions.c.revision == revision,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    def _latest_revision_row(self, connection: Connection, case_id: str) -> RowMapping | None:
        return (
            connection.execute(
                select(self.revisions)
                .where(
                    and_(
                        self._revision_scope(),
                        self.revisions.c.case_id == case_id,
                    )
                )
                .order_by(self.revisions.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )

    def _latest_rows(self, connection: Connection, limit: int) -> tuple[RowMapping, ...]:
        latest = (
            select(
                self.revisions.c.case_id.label("case_id"),
                func.max(self.revisions.c.revision).label("revision"),
            )
            .where(self._revision_scope())
            .group_by(self.revisions.c.case_id)
            .subquery()
        )
        rows = (
            connection.execute(
                select(self.revisions)
                .join(
                    latest,
                    and_(
                        self.revisions.c.case_id == latest.c.case_id,
                        self.revisions.c.revision == latest.c.revision,
                    ),
                )
                .where(self._revision_scope())
                .order_by(self.revisions.c.updated_at_us.desc(), self.revisions.c.case_id.desc())
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return tuple(rows)

    def _require_profile_references(
        self,
        connection: Connection,
        case: RemediationCase,
    ) -> None:
        finding_ids = set(case.finding_ids)
        stored_finding_ids = {
            str(row[0])
            for row in connection.execute(
                select(self.phase5_findings.c.id).where(
                    and_(
                        self.phase5_findings.c.vault_id == self.vault_id,
                        self.phase5_findings.c.profile_id == self.profile_id,
                        self.phase5_findings.c.id.in_(tuple(finding_ids)),
                    )
                )
            ).all()
        }
        if stored_finding_ids != finding_ids:
            raise LookupError("remediation finding is unavailable in this profile")

        nested_evidence = {
            reference
            for response in case.provider_responses
            for reference in response.evidence_references
        } | {reference for event in case.history for reference in event.evidence_references}
        evidence_ids = set(case.evidence_references)
        if not nested_evidence <= evidence_ids:
            raise ValueError("remediation nested evidence is not linked to the case")
        if not evidence_ids:
            return
        stored_evidence_ids = {
            str(row[0])
            for row in connection.execute(
                select(self.phase5_evidence.c.id).where(
                    and_(
                        self.phase5_evidence.c.vault_id == self.vault_id,
                        self.phase5_evidence.c.profile_id == self.profile_id,
                        self.phase5_evidence.c.id.in_(tuple(evidence_ids)),
                    )
                )
            ).all()
        }
        if stored_evidence_ids != evidence_ids:
            raise LookupError("remediation evidence is unavailable in this profile")

    @staticmethod
    def _require_revision_delta(previous: RemediationCase, current: RemediationCase) -> None:
        # Each allowed state delta must match the single new history event. This
        # prevents a caller from smuggling unrelated edits into an otherwise
        # valid revision increment.
        event_type = current.history[-1].event_type
        if not set(previous.finding_ids) <= set(current.finding_ids):
            raise RemediationPersistenceConflict("remediation finding history is not append-only")
        if not set(previous.evidence_references) <= set(current.evidence_references):
            raise RemediationPersistenceConflict("remediation evidence history is not append-only")
        if current.provider_responses[: len(previous.provider_responses)] != (
            previous.provider_responses
        ):
            raise RemediationPersistenceConflict("remediation response history is not append-only")

        finding_changed = current.finding_ids != previous.finding_ids
        evidence_changed = current.evidence_references != previous.evidence_references
        responses_changed = current.provider_responses != previous.provider_responses
        reappearance_changed = (
            current.reappearance_count != previous.reappearance_count
            or current.last_reappearance_at_us != previous.last_reappearance_at_us
        )
        if finding_changed and event_type is not RemediationEventType.REAPPEARANCE_RECORDED:
            raise RemediationPersistenceConflict("remediation finding change lacks history")
        if evidence_changed and event_type not in {
            RemediationEventType.EVIDENCE_LINKED,
            RemediationEventType.PROVIDER_RESPONSE_RECORDED,
            RemediationEventType.REAPPEARANCE_RECORDED,
        }:
            raise RemediationPersistenceConflict("remediation evidence change lacks history")
        if responses_changed and event_type is not RemediationEventType.PROVIDER_RESPONSE_RECORDED:
            raise RemediationPersistenceConflict("remediation response change lacks history")
        if event_type is RemediationEventType.PROVIDER_RESPONSE_RECORDED and (
            len(current.provider_responses) != len(previous.provider_responses) + 1
        ):
            raise RemediationPersistenceConflict("remediation response revision is inconsistent")
        if reappearance_changed:
            if (
                event_type is not RemediationEventType.REAPPEARANCE_RECORDED
                or current.reappearance_count != previous.reappearance_count + 1
                or current.last_reappearance_at_us != current.updated_at_us
            ):
                raise RemediationPersistenceConflict(
                    "remediation reappearance revision is inconsistent"
                )
        elif event_type is RemediationEventType.REAPPEARANCE_RECORDED:
            raise RemediationPersistenceConflict("remediation reappearance history lacks state")

        if (
            current.draft_text != previous.draft_text
            and event_type is not RemediationEventType.DRAFT_UPDATED
        ):
            raise RemediationPersistenceConflict("remediation draft revision is inconsistent")
        if (current.deadline_at_us != previous.deadline_at_us) != (
            event_type is RemediationEventType.DEADLINE_CHANGED
        ):
            raise RemediationPersistenceConflict("remediation deadline revision is inconsistent")
        if current.action_disposition is not previous.action_disposition and (
            event_type is not RemediationEventType.APPROVAL_REQUIRED
        ):
            raise RemediationPersistenceConflict("remediation disposition change lacks history")
        if (
            event_type
            in {
                RemediationEventType.DEADLINE_CHANGED,
                RemediationEventType.EVIDENCE_LINKED,
            }
            and current.status is not previous.status
        ):
            raise RemediationPersistenceConflict("remediation status change is inconsistent")

    def _insert_revision(
        self,
        connection: Connection,
        case: RemediationCase,
        payload_sha256: str,
    ) -> None:
        values = self._case_scope(case.case_id, case.revision)
        connection.execute(
            insert(self.revisions).values(
                **values,
                previous_revision=None if case.revision == 1 else case.revision - 1,
                action=case.action.value,
                action_disposition=case.action_disposition.value,
                status=case.status.value,
                deadline_at_us=case.deadline_at_us,
                draft_text=case.draft_text,
                reappearance_count=case.reappearance_count,
                last_reappearance_at_us=case.last_reappearance_at_us,
                created_at_us=case.created_at_us,
                updated_at_us=case.updated_at_us,
                payload_sha256=payload_sha256,
            )
        )
        for ordinal, finding_id in enumerate(case.finding_ids):
            connection.execute(
                insert(self.findings).values(**values, ordinal=ordinal, finding_id=finding_id)
            )
        for ordinal, evidence_id in enumerate(case.evidence_references):
            connection.execute(
                insert(self.evidence).values(
                    **values,
                    ordinal=ordinal,
                    evidence_artifact_id=evidence_id,
                )
            )
        for response_ordinal, response in enumerate(case.provider_responses):
            connection.execute(
                insert(self.responses).values(
                    **values,
                    ordinal=response_ordinal,
                    provider_id=response.provider_id,
                    response_code=response.response_code,
                    summary=response.summary,
                    received_at_us=response.received_at_us,
                )
            )
            for evidence_ordinal, evidence_id in enumerate(response.evidence_references):
                connection.execute(
                    insert(self.response_evidence).values(
                        **values,
                        response_ordinal=response_ordinal,
                        evidence_ordinal=evidence_ordinal,
                        evidence_artifact_id=evidence_id,
                    )
                )

        event = case.history[-1]
        connection.execute(
            insert(self.history).values(
                **values,
                event_type=event.event_type.value,
                actor_id=event.actor_id,
                occurred_at_us=event.occurred_at_us,
                previous_status=(
                    None if event.previous_status is None else event.previous_status.value
                ),
                current_status=event.current_status.value,
                detail_code=event.detail_code,
                subject_id=event.subject_id,
                note=event.note,
            )
        )
        for ordinal, evidence_id in enumerate(event.evidence_references):
            connection.execute(
                insert(self.history_evidence).values(
                    **values,
                    ordinal=ordinal,
                    evidence_artifact_id=evidence_id,
                )
            )

    def _record(self, connection: Connection, row: RowMapping) -> RemediationCaseRecord:
        case_id = str(row["case_id"])
        revision = int(row["revision"])
        scope = self._child_scope(case_id, revision)
        finding_rows = connection.execute(
            select(self.findings.c.finding_id)
            .where(scope(self.findings))
            .order_by(self.findings.c.ordinal)
        ).all()
        evidence_rows = connection.execute(
            select(self.evidence.c.evidence_artifact_id)
            .where(scope(self.evidence))
            .order_by(self.evidence.c.ordinal)
        ).all()
        response_rows = (
            connection.execute(
                select(self.responses)
                .where(scope(self.responses))
                .order_by(self.responses.c.ordinal)
            )
            .mappings()
            .all()
        )
        responses = tuple(
            ProviderResponse(
                provider_id=str(response["provider_id"]),
                response_code=str(response["response_code"]),
                summary=str(response["summary"]),
                received_at_us=int(response["received_at_us"]),
                evidence_references=self._response_evidence(
                    connection,
                    case_id,
                    revision,
                    int(response["ordinal"]),
                ),
            )
            for response in response_rows
        )
        history_rows = (
            connection.execute(
                select(self.history)
                .where(
                    and_(
                        self.history.c.vault_id == self.vault_id,
                        self.history.c.profile_id == self.profile_id,
                        self.history.c.case_id == case_id,
                        self.history.c.revision <= revision,
                    )
                )
                .order_by(self.history.c.revision)
            )
            .mappings()
            .all()
        )
        history = tuple(
            RemediationHistoryEntry(
                revision=int(event["revision"]),
                event_type=RemediationEventType(str(event["event_type"])),
                actor_id=str(event["actor_id"]),
                occurred_at_us=int(event["occurred_at_us"]),
                previous_status=(
                    None
                    if event["previous_status"] is None
                    else RemediationStatus(str(event["previous_status"]))
                ),
                current_status=RemediationStatus(str(event["current_status"])),
                detail_code=str(event["detail_code"]),
                subject_id=None if event["subject_id"] is None else str(event["subject_id"]),
                evidence_references=self._history_evidence(
                    connection,
                    case_id,
                    int(event["revision"]),
                ),
                note=None if event["note"] is None else str(event["note"]),
            )
            for event in history_rows
        )
        case = RemediationCase(
            case_id=case_id,
            finding_ids=tuple(str(item[0]) for item in finding_rows),
            action=RemediationAction(str(row["action"])),
            action_disposition=ActionDisposition(str(row["action_disposition"])),
            status=RemediationStatus(str(row["status"])),
            deadline_at_us=(None if row["deadline_at_us"] is None else int(row["deadline_at_us"])),
            draft_text=None if row["draft_text"] is None else str(row["draft_text"]),
            evidence_references=tuple(str(item[0]) for item in evidence_rows),
            provider_responses=responses,
            reappearance_count=int(row["reappearance_count"]),
            last_reappearance_at_us=(
                None
                if row["last_reappearance_at_us"] is None
                else int(row["last_reappearance_at_us"])
            ),
            revision=revision,
            created_at_us=int(row["created_at_us"]),
            updated_at_us=int(row["updated_at_us"]),
            history=history,
        )
        expected = str(row["payload_sha256"])
        if _payload_sha256(self._case_payload(case)) != expected:
            raise Phase6IntegrityError("remediation case integrity verification failed")
        return RemediationCaseRecord(case=case, payload_sha256=expected)

    def _summary(self, connection: Connection, row: RowMapping) -> RemediationCaseSummary:
        case_id = str(row["case_id"])
        revision = int(row["revision"])
        scope = self._child_scope(case_id, revision)

        def count(table: Table) -> int:
            return int(
                connection.execute(
                    select(func.count()).select_from(table).where(scope(table))
                ).scalar_one()
            )

        finding_ids = tuple(
            str(item[0])
            for item in connection.execute(
                select(self.findings.c.finding_id)
                .where(scope(self.findings))
                .order_by(self.findings.c.ordinal)
            ).all()
        )

        return RemediationCaseSummary(
            case_id=case_id,
            finding_ids=finding_ids,
            action=RemediationAction(str(row["action"])),
            action_disposition=ActionDisposition(str(row["action_disposition"])),
            status=RemediationStatus(str(row["status"])),
            deadline_at_us=(None if row["deadline_at_us"] is None else int(row["deadline_at_us"])),
            reappearance_count=int(row["reappearance_count"]),
            revision=revision,
            created_at_us=int(row["created_at_us"]),
            updated_at_us=int(row["updated_at_us"]),
            finding_count=len(finding_ids),
            evidence_count=count(self.evidence),
            provider_response_count=count(self.responses),
        )

    def _response_evidence(
        self,
        connection: Connection,
        case_id: str,
        revision: int,
        response_ordinal: int,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            select(self.response_evidence.c.evidence_artifact_id)
            .where(
                and_(
                    self.response_evidence.c.vault_id == self.vault_id,
                    self.response_evidence.c.profile_id == self.profile_id,
                    self.response_evidence.c.case_id == case_id,
                    self.response_evidence.c.revision == revision,
                    self.response_evidence.c.response_ordinal == response_ordinal,
                )
            )
            .order_by(self.response_evidence.c.evidence_ordinal)
        ).all()
        return tuple(str(row[0]) for row in rows)

    def _history_evidence(
        self,
        connection: Connection,
        case_id: str,
        revision: int,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            select(self.history_evidence.c.evidence_artifact_id)
            .where(
                and_(
                    self.history_evidence.c.vault_id == self.vault_id,
                    self.history_evidence.c.profile_id == self.profile_id,
                    self.history_evidence.c.case_id == case_id,
                    self.history_evidence.c.revision == revision,
                )
            )
            .order_by(self.history_evidence.c.ordinal)
        ).all()
        return tuple(str(row[0]) for row in rows)

    def _case_scope(self, case_id: str, revision: int) -> dict[str, object]:
        return {
            "vault_id": self.vault_id,
            "profile_id": self.profile_id,
            "case_id": case_id,
            "revision": revision,
        }

    def _child_scope(
        self,
        case_id: str,
        revision: int,
    ) -> Callable[[Table], ColumnElement[bool]]:
        def scope(table: Table) -> ColumnElement[bool]:
            return and_(
                table.c.vault_id == self.vault_id,
                table.c.profile_id == self.profile_id,
                table.c.case_id == case_id,
                table.c.revision == revision,
            )

        return scope

    @staticmethod
    def _case_payload(case: RemediationCase) -> dict[str, object]:
        return {
            "action": case.action.value,
            "actionDisposition": case.action_disposition.value,
            "caseId": case.case_id,
            "createdAtUs": case.created_at_us,
            "deadlineAtUs": case.deadline_at_us,
            "draftText": case.draft_text,
            "evidenceReferences": list(case.evidence_references),
            "findingIds": list(case.finding_ids),
            "history": [
                {
                    "actorId": event.actor_id,
                    "currentStatus": event.current_status.value,
                    "detailCode": event.detail_code,
                    "eventType": event.event_type.value,
                    "evidenceReferences": list(event.evidence_references),
                    "note": event.note,
                    "occurredAtUs": event.occurred_at_us,
                    "previousStatus": (
                        None if event.previous_status is None else event.previous_status.value
                    ),
                    "revision": event.revision,
                    "subjectId": event.subject_id,
                }
                for event in case.history
            ],
            "lastReappearanceAtUs": case.last_reappearance_at_us,
            "providerResponses": [
                {
                    "evidenceReferences": list(response.evidence_references),
                    "providerId": response.provider_id,
                    "receivedAtUs": response.received_at_us,
                    "responseCode": response.response_code,
                    "summary": response.summary,
                }
                for response in case.provider_responses
            ],
            "reappearanceCount": case.reappearance_count,
            "revision": case.revision,
            "status": case.status.value,
            "updatedAtUs": case.updated_at_us,
        }
