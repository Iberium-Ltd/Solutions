"""Closed durable-job transitions shared by every worker implementation.

The database state, not a running coroutine, is authoritative.  Keeping the
normal and crash-recovery graphs here prevents a worker or new task adapter from
inventing a shortcut that would report work as completed without a committed
attempt.
"""

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


# BLOCKED is deliberately recoverable: a later approval, credential, provider,
# or dependency change can make the same durable job eligible again.
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

# Recovery is narrower than ordinary command handling.  An expired lease proves
# that ownership was lost; it never proves that the abandoned work succeeded.
ALLOWED_RECOVERY_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.RUNNING: frozenset({JobState.QUEUED, JobState.FAILED}),
    JobState.PAUSE_REQUESTED: frozenset({JobState.PAUSED}),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED}),
}


class JobStateConflict(ValueError):
    """Raised when a command would bypass the durable job state machine."""


def require_job_transition(current: JobState, requested: JobState) -> None:
    """Enforce the job transition state invariant at one shared boundary."""

    if requested not in ALLOWED_JOB_TRANSITIONS[current]:
        raise JobStateConflict(
            f"job transition {current.value} -> {requested.value} is not allowed"
        )


def require_job_recovery_transition(current: JobState, requested: JobState) -> None:
    """Enforce the job recovery transition state invariant at one shared boundary."""

    if requested not in ALLOWED_RECOVERY_TRANSITIONS.get(current, frozenset()):
        raise JobStateConflict(
            f"job recovery transition {current.value} -> {requested.value} is not allowed"
        )
