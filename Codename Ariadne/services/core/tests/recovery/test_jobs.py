from __future__ import annotations

import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import and_, func, select, update

from ariadne_core.application.vault import VaultManager
from ariadne_core.domain.jobs import (
    ALLOWED_JOB_TRANSITIONS,
    ALLOWED_RECOVERY_TRANSITIONS,
    DependencyFailurePolicy,
    DependencyRequiredState,
    JobState,
    JobStateConflict,
    require_job_recovery_transition,
    require_job_transition,
)
from ariadne_core.infrastructure.db.models import (
    event_outbox,
    idempotency_records,
    job_attempts,
    job_dependencies,
    jobs,
)
from ariadne_core.infrastructure.db.repositories import (
    DependencyConflict,
    IdempotencyConflict,
    JobManifest,
    JobRepository,
    LeaseConflict,
    RecoverySummary,
    RevisionConflict,
)
from ariadne_core.security.key_custody import MemoryKeyCustodian
from ariadne_core.workers.engine import TaskEngine


def _repository(tmp_path):
    manager = VaultManager(tmp_path / "vault", MemoryKeyCustodian())
    manifest = manager.create(display_name="Synthetic task vault")
    return manager, manifest, JobRepository(manager.engine, idempotency_hmac_key=b"i" * 32)


