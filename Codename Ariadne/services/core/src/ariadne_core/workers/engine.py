"""Bounded foundation worker used to prove the durable lifecycle contract.

Only synthetic jobs execute here.  Real discovery, evidence, or provider work
must register a dedicated typed handler with its own replay and cancellation
contract; accepting an arbitrary stored callable would turn vault data into code.
"""

from __future__ import annotations

from uuid import uuid4

import anyio

from ariadne_core.domain.jobs import JobState, JobStateConflict
from ariadne_core.infrastructure.db.repositories import (
    JobRecord,
    JobRepository,
    LeaseConflict,
)


class UnsupportedFoundationJob(RuntimeError):
    pass


class TaskEngine:
    """Project durable claims into at most four local worker executions."""

    def __init__(self, repository: JobRepository, *, worker_id: str | None = None) -> None:
        self.repository = repository
        self.worker_id = str(uuid4()) if worker_id is None else worker_id
        self._limiter = anyio.CapacityLimiter(4)
        self._accepting = True

    def stop_claiming(self) -> None:
        self._accepting = False

    async def run_once(self) -> JobRecord | None:
        if not self._accepting:
            return None
        job = await anyio.to_thread.run_sync(
            lambda: self.repository.claim_next(worker_id=self.worker_id),
            limiter=self._limiter,
        )
        if job is None:
            return None
        # The lease is already durable before handler work begins.  No database
        # transaction remains open while the worker sleeps or performs I/O.
        try:
            if job.job_type == "NOOP":
                pass
            elif job.job_type == "TEST_SLEEP":
                job = await anyio.to_thread.run_sync(
                    lambda: self.repository.report_progress(
                        job.id,
                        worker_id=self.worker_id,
                        expected_revision=job.revision,
                        progress_micros=500_000,
                    ),
                    limiter=self._limiter,
                )
                await anyio.sleep((job.manifest.duration_ms or 1) / 1_000)
            else:
                raise UnsupportedFoundationJob("job requires a dedicated local service")
        except UnsupportedFoundationJob:
            return await self._finish(
                job,
                JobState.BLOCKED,
                outcome_code="LOCAL_SERVICE_REQUIRED",
            )
        except Exception:
            return await self._finish(job, JobState.FAILED, outcome_code="LOCAL_WORKER_FAILED")
        return await self._finish(job, JobState.SUCCEEDED, outcome_code="OK")

    async def _finish(
        self,
        job: JobRecord,
        requested: JobState,
        *,
        outcome_code: str,
    ) -> JobRecord:
        try:
            return await anyio.to_thread.run_sync(
                lambda: self.repository.transition(
                    job.id,
                    requested,
                    worker_id=self.worker_id,
                    expected_revision=job.revision,
                    outcome_code=outcome_code,
                ),
                limiter=self._limiter,
            )
        except (JobStateConflict, LeaseConflict):
            # Pause/cancel can win the race after the handler's last checkpoint.
            # Re-read the durable state and acknowledge only a request still
            # owned by this worker; another owner or transition remains an error.
            current = await anyio.to_thread.run_sync(
                lambda: self.repository.get(job.id),
                limiter=self._limiter,
            )
            if current.lease_owner != self.worker_id:
                raise
            if current.state is JobState.CANCEL_REQUESTED:
                reconciled = JobState.CANCELLED
                reconciled_code = "CANCELLED_AT_SYNTHETIC_CHECKPOINT"
            elif current.state is JobState.PAUSE_REQUESTED:
                reconciled = JobState.PAUSED
                reconciled_code = "PAUSED_AT_SYNTHETIC_CHECKPOINT"
            else:
                raise
            return await anyio.to_thread.run_sync(
                lambda: self.repository.transition(
                    current.id,
                    reconciled,
                    worker_id=self.worker_id,
                    expected_revision=current.revision,
                    outcome_code=reconciled_code,
                ),
                limiter=self._limiter,
            )
