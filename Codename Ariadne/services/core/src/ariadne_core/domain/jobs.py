"""Durable job state rules kept independent of worker implementation."""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class DependencyRequiredState(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    TERMINAL = "TERMINAL"


class DependencyFailurePolicy(StrEnum):
    BLOCK = "BLOCK"
    CANCEL = "CANCEL"


TERMINAL_JOB_STATES = frozenset(
    {JobState.CANCELLED, JobState.SUCCEEDED, JobState.PARTIAL, JobState.FAILED}
)

ALLOWED_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.DRAFT: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset(
        {JobState.RUNNING, JobState.WAITING_APPROVAL, JobState.CANCELLED, JobState.BLOCKED}
    ),
    JobState.WAITING_APPROVAL: frozenset(
        {JobState.QUEUED, JobState.CANCEL_REQUESTED, JobState.CANCELLED}
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.PAUSE_REQUESTED,
            JobState.CANCEL_REQUESTED,
            JobState.SUCCEEDED,
            JobState.PARTIAL,
            JobState.FAILED,
            JobState.BLOCKED,
        }
    ),
    JobState.PAUSE_REQUESTED: frozenset(
        {JobState.PAUSED, JobState.CANCEL_REQUESTED, JobState.FAILED}
    ),
    JobState.PAUSED: frozenset({JobState.QUEUED, JobState.CANCEL_REQUESTED, JobState.CANCELLED}),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED, JobState.PARTIAL, JobState.FAILED}),
    JobState.BLOCKED: frozenset(
        {JobState.QUEUED, JobState.CANCEL_REQUESTED, JobState.CANCELLED, JobState.PARTIAL}
    ),
    JobState.CANCELLED: frozenset(),
    JobState.SUCCEEDED: frozenset(),
    JobState.PARTIAL: frozenset(),
    JobState.FAILED: frozenset(),
}

ALLOWED_RECOVERY_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.RUNNING: frozenset({JobState.QUEUED, JobState.FAILED}),
    JobState.PAUSE_REQUESTED: frozenset({JobState.PAUSED}),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED}),
}


class JobStateConflict(ValueError):
    """Raised when a command would bypass the durable job state machine."""


def require_job_transition(current: JobState, requested: JobState) -> None:
    if requested not in ALLOWED_JOB_TRANSITIONS[current]:
        raise JobStateConflict(
            f"job transition {current.value} -> {requested.value} is not allowed"
        )


def require_job_recovery_transition(current: JobState, requested: JobState) -> None:
    if requested not in ALLOWED_RECOVERY_TRANSITIONS.get(current, frozenset()):
        raise JobStateConflict(
            f"job recovery transition {current.value} -> {requested.value} is not allowed"
        )
