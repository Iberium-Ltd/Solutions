# Security Policy

Status: 57-operation/55-path local candidate aggregate/package passed; production boundary remains incomplete
Last reviewed: 2026-07-23

Codename Ariadne is intended to handle sensitive personal audit material, but the current repository is not a production security boundary. Historical `0005`–`0008` packages remain separately identified. The current 57-operation candidate at `0011_profile_purge` adds persistent named-person audits, a seven-provider bounded public frontier, restart recovery, cited selected-local-AI analysis, exact-source canonical promotion, and confirmed whole-profile deletion. Its full aggregate, privacy, frozen-sidecar, and packaged lifecycle gates pass. Production key rotation, physical power/Keychain validation, selective retention, authorised connectors, hardened-runtime signing, clean-machine/notarisation, and release hardening remain incomplete.

## Current security boundary

The checked-in prototype:

- uses only invented fixture data and reserved `.invalid` hosts;
- permits real external search only through the explicit self-audit-authorised public-discovery boundary; no authorised account connector, provider-contact, or remediation request exists;
- binds browser development and preview servers to `127.0.0.1`;
- packages fonts and visual assets locally;
- gives the Tauri window only `core:default` capability permissions;
- applies a Tauri content security policy that denies frames, objects, arbitrary form targets, and non-self scripts;
- blocks non-local requests in Playwright route and screenshot tests;
- includes a disabled-by-default, explicit-model local-AI vertical restricted to loopback Ollama/OpenAI-compatible runtimes such as Qwen through Ollama or models served by LM Studio, with strict limits, no LAN discovery/redirect/cloud fallback, exact source citations for corpus/workspace reasoning, review-only output, and deterministic fallback;
- keeps confidential references, runtime data, evidence, exports, secrets, databases, and generated captures ignored;
- runs `scripts/privacy_check.py` to detect confidential paths, non-reserved development emails, likely secrets, and private-reference collisions without printing matched confidential values;
- starts the Python core only from a size-bounded one-shot bootstrap, retains only a digest of the 256-bit per-launch credential, and rejects missing, expired, replayed, wrong-contract, wrong-Host, wrong-Origin, forwarded, or oversized requests;
- exposes 57 generated route-specific source operations (4 GET, 53 POST) across 55 paths, including nine profile/intake/entity/graph boundaries and eight persistent identity-audit boundaries; keeps replay/profile listing shell-internal, disables runtime OpenAPI documentation, and generates canonical OpenAPI, TypeScript, and Rust schema-hash allowlists offline. Every earlier package remains separately identified and is not proof of this source head;
- binds development service traffic to a random `127.0.0.1` port and supports a private user-owned `0600` Unix socket in the verified sidecar runtime; no LAN bind option or packaged TCP fallback is defined;
- fails closed when SQLCipher is absent, the underlying SQLite version is below the approved floor, a key is wrong, integrity checks fail, or schema migration is incompatible;
- uses forward-only migrations, revisioned typed settings, transactional redacted audit/outbox records, bounded synthetic job leases, capability-brokered file paths, and authenticated encrypted backups whose input/envelope bounds, canonical metadata, declared lengths, and nonce non-reuse fail closed before expensive work;
- requires an unexpired UUID worker lease and expected job revision for heartbeat, progress, and completion; recovery closes attempts and emits redacted state in the same transaction, while completion cannot override a persisted pause or cancellation request;
- keeps Keychain custody in Rust and transfers one 32-byte database key only over an inherited anonymous Unix socket at FD 198, using a bounded binary protocol bound to startup/lease/transaction nonces, canonical manifest digest, vault ID, opaque reference, key version, and operation;
- stages SQLCipher while the API remains locked, publishes only after Rust `COMMIT`, confirms with `COMMITTED`, consumes the channel, and replaces the sidecar after lock;
- re-checks authorization immediately after Keychain retrieval before `GRANT` and again before `COMMIT`, so a system lock during an outstanding prompt can revoke the late result;
- applies a native 300-second idle policy, stops extending the app-local deadline when the window loses focus, and uses only an elapsed-input duration rather than an event tap or raw input capture;
- observes macOS workspace sleep/wake, screen sleep/wake, and session active/inactive notifications; a system-lock request synchronously drops endpoints, session credentials, lease handles, and unlocked state, signals the old sidecar, coalesces duplicates, and restarts locked only after active operations drain;
- revokes startup state and terminates the owned child on premature exit or rejected readiness; after readiness it revokes all per-process state on unexpected exit and permits at most three locked restart attempts per rolling 60 seconds with bounded backoff;
- replays at most 32 payload-free encrypted-outbox events per authenticated request and lets only Rust retain the opaque cursor; the native relay suppresses duplicate IDs, requests scoped refetch on gaps or cursor expiry, ignores unknown additive variants, and emits no core credential or transport cursor;
- lets React invoke only generated narrow commands; native Intake, Entities, Graph, Settings/local-AI, Transmission/query, profile resume, Findings, Compare, and Removal Tracker slices use exact request/response validation and clear sensitive state on lock, while browser runs use explicit simulation fallbacks and no credential, socket path, vault key, or generic proxy enters frontend state;
- accepts only consent-confirmed pasted text or one selected TXT, Markdown, CSV, JSON, or vCard file up to 1 MiB; validates canonical base64, extension/media agreement, exact byte count, SHA-256, UTF-8, structure, and parser budgets;
- parses structured input in a spawned, bounded worker and applies a parent-side restricted-value gate before parsed segments can return to the compiler;
- fully redacts restricted values before ordinary extraction, including short, phrase, escaped, overlapping, free-text, and structured forms; persists only quarantine reason/retention metadata, and structurally excludes restricted plaintext from entities, graph nodes, semantic input, jobs, and future provider input;
- persists normal intake contentlessly by default, opportunistically purges expired temporary content on repository entry, and clears pasted/file UI state and sensitive Intake/Entities DOM state on lock;
- derives a request-scoped fingerprint subkey from the unlocked vault key, copies it only into zeroised repository memory, and uses keyed HMACs so deduplication is profile-scoped without plaintext indexes;
- enforces profile scope through composite foreign keys, repository predicates, API checks, and negative cross-profile tests; Phase 3 side effects use durable HMAC-keyed idempotency reservations/results with request-digest conflict checks, 60-second in-flight ambiguity, and 24-hour historical replay;
- persists append-only decision records with durable before/after sensitivity, temporal, search, and transmission policies; maps `LOCAL_ONLY` without weakening, enforces false-positive/excluded and highly-sensitive policy invariants in both repository logic and database triggers, and retains legacy-upgrade honesty through `0004_decision_policy`;
- at verified head `0005_graph_edge_origins`, binds every support/contradiction observation to one source, segment, extraction run, and graph edge in the same profile; keyed deduplication preserves observations from distinct sources, reads return complete counts plus bounded samples, and migration fails closed rather than inventing missing legacy provenance;
- preserves entity/relation provenance while suppressing rejected or excluded nodes and incident edges from graph snapshots;
- at candidate head `0006_query_policy_core`, persists a vault-scoped provider catalog and profile-scoped plan/check/budget/approval/ledger state with keyed query/payload digests; the current catalog is fail-closed to local `DRY_RUN`/`MANUAL_LOCAL` manifests with no network, identifiers, processing region, or external-provider flag;
- keeps public discovery outside that generic catalog and limits it to explicit self-audit-authorised DuckDuckGo HTML or unauthenticated GitHub-user search; exact result URLs/source identifiers are retained, access challenges fail honestly, and the adapter cannot bypass authentication, CAPTCHA, paywalls, or rate limits;
- at `0007_phase5_evidence_attribution`, requires an already-open SQLCipher vault and exact profile before constructing durable Phase 5 repositories; stores immutable bounded originals/derivatives and many-to-many finding links, reconstructs originals through SHA-256 validation, constrains assessment signals to evidence already linked to the same finding, and appends revision-linked human decisions separately from automated scores;
- exposes bounded metadata through two Phase 5 read routes and adds three explicit local writes: manual import verifies bounded canonical base64/kind and persists inside SQLCipher, derivative creation requires caller confirmation that supplied bytes are already redacted, and human decisions use expected prior identity/revision. Stored evidence bytes are never returned to the webview;
- lets an empty profile create a bounded manual finding plus a neutral score-zero initial assessment atomically, with server UUID/time, complete missing-evidence state, and mandatory human review; it creates no evidence, human decision, attribution conclusion, or network activity;
- atomically captures one explicitly reviewed public result as an exact-URL `URL_REFERENCE` artifact, finding, neutral assessment, and link; exact URL hashes, keyed query references, profile isolation, idempotency, and rollback in both failure directions are enforced;
- at historical packaged and current source head `0008_phase6_audit_remediation`, stores immutable bounded audit snapshots/findings/coverage and complete immutable remediation revisions/history across ten profile-scoped tables; canonical payload hashes detect replay corruption, composite references reject cross-profile links, and selected nonadjacent comparisons retain every intervening lifecycle observation;
- exposes Phase 6 audit list/compare and remediation list/detail plus local create/draft/require-approval/status/deadline/evidence/provider-response/reappearance mutations with strict bounds and revision CAS; no route sends, submits, dispatches, or contacts a provider, and attribution never auto-assigns a human state;
- lets a user gesture automatically materialise a bounded local checkpoint from contentless Phase 5 metadata plus explicit provider coverage; canonical fingerprints include derivative and assessment/decision state, while server sequence/time and UUID are allocated locally. No adapter, scheduler, background worker, provider, or network is invoked;
- generates one bounded in-memory JSON or inert Markdown report from selected persisted runs. Redacted mode is the default and deterministically remaps identifiers/URLs and replaces sensitive text; full-explicit mode requires a fresh request-bound approval UUID. Evidence bytes and active content are excluded, and the core performs no filesystem write, network request, send, or provider contact;
- has a hash-pinned CommonCrypto SQLCipher build and native arm64 frozen-sidecar proof with no Homebrew, OpenSSL, external SQLCipher, or system SQLite runtime dependency;
- embeds the reviewed Alembic configuration and forward migrations in the sidecar source; historical frozen proofs reach `0005`–`0008`, while current proof reaches exact schema/archive `0011_profile_purge`;
- preserves the earlier 37-operation `0008` package under `e156e9…` staged-sidecar, `359fd0…` signed-sidecar, and `fc02da…` desktop identities as historical evidence;
- preserves the historical 40-operation `0008` package under `96c368…` staged-sidecar, `77338e…` signed-sidecar, and `214ccd…` desktop identities: frozen manual-finding/two-checkpoint/report UDS requests returned 200; requested/SIGKILL starts completed in 4,116/2,646 ms with exit 0/-9, two sidecars, cleanup, zero TCP, `0700`/`0600` permissions, and deep/main/sidecar strict ad-hoc signatures. Its source gates passed 372 Python tests, 82 Rust tests plus one ignored manual-Keychain test, 96 frontend tests across 23 files, Chromium/WebKit route-accessibility smokes, exact 40-route parity, language/type/lint/build gates, and a 354-candidate privacy scan;
- preserves the historical 45-operation package under `b33e411e…` staged-sidecar, `536c16a8…` signed-sidecar, and `d3eef7ba…` desktop identities without relabelling them;
- preserves the 48-operation build under `5ca6b790…` staged-sidecar, `4ba7fd0…` signed-sidecar, and `ca68fdd4…` desktop identities as historical evidence;
- proves the current 57-operation local candidate under `dccaaa5…` staged-sidecar, `74325b3…` signed-sidecar, and `08491aa…` desktop identities. Its aggregate passes 498 Python tests with 4 intentional skips, 95 Rust tests plus one ignored manual-Keychain test, 148 frontend tests, a 440-candidate privacy scan, fresh frozen/staged workflows, deep strict ad-hoc signing, and requested/abrupt cleanup with zero TCP and `0700`/`0600` modes. This is local candidate proof, not a production security or release boundary.

