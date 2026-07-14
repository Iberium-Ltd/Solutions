# ADR-003: Core IPC and Sidecar Lifecycle

- Status: Accepted for the Phase 2 local foundation
- Date: 2026-07-11
- Decision owners: Desktop, core-service, security, and contract engineering
- Scope: Tauri-to-Python transport, authentication, supervision, and event relay

## Context

The webview must not gain direct filesystem, Keychain, database, provider, or arbitrary local-service access. A browser tab or same-network host must not be able to call Ariadne Core. At the same time, the React client needs typed commands and redacted live state without learning service credentials or transport details.

The packaged application and browser-based development environment have different transport needs. Treating loopback HTTP as a permanent release shortcut would add Host, Origin, browser, firewall, and local-port exposure that the packaged application does not need.

## Decision

### Ownership boundary

Rust owns sidecar discovery, process launch, process identity, startup credentials, Keychain mediation, filesystem broker tokens, request authorization, lifecycle, and the Tauri event relay. Python owns typed domain validation and the local service. React invokes only route-specific Tauri commands generated or reviewed against the API contract.

The webview never receives a socket path, bearer token, Keychain handle, database key, arbitrary URL, arbitrary method, or generic request primitive. A single generic `invokeCore(method, path, body)` command is prohibited.

### Packaged transport

The packaged arm64 application exposes no core TCP listener. Rust creates a fresh private runtime directory under the macOS per-user temporary directory, validates that the parent is local and user-owned, and sets the child directory to mode `0700`. The directory uses a short random name so the final Unix-domain socket path remains safely below the macOS `sun_path` limit. Python binds `core.sock` inside it with mode `0600` and refuses symlinks, non-socket replacement, unexpected ownership, or permissive modes.

Only the Rust parent receives the runtime path. Cleanup removes a socket or directory only after verifying ownership, type, and the per-launch identity marker; it never recursively removes an unverified path. A stale verified directory from an earlier crash may be quarantined and removed during supervised startup.

Logical `/v1` HTTP semantics may be carried over ASGI on the Unix socket, but this is an internal framing choice. It cannot change the generated route allowlist, expose a generic proxy, or bind a release TCP port.

### Per-launch authentication

Rust generates a fresh uniformly random 256-bit session token for every sidecar process. It transmits one bounded base64url startup record through the child's anonymous stdin pipe, flushes it, and closes the pipe. The token is never placed in argv, environment variables, a file, process title, URL, webview storage, crash metadata, or logs.

The sidecar accepts startup only when stdin is a pipe, the record has the exact version and length, decoding yields 32 bytes, and EOF follows the record. Malformed, repeated, missing, or timed-out startup input terminates the process. The token remains memory-only and is compared in constant time on every request and event subscription. Restarting the sidecar invalidates the previous token.

The token authenticates the Rust parent to this sidecar instance; it is not a vault key and grants no Keychain authorization by itself. Vault lock state, resource scope, reveal capabilities, and command policy remain independent checks.

### Route-specific Rust commands

Each exposed Tauri command binds:

- one logical API method and route template;
- request and response schema hashes and contract major version;
- maximum request, response, and collection sizes;
- required vault lock state and resource scope;
- idempotency and revision requirements; and
- reveal or authorization class, when applicable.

Rust rejects method substitution, unknown routes, arbitrary headers, oversized payloads, stale generated contracts, and invalid file/reveal tokens before forwarding. It attaches the core session token, contract version, request ID, and safe idempotency metadata. Python independently validates the same domain and privacy constraints; Rust validation is not treated as sufficient authorization.

Responses are decoded against the bound schema before reaching JavaScript. Transport errors and sidecar exits become typed, redacted local errors. Raw Python tracebacks, headers, paths, response bodies, and credentials never cross into the webview.

### Development transport

Browser development may start an explicitly development-mode service on an operating-system-assigned random port bound to `127.0.0.1` only. It uses the same 256-bit per-launch token, exact Host and Origin allowlists, no wildcard CORS, authenticated events, short expiry, request-size limits, and disabled interactive API documentation unless a separate developer flag enables it.

Development mode refuses non-loopback bind addresses and is unavailable in a packaged release. It is not a fallback when Unix-socket startup fails.

### Startup and compatibility handshake

Rust spawns exactly the packaged sidecar binary, with no shell interpretation, and passes only non-secret fixed arguments such as protocol mode. Startup has a bounded deadline. Before the UI may open a vault, Rust performs an authenticated capabilities handshake and verifies:

- logical API and event-contract compatibility;
- sidecar build identity and expected feature set;
- packaged SQLCipher/SQLite compatibility;
- transport mode and lock state; and
- that no unexpected TCP listener was created.