def test_idempotent_creation_and_state_machine(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    request = JobManifest(operation="NOOP", resource_ids=[])
    key = secrets.token_urlsafe(24)
    created, replay = repository.create(
        vault_id=manifest.vault_id, manifest=request, idempotency_key=key
    )
    repeated, replayed = repository.create(
        vault_id=manifest.vault_id, manifest=request, idempotency_key=key
    )
    assert replay is False
    assert replayed is True
    assert repeated.id == created.id

    with pytest.raises(IdempotencyConflict):
        repository.create(
            vault_id=manifest.vault_id,
            manifest=JobManifest(operation="TEST_SLEEP", duration_ms=1),
            idempotency_key=key,
        )
    with pytest.raises(JobStateConflict):
        require_job_transition(JobState.QUEUED, JobState.SUCCEEDED)
    manager.lock()


def test_expired_inline_intake_key_cancels_stale_job_and_releases_record(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    request = JobManifest(operation="INTAKE_EXTRACT", resource_ids=[])
    key = secrets.token_urlsafe(24)
    expired, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=request,
        idempotency_key=key,
    )
    with manager.engine.begin() as connection:
        expired_record_id = connection.execute(
            select(jobs.c.idempotency_record_id).where(jobs.c.id == expired.id)
        ).scalar_one()
        connection.execute(
            update(idempotency_records)
            .where(idempotency_records.c.id == expired_record_id)
            .values(expires_at_us=1)
        )

    replacement, replayed = repository.create(
        vault_id=manifest.vault_id,
        manifest=request,
        idempotency_key=key,
    )
    assert replayed is False
    assert replacement.id != expired.id
    assert repository.get(expired.id).state is JobState.CANCELLED
    assert repository.get(replacement.id).state is JobState.QUEUED
    with manager.engine.connect() as connection:
        assert (
            connection.execute(
                select(jobs.c.idempotency_record_id).where(jobs.c.id == expired.id)
            ).scalar_one()
            is None
        )
        assert (
            connection.execute(
                select(func.count())
                .select_from(idempotency_records)
                .where(idempotency_records.c.route_code == "LOCAL_JOB_CREATE")
            ).scalar_one()
            == 1
        )
    manager.lock()


def test_bounded_worker_completes_synthetic_noop(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    result = anyio.run(TaskEngine(repository).run_once)
    assert result is not None
    assert result.id == created.id
    assert result.state is JobState.SUCCEEDED
    manager.lock()


def test_expired_lease_is_recovered_without_duplicate_effect(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="TEST_SLEEP", duration_ms=5),
        idempotency_key=secrets.token_urlsafe(24),
        retry_limit=1,
    )
    worker_id = str(uuid4())
    claimed = repository.claim_next(worker_id=worker_id, lease_us=500_000)
    assert claimed is not None and claimed.state is JobState.RUNNING
    with manager.engine.begin() as connection:
        connection.execute(
            update(jobs)
            .where(jobs.c.id == created.id)
            .values(lease_expires_at_us=time.time_ns() // 1_000 - 1)
        )
    recovery_timestamp = time.time_ns() // 1_000
    assert repository.recover_expired_leases(timestamp_us=recovery_timestamp) == RecoverySummary(
        requeued=1
    )
    recovered = repository.get(created.id)
    assert recovered.state is JobState.QUEUED
    assert recovered.retry_count == 1
    assert recovered.lease_owner is None
    with manager.engine.connect() as connection:
        attempt = connection.execute(
            select(job_attempts.c.finished_at_us, job_attempts.c.outcome_code).where(
                job_attempts.c.job_id == created.id
            )
        ).one()
        recovery_event = connection.execute(
            select(event_outbox.c.event_type, event_outbox.c.payload_json)
            .where(
                and_(
                    event_outbox.c.resource_id == created.id,
                    event_outbox.c.event_type == "JOB_QUEUED",
                )
            )
            .order_by(event_outbox.c.sequence.desc())
            .limit(1)
        ).one()
        scheduled_at_us = connection.execute(
            select(jobs.c.scheduled_at_us).where(jobs.c.id == created.id)
        ).scalar_one()
    assert attempt == (recovery_timestamp, "WORKER_LEASE_EXPIRED_REQUEUED")
    assert recovery_event[0] == "JOB_QUEUED"
    assert "WORKER_LEASE_EXPIRED_REQUEUED" in recovery_event[1]
    assert 250_000 <= scheduled_at_us - recovery_timestamp <= 500_000
    manager.lock()


def test_every_normal_and_recovery_transition_is_closed() -> None:
    for current in JobState:
        for requested in JobState:
            if requested in ALLOWED_JOB_TRANSITIONS[current]:
                require_job_transition(current, requested)
            else:
                with pytest.raises(JobStateConflict):
                    require_job_transition(current, requested)

            if requested in ALLOWED_RECOVERY_TRANSITIONS.get(current, frozenset()):
                require_job_recovery_transition(current, requested)
            else:
                with pytest.raises(JobStateConflict):
                    require_job_recovery_transition(current, requested)


def test_lease_owner_and_revision_are_authoritative(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    owner = str(uuid4())
    stale_owner = str(uuid4())
    claimed = repository.claim_next(worker_id=owner)
    assert claimed is not None and claimed.id == created.id
    assert repository.claim_next(worker_id=stale_owner) is None

    with pytest.raises(LeaseConflict):
        repository.heartbeat(
            created.id,
            worker_id=stale_owner,
            expected_revision=claimed.revision,
        )
    heartbeat = repository.heartbeat(
        created.id,
        worker_id=owner,
        expected_revision=claimed.revision,
    )
    with pytest.raises(ValueError, match="progress"):
        repository.report_progress(
            created.id,
            worker_id=owner,
            expected_revision=heartbeat.revision,
            progress_micros=0,
        )
    with pytest.raises(LeaseConflict):
        repository.report_progress(
            created.id,
            worker_id=stale_owner,
            expected_revision=heartbeat.revision,
            progress_micros=500_000,
        )
    progress = repository.report_progress(
        created.id,
        worker_id=owner,
        expected_revision=heartbeat.revision,
        progress_micros=500_000,
    )
    assert progress.progress_micros == 500_000
    with pytest.raises(LeaseConflict):
        repository.transition(
            created.id,
            JobState.SUCCEEDED,
            worker_id=owner,
            expected_revision=claimed.revision,
            outcome_code="OK",
        )
    completed = repository.transition(
        created.id,
        JobState.SUCCEEDED,
        worker_id=owner,
        expected_revision=progress.revision,
        outcome_code="OK",
    )
    assert completed.state is JobState.SUCCEEDED
    manager.lock()


def test_recovery_distinguishes_pause_cancel_and_exhausted_retry(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    cases = (
        (JobState.PAUSE_REQUESTED, 1),
        (JobState.CANCEL_REQUESTED, 1),
        (JobState.RUNNING, 0),
    )
    job_ids: list[str] = []
    for requested, retry_limit in cases:
        created, _ = repository.create(
            vault_id=manifest.vault_id,
            manifest=JobManifest(operation="NOOP"),
            idempotency_key=secrets.token_urlsafe(24),
            retry_limit=retry_limit,
        )
        claimed = repository.claim_next(worker_id=str(uuid4()))
        assert claimed is not None and claimed.id == created.id
        with manager.engine.begin() as connection:
            connection.execute(
                update(jobs)
                .where(jobs.c.id == created.id)
                .values(state=requested.value, lease_expires_at_us=99)
            )
        job_ids.append(created.id)

    summary = repository.recover_expired_leases(timestamp_us=100)
    assert summary == RecoverySummary(paused=1, cancelled=1, failed=1)
    assert [repository.get(job_id).state for job_id in job_ids] == [
        JobState.PAUSED,
        JobState.CANCELLED,
        JobState.FAILED,
    ]
    manager.lock()


def test_recovery_rolls_back_job_attempt_and_outbox_together(tmp_path, monkeypatch) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    claimed = repository.claim_next(worker_id=str(uuid4()))
    assert claimed is not None
    with manager.engine.begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == created.id).values(lease_expires_at_us=99)
        )

    from ariadne_core.infrastructure.db import repositories as repository_module

    def fail_event(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic transactional failure")

    monkeypatch.setattr(repository_module, "_append_event", fail_event)
    with pytest.raises(RuntimeError, match="synthetic transactional failure"):
        repository.recover_expired_leases(timestamp_us=100)

    assert repository.get(created.id).state is JobState.RUNNING
    with manager.engine.connect() as connection:
        open_attempt = connection.execute(
            select(job_attempts.c.finished_at_us).where(job_attempts.c.job_id == created.id)
        ).scalar_one()
    assert open_attempt is None
    manager.lock()


def test_worker_and_lease_bounds_reject_untrusted_labels(tmp_path) -> None:
    manager, _manifest, repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="worker ID"):
        repository.claim_next(worker_id="synthetic-sensitive-canary")
    with pytest.raises(ValueError, match="lease duration"):
        repository.claim_next(worker_id=str(uuid4()), lease_us=499_999)
    manager.lock()


def test_scheduler_stop_prevents_new_claims(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    engine = TaskEngine(repository)
    engine.stop_claiming()
    assert anyio.run(engine.run_once) is None
    assert repository.get(created.id).state is JobState.QUEUED
    manager.lock()


def test_two_schedulers_cannot_claim_the_same_job(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    worker_ids = (str(uuid4()), str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(lambda worker: repository.claim_next(worker_id=worker), worker_ids)
        )
    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    assert claimed[0].id == created.id
    assert repository.get(created.id).lease_owner == claimed[0].lease_owner
    manager.lock()


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (JobState.CANCEL_REQUESTED, JobState.CANCELLED),
        (JobState.PAUSE_REQUESTED, JobState.PAUSED),
    ],
)
def test_completion_request_races_resolve_without_false_success(
    tmp_path,
    requested: JobState,
    expected: JobState,
) -> None:
    manager, manifest, repository = _repository(tmp_path)
    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="TEST_SLEEP", duration_ms=1_000),
        idempotency_key=secrets.token_urlsafe(24),
    )
    engine = TaskEngine(repository)

    async def race() -> JobState:
        results = []

        async def run_worker() -> None:
            results.append(await engine.run_once())

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_worker)
            while True:
                current = await anyio.to_thread.run_sync(lambda: repository.get(created.id))
                if current.state is JobState.RUNNING and current.progress_micros == 500_000:
                    break
                await anyio.sleep(0.005)
            with pytest.raises(RevisionConflict):
                await anyio.to_thread.run_sync(
                    lambda: repository.request_transition(
                        created.id,
                        requested,
                        expected_revision=current.revision - 1,
                    )
                )
            await anyio.to_thread.run_sync(
                lambda: repository.request_transition(
                    created.id,
                    requested,
                    expected_revision=current.revision,
                )
            )
        assert len(results) == 1 and results[0] is not None
        return results[0].state

    assert anyio.run(race) is expected
    assert repository.get(created.id).state is expected
    manager.lock()


