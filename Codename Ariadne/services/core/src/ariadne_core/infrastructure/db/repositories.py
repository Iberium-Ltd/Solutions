"""Transactional job, settings, audit, and outbox persistence.

Mutations that change durable state append their redacted audit/outbox event in
the same transaction.  Workers may disappear at any point; leases, revisions,
attempts, and idempotency records are therefore the authority, while in-memory
queues and emitted UI events are replaceable projections.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import nullcontext
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, and_, delete, exists, func, insert, or_, select, text, update
from sqlalchemy.engine import Engine, RowMapping
from uuid6 import uuid7

from ariadne_core.domain.jobs import (
    TERMINAL_JOB_STATES,
    DependencyFailurePolicy,
    DependencyRequiredState,
    JobState,
    require_job_recovery_transition,
    require_job_transition,
)
from ariadne_core.domain.settings import VaultSettings, VaultSettingsPatch
from ariadne_core.infrastructure.db.models import (
    audit_events,
    event_outbox,
    event_stream_sessions,
    idempotency_records,
    job_attempts,
    job_dependencies,
    jobs,
    settings,
    vaults,
)

MAX_JOB_DEPENDENCIES = 64


def now_us() -> int:
    """Use one integer timestamp representation across persistence and optimistic concurrency."""

    return time.time_ns() // 1_000


def canonical_json(value: object) -> str:
    """Serialize persisted structured values deterministically for hashing and comparison."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class RevisionConflict(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


class LeaseConflict(RuntimeError):
    pass


class DependencyConflict(RuntimeError):
    pass


