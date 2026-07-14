# ADR-004: Durable Task Engine

- Status: Accepted for the Phase 2 local foundation
- Date: 2026-07-11
- Decision owners: Core-service, data, privacy, and desktop engineering
- Scope: local job durability, bounded execution, idempotency, cancellation, and redacted progress

## Context

Ariadne will eventually coordinate parsing, provider checks, evidence capture, hashing, OCR, reports, backup, restore, and purge work. Those operations must survive sidecar restarts, remain cancellable, expose honest progress, and never duplicate a disclosure or irreversible effect because a client retried.

An external queue would add another daemon and security boundary to a single-user local application. Purely in-memory tasks would lose state during lock, crash, update, or ordinary application shutdown and could turn incomplete work into an unexplained result.

Phase 2 is a foundation, not authorization to implement provider activity. Its worker registry contains only synthetic `NOOP` and `TEST_SLEEP` tasks for lifecycle verification.

## Decision

### Durable source of truth

SQLCipher tables are the source of truth for jobs, dependencies, attempts, idempotency records, and the redacted event outbox. In-memory tasks, queues, progress objects, and Tauri events are disposable projections.

Every job has a typed input manifest containing only bounded IDs, policy references, synthetic test parameters, and version information. It never contains unrestricted file paths, credentials, raw evidence, arbitrary callables, pickled objects, or provider secrets.

The durable states are:

`DRAFT`, `QUEUED`, `WAITING_APPROVAL`, `RUNNING`, `PAUSE_REQUESTED`, `PAUSED`, `CANCEL_REQUESTED`, `CANCELLED`, `SUCCEEDED`, `PARTIAL`, `FAILED`, and `BLOCKED`.

Transitions are implemented by one closed state-machine function and compare-and-swap revision checks. Terminal states are immutable. `NOT_FOUND`, provider outcomes, and attribution are not job states.

### Serialized writes and bounded workers

One serialized SQLCipher writer owns all state transitions, leases, attempt records, idempotency completion, resource mutation, and outbox inserts. Transactions are short; worker I/O and computation never run while holding the writer transaction. Reads use a bounded pool only after the SQLCipher/WAL spike proves the selected driver and journal configuration.

AnyIO runs a bounded worker group. Phase 2 defaults to four task slots and one database writer regardless of the target Mac's 16 CPU cores and 64 GB memory. Limits are typed settings with safe minimums and maximums, not environment-controlled unbounded integers. Later task classes may add independently bounded browser, provider, or process pools after benchmarks and threat review.

The Phase 2 registry permits only:

- `NOOP`, which performs no I/O or state mutation beyond its own progress/result records; and
- `TEST_SLEEP`, which waits through an injected clock/cancellation seam and emits bounded synthetic progress.

Both are development/test capabilities. A production build refuses to create them unless an explicit compiled test feature is active. They cannot accept an external destination, identity value, file path, command, URL, or arbitrary duration.

### Claiming, leases, and recovery

A scheduler claims an eligible `QUEUED` job with `BEGIN IMMEDIATE`, verifies dependencies and lock requirements, creates an append-only attempt, sets a random ephemeral worker ID, and stores a bounded lease expiry. Only the current lease owner and expected job revision may heartbeat, report progress, or complete the attempt.

Workers heartbeat at a configured interval shorter than the lease and never infer completion from process survival. On startup and periodically, recovery finds expired `RUNNING`, `PAUSE_REQUESTED`, or `CANCEL_REQUESTED` leases. It closes the abandoned attempt with a redacted crash/recovery code, clears the lease, and then:

- requeues retryable work when its persisted retry budget remains;
- moves a requested pause to `PAUSED` when no effect is in flight;
- completes cancellation when the task's cancellation contract permits; or
- marks the job `FAILED` or `BLOCKED` with an explicit reason when safe replay cannot be established.

Recovery never reports `SUCCEEDED` without a committed success record. Later effectful handlers must define their own idempotent reconciliation before registration.

### Retry, pause, and cancellation

Retry limits, timeouts, and scheduled timestamps are persisted. Backoff is capped exponential delay with bounded persisted jitter so restart does not change the schedule. A retry creates a new attempt, not a new history-free job, unless the API explicitly creates a replacement job linked to the original.

Pause and cancellation are cooperative requests. The command transaction records the request and emits an outbox event; the worker checks at bounded checkpoints. Completion races are resolved by the state machine and expected revision. Cancellation does not roll back already committed effects and must never be presented as if it did. Phase 2 synthetic tasks have no external effects, allowing all race paths to be tested safely.

### Idempotent commands

Every job-creating or side-effecting logical command requires an idempotency record scoped to vault, actor class, route, and an HMAC of the client key. The record also stores the canonical request digest, state, expiry, and only safe references to the resulting job or resource.