def test_dependency_dag_blocks_claim_until_success_and_rejects_cycles(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    upstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    downstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    repository.add_dependency(downstream.id, upstream.id)
    with pytest.raises(DependencyConflict, match="already exists"):
        repository.add_dependency(downstream.id, upstream.id)
    with pytest.raises(DependencyConflict, match="itself"):
        repository.add_dependency(upstream.id, upstream.id)
    with pytest.raises(DependencyConflict, match="cycle"):
        repository.add_dependency(upstream.id, downstream.id)

    worker = str(uuid4())
    claimed_upstream = repository.claim_next(worker_id=worker)
    assert claimed_upstream is not None and claimed_upstream.id == upstream.id
    assert repository.claim_next(worker_id=str(uuid4())) is None
    repository.transition(
        upstream.id,
        JobState.SUCCEEDED,
        worker_id=worker,
        expected_revision=claimed_upstream.revision,
        outcome_code="OK",
    )
    claimed_downstream = repository.claim_next(worker_id=str(uuid4()))
    assert claimed_downstream is not None and claimed_downstream.id == downstream.id
    with manager.engine.connect() as connection:
        assert connection.execute(select(job_dependencies)).all()
    manager.lock()


@pytest.mark.parametrize(
    ("failure_policy", "expected"),
    [
        (DependencyFailurePolicy.BLOCK, JobState.BLOCKED),
        (DependencyFailurePolicy.CANCEL, JobState.CANCELLED),
    ],
)
def test_failed_success_dependency_propagates_explicit_policy(
    tmp_path,
    failure_policy: DependencyFailurePolicy,
    expected: JobState,
) -> None:
    manager, manifest, repository = _repository(tmp_path)
    upstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
        retry_limit=0,
    )
    downstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    repository.add_dependency(
        downstream.id,
        upstream.id,
        failure_policy=failure_policy,
    )
    worker = str(uuid4())
    claimed = repository.claim_next(worker_id=worker)
    assert claimed is not None and claimed.id == upstream.id
    repository.transition(
        upstream.id,
        JobState.FAILED,
        worker_id=worker,
        expected_revision=claimed.revision,
        outcome_code="SYNTHETIC_FAILURE",
    )
    assert repository.claim_next(worker_id=str(uuid4())) is None
    assert repository.get(downstream.id).state is expected
    manager.lock()


