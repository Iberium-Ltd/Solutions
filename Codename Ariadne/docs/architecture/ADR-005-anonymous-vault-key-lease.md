# ADR-005: Anonymous Vault-Key Lease

- Status: Accepted and implemented for the completed Phase 2 local foundation
- Date: 2026-07-11
- Decision owners: Desktop, core-service, security, and packaging engineering
- Scope: one-way release of a Keychain-custodied database key for one create or
  unlock operation from the Rust shell to one Python sidecar process

## Context

ADR-002 assigns production Keychain custody to the Rust shell while Python owns
the SQLCipher connection. The sidecar therefore needs a narrow way to receive
one 32-byte database key while creating a vault or after an authorised unlock,
without exposing that key to the webview or the logical HTTP API.

The existing channels have different purposes:

- anonymous stdin carries the one-shot process bootstrap record and then closes;
- stdout carries one bounded readiness record before it is drained;
- stderr is drained as redacted diagnostics; and
- the packaged HTTP API runs over a private Unix-domain socket and carries only
  route-specific application contracts.

Reusing any of them for a vault key would mix trust purposes and enlarge the set
of parsers, middleware, buffers, and error paths that can observe key material.
Passing a key in argv, an environment variable, a temporary file, a socket path,
or webview state is prohibited.

The selected PyInstaller one-file sidecar adds a process-topology constraint.
Rust directly spawns the outer bootloader, which starts the inner process that
runs Python. A handoff must survive that transition without treating a
filesystem pathname or a PID supplied by either process as authentication.

## Decision

### Dedicated anonymous channel

For each packaged sidecar launch, Rust creates a connected anonymous Unix
`SOCK_STREAM` socket pair. One endpoint stays in Rust. Only the other endpoint
is intentionally inherited by the sidecar at descriptor **198**.

The channel is dedicated to exactly one authorised `DATABASE_CREATE_V1` or
`DATABASE_UNLOCK_V1` operation. It is not an application API, generic secret
broker, event stream, or reusable control channel. Phase 2 does not use it for
backup keys, connector secrets, signing keys, or arbitrary Keychain items. A
later operation type requires an explicit protocol and threat-model revision.

Both descriptors are created with `FD_CLOEXEC`. Before spawning, Rust verifies
that the child soft descriptor limit admits descriptor 198 and reserves that
exact number without overwriting an existing descriptor. If the socket endpoint
is not already 198, `F_DUPFD_CLOEXEC` is called with 198 as its minimum and must
return exactly 198; a higher result proves the target was occupied and fails the
launch. Rust then closes the superseded source endpoint.

The child's `pre_exec` hook performs one async-signal-safe operation: `fcntl`
clears `FD_CLOEXEC` on descriptor 198 in the child process only. Any failure
prevents the sidecar from starting. Reserving the descriptor before spawn avoids
a check-then-`dup2` collision with another thread in the Tauri process.

The parent endpoint and every unrelated descriptor remain close-on-exec. Rust
drops its copy of the sidecar endpoint immediately after a successful spawn and
closes both endpoints on spawn failure. Descriptor 198 is a fixed part of the
packaged protocol; it is not announced through argv or the environment and
there is no alternate-descriptor fallback.

Python validates descriptor 198 before accepting normal operation. It must be a
connected Unix stream socket, its peer effective UID must equal the process
effective UID, and it must not alias stdin, stdout, or stderr. Python immediately
sets `FD_CLOEXEC` on descriptor 198 before importing or starting code that may
spawn a worker. A missing, closed, wrong-type, or unsafe descriptor terminates
packaged startup with a generic error.

Development may exercise the same protocol using synthetic keys and a supervised
Python process. A development TCP route is never a key-handoff fallback.

### PyInstaller process caveat

The pinned PyInstaller 6.21.0 POSIX one-file bootloader currently forks and
executes the inner application without blanket-closing non-`CLOEXEC`
descriptors. Descriptor 198 therefore reaches the inner Python process. The
outer bootloader also retains a duplicate of that endpoint until it exits.

The duplicate has three consequences:

- Rust cannot use EOF as proof that Python consumed or closed the channel;
- macOS peer-PID information for a socket pair created before the fork does not
  identify the inner Python process reliably; and
- every transition requires an explicit frame and a local timeout.