These controls materially extend the development fixture boundary, but they do not yet create a production boundary. Native workflows pass for the tested local scope and current local package. Scheduled ingestion, selective retention, evidence streaming, durable report/approval/artifact lifecycle, broader export formats/destinations, credentialed connectors, and production signing remain incomplete. Whole-profile purge is implemented. The automated lifecycle uses a synthetic in-memory custodian rather than the user's Keychain, and all package proofs are local and ad-hoc.

The current selected-file flows intentionally use browser file inputs, read bounded bytes into webview memory, and send canonical base64 through typed Tauri commands. Intake is capped at 1 MiB and Phase 5 evidence/derivative input at 10 MiB. They prevent arbitrary path disclosure and revalidate bounds/encoding; the core computes and verifies stored evidence hashes. Transient raw bytes and a roughly 4/3-size base64 copy still exist in the webview/serialization boundary, so an opaque native broker handle remains the preferred production design for real-data imports.

Current residuals also include a bounded 60-second ambiguous response window after an interrupted side effect, a 24-hour completed-result replay lifetime, and retry keys held only in webview memory across a reload. Free-form decision reasons are reduced to keyed opaque codes rather than retained as human-readable history. The parser worker has strong resource and network bounds, but macOS provides no complete sandbox here against every file readable by the same user. Quarantine is descriptor-only, so a later encrypted quarantine-blob feature must add independently verified deletion.