def test_terminal_dependency_allows_explicit_non_success_completion(tmp_path) -> None:
    manager, manifest, repository = _repository(tmp_path)
    upstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    downstream, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    repository.add_dependency(
        downstream.id,
        upstream.id,
        required_state=DependencyRequiredState.TERMINAL,
    )
    worker = str(uuid4())
    claimed = repository.claim_next(worker_id=worker)
    assert claimed is not None and claimed.id == upstream.id
    repository.transition(
        upstream.id,
        JobState.FAILED,
        worker_id=worker,
        expected_revision=claimed.revision,
        outcome_code="SYNTHETIC_FAILURE",
    )
    eligible = repository.claim_next(worker_id=str(uuid4()))
    assert eligible is not None and eligible.id == downstream.id
    manager.lock()


def test_dependency_fan_in_is_bounded(tmp_path, monkeypatch) -> None:
    manager, manifest, repository = _repository(tmp_path)
    dependent, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    upstream_ids = []
    for _ in range(3):
        upstream, _ = repository.create(
            vault_id=manifest.vault_id,
            manifest=JobManifest(operation="NOOP"),
            idempotency_key=secrets.token_urlsafe(24),
        )
        upstream_ids.append(upstream.id)

    from ariadne_core.infrastructure.db import repositories as repository_module

    monkeypatch.setattr(repository_module, "MAX_JOB_DEPENDENCIES", 2)
    repository.add_dependency(dependent.id, upstream_ids[0])
    repository.add_dependency(dependent.id, upstream_ids[1])
    with pytest.raises(DependencyConflict, match="limit"):
        repository.add_dependency(dependent.id, upstream_ids[2])
    manager.lock()


def test_faults_at_create_claim_progress_and_completion_boundaries_roll_back(
    tmp_path, monkeypatch
) -> None:
    manager, manifest, repository = _repository(tmp_path)
    from ariadne_core.infrastructure.db import repositories as repository_module

    def fail_event(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic process-death boundary")

    with monkeypatch.context() as patch:
        patch.setattr(repository_module, "_append_event", fail_event)
        with pytest.raises(RuntimeError, match="process-death"):
            repository.create(
                vault_id=manifest.vault_id,
                manifest=JobManifest(operation="NOOP"),
                idempotency_key=secrets.token_urlsafe(24),
            )
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(jobs)).scalar_one() == 0
        assert (
            connection.execute(select(func.count()).select_from(idempotency_records)).scalar_one()
            == 0
        )

    created, _ = repository.create(
        vault_id=manifest.vault_id,
        manifest=JobManifest(operation="NOOP"),
        idempotency_key=secrets.token_urlsafe(24),
    )
    worker = str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(repository_module, "_append_event", fail_event)
        with pytest.raises(RuntimeError, match="process-death"):
            repository.claim_next(worker_id=worker)
    assert repository.get(created.id).state is JobState.QUEUED
    with manager.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(job_attempts)).scalar_one() == 0

    claimed = repository.claim_next(worker_id=worker)
    assert claimed is not None
    with monkeypatch.context() as patch:
        patch.setattr(repository_module, "_append_event", fail_event)
        with pytest.raises(RuntimeError, match="process-death"):
            repository.report_progress(
                created.id,
                worker_id=worker,
                expected_revision=claimed.revision,
                progress_micros=500_000,
            )
    after_progress_fault = repository.get(created.id)
    assert after_progress_fault.revision == claimed.revision
    assert after_progress_fault.progress_micros == 0

    with monkeypatch.context() as patch:
        patch.setattr(repository_module, "_append_event", fail_event)
        with pytest.raises(RuntimeError, match="process-death"):
            repository.transition(
                created.id,
                JobState.SUCCEEDED,
                worker_id=worker,
                expected_revision=claimed.revision,
                outcome_code="OK",
            )
    assert repository.get(created.id).state is JobState.RUNNING
    with manager.engine.connect() as connection:
        assert (
            connection.execute(
                select(job_attempts.c.finished_at_us).where(job_attempts.c.job_id == created.id)
            ).scalar_one()
            is None
        )
    manager.lock()