Possession of the inherited endpoint, the fresh launch nonces, and the validated
packaged binary form the process binding. Peer PID is diagnostic only and is
never an authorisation input. PyInstaller descriptor behaviour is an observed,
pinned packaging property rather than a stable public API, so every freezer
upgrade must re-run the packaged descriptor and lifecycle tests.

### Binary framing

The lease channel carries binary frames only. It never carries JSON, UTF-8 key
text, hexadecimal key text, base64, HTTP, or newline-delimited records.

Every frame begins with this 16-byte network-byte-order header:

| Offset | Size | Field | Rule |
|---:|---:|---|---|
| 0 | 4 | Magic | ASCII `AKL1` |
| 4 | 1 | Protocol major | exactly `1` |
| 5 | 1 | Message type | one closed enum value |
| 6 | 2 | Flags | exactly zero |
| 8 | 4 | Payload length | exact length for the message type |
| 12 | 4 | Sequence | exact state-machine sequence |

No complete frame may exceed 256 bytes. Receivers use bounded `read_exact` /
`recv_into` loops and reject truncation, trailing bytes, unknown types, unknown
flags, wrong lengths, wrong direction, or extra frames. A frame is never logged
or included in an error. There is no secret-bearing error frame.

Canonical binding fields are:

- the 16-byte startup nonce already authenticated by the stdin bootstrap;
- a fresh 32-byte sidecar lease nonce generated for `HELLO`;
- a fresh 16-byte transaction identifier generated by Rust;
- the exact 16-byte vault UUID;
- the 32-byte digest of the validated canonical vault manifest;
- the exact canonical 42-byte `kc:v1:<hyphenated UUID>` database-key reference;
- the unsigned 32-bit key version; and
- the unsigned 16-bit operation code: `DATABASE_CREATE_V1 = 1` or
  `DATABASE_UNLOCK_V1 = 2`.

Rust and Python construct a canonical binding in that order and compute its
SHA-256 binding digest. `REQUEST` and `GRANT` repeat the full binding rather than
depending on ambient state. `PREPARED`, `COMMIT`, and `COMMITTED` repeat the
startup nonce, lease nonce, transaction identifier, and binding digest. The
32-byte database key appears only as the final fixed-width field of `GRANT` and
is excluded from every digest and acknowledgement.

The exact message types, sequences, and payload layouts are:

| Type | Sequence | Payload, in order | Payload bytes |
|---:|---:|---|---:|
| `HELLO = 1` | 0 | startup nonce (16), lease nonce (32) | 48 |
| `REQUEST = 2` | 1 | canonical binding | 160 |
| `GRANT = 3` | 2 | canonical binding (160), raw key (32) | 192 |
| `PREPARED = 4` | 3 | startup (16), lease (32), transaction (16), binding digest (32) | 96 |
| `COMMIT = 5` | 4 | startup (16), lease (32), transaction (16), binding digest (32) | 96 |
| `COMMITTED = 6` | 5 | startup (16), lease (32), transaction (16), binding digest (32) | 96 |

The canonical binding is exactly 160 bytes: startup nonce (16), lease nonce
(32), transaction identifier (16), vault UUID (16), manifest SHA-256 digest
(32), database-key reference ASCII bytes (42), key version as unsigned 32-bit
network order (4), and operation as unsigned 16-bit network order (2). There is
no outer length prefix, acknowledgement frame, denial frame, revocation frame,
variable-width field, or extension area in version 1. A failure closes and
poisons the channel without sending key material or a secret-bearing error.

### Authorisation and exact vault binding

React invokes a route-specific Rust create command with a bounded display name,
or an unlock command with a previously issued opaque vault handle. It cannot
provide a path, vault identifier, Keychain reference, manifest digest, key
version, descriptor, transaction identifier, or key bytes.

For create, Rust chooses the vault UUID, private location, two fresh opaque key
references, format version, and database-key version. Rust and Python
independently construct the same canonical initial manifest, and Python also
requires an empty safe destination before sending `REQUEST`. Rust creates the
database and backup Keychain items only for that exact pending transaction and
deletes both if creation does not commit. Only the database key crosses the
lease channel; the backup key remains in shell custody.

