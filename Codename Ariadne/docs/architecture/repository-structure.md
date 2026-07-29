# Repository Structure

Status: Complete 57-operation/55-path source, frozen, and packaged lifecycle gates pass at `0011_profile_purge`; distinct historical package milestones are preserved.

The repository is created incrementally. This tree describes the current
tracked implementation boundaries, not the larger Phase 4+ target and not a
production personal-data or operational-audit release.

```text
.
├── .vscode/
│   ├── extensions.json
│   ├── settings.json
│   └── tasks.json
├── Instructions/
│   ├── ARIADNE_STARTER_PACK_README.md
│   ├── CODEX_MASTER_PROMPT_ARIADNE.md
│   └── private_reference/              # local-only, ignored, never packaged
├── apps/
│   └── desktop/
│       ├── e2e/                        # Chromium/WebKit and visual contracts
│       ├── public/                     # packaged local assets
│       ├── src/
│       │   ├── app/                    # native boundaries and durable workspace coordination
│       │   ├── components/
│       │   ├── pages/                  # 17 accepted Phase 1 routes
│       │   ├── styles/
│       │   └── test/
│       ├── src-tauri/
│       │   ├── binaries/               # ignored, inspected sidecar staging
│       │   ├── capabilities/
│       │   ├── icons/
│       │   ├── src/
│       │   │   ├── core/               # supervisor, event relay, contracts, manifest, key lease
│       │   │   ├── platform.rs         # macOS power/screen/session observers
│       │   │   ├── security/           # macOS Keychain custody boundary
│       │   │   ├── lib.rs
│       │   │   └── main.rs
│       │   ├── Cargo.lock
│       │   ├── Cargo.toml
│       │   ├── tauri.conf.json
│       │   └── tauri.packaging-spike.conf.json
│       ├── package.json
│       └── vite.config.ts
├── services/
│   └── core/
│       ├── migrations/
│       │   └── versions/               # forward-only foundation through candidate 0011
│       ├── src/ariadne_core/
│       │   ├── api/                    # 57 generated local operations at source head
│       │   ├── application/            # vault/intake/identity/query, Phase 5/6, and reporting
│       │   ├── domain/                 # identity/audit/query/evidence/attribution/diff/remediation/reporting
│       │   ├── infrastructure/         # SQLCipher identity/query/Phase 5/6 repositories and logging
│       │   ├── intake/                 # bounded parsers and restricted-value gate
│       │   ├── local_ai/               # disabled loopback-only local-model foundation
│       │   ├── privacy/
│       │   ├── security/               # session, backup, broker, custody ports
│       │   ├── workers/                # bounded synthetic foundation engine
│       │   ├── bootstrap.py
│       │   └── cli.py
│       ├── tests/
│       │   ├── contract/
│       │   ├── integration/
│       │   ├── persistence/
│       │   ├── privacy/
│       │   ├── recovery/
│       │   ├── security/
│       │   ├── unit/
│       │   └── unit_foundation/
│       ├── alembic.ini
│       └── pyproject.toml
├── packages/
│   ├── contracts/
│   │   ├── openapi/                    # generated local API contract
│   │   ├── src/generated/              # TypeScript and Rust allowlist
│   │   └── generate.py
│   └── synthetic-data/                 # invented reusable UI fixtures only
├── scripts/
│   ├── package-sidecar/                # ignored-output packaging proofs
│   │   ├── patches/
│   │   ├── build_sqlcipher_commoncrypto.sh
│   │   ├── freeze_pyinstaller.sh
│   │   ├── inspect_frozen_sidecar.sh
│   │   ├── inspect_sqlcipher_commoncrypto.sh
│   │   ├── runtime_probe.py
│   │   ├── stage_tauri_sidecar.sh
│   │   ├── verify_frozen_sidecar.py
│   │   ├── verify_packaged_app.py
│   │   └── versions.env
│   ├── bootstrap_core.sh
│   └── privacy_check.py
├── artifacts/                          # ignored local evidence and captures
├── docs/
├── Makefile
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml                      # uv workspace root
├── rust-toolchain.toml
└── uv.lock
```

## Current boundaries

- `Instructions/private_reference/` is never a source, fixture, package input,
  test-data directory, or runtime import shortcut.
- `apps/desktop/src` retains the accepted synthetic Phase 1 audit experience.
  Native mode additionally connects profile/intake/entity review, persisted
  Graph, selectable local-AI Settings, network-free Transmission planning,
  profile resume, persisted Findings plus first-finding/writes, Compare plus
  local checkpoints, Removal Tracker, and local Reports. Browser mode and other audit screens remain synthetic; evidence
  viewing/streaming and operational ingestion remain absent.