The first local hardened-runtime packaging attempt failed closed because a PyInstaller-extracted `libpython` carried a different Team ID from the ad-hoc Tauri application. `tauri.packaging-spike.conf.json` deliberately disables hardened runtime only for the local packaging experiment. Production must propagate one Developer ID through PyInstaller internals, the sidecar, and Tauri, then enable hardened runtime and pass clean macOS 14 plus notarisation validation.

## Required handling rules

- Never add real identity data, credentials, live provider responses, exact private locations, or user evidence to source, fixtures, tests, screenshots, documentation, logs, or Git history.
- Use `packages/synthetic-data` for reusable demo values and `.invalid` for illustrative domains.
- Do not bypass access controls, CAPTCHA, authentication, rate limits, paywalls, or provider terms.
- Do not implement automatic accusations, legal submissions, deletion requests, provider contact, or other external actions.
- Run the privacy check before staging or sharing changes.
- Treat screenshots, traces, test reports, databases, imports, and exports as sensitive even when they are expected to be synthetic.

## Development checks

From the repository root:

```sh
python3 scripts/privacy_check.py
corepack pnpm typecheck
corepack pnpm test
corepack pnpm test:e2e
make core-lint
make core-typecheck
make core-test
make contracts-check
make rust-check
make sidecar-scripts-check
make package-spike-app-check
```