Before arming an unlock transaction, Rust resolves the handle to a private,
validated vault location and independently parses the canonical manifest. It
requires safe ownership, file type, permissions, vault UUID, key-reference
namespace, and key version. Rust then sends only the safe transaction identifier
and vault operation context over the authenticated logical API so Python can
perform its independent manifest validation.

Python may send `REQUEST` only after that route-specific preparation succeeds.
Rust compares every request binding byte with its independently authorised
transaction. It never treats a Python-supplied Keychain reference as sufficient
authority and never fetches an arbitrary item requested by the webview or
sidecar. Any mismatch consumes the channel, leaves the vault locked, and fails
the sidecar.

Only after the exact comparison succeeds may Rust create or fetch the bound
macOS Keychain item. Keychain denial, cancellation, absence, duplicate create,
wrong length, or an expired transaction sends no `GRANT`; Rust zeroizes any
returned material, closes the channel, and fails locked.

### Lease state machine

The only successful sequence is:

| Sequence | Frame | Direction | Required effect |
|---:|---|---|---|
| 0 | `HELLO` | Python → Rust | Bind descriptor 198 to the startup nonce and fresh lease nonce before packaged readiness is accepted |
| 1 | `REQUEST` | Python → Rust | Request the one authorised database-key binding after independent manifest validation |
| 2 | `GRANT` | Rust → Python | Deliver exactly one 32-byte key for that binding |
| 3 | `PREPARED` | Python → Rust | Confirm SQLCipher opened, authenticated, and verified the expected vault without exposing unlocked operations |
| 4 | `COMMIT` | Rust → Python | Confirm that the original user command and lock policy still authorise publication |
| 5 | `COMMITTED` | Python → Rust | Publish the unlocked state and confirm the transaction, after which both sides close the channel |

The states are correspondingly `AWAIT_HELLO`, `IDLE`, `AWAIT_REQUEST`,
`AWAIT_GRANT`, `AWAIT_PREPARED`, `AWAIT_COMMIT`, `AWAIT_COMMITTED`, and
`CONSUMED`. Only one transition is legal from each state. Duplicate, replayed,
out-of-order, cross-direction, or post-`CONSUMED` input is fatal.

Python stages the verified SQLCipher engine before `PREPARED` but does not make
it available to request handlers or workers. EOF, cancellation, timeout, or
parent loss before `COMMIT` disposes the staged engine and wipes its application
buffers. After sending `COMMIT`, Rust waits for `COMMITTED`; if that result is
ambiguous, it may query the authenticated session route once. If the committed
state cannot be proved, Rust terminates the sidecar rather than guessing.

No protocol retry occurs on the consumed channel. A failed key-bearing attempt
requires a new sidecar process, bootstrap token, startup nonce, socket pair,
lease nonce, and transaction identifier.

### Monotonic bounds and replay resistance

Each process enforces deadlines with its own local monotonic clock. No wall-clock
timestamp or serialised monotonic value is trusted across the boundary.

Initial bounds are deliberately small and named constants:

- `HELLO`: within the bounded 30-second supervisor startup deadline; the packaged-app acceptance gate remains stricter and requires readiness within 20 seconds;
- prepared create or unlock to `REQUEST`: 30 seconds, allowing bounded cold
  request dispatch from an external volume before any key is fetched;
- Keychain authorisation: 120 seconds, with a late platform result discarded;
- successful Keychain return to complete `GRANT`: 2 seconds;
- `GRANT` to `PREPARED`: 5 seconds;
- `PREPARED` to `COMMIT`: 2 seconds; and
- `COMMIT` to `COMMITTED`: 2 seconds.

The database key is not created or fetched while waiting for unrelated UI
approval. A Keychain interaction may use the separate 120-second authorisation
bound; the short key-bearing deadline begins only after Keychain successfully
returns. Timeout values may change only with tests and an ADR amendment; timeout
failure never selects a weaker transport.

Replay is rejected by the fresh startup nonce, lease nonce, transaction
identifier, exact sequence, exact binding, single accepted `GRANT`, channel
closure, and mandatory process replacement after the lease ends.

### Memory handling and SQLCipher requirement

Rust keeps Keychain results in fixed-size `Zeroizing<[u8; 32]>` storage, writes
directly from that storage, and drops it immediately after the key-bearing
transaction resolves. Debug and display implementations remain redacted.