- The Rust shell exposes only generated route-specific capability/session,
  vault lifecycle, profile list/intake/review/decision/graph, local-AI, local
  query-policy, Phase 5 finding/evidence/decision, Phase 6 audit/remediation,
  and report-generation
  commands. In debug
  builds it supervises the uv-managed Python service over authenticated
  loopback. The completed local packaging spike stages the verified frozen
  binary as an ignored Tauri external binary and supervises it over UDS. React
  invokes no generic proxy.
- `services/core` owns the local domain and security foundation. Its source-head
  surface is 40 authenticated operations: six foundation, seven Phase 3/profile,
  four local-AI, three network-free query-policy, six Phase 5, thirteen Phase
  6, and one report route. General jobs, backup, evidence-byte access,
  operational adapter dispatch/scheduled snapshots, and durable report catalog/
  destination primitives are not UI-facing routes.
- The macOS Keychain custodian and FD-198 lease are wired through Rust commands;
  automated end-to-end lifecycle proof uses a synthetic in-memory custodian so
  it never mutates or prompts for the user's Keychain.
- `packages/contracts` is generated from Pydantic/OpenAPI and supplies the
  TypeScript shapes and Rust route allowlist. Generated files are drift-checked.
- `packages/synthetic-data` is the only reusable development identity source.
  Provider configuration, credentials, and real user data are absent.
- `graph_edge_origins` at migration `0005_graph_edge_origins` binds each support
  or contradiction observation to its vault/profile, graph edge, intake source,
  segment, and extraction run. Duplicate observations deduplicate by keyed HMAC;
  separate sources remain separate provenance. Snapshot responses expose bounded
  counts and samples, not unbounded observation bodies. Legacy migration
  backfills only edges whose joint source/segment/run provenance can be proven
  and fails closed if any live edge cannot be verified.
- Candidate `0006_query_policy_core` adds encrypted provider/run/check/budget/
  approval/ledger persistence. Runtime provider manifests remain network-free,
  local-only, regionless, and unable to send identifiers.
- Candidate `0007_phase5_evidence_attribution` adds immutable SQLCipher-backed,
  profile-scoped findings, bounded originals/derivatives, multi-finding links,
  assessments/signals/missing evidence, and append-only human decisions.
  `infrastructure/db/phase5_repository.py` owns durable writes and reads;
  `application/phase5.py` exposes metadata-only projections plus bounded manual
  first-finding/neutral-assessment bootstrap, import, caller-redacted derivative,
  and append-only human-decision mutations
  through generated routes, strict Rust commands, `app/phase5Boundary.ts`, and
  native Findings views. Automated capture, assessment creation, evidence
  streaming, retention, and purge remain absent.
- Candidate `0008_phase6_audit_remediation` adds ten immutable SQLCipher-backed,
  profile-scoped audit snapshot/finding/coverage and remediation revision/
  finding/evidence/provider-response/history tables. `phase6_repository.py`
  verifies canonical payload hashes and exact profile references, and returns
  the full persisted interval for selected nonadjacent comparisons. Generated
  Python/Rust/TypeScript boundaries drive native Compare and Removal Tracker
  reads plus local revision-CAS remediation mutations. The current package adds
  a user-triggered contentless checkpoint route; there is still no scheduled or
  provider-driven snapshot ingestion and no outbound send/submit/dispatch command.
- Candidate `0009_identity_discovery_engine` and
  `0010_identity_ai_provenance` add persistent named-person knowledge, audit
  configurations, durable frontier tasks/attempts/results, exact-source leads,
  review proposals, receipts, cited AI analyses, and canonical promotion
  origins. The People workflow resumes from SQLite rather than route-local form
  state and executes seven bounded public surfaces automatically.
- Candidate `0011_profile_purge` retains normal Phase 5/6 immutability while
  permitting one exact-name/revision-confirmed whole-profile purge. The
  repository deletes profile-scoped rows and linked jobs/idempotency results
  transactionally, enables secure deletion, and vacuums after commit.
- `domain/reporting.py`, `application/reporting.py`, and
  `application/reporting_projection.py` generate bounded deterministic JSON and
  inert Markdown from persisted profile-scoped Phase 5/6 state. The strict
  report route and Rust/UI boundary return one in-memory artifact; the core does
  not write a file or persist a report/approval/artifact row.
