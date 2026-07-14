# Ariadne Core

Status: The current source contains 48 operations across 46 paths. Its full aggregate, frozen-sidecar, local package lifecycle, and targeted browser gates pass under fresh identities; production signing remains release work.

This package contains the Python 3.12 sidecar, authenticated local transport,
generated contracts, SQLCipher persistence through schema `0008`, durable job
foundations, vault-key lease, deterministic intake/graph/query-policy workflows,
selectable loopback local AI plus optional OpenAI Responses with cited corpus/
workspace reasoning, bounded public/HIBP discovery, deterministic non-executing
investigation planning, atomic capture, exact provenance, Phase 5 findings/evidence/
attribution, Phase 6 audit/remediation/checkpoints, and local report generation.

It does not implement broad operational providers, authorised account
connectors, scheduled snapshot ingestion, retention/purge, or durable report
retention/destination handling. Discovery is limited to the explicit current
providers and cannot bypass authentication, CAPTCHA, paywalls, plan gates,
domain verification, rate limits, or other access controls.

The desktop advanced query composer is local presentation logic and adds no
core route. Browser-provider handoffs are user-opened; Core does not scrape or
automatically import their results or evidence.

## Current API surface

The CLI exposes exactly 48 authenticated route-specific operations (4 GET,
44 POST; 46 paths): foundation/session/vault/event replay, profile/intake/entity/
graph, local/optional OpenAI analysis, network-free query planning, public/HIBP
discovery, deterministic investigation planning, public capture,
Phase 5 findings/evidence/attribution, Phase 6 audit/remediation/checkpoints,
and local report generation.
The exact list and limits are documented in `docs/api.md` and generated into
OpenAPI, TypeScript, and Rust allowlists under `packages/contracts`.

All operations require the per-launch session, contract version, canonical
request ID, exact Host, and exact Origin. The service rejects forwarded headers,
replayed IDs, wrong tokens, unexpected origins, and out-of-bound requests.
Runtime API documentation is disabled.

## Development bootstrap

From the repository root:

```sh
scripts/bootstrap_core.sh
```

This installs the locked uv workspace and verifies the development SQLCipher
DB-API. For rapid local tests only, that extension links the target Mac's
Homebrew SQLCipher. It is not copied into a package and is never a release
input.

The sidecar itself accepts no unauthenticated convenience launch. It requires a
single bounded bootstrap record on stdin. The Rust debug supervisor and the
integration harness generate that record; do not place a session token,
database key, backup key, or vault path in arguments, environment variables,
logs, fixtures, or frontend state.

Run the current verification suite with:

```sh
make core-lint
make core-typecheck
make core-test
make contracts-check
```

The live integration tests exercise a random `127.0.0.1` development port and
a private `0700` runtime directory containing a `0600` Unix socket. Packaged
Tauri use is UDS-only; development loopback is not a release fallback.

## Reproducible packaging proof

Release-oriented packaging does not reuse the Homebrew-linked development
extension. Build the pinned SQLCipher 4.17.0 / SQLite 3.53.3 CommonCrypto
package with:

```sh
make sqlcipher-package-spike
```

Build and verify the current CLI as a pinned PyInstaller arm64 sidecar with:

```sh
make frozen-sidecar-spike
```

Both targets write to fresh `/tmp` directories by default and print their
output paths. The frozen-sidecar target rebuilds the CommonCrypto driver,
exports locked runtime dependencies, substitutes the verified driver, freezes
`ariadne_core.cli`, inspects the Mach-O/archive, and exercises authenticated
capabilities, session, replay denial, wrong-token denial, Origin denial,
shutdown, and UDS cleanup.

The result is accepted only after its own gate. The current 48-operation source
completed this workflow under the exact identities below. See
`scripts/package-sidecar/README.md` for pinned inputs and measured evidence.

## Local Tauri packaging-spike integration

After `freeze_pyinstaller.sh` completes, stage its inspected output and build
the local Tauri overlay:

```sh
make stage-frozen-sidecar FROZEN_OUTPUT_ROOT=...
make package-spike-app
make package-spike-app-check
```

Staging copies the digest-verified target-suffixed executable into the ignored
`apps/desktop/src-tauri/binaries` directory. The ordinary Tauri configuration
does not acquire an unverified binary; `tauri.packaging-spike.conf.json` is an
explicit local overlay that adds the staged external binary.