Python receives `GRANT` into a preallocated mutable `bytearray`/`memoryview`,
copies only where the SQLCipher API requires it, and overwrites every
application-owned receive, staging, and retained-key buffer on all success and
failure paths. Immutable `bytes`, `str`, hexadecimal, base64, formatted SQL, and
exception copies of the key are prohibited.

The production SQLCipher binding must expose a mutable byte-buffer key method
backed by `sqlite3_key` or `sqlite3_key_v2`, or an equivalently reviewed native
API. Constructing `PRAGMA key` with `bytes(key).hex()` or a formatted string does
not meet this decision because Python cannot reliably overwrite those immutable
objects. The new handoff cannot be marked complete while that string-based path
remains.

SQLCipher necessarily retains derived key state while connections are open.
Lock therefore stops new work, drains or cancels bounded operations, closes all
connections, disposes the engine, and only then overwrites application buffers.
Zeroization is a best-effort memory-hygiene control, not protection from a
process already running with the user's privileges.

### Lock and process replacement

The successful lease ends when `COMMITTED` closes the handoff channel, but the
authorised key use lasts only for the current unlocked sidecar process.

On manual lock, auto-lock, profile switch, application background policy, or
shutdown:

1. Rust rejects new vault commands and revokes reveal, file, and event
   capabilities.
2. Python enters `LOCKING`, stops claims, drains or cancels bounded work, closes
   decrypted streams and SQLCipher connections, and wipes mutable key buffers.
3. Rust terminates the old sidecar under the bounded supervisor policy and does
   not report `LOCKED` to the webview until old-process exit is confirmed.
4. If the application remains open, Rust starts a fresh locked sidecar with a
   new bootstrap token and a new anonymous descriptor-198 channel.

Re-unlock never reuses the old process or channel. If graceful lock fails, Rust
force-terminates the owned process and reports a safe local failure; operating
system process teardown is not described as verified application zeroization.

### Exclusion from observable surfaces

The raw key must never appear in:

- argv, environment variables, stdin, stdout, stderr, process titles, or URLs;
- HTTP or ASGI request/response bodies, headers, middleware, OpenAPI, or events;
- runtime files, Unix-socket pathnames, readiness records, logs, traces, crash
  metadata, metrics, diagnostics, screenshots, fixtures, or Git;
- Tauri command inputs/results, JavaScript memory, webview storage, clipboard,
  accessibility labels, or rendered UI; or
- manifest fields, binding digests, acknowledgements, error messages, or test
  snapshots.

Only synthetic random canaries may be used to exercise this exclusion contract.

## Alternatives considered

### Reuse the stdin bootstrap pipe

Rejected. Stdin has a one-record-and-EOF authentication contract. Keeping it
open would mix process authentication with later key custody, provide no native
duplex commit acknowledgement, and encourage text/base64 key copies.

### Two dedicated anonymous pipes

Rejected. A request and acknowledgement protocol needs two pipes, more
descriptor lifecycle handling, and manual half-close semantics while providing
no advantage over one full-duplex socket pair.

### One-time filesystem Unix socket with peer-PID checks

Rejected for the primary path. It creates a discoverable same-user namespace,
accept/race/cleanup cases, and PID-lineage complexity across the PyInstaller
outer and inner processes. macOS peer credentials can strengthen such a socket,
but a pre-connected inherited endpoint is narrower. A named socket is not a
fallback if descriptor inheritance fails.

### Deliver the key over HTTP on the application UDS

Rejected. It would add a secret-bearing route and expose the key to HTTP
framing, ASGI middleware, request buffering, schema/error handling, and a
long-lived socket reachable by other processes under the same user account.

### Argv, environment, temporary file, shared memory name, or webview relay

Rejected. These surfaces are easier to inspect, inherit, log, persist, race, or
accidentally include in diagnostics. The webview is never a key custodian.

### Let Python read the Keychain directly

Rejected. It would duplicate macOS custody policy and entitlements in the
less-privileged sidecar, weaken the reviewed Rust capability boundary, and make
arbitrary reference requests harder to prevent.

### Reusable multi-operation key channel

Rejected for Phase 2. Reuse adds re-key, replay-window, concurrency, cancellation,
and stale-state complexity. One operation per channel plus sidecar replacement
on lock is simpler to audit and invalidates every old capability together.