- Runtime vaults, imports, evidence, reports, logs, screenshots, build trees,
  CommonCrypto packages, and frozen binaries stay in ignored or `/tmp` output.
  `apps/desktop/src-tauri/binaries/ariadne-core-*` is an ignored staging path,
  not a source or committed release artifact.

## Optional local-AI boundary

The provider-neutral local-AI settings vertical is implemented across encrypted
settings, generated API, Rust, and desktop Settings. It is disabled by default,
requires an explicit user-selected model, and accepts a user-managed Ollama,
LM Studio, or other OpenAI-compatible runtime only on an approved loopback
endpoint. Candidate intake enrichment receives restricted-value-redacted text,
returns probable review-only suggestions with provenance, and leaves
deterministic extraction as the complete fallback. No cloud account, paid API,
remote fallback, tool authority, or attribution authority exists. Its verified
`0007` package evidence remains separate from the verified `0008` package;
operational-data privacy review remains pending before real-data use.

## Development sidecar versus packaging proof

The debug workflow uses `scripts/bootstrap_core.sh` and the uv workspace. Its
`pysqlcipher3` extension links the target Mac's Homebrew SQLCipher installation
for fast test iteration. That extension is machine-local and is never a release
input.

The packaging workflow under `scripts/package-sidecar` independently fetches
and hash-verifies pinned SQLCipher and binding sources, builds a macOS 14 arm64
CommonCrypto extension without Homebrew/OpenSSL linkage, then freezes the
current `ariadne_core.cli` with pinned PyInstaller. The local proof exercises
authenticated development TCP and the profile/intake/quarantine/review flow
over private UDS and inspects architecture, minimum OS, archive contents,
dependencies, size, and cleanup.
Generated packages and binaries are evidence, not tracked repository content.

The Tauri packaging-spike continuation then:

1. Re-inspects and stages the target-suffixed frozen binary in the ignored
   `src-tauri/binaries` directory.
2. Applies `tauri.packaging-spike.conf.json` as an overlay that declares the
   external binary.
3. Builds the local release-mode `.app`.
4. Launches the app and proves authenticated packaged UDS startup, a user-owned
   `0700` runtime directory and `0600` socket, zero TCP listeners across the app
   and both PyInstaller processes, no inherited probe/credential environment,
   and bounded cleanup after both requested and abrupt app exits.

The reproducible command sequence is:

```sh
make stage-frozen-sidecar FROZEN_OUTPUT_ROOT=...
make package-spike-app
make package-spike-app-check
```

The overlay intentionally sets `hardenedRuntime` to false only for this ad-hoc
local proof. With hardened runtime enabled, Tauri's ad-hoc re-signing of the
PyInstaller sidecar caused the extracted `libpython` to fail Team-ID library
validation. Disabling that validation is not a production solution. Production
must retain hardened runtime and sign the freezer payload, frozen executable,
Tauri executables, and application bundle with the same Developer ID before
notarisation and clean-machine testing.

## Verified Phase 3 and current candidate boundary

The Rust shell hands authorised database-key material to the sidecar over
anonymous FD 198 without argv/environment/HTTP/webview exposure. Phase 3 now
historically reaches schema head `0005_graph_edge_origins`; its aggregate,
frozen UDS, deep strict signature, zero-TCP, and packaged normal/SIGKILL gates
pass. The separately labelled `0006_query_policy_core` evidence remains intact;
verified package evidence reaches `0007_phase5_evidence_attribution`, whose
aggregate, frozen UDS, deep strict signature, zero-TCP, and packaged normal/
SIGKILL gates pass under new identities rather than relabelled `0005` or `0006`
artifacts. The earlier packaged 37-operation source reaches
`0008_phase6_audit_remediation`; its identities remain historical evidence.
schema `0008` and passes source, frozen UDS, and packaged normal/SIGKILL gates
under `96c368…` staged-sidecar, `77338e…` signed-sidecar, and `214ccd…` desktop
identities. The later 48-operation package identities remain historical. The
current source reaches `0011_profile_purge` with 57 operations and passes 498
Python tests plus four intentional skips, 95 Rust tests plus one manual
Keychain ignore, 148 frontend tests, generated-contract drift, and the 440-file
privacy scan, fresh frozen/staged inspection, and packaged normal/abrupt
lifecycle verification. No earlier artifact is relabelled.
Physical power/Keychain validation, production key rotation, one-Developer-ID
hardened-runtime signing, notarisation, and clean macOS 14 testing remain Phase
9 release work. Native idle/system-lock dispatch
and the separately reviewed narrow capability/session/lock UI state connection
are complete.