Creating the idempotency record, job/resource mutation, audit record where required, and initial outbox event occurs in one SQLCipher transaction. Repeating the same key and request digest returns the existing result with `idempotentReplay: true`. Reusing the key with a different digest returns a conflict. A pending record is reconciled from its committed references after restart; it does not authorize a duplicate job.

Raw idempotency keys and response bodies are not stored or logged. Idempotency retention is at least as long as the referenced job and any retry window. Later external or irreversible actions may require longer non-reuse tombstones defined by their own adapter contract.

### Transactional outbox

Every durable resource or job mutation appends its bounded redacted outbox row in the same writer transaction. A committed mutation without its event and an event without its mutation are both prohibited.

The relay publishes committed rows in sequence and records first publication without immediately deleting them. Delivery is at least once. Consumers deduplicate by event ID, detect sequence gaps, and refetch the scoped resource. Relay failure, duplicate publication, restart, or slow consumers do not alter job state.

Progress events contain a code, integer progress micros, safe typed display arguments, resource IDs, and timestamps. They cannot contain task input values, query text, paths, exceptions, tokens, or arbitrary worker strings.

### Dependencies and shutdown

Job dependencies form a directed acyclic graph validated before commit and exercised with recursive-CTE cycle tests. A dependent job cannot run until its declared success/terminal condition is met. Failure and cancellation propagate only according to the stored dependency rule; they are never silently converted to success.

On vault lock or sidecar shutdown, the scheduler stops claiming. Workers receive cooperative stop requests and a bounded grace period. Unfinished work remains durable and is reconciled by lease recovery on the next authorized startup. Python tasks never daemonize or outlive the supervised sidecar intentionally.

## Alternatives considered

### In-memory `asyncio` tasks

Rejected as the source of truth. They cannot provide crash recovery, idempotency, audit history, or reliable UI reconciliation.

### Redis, Celery, or another external broker

Rejected for the local single-device foundation. It would add installation, credentials, updates, network surfaces, and backup semantics without a demonstrated need.

### Multiple SQLite writers

Rejected initially. A serialized writer makes lease, approval, idempotency, and outbox atomicity easier to reason about. Throughput is measured before adding writer complexity.

### Arbitrary Python handler names or pickled payloads

Rejected. A closed typed registry prevents stored data from becoming code execution and keeps migrations and privacy validation tractable.

### Exactly-once event delivery

Rejected as an unprovable transport claim. Atomic state/outbox commit, at-least-once relay, idempotent commands, and consumer deduplication provide the required behavior.

## Verification requirements

The current foundation exhaustively checks the closed normal and recovery state
maps; enforces UUID lease ownership, expected revisions, bounded lease/progress
values, and two-scheduler claim exclusion; reconciles completion against pause
or cancellation without false success; persists bounded deterministic retry
delay; closes abandoned attempts and appends recovery events in one transaction;
and prevents new claims after the scheduler stop gate. Migration
`0002_job_dependencies` now adds a vault-scoped DAG with at most 64 prerequisites
per job, recursive-CTE cycle rejection, success/terminal eligibility, and
explicit block/cancel propagation. Boundary-by-boundary failure injection
is implemented at the repository transaction seam for
create, claim/attempt, progress, and completion; each mutation and its outbox or
attempt records roll back together without false success.

The Phase 2 local-foundation gate uses deterministic tests to prove:

- every allowed and forbidden state transition, including completion/cancel and pause/cancel races;
- bounded claiming, concurrency, progress, retry count, timeout, backoff, jitter, and input duration;
- two schedulers cannot own one lease and a stale owner cannot heartbeat or complete it;
- injected transaction failure at each create/claim/attempt/progress/completion boundary recovers without false success or duplicate work;
- identical idempotent replay returns the original safe reference and mismatched replay conflicts;
- mutation, idempotency record, attempt/audit history, and outbox event commit or roll back together;
- duplicate, delayed, failed, and replayed outbox delivery does not corrupt job state;
- dependency cycles and unsatisfied dependency transitions are rejected;
- lock and shutdown stop new claims and leave unfinished work recoverable;
- all event, error, attempt, and diagnostic fields reject generated sensitive canaries; and
- only bounded synthetic `NOOP` and `TEST_SLEEP` handlers can run in the Phase 2 test build, with no network or arbitrary filesystem access.

Phase 9 release chaos testing must repeat the transaction-boundary cases with actual process termination on the signed production bundle. That test is intentionally distinct from the deterministic foundation gate and is not claimed here.

## Consequences

The task engine favors inspectability and recovery over maximum local throughput. One writer and four Phase 2 workers are ample for foundation tests and easy to reason about. Later provider, browser, OCR, model, and evidence handlers must supply typed manifests, privacy classifications, cancellation checkpoints, retry policy, and idempotent reconciliation before entering the registry.