## Verification requirements

The current automated implementation proves native idle/focus policy, a finite
macOS elapsed-input query, coalesced system-lock revocation, authorization checks
after delayed key retrieval and before `GRANT`, locked sidecar replacement, and
the real Rust↔Python lifecycle with a blocking synthetic custodian. Physical
sleep/wake, the real macOS Keychain dialog, the complete crash matrix, and
production signing/clean-machine evidence remain Phase 9 release work. The
applicable automated foundation requirements below pass.

The Phase 2 local-foundation tests prove all of the following:

- Rust gives only the intended sidecar endpoint descriptor 198, retains only
  its peer, keeps unrelated descriptors close-on-exec, and fails safely when
  descriptor 198 is unavailable or outside the soft limit.
- Python rejects a missing, closed, wrong-type, unconnected, wrong-UID, or
  inheritable-after-initialisation descriptor and does not pass descriptor 198
  to any worker or subprocess.
- The exact packaged PyInstaller outer/inner topology carries descriptor 198 to
  Python; tests do not depend on peer PID or EOF while the outer duplicate lives.
- Every frame direction, length, sequence, nonce, binding field, digest, timeout,
  partial read/write boundary, duplicate, replay, and trailing-byte case fails
  closed unless it is the single canonical sequence.
- A Python `REQUEST` cannot select a different vault, manifest, reference,
  version, operation, or transaction than Rust independently authorised.
- Keychain denial, cancellation, absence, wrong-length data, late completion,
  write failure, wrong key, corrupt vault, and SQLCipher verification failure
  never produce an unlocked state or a retry on the same channel.
- Loss of `PREPARED`, `COMMIT`, or `COMMITTED` cannot leave an unconfirmed
  unlocked sidecar; ambiguity is resolved by authenticated state or termination.
- A synthetic key canary is absent from argv, environment, stdin, HTTP,
  stdout/stderr, files, logs, traces, errors, diagnostics, screenshots, webview
  state, and packaged resources.
- The SQLCipher adapter accepts mutable key bytes without hexadecimal, formatted
  SQL, or immutable Python key copies, and all application-owned buffers are
  overwritten on injected success and failure paths.
- Concurrent unlock, lock-during-unlock, manual/automatic/system lock,
  application quit, parent crash, startup child exit, rejected readiness, and
  ready Python-child crash leave no old usable session, descriptor, endpoint,
  socket, or runtime directory within the tested local boundary.
- A successful lock confirms old-process exit and a re-unlock uses a fresh
  process, session token, startup nonce, socket pair, lease nonce, and
  transaction identifier.
- The packaged application still opens zero TCP listeners and never falls back
  to development transport.

The packaging gate runs against the frozen arm64 sidecar inside the Tauri
`.app`, not only an unfrozen Python process. Every PyInstaller upgrade repeats
the descriptor tests. Production also requires hardened runtime, no debug
`get-task-allow` entitlement, the same Developer ID through freezer contents,
sidecar, Tauri executables, and final bundle, notarisation/stapling, and a clean
macOS 14 launch. The local ad-hoc packaging overlay that disables hardened
runtime is not evidence for this release gate.

Physical sleep/wake, the real platform-Keychain dialog, bootloader-specific
chaos timing, Developer ID/hardened-runtime signing, notarisation/stapling, and
clean macOS 14 execution remain mandatory Phase 9 checks and are not claimed by
the Phase 2 result.

## Consequences and residual risk

The decision creates a small macOS-specific binary protocol and one intentional
inherited descriptor. In return, key bytes bypass every long-lived application
transport and every frontend surface, while commit ambiguity, replay, and lock
are reduced to a finite state machine that can be exhaustively tested.

Sidecar restart on lock adds bounded startup latency and requires durable jobs to
recover according to ADR-004. That cost is accepted because it rotates the API
credential and destroys the old key channel and Python process together.

The protocol does not protect a vault already unlocked inside a process that is
readable by same-user malware, a debugger with sufficient entitlement, root, or
a compromised operating system. Production signing, hardened runtime, removal
of debug entitlements, auto-lock, short key-bearing deadlines, and best-effort
buffer clearing reduce exposure but cannot eliminate that residual risk.