The E2E suite rejects unexpected console errors, page errors, failed requests, serious Axe violations, and external network attempts. Passing these checks is necessary but is not a penetration test or release security review.

## Before production data is permitted

Before production data is permitted, the remaining dedicated gates include:

- independently versioned, crash-safe database-key and backup-key rotation with verified rollback and no unverified active reference;
- physical sleep/wake and real macOS Keychain-prompt validation, plus the remaining crash/timeout matrix around the implemented and synthetic-tested idle/system-lock path; the current high-level Keychain API cannot dismiss an already visible dialog, although its result is revoked before delivery;
- one Developer ID propagated through PyInstaller internals and every nested Tauri artifact, required hardened runtime restored, and clean macOS 14 arm64 startup, nested-signature, notarisation, and stapling validation;
- authenticated evidence-object streaming, broader automated content capture beyond exact public URL references, trusted redaction tooling, retention/purge, and migration/rotation beyond the current bounded SQLCipher milestone;
- an independent hostile-input/security review of the implemented parser worker and selected-file bridge, including fuzzing and sanitizer-backed native dependency review;
- extension of the proven profile scope to future evidence, adapter caches, exports, browser contexts, and connector data;
- explicit transmission preflight, provider policy, budgets, and an auditable ledger;
- signed nested binaries, hardened runtime, notarisation, signed updates, SBOM, and dependency review.

See [THREAT_MODEL.md](THREAT_MODEL.md) and [PRIVACY_MODEL.md](PRIVACY_MODEL.md) for the broader risk and data-governance model.

## Reporting a security concern

Do not include secrets, personal data, private evidence, or confidential-reference content in a public issue. Notify the repository maintainer through the established private project channel with a minimal reproduction using synthetic data. If a report itself contains sensitive material, agree on an encrypted transfer method before sending it.