The completed check launched the packaged `.app`, observed the Rust supervisor
complete its authenticated capabilities handshake over a private UDS, and
proved a user-owned `0700` runtime directory, `0600` socket, zero TCP listeners
for the app and both PyInstaller processes, no inherited probe/session material
in the sidecar environment, and removal of processes, socket, and directory
after both requested quit and abrupt parent termination.

The current staged 48-operation sidecar is 20,946,896 bytes with SHA-256
`5ca6b790878cc7f77b99cc21e75e49c2febf8208dccbf87cb523669515262df3`.
Ad-hoc packaging produced a 20,946,880-byte arm64/minimum-macOS-11 sidecar with
SHA-256
`4ba7fd0a6f99135b96f412a4371c5f7783ffb6c4ae5cbe6ac1f8fd82d36d324b`
and a 16,979,744-byte arm64/minimum-macOS-14 desktop executable with SHA-256
`ca68fdd4957c7540716f4e7a9b0d54cea657e44cb2bdf68cc012d67cada3d3ec`.
Requested quit and abrupt-parent startup completed in 3,290/2,550 ms with exit
0/-9; both runs used two sidecar processes, cleaned up fully, opened zero TCP
listeners, preserved `0700`/`0600` runtime modes, and passed deep strict ad-hoc
bundle verification.

The historically verified staged 45-operation sidecar is 20,892,240 bytes with SHA-256
`b33e411e95c4147ed3a16fe7894f490bcb47884c23703a1888f648638267831f`.
Ad-hoc packaging produced a 20,892,224-byte arm64/minimum-macOS-11 sidecar with
SHA-256
`536c16a851d11676438899b5edc07de2bef11efa704648618149581602f8e82f`
and a 16,435,024-byte arm64/minimum-macOS-14 desktop executable with SHA-256
`d3eef7bac068674849b9c3489caafe4887f76d6b53ed90d48b202276c711819f`.
Requested quit and SIGKILL startup completed in 6,974/5,511 ms with exit 0/-9;
both runs used two sidecar processes, cleaned up fully, opened zero TCP
listeners, preserved `0700`/`0600` runtime modes, and passed deep bundle plus
strict main/sidecar ad-hoc signature verification.

Those exact identities prove only the historical 45-operation local candidate
and have not been relabelled. The current identities above prove the
48-operation local candidate. This is a local ad-hoc packaging proof. Its overlay intentionally disables
hardened runtime because Tauri's ad-hoc re-sign of the one-file PyInstaller
binary caused its extracted `libpython` to fail Team-ID library validation.
Production must not copy that exception: it must keep hardened runtime enabled
and sign the freezer contents, frozen sidecar, Tauri binaries, and final bundle
with the same Developer ID before notarisation and clean-machine verification.

## Current result and remaining release work

Rust now hands one authorised database key to Python through anonymous FD 198.
Synthetic real-process tests cover create, lock/restart, delayed-Keychain
revocation before `GRANT`, locked restart, unlock, and system lock/restart. The
native React shell also consumes narrow profile/intake/graph/AI/query/discovery/
HIBP/investigation-plan/findings/checkpoint/comparison/remediation/report projections; unsupported
browser and audit surfaces remain explicitly synthetic.

HIBP and OpenAI credentials are request-ephemeral and excluded from persistent
settings. OpenAI Responses requires an explicit model ID, uses `store: false`,
validates strict structured output, and remaps citations to exact local sources.
The direct official HIBP synthetic smoke succeeded with one exact source; the
public test key correctly received HTTP 401 from the plan-gated k-anonymity
endpoint. No real paid OpenAI-key live result is claimed.

The Rust supervisor also detects an unexpected ready-child exit and performs a
locked restart under a three-attempt rolling budget. Authenticated event replay
now reads bounded, payload-free references from the encrypted outbox; a native
relay retains the opaque cursor and emits only closed safe variants. Durable
synthetic jobs now enforce lease ownership/revisions, cover principal
pause/cancel/retry recovery races transactionally, and use a bounded migrated
dependency DAG with recursive-CTE cycle rejection. Transaction-fault tests now
cover create, claim/attempt, progress, and completion rollback without false
success; startup child exit and readiness rejection revoke state and terminate
the owned child.

The Phase 2 local-foundation gate passes. Physical sleep/wake, real-Keychain
validation, production key rotation, hardened-runtime nested signing with one
Developer ID, notarisation/stapling, clean macOS 14 validation, and production
chaos testing remain explicit Phase 9 gates before real-data use. Packaged mode
remains UDS-only and must never
fall back to development TCP.