class JobManifest(BaseModel):
    """IDs and bounded local worker parameters only; no raw user payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str = Field(
        pattern=(
            r"^(NOOP|TEST_SLEEP|BACKUP|RESTORE_VERIFY|IMPORT_SCAFFOLD|"
            r"EXPORT_SCAFFOLD|INTAKE_EXTRACT)$"
        )
    )
    resource_ids: list[UUID] = Field(default_factory=list, max_length=64)
    duration_ms: int | None = Field(default=None, ge=1, le=5_000)
    input_digest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    values: VaultSettings
    revision: int


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    vault_id: str
    job_type: str
    state: JobState
    retry_count: int
    retry_limit: int
    revision: int
    manifest: JobManifest
    lease_owner: str | None
    lease_expires_at_us: int | None
    progress_micros: int


@dataclass(frozen=True, slots=True)
class EventRecord:
    event_id: str
    sequence: int
    event_type: str
    resource_type: str | None
    resource_id: str | None
    resource_revision: int | None


@dataclass(frozen=True, slots=True)
class EventReplay:
    disposition: str
    events: tuple[EventRecord, ...]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    requeued: int = 0
    paused: int = 0
    cancelled: int = 0
    failed: int = 0


def _append_event(
    connection: Connection,
    *,
    vault_id: str,
    event_type: str,
    target_type: str,
    target_id: str | None,
    resource_revision: int | None,
    metadata: dict[str, object],
) -> None:
    """Append audit history and the publishable event as one caller transaction.

    Callers must pass the connection that owns the resource mutation.  Opening a
    nested transaction here would permit either history or state to commit alone.
    Metadata is intentionally bounded, redacted context rather than source data.
    """
    timestamp = now_us()
    audit_id = str(uuid7())
    event_id = str(uuid7())
    metadata_json = canonical_json(metadata)
    audit_form = canonical_json(
        {
            "actorType": "LOCAL_USER",
            "eventType": event_type,
            "id": audit_id,
            "metadata": metadata,
            "occurredAtUs": timestamp,
            "targetId": target_id,
            "targetType": target_type,
            "vaultId": vault_id,
        }
    )
    connection.execute(
        insert(audit_events).values(
            id=audit_id,
            vault_id=vault_id,
            event_type=event_type,
            actor_type="LOCAL_USER",
            target_type=target_type,
            target_id=target_id,
            before_digest=None,
            after_digest=None,
            metadata_json=metadata_json,
            occurred_at_us=timestamp,
            previous_event_hash=None,
            event_hash=hashlib.sha256(audit_form.encode("utf-8")).hexdigest(),
        )
    )

    stream = (
        connection.execute(
            select(event_stream_sessions)
            .where(
                and_(
                    event_stream_sessions.c.vault_id == vault_id,
                    event_stream_sessions.c.closed_at_us.is_(None),
                )
            )
            .order_by(event_stream_sessions.c.started_at_us.desc())
            .limit(1)
        )
        .mappings()
        .one()
    )
    sequence = int(stream["next_sequence"])
    connection.execute(
        update(event_stream_sessions)
        .where(event_stream_sessions.c.id == stream["id"])
        .values(next_sequence=sequence + 1)
    )
    connection.execute(
        insert(event_outbox).values(
            id=str(uuid7()),
            vault_id=vault_id,
            stream_session_id=stream["id"],
            sequence=sequence,
            event_id=event_id,
            event_type=event_type,
            resource_type=target_type,
            resource_id=target_id,
            resource_revision=resource_revision,
            payload_json=metadata_json,
            created_at_us=timestamp,
            published_at_us=None,
            expires_at_us=timestamp + 86_400_000_000,
        )
    )


class EventReplayRepository:
    """Read a bounded, payload-free replay window from the durable outbox."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replay(
        self,
        vault_id: str,
        *,
        cursor: str | None,
        limit: int,
        timestamp_us: int | None = None,
    ) -> EventReplay:
        if limit < 1 or limit > 64:
            raise ValueError("event replay limit is outside the allowed range")
        timestamp = now_us() if timestamp_us is None else timestamp_us
        with self.engine.connect() as connection:
            stream = (
                connection.execute(
                    select(event_stream_sessions)
                    .where(
                        and_(
                            event_stream_sessions.c.vault_id == vault_id,
                            event_stream_sessions.c.closed_at_us.is_(None),
                        )
                    )
                    .order_by(event_stream_sessions.c.started_at_us.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
            expected_sequence = int(stream["minimum_retained_sequence"])
            disposition = "OK"

            if cursor is not None:
                cursor_row = (
                    connection.execute(
                        select(event_outbox.c.sequence, event_outbox.c.expires_at_us).where(
                            and_(
                                event_outbox.c.vault_id == vault_id,
                                event_outbox.c.stream_session_id == stream["id"],
                                event_outbox.c.event_id == cursor,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if cursor_row is None or int(cursor_row["expires_at_us"]) <= timestamp:
                    recovery_cursor = connection.execute(
                        select(event_outbox.c.event_id)
                        .where(
                            and_(
                                event_outbox.c.vault_id == vault_id,
                                event_outbox.c.stream_session_id == stream["id"],
                                event_outbox.c.expires_at_us > timestamp,
                            )
                        )
                        .order_by(event_outbox.c.sequence.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    return EventReplay(
                        disposition="CURSOR_EXPIRED",
                        events=(),
                        next_cursor=None if recovery_cursor is None else str(recovery_cursor),
                        has_more=False,
                    )
                expected_sequence = int(cursor_row["sequence"]) + 1

            rows = (
                connection.execute(
                    select(event_outbox)
                    .where(
                        and_(
                            event_outbox.c.vault_id == vault_id,
                            event_outbox.c.stream_session_id == stream["id"],
                            event_outbox.c.sequence >= expected_sequence,
                            event_outbox.c.expires_at_us > timestamp,
                        )
                    )
                    .order_by(event_outbox.c.sequence)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            if rows and int(rows[0]["sequence"]) != expected_sequence:
                disposition = "GAP"
            events = tuple(
                EventRecord(
                    event_id=str(row["event_id"]),
                    sequence=int(row["sequence"]),
                    event_type=str(row["event_type"]),
                    resource_type=(
                        None if row["resource_type"] is None else str(row["resource_type"])
                    ),
                    resource_id=None if row["resource_id"] is None else str(row["resource_id"]),
                    resource_revision=(
                        None if row["resource_revision"] is None else int(row["resource_revision"])
                    ),
                )
                for row in rows
            )
            next_cursor = cursor if not events else events[-1].event_id
            return EventReplay(disposition, events, next_cursor, has_more)


class SettingsRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, vault_id: str) -> SettingsSnapshot:
        with self.engine.connect() as connection:
            revision = connection.execute(
                select(vaults.c.settings_revision).where(vaults.c.id == vault_id)
            ).scalar_one()
            rows = connection.execute(
                select(settings.c.setting_key, settings.c.value_json).where(
                    and_(settings.c.vault_id == vault_id, settings.c.profile_id.is_(None))
                )
            ).all()
        values = {str(key): json.loads(str(raw)) for key, raw in rows}
        return SettingsSnapshot(VaultSettings.model_validate(values), int(revision))

    def update(
        self,
        vault_id: str,
        patch: VaultSettingsPatch,
        *,
        expected_revision: int,
    ) -> SettingsSnapshot:
        current = self.get(vault_id)
        if current.revision != expected_revision:
            raise RevisionConflict("settings revision is stale")
        requested = patch.apply(current.values)
        changes = {
            key: value
            for key, value in requested.model_dump(mode="json").items()
            if current.values.model_dump(mode="json")[key] != value
        }
        if not changes:
            return current

        timestamp = now_us()
        next_revision = expected_revision + 1
        with self.engine.begin() as connection:
            result = connection.execute(
                update(vaults)
                .where(
                    and_(
                        vaults.c.id == vault_id,
                        vaults.c.settings_revision == expected_revision,
                    )
                )
                .values(
                    settings_revision=next_revision,
                    revision=vaults.c.revision + 1,
                    updated_at_us=timestamp,
                    auto_lock_seconds=requested.auto_lock_seconds,
                )
            )
            if result.rowcount != 1:
                raise RevisionConflict("settings revision is stale")
            for key, value in changes.items():
                changed = connection.execute(
                    update(settings)
                    .where(
                        and_(
                            settings.c.vault_id == vault_id,
                            settings.c.profile_id.is_(None),
                            settings.c.setting_key == key,
                        )
                    )
                    .values(
                        value_json=canonical_json(value),
                        source="USER",
                        revision=settings.c.revision + 1,
                        updated_at_us=timestamp,
                    )
                )
                if changed.rowcount != 1:
                    connection.execute(
                        insert(settings).values(
                            id=str(uuid7()),
                            vault_id=vault_id,
                            profile_id=None,
                            setting_key=key,
                            value_json=canonical_json(value),
                            schema_version=1,
                            source="USER",
                            created_at_us=timestamp,
                            updated_at_us=timestamp,
                            revision=1,
                        )
                    )
            _append_event(
                connection,
                vault_id=vault_id,
                event_type="SETTINGS_UPDATED",
                target_type="SETTINGS",
                target_id=None,
                resource_revision=next_revision,
                metadata={"changedKeys": sorted(changes)},
            )
        return SettingsSnapshot(requested, next_revision)


class JobRepository:
    """Serialize durable job commands and enforce lease/revision ownership."""

    def __init__(self, engine: Engine, *, idempotency_hmac_key: bytes | bytearray) -> None:
        if len(idempotency_hmac_key) < 32:
            raise ValueError("idempotency HMAC key is too short")
        self.engine = engine
        self._hmac_key = idempotency_hmac_key

    def _token_hmac(self, token: str) -> str:
        return hmac.new(self._hmac_key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def find_active_replay(
        self,
        *,
        vault_id: str,
        manifest: JobManifest,
        idempotency_key: str,
    ) -> JobRecord | None:
        """Read an unexpired idempotent job without creating durable state."""

        if len(idempotency_key) < 16 or len(idempotency_key) > 256:
            raise ValueError("idempotency key length is outside the allowed range")
        request_digest = hashlib.sha256(
            canonical_json(manifest.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()
        token_hmac = self._token_hmac(idempotency_key)
        with self.engine.connect() as connection:
            existing = (
                connection.execute(
                    select(idempotency_records).where(
                        and_(
                            idempotency_records.c.vault_id == vault_id,
                            idempotency_records.c.route_code == "LOCAL_JOB_CREATE",
                            idempotency_records.c.actor_class == "LOCAL_USER",
                            idempotency_records.c.idempotency_key_hmac == token_hmac,
                            idempotency_records.c.expires_at_us > now_us(),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                return None
            if existing["request_digest"] != request_digest:
                raise IdempotencyConflict("idempotency key was reused with a different request")
            result_id = existing["result_id"]
            if result_id is None:
                raise IdempotencyConflict("idempotency result is unavailable")
            return self._get_with_connection(connection, str(result_id))

    def create(
        self,
        *,
        vault_id: str,
        manifest: JobManifest,
        idempotency_key: str,
        retry_limit: int = 2,
        connection: Connection | None = None,
    ) -> tuple[JobRecord, bool]:
        """Create once per logical command, atomically with its replay record."""
        if len(idempotency_key) < 16 or len(idempotency_key) > 256:
            raise ValueError("idempotency key length is outside the allowed range")
        if retry_limit < 0 or retry_limit > 5:
            raise ValueError("retry limit is outside the allowed range")
        manifest_json = canonical_json(manifest.model_dump(mode="json"))
        request_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
        token_hmac = self._token_hmac(idempotency_key)
        timestamp = now_us()
        transaction = self.engine.begin() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            existing = (
                active_connection.execute(
                    select(idempotency_records).where(
                        and_(
                            idempotency_records.c.vault_id == vault_id,
                            idempotency_records.c.route_code == "LOCAL_JOB_CREATE",
                            idempotency_records.c.actor_class == "LOCAL_USER",
                            idempotency_records.c.idempotency_key_hmac == token_hmac,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None and int(existing["expires_at_us"]) <= timestamp:
                result_id = existing["result_id"]
                if result_id is not None:
                    expired_job = self._get_with_connection(
                        active_connection,
                        str(result_id),
                    )
                    if (
                        expired_job.job_type == "INTAKE_EXTRACT"
                        and expired_job.state is JobState.QUEUED
                    ):
                        active_connection.execute(
                            update(jobs)
                            .where(
                                and_(
                                    jobs.c.vault_id == vault_id,
                                    jobs.c.id == expired_job.id,
                                    jobs.c.state == JobState.QUEUED.value,
                                    jobs.c.revision == expired_job.revision,
                                )
                            )
                            .values(
                                state=JobState.CANCELLED.value,
                                progress_message_code="JOB_IDEMPOTENCY_EXPIRED",
                                updated_at_us=timestamp,
                                revision=expired_job.revision + 1,
                            )
                        )
                        _append_event(
                            active_connection,
                            vault_id=vault_id,
                            event_type="JOB_CANCELLED",
                            target_type="JOB",
                            target_id=expired_job.id,
                            resource_revision=expired_job.revision + 1,
                            metadata={
                                "jobType": "INTAKE_EXTRACT",
                                "state": JobState.CANCELLED.value,
                            },
                        )
                active_connection.execute(
                    update(jobs)
                    .where(
                        and_(
                            jobs.c.vault_id == vault_id,
                            jobs.c.idempotency_record_id == str(existing["id"]),
                        )
                    )
                    .values(idempotency_record_id=None)
                )
                active_connection.execute(
                    delete(idempotency_records).where(
                        and_(
                            idempotency_records.c.vault_id == vault_id,
                            idempotency_records.c.id == str(existing["id"]),
                        )
                    )
                )
                existing = None
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise IdempotencyConflict("idempotency key was reused with a different request")
                result_id = existing["result_id"]
                if result_id is None:
                    raise IdempotencyConflict("idempotency result is unavailable")
                return self._get_with_connection(active_connection, str(result_id)), True

            idempotency_id = str(uuid7())
            job_id = str(uuid7())
            # The idempotency result points at the job created below.  Both rows
            # and the initial event share this transaction so a retry can never
            # observe a replay token without its durable result.
            active_connection.execute(
                insert(idempotency_records).values(
                    id=idempotency_id,
                    vault_id=vault_id,
                    route_code="LOCAL_JOB_CREATE",
                    actor_class="LOCAL_USER",
                    idempotency_key_hmac=token_hmac,
                    request_digest=request_digest,
                    result_type="JOB",
                    result_id=job_id,
                    created_at_us=timestamp,
                    expires_at_us=timestamp + 86_400_000_000,
                )
            )
            active_connection.execute(
                insert(jobs).values(
                    id=job_id,
                    vault_id=vault_id,
                    job_type=manifest.operation,
                    state=JobState.QUEUED.value,
                    priority=50,
                    progress_micros=0,
                    progress_message_code="JOB_QUEUED",
                    scheduled_at_us=timestamp,
                    lease_owner=None,
                    lease_expires_at_us=None,
                    retry_count=0,
                    retry_limit=retry_limit,
                    cancel_requested_at_us=None,
                    idempotency_record_id=idempotency_id,
                    input_manifest_json=manifest_json,
                    created_at_us=timestamp,
                    updated_at_us=timestamp,
                    revision=1,
                )
            )
            _append_event(
                active_connection,
                vault_id=vault_id,
                event_type="JOB_QUEUED",
                target_type="JOB",
                target_id=job_id,
                resource_revision=1,
                metadata={"jobType": manifest.operation, "state": JobState.QUEUED.value},
            )
            return self._get_with_connection(active_connection, job_id), False

    def get(self, job_id: str) -> JobRecord:
        with self.engine.connect() as connection:
            return self._get_with_connection(connection, job_id)

    def complete_inline_intake(
        self,
        *,
        vault_id: str,
        job_id: str,
        connection: Connection | None = None,
    ) -> JobRecord:
        """Mark the bounded synchronous intake job complete without a worker lease."""

        timestamp = now_us()
        transaction = self.engine.begin() if connection is None else nullcontext(connection)
        with transaction as active_connection:
            current = self._get_with_connection(active_connection, job_id)
            if current.vault_id != vault_id or current.job_type != "INTAKE_EXTRACT":
                raise LookupError("inline intake job is unavailable")
            if current.state is JobState.SUCCEEDED:
                return current
            if current.state is not JobState.QUEUED:
                raise RevisionConflict("inline intake job state is incompatible")
            changed = active_connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.vault_id == vault_id,
                        jobs.c.id == job_id,
                        jobs.c.state == JobState.QUEUED.value,
                        jobs.c.revision == current.revision,
                    )
                )
                .values(
                    state=JobState.SUCCEEDED.value,
                    progress_micros=1_000_000,
                    progress_message_code="JOB_SUCCEEDED",
                    updated_at_us=timestamp,
                    revision=current.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("inline intake job revision is stale")
            _append_event(
                active_connection,
                vault_id=vault_id,
                event_type="JOB_SUCCEEDED",
                target_type="JOB",
                target_id=job_id,
                resource_revision=current.revision + 1,
                metadata={"jobType": "INTAKE_EXTRACT", "state": JobState.SUCCEEDED.value},
            )
            return self._get_with_connection(active_connection, job_id)

    def _get_with_connection(self, connection: Connection, job_id: str) -> JobRecord:
        row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
        return JobRecord(
            id=str(row["id"]),
            vault_id=str(row["vault_id"]),
            job_type=str(row["job_type"]),
            state=JobState(str(row["state"])),
            retry_count=int(row["retry_count"]),
            retry_limit=int(row["retry_limit"]),
            revision=int(row["revision"]),
            manifest=JobManifest.model_validate_json(str(row["input_manifest_json"])),
            lease_owner=None if row["lease_owner"] is None else str(row["lease_owner"]),
            lease_expires_at_us=(
                None if row["lease_expires_at_us"] is None else int(row["lease_expires_at_us"])
            ),
            progress_micros=int(row["progress_micros"]),
        )

    def add_dependency(
        self,
        job_id: str,
        depends_on_job_id: str,
        *,
        required_state: DependencyRequiredState = DependencyRequiredState.SUCCEEDED,
        failure_policy: DependencyFailurePolicy = DependencyFailurePolicy.BLOCK,
    ) -> JobRecord:
        _require_job_id(job_id)
        _require_job_id(depends_on_job_id)
        if job_id == depends_on_job_id:
            raise DependencyConflict("a job cannot depend on itself")
        timestamp = now_us()
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(jobs.c.id, jobs.c.vault_id, jobs.c.state, jobs.c.revision).where(
                        jobs.c.id.in_([job_id, depends_on_job_id])
                    )
                )
                .mappings()
                .all()
            )
            by_id = {str(row["id"]): row for row in rows}
            if set(by_id) != {job_id, depends_on_job_id}:
                raise DependencyConflict("job dependency endpoint is unavailable")
            dependent = by_id[job_id]
            upstream = by_id[depends_on_job_id]
            if dependent["vault_id"] != upstream["vault_id"]:
                raise DependencyConflict("job dependency crosses a vault boundary")
            if JobState(str(dependent["state"])) is not JobState.QUEUED:
                raise DependencyConflict("dependencies can be added only before a job is claimed")
            existing = connection.execute(
                select(job_dependencies.c.job_id).where(
                    and_(
                        job_dependencies.c.vault_id == dependent["vault_id"],
                        job_dependencies.c.job_id == job_id,
                        job_dependencies.c.depends_on_job_id == depends_on_job_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise DependencyConflict("job dependency already exists")
            dependency_count = connection.execute(
                select(func.count())
                .select_from(job_dependencies)
                .where(
                    and_(
                        job_dependencies.c.vault_id == dependent["vault_id"],
                        job_dependencies.c.job_id == job_id,
                    )
                )
            ).scalar_one()
            if int(dependency_count) >= MAX_JOB_DEPENDENCIES:
                raise DependencyConflict("job dependency limit is reached")
            cycle = connection.execute(
                text(
                    """
                    SELECT EXISTS(
                        WITH RECURSIVE ancestors(id) AS (
                            SELECT depends_on_job_id
                            FROM job_dependencies
                            WHERE vault_id = :vault_id AND job_id = :upstream_id
                            UNION
                            SELECT dependency.depends_on_job_id
                            FROM job_dependencies AS dependency
                            JOIN ancestors ON dependency.job_id = ancestors.id
                            WHERE dependency.vault_id = :vault_id
                        )
                        SELECT 1 FROM ancestors WHERE id = :dependent_id
                    )
                    """
                ),
                {
                    "vault_id": str(dependent["vault_id"]),
                    "upstream_id": depends_on_job_id,
                    "dependent_id": job_id,
                },
            ).scalar_one()
            if bool(cycle):
                raise DependencyConflict("job dependency would create a cycle")
            connection.execute(
                insert(job_dependencies).values(
                    vault_id=dependent["vault_id"],
                    job_id=job_id,
                    depends_on_job_id=depends_on_job_id,
                    required_state=required_state.value,
                    failure_policy=failure_policy.value,
                    created_at_us=timestamp,
                )
            )
            changed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.state == JobState.QUEUED.value,
                        jobs.c.revision == dependent["revision"],
                    )
                )
                .values(updated_at_us=timestamp, revision=jobs.c.revision + 1)
            )
            if changed.rowcount != 1:
                raise DependencyConflict("dependent job changed while adding the dependency")
            updated = self._get_with_connection(connection, job_id)
            _append_event(
                connection,
                vault_id=updated.vault_id,
                event_type="JOB_DEPENDENCY_ADDED",
                target_type="JOB",
                target_id=job_id,
                resource_revision=updated.revision,
                metadata={
                    "failurePolicy": failure_policy.value,
                    "requiredState": required_state.value,
                },
            )
            return updated

    def reconcile_dependency_failures(self) -> tuple[int, int]:
        """Resolve terminal failed prerequisites without claiming dependent work."""

        timestamp = now_us()
        upstream = jobs.alias("upstream_job")
        failed_terminal_states = sorted(
            state.value for state in TERMINAL_JOB_STATES if state is not JobState.SUCCEEDED
        )
        blocked = cancelled = 0
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(
                        jobs.c.id,
                        jobs.c.vault_id,
                        jobs.c.revision,
                        job_dependencies.c.failure_policy,
                    )
                    .select_from(
                        jobs.join(
                            job_dependencies,
                            and_(
                                job_dependencies.c.vault_id == jobs.c.vault_id,
                                job_dependencies.c.job_id == jobs.c.id,
                            ),
                        ).join(
                            upstream,
                            and_(
                                upstream.c.vault_id == job_dependencies.c.vault_id,
                                upstream.c.id == job_dependencies.c.depends_on_job_id,
                            ),
                        )
                    )
                    .where(
                        and_(
                            jobs.c.state == JobState.QUEUED.value,
                            job_dependencies.c.required_state
                            == DependencyRequiredState.SUCCEEDED.value,
                            upstream.c.state.in_(failed_terminal_states),
                        )
                    )
                    .order_by(jobs.c.id)
                )
                .mappings()
                .all()
            )
            grouped: dict[str, list[RowMapping]] = {}
            for row in rows:
                grouped.setdefault(str(row["id"]), []).append(row)
            for job_id, failures in grouped.items():
                row = failures[0]
                cancel = any(
                    failure["failure_policy"] == DependencyFailurePolicy.CANCEL.value
                    for failure in failures
                )
                requested = JobState.CANCELLED if cancel else JobState.BLOCKED
                changed = connection.execute(
                    update(jobs)
                    .where(
                        and_(
                            jobs.c.id == job_id,
                            jobs.c.state == JobState.QUEUED.value,
                            jobs.c.revision == row["revision"],
                        )
                    )
                    .values(
                        state=requested.value,
                        progress_message_code=f"JOB_{requested.value}",
                        updated_at_us=timestamp,
                        revision=jobs.c.revision + 1,
                    )
                )
                if changed.rowcount != 1:
                    continue
                updated = self._get_with_connection(connection, job_id)
                _append_event(
                    connection,
                    vault_id=updated.vault_id,
                    event_type=f"JOB_{requested.value}",
                    target_type="JOB",
                    target_id=job_id,
                    resource_revision=updated.revision,
                    metadata={
                        "dependencyResolution": ("UPSTREAM_TERMINAL_WITHOUT_SUCCESS"),
                        "state": requested.value,
                    },
                )
                if cancel:
                    cancelled += 1
                else:
                    blocked += 1
        return blocked, cancelled

    def claim_next(self, *, worker_id: str, lease_us: int = 10_000_000) -> JobRecord | None:
        """Claim one dependency-ready job with a compare-and-swap lease."""
        _require_worker_id(worker_id)
        if lease_us < 500_000 or lease_us > 60_000_000:
            raise ValueError("job lease duration is outside the allowed range")
        self.reconcile_dependency_failures()
        timestamp = now_us()
        upstream = jobs.alias("claim_upstream_job")
        terminal_states = sorted(state.value for state in TERMINAL_JOB_STATES)
        unsatisfied_dependency = exists(
            select(1)
            .select_from(
                job_dependencies.join(
                    upstream,
                    and_(
                        upstream.c.vault_id == job_dependencies.c.vault_id,
                        upstream.c.id == job_dependencies.c.depends_on_job_id,
                    ),
                )
            )
            .where(
                and_(
                    job_dependencies.c.vault_id == jobs.c.vault_id,
                    job_dependencies.c.job_id == jobs.c.id,
                    or_(
                        and_(
                            job_dependencies.c.required_state
                            == DependencyRequiredState.SUCCEEDED.value,
                            upstream.c.state != JobState.SUCCEEDED.value,
                        ),
                        and_(
                            job_dependencies.c.required_state
                            == DependencyRequiredState.TERMINAL.value,
                            upstream.c.state.not_in(terminal_states),
                        ),
                    ),
                )
            )
        ).correlate(jobs)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(jobs.c.id)
                .where(
                    and_(
                        jobs.c.state == JobState.QUEUED.value,
                        jobs.c.job_type != "INTAKE_EXTRACT",
                        jobs.c.scheduled_at_us <= timestamp,
                        ~unsatisfied_dependency,
                    )
                )
                .order_by(jobs.c.priority.desc(), jobs.c.scheduled_at_us, jobs.c.id)
                .limit(1)
            ).first()
            if row is None:
                return None
            job_id = str(row[0])
            # Selection and conditional update intentionally share a transaction.
            # Multiple schedulers may select the same candidate, but only one can
            # move its still-QUEUED revision to RUNNING and own the attempt.
            claimed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.state == JobState.QUEUED.value,
                        jobs.c.job_type != "INTAKE_EXTRACT",
                    )
                )
                .values(
                    state=JobState.RUNNING.value,
                    lease_owner=worker_id,
                    lease_expires_at_us=timestamp + lease_us,
                    updated_at_us=timestamp,
                    revision=jobs.c.revision + 1,
                    progress_message_code="JOB_RUNNING",
                )
            )
            if claimed.rowcount != 1:
                return None
            job = self._get_with_connection(connection, job_id)
            connection.execute(
                insert(job_attempts).values(
                    id=str(uuid7()),
                    vault_id=job.vault_id,
                    job_id=job.id,
                    attempt_number=job.retry_count + 1,
                    worker_kind="LOCAL_BOUNDED",
                    started_at_us=timestamp,
                    finished_at_us=None,
                    outcome_code=None,
                    result_metadata_json="{}",
                )
            )
            _append_event(
                connection,
                vault_id=job.vault_id,
                event_type="JOB_RUNNING",
                target_type="JOB",
                target_id=job.id,
                resource_revision=job.revision,
                metadata={"state": JobState.RUNNING.value},
            )
            return job

    def transition(
        self,
        job_id: str,
        requested: JobState,
        *,
        worker_id: str,
        expected_revision: int,
        outcome_code: str,
        timestamp_us: int | None = None,
    ) -> JobRecord:
        """Commit a worker result only for the current, unexpired lease revision."""
        _require_worker_id(worker_id)
        timestamp = now_us() if timestamp_us is None else timestamp_us
        with self.engine.begin() as connection:
            current = self._get_with_connection(connection, job_id)
            require_job_transition(current.state, requested)
            if (
                current.revision != expected_revision
                or current.lease_owner != worker_id
                or current.lease_expires_at_us is None
                or current.lease_expires_at_us <= timestamp
            ):
                raise LeaseConflict("job lease is stale or owned by another worker")
            changed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.revision == expected_revision,
                        jobs.c.lease_owner == worker_id,
                        jobs.c.lease_expires_at_us > timestamp,
                    )
                )
                .values(
                    state=requested.value,
                    progress_micros=1_000_000
                    if requested is JobState.SUCCEEDED
                    else jobs.c.progress_micros,
                    progress_message_code=f"JOB_{requested.value}",
                    lease_owner=None,
                    lease_expires_at_us=None,
                    updated_at_us=timestamp,
                    revision=jobs.c.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise LeaseConflict("job lease changed during completion")
            connection.execute(
                update(job_attempts)
                .where(
                    and_(
                        job_attempts.c.job_id == job_id,
                        job_attempts.c.finished_at_us.is_(None),
                    )
                )
                .values(finished_at_us=timestamp, outcome_code=outcome_code)
            )
            updated = self._get_with_connection(connection, job_id)
            _append_event(
                connection,
                vault_id=updated.vault_id,
                event_type=f"JOB_{requested.value}",
                target_type="JOB",
                target_id=job_id,
                resource_revision=updated.revision,
                metadata={"state": requested.value},
            )
            return updated

    def request_transition(
        self,
        job_id: str,
        requested: JobState,
        *,
        expected_revision: int,
        timestamp_us: int | None = None,
    ) -> JobRecord:
        if requested not in {JobState.PAUSE_REQUESTED, JobState.CANCEL_REQUESTED}:
            raise ValueError("job request transition is invalid")
        timestamp = now_us() if timestamp_us is None else timestamp_us
        with self.engine.begin() as connection:
            current = self._get_with_connection(connection, job_id)
            require_job_transition(current.state, requested)
            if current.revision != expected_revision:
                raise RevisionConflict("job revision is stale")
            changed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.state == current.state.value,
                        jobs.c.revision == expected_revision,
                    )
                )
                .values(
                    state=requested.value,
                    cancel_requested_at_us=(
                        timestamp
                        if requested is JobState.CANCEL_REQUESTED
                        else jobs.c.cancel_requested_at_us
                    ),
                    progress_message_code=f"JOB_{requested.value}",
                    updated_at_us=timestamp,
                    revision=jobs.c.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflict("job revision changed during request")
            updated = self._get_with_connection(connection, job_id)
            _append_event(
                connection,
                vault_id=updated.vault_id,
                event_type=f"JOB_{requested.value}",
                target_type="JOB",
                target_id=job_id,
                resource_revision=updated.revision,
                metadata={"state": requested.value},
            )
            return updated

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        expected_revision: int,
        lease_us: int = 10_000_000,
        timestamp_us: int | None = None,
    ) -> JobRecord:
        _require_worker_id(worker_id)
        if lease_us < 500_000 or lease_us > 60_000_000:
            raise ValueError("job lease duration is outside the allowed range")
        timestamp = now_us() if timestamp_us is None else timestamp_us
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.state.in_(
                            [
                                JobState.RUNNING.value,
                                JobState.PAUSE_REQUESTED.value,
                                JobState.CANCEL_REQUESTED.value,
                            ]
                        ),
                        jobs.c.revision == expected_revision,
                        jobs.c.lease_owner == worker_id,
                        jobs.c.lease_expires_at_us > timestamp,
                    )
                )
                .values(
                    lease_expires_at_us=timestamp + lease_us,
                    updated_at_us=timestamp,
                    revision=jobs.c.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise LeaseConflict("job lease is stale or owned by another worker")
            updated = self._get_with_connection(connection, job_id)
            _append_event(
                connection,
                vault_id=updated.vault_id,
                event_type="JOB_HEARTBEAT",
                target_type="JOB",
                target_id=job_id,
                resource_revision=updated.revision,
                metadata={"state": updated.state.value},
            )
            return updated

    def report_progress(
        self,
        job_id: str,
        *,
        worker_id: str,
        expected_revision: int,
        progress_micros: int,
        timestamp_us: int | None = None,
    ) -> JobRecord:
        _require_worker_id(worker_id)
        if progress_micros < 1 or progress_micros >= 1_000_000:
            raise ValueError("job progress is outside the non-terminal range")
        timestamp = now_us() if timestamp_us is None else timestamp_us
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(jobs)
                .where(
                    and_(
                        jobs.c.id == job_id,
                        jobs.c.state == JobState.RUNNING.value,
                        jobs.c.revision == expected_revision,
                        jobs.c.lease_owner == worker_id,
                        jobs.c.lease_expires_at_us > timestamp,
                        jobs.c.progress_micros < progress_micros,
                    )
                )
                .values(
                    progress_micros=progress_micros,
                    progress_message_code="JOB_TEST_PROGRESS",
                    updated_at_us=timestamp,
                    revision=jobs.c.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise LeaseConflict("job progress lease or revision is stale")
            updated = self._get_with_connection(connection, job_id)
            _append_event(
                connection,
                vault_id=updated.vault_id,
                event_type="JOB_PROGRESS",
                target_type="JOB",
                target_id=job_id,
                resource_revision=updated.revision,
                metadata={
                    "progressMicros": updated.progress_micros,
                    "progressMessageCode": "JOB_TEST_PROGRESS",
                },
            )
            return updated

    def recover_expired_leases(self, *, timestamp_us: int | None = None) -> RecoverySummary:
        """Reconcile abandoned attempts without inferring successful completion."""
        timestamp = now_us() if timestamp_us is None else timestamp_us
        counts = {"requeued": 0, "paused": 0, "cancelled": 0, "failed": 0}
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(jobs).where(
                        and_(
                            jobs.c.state.in_(
                                [
                                    JobState.RUNNING.value,
                                    JobState.PAUSE_REQUESTED.value,
                                    JobState.CANCEL_REQUESTED.value,
                                ]
                            ),
                            jobs.c.lease_expires_at_us < timestamp,
                        )
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                current = JobState(str(row["state"]))
                retry_count = int(row["retry_count"])
                if current is JobState.PAUSE_REQUESTED:
                    requested = JobState.PAUSED
                    outcome_code = "WORKER_PAUSED_AFTER_LEASE_EXPIRY"
                    count_key = "paused"
                    next_retry_count = retry_count
                    scheduled_at_us = int(row["scheduled_at_us"])
                elif current is JobState.CANCEL_REQUESTED:
                    requested = JobState.CANCELLED
                    outcome_code = "WORKER_CANCELLED_AFTER_LEASE_EXPIRY"
                    count_key = "cancelled"
                    next_retry_count = retry_count
                    scheduled_at_us = int(row["scheduled_at_us"])
                elif retry_count < int(row["retry_limit"]):
                    # Persisted deterministic delay makes restart preserve the
                    # retry schedule rather than creating a tight retry loop.
                    requested = JobState.QUEUED
                    outcome_code = "WORKER_LEASE_EXPIRED_REQUEUED"
                    count_key = "requeued"
                    next_retry_count = retry_count + 1
                    scheduled_at_us = timestamp + _retry_delay_us(str(row["id"]), next_retry_count)
                else:
                    requested = JobState.FAILED
                    outcome_code = "WORKER_LEASE_EXPIRED_FAILED"
                    count_key = "failed"
                    next_retry_count = retry_count
                    scheduled_at_us = int(row["scheduled_at_us"])
                require_job_recovery_transition(current, requested)
                changed = connection.execute(
                    update(jobs)
                    .where(
                        and_(
                            jobs.c.id == row["id"],
                            jobs.c.revision == row["revision"],
                            jobs.c.state == current.value,
                            jobs.c.lease_expires_at_us < timestamp,
                        )
                    )
                    .values(
                        state=requested.value,
                        retry_count=next_retry_count,
                        lease_owner=None,
                        lease_expires_at_us=None,
                        scheduled_at_us=scheduled_at_us,
                        updated_at_us=timestamp,
                        revision=int(row["revision"]) + 1,
                        progress_message_code=f"JOB_{requested.value}",
                    )
                )
                if changed.rowcount != 1:
                    continue
                connection.execute(
                    update(job_attempts)
                    .where(
                        and_(
                            job_attempts.c.vault_id == row["vault_id"],
                            job_attempts.c.job_id == row["id"],
                            job_attempts.c.finished_at_us.is_(None),
                        )
                    )
                    .values(finished_at_us=timestamp, outcome_code=outcome_code)
                )
                _append_event(
                    connection,
                    vault_id=str(row["vault_id"]),
                    event_type=f"JOB_{requested.value}",
                    target_type="JOB",
                    target_id=str(row["id"]),
                    resource_revision=int(row["revision"]) + 1,
                    metadata={"recoveryCode": outcome_code, "state": requested.value},
                )
                counts[count_key] += 1
        return RecoverySummary(
            requeued=counts["requeued"],
            paused=counts["paused"],
            cancelled=counts["cancelled"],
            failed=counts["failed"],
        )


def _retry_delay_us(job_id: str, retry_count: int) -> int:
    base = min(30_000_000, 250_000 * (2 ** (retry_count - 1)))
    digest = hashlib.sha256(f"{job_id}:{retry_count}".encode("ascii")).digest()
    jitter = int.from_bytes(digest[:4], "big") % 250_001
    return base + jitter


def _require_worker_id(worker_id: str) -> None:
    try:
        parsed = UUID(worker_id)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("worker ID is invalid") from error
    if str(parsed) != worker_id or parsed.version != 4:
        raise ValueError("worker ID is invalid")


def _require_job_id(job_id: str) -> None:
    try:
        parsed = UUID(job_id)
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("job ID is invalid") from error
    if str(parsed) != job_id or parsed.version not in {4, 7}:
        raise ValueError("job ID is invalid")