An incompatible or unhealthy sidecar leaves the application in a local recovery screen. It does not expose development transport or weaken authentication.

### Supervision and shutdown

Rust is the sole sidecar supervisor and retains the child handle. Unexpected exit records only a stable reason code and exit class. Automatic restart is bounded to three attempts in a rolling 60-second window with backoff; exceeding the budget stops restart and presents a recoverable service-unavailable state. Durable job recovery follows ADR-004, so process restart is never treated as proof that a job failed or succeeded.

On vault lock, Rust revokes reveal/file capabilities and closes decrypted streams before acknowledging the locked state. On application shutdown it stops accepting commands, requests graceful sidecar shutdown, waits up to five seconds, sends termination if needed, waits a further two seconds, then force-terminates the owned child as a last resort. It verifies process exit and cleans only its verified runtime directory.

The sidecar must support macOS `spawn` semantics and frozen-executable startup. It must not daemonize, outlive the parent intentionally, inherit unrelated file descriptors, or discover secrets through the environment.

### Event relay

Rust holds one authenticated event subscription for the active unlocked vault and relays only generated, schema-validated, bounded, redacted event variants through a dedicated Tauri channel. The webview receives event IDs and safe resource references, not the core credential or transport cursor. Reconnect uses the encrypted outbox and an opaque cursor retained by Rust. Duplicates are tolerated by event ID; gaps trigger a scoped resource refetch.

Lock, profile switch, application background policy, contract mismatch, or sidecar restart closes or re-establishes the subscription with new authorization. Events never become the source of truth.

## Alternatives considered

### Direct webview-to-FastAPI access

Rejected. It would expose credentials and a general local API to browser-origin threats and bypass Tauri capability mediation.

### Packaged loopback HTTP

Rejected. The application does not need a release TCP listener. Unix-socket permissions and a private runtime path provide a narrower local boundary.

### Generic Rust HTTP proxy

Rejected. A generic proxy turns any frontend compromise into an opportunity to explore the entire core API. Route-specific commands make capability review and negative testing tractable.

### Token in argv, environment, or a temporary file

Rejected. Those channels are more easily inherited, inspected, logged, or left behind. A one-shot anonymous stdin pipe is simpler to bound and leaves no filesystem artifact.

### Unlimited automatic restart

Rejected. Restart loops hide deterministic faults, consume resources, and can repeatedly exercise a corrupt vault. The bounded budget preserves an inspectable failure state.

## Verification requirements

The current implementation detects an actual unexpected ready-child exit,
revokes its endpoint, credential, lease, and unlocked state, and restarts locked.
An injected rolling-window test proves 250/500/1,000 ms backoff and no fourth
attempt within 60 seconds. Startup-child exit and rejected-readiness tests prove
that credentials and capabilities are revoked and the owned child is terminated.
Authenticated event replay now uses the encrypted
outbox, a generated route boundary, a Rust-owned opaque cursor, and a closed
payload-free Tauri relay. Duplicate, gap, expired-cursor, unknown-additive, and
lock/restart-pause tests pass.

The Phase 2 local-foundation gate uses tests to prove:

- packaged builds create only a user-owned `0700` runtime directory and `0600` Unix socket and create no TCP listener;
- long paths, stale sockets, symlinks, regular-file substitution, wrong ownership, and unsafe modes fail closed;
- missing, malformed, short, long, repeated, expired, and prior-launch tokens are rejected;
- no credential appears in webview state, argv, environment, files, logs, traces, or error payloads;
- route, method, schema, lock state, scope, size, idempotency, and reveal mismatches are rejected by Rust and Python;
- no generic proxy command or unlisted Tauri capability is packaged;
- development binds only a random `127.0.0.1` port with exact Host/Origin rules and cannot be enabled in release mode;
- handshake timeout, incompatibility, crash, restart budget, graceful shutdown, forced shutdown, and parent exit behave deterministically;
- authenticated event replay handles duplicates, gaps, cursor expiry, unknown additive variants, and lock/restart; and
- the frozen arm64 sidecar launches on macOS 14-compatible packaging without inheriting unrelated descriptors.

Bootloader-specific chaos timing on a Developer ID-signed/notarised bundle and clean-machine macOS 14 validation remain Phase 9 release gates; the local ad-hoc packaging proof does not claim them.

## Consequences

The decision adds a small amount of Rust command and supervision code for every logical capability, but it prevents the webview from becoming a generic local-service client. Development remains convenient through a tightly constrained loopback mode, while packaged builds have no core TCP exposure.

Any later plugin protocol, remote-control feature, multi-window credential sharing, or alternate transport requires a new ADR and may not weaken the route-specific capability boundary.
