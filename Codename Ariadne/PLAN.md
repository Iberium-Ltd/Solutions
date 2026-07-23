# Codename Ariadne — Delivery Plan

Last updated: 2026-07-22  
Current focus: refocus the product around persistent people and a durable recursive identity-discovery audit

## 2026-07 product refocus — implementation plan

The existing encrypted `profiles` boundary becomes the persistent **Person**
aggregate instead of introducing a second competing identity root. Existing
entities, exact origins, graph relationships, findings, evidence, checkpoints,
reports, and remediation records remain attached to that stable ID.

The minimum new persistence layer is one forward-only migration containing:

- editable person metadata (notes and tags) and a canonical source/link library;
- named, dated audit runs with mode, budgets, real counters, stage, state, and
  explicit stop reason;
- a durable search frontier whose tasks retain parent lead, depth, priority,
  expected information gain, retries, receipts, and terminal coverage state;
- canonical discovery results and leads with complete parent/discovery paths;
- reviewable knowledge proposals with supporting signals, contradictions,
  confidence, temporal/ownership/review state, and exact provenance; and
- structured LLM tool invocations that retain approved arguments/result
  receipts but never hidden reasoning or unbounded command text.

Execution sequence:

1. Add and migration-test the schema and repository invariants without changing
   current Phase 3–6 records.
2. Add bounded People, knowledge, source-library, audit, frontier, proposal, and
   review contracts through Python, generated TypeScript/Rust, and Tauri.
3. Deliver the People UI with create/select/edit, manual knowledge, pasted URL
   seeds, previous audits, unresolved leads, and source actions.
4. Convert confirmed eligible entities and reusable sources into incremental or
   full-rescan frontier tasks without returning unrelated raw values.
5. Execute supported providers concurrently with retries, cancellation, resume,
   pagination metadata, exact receipts, honest empty/blocked/failed states, and
   persisted progress.
6. Add bounded public-page exploration, HTML/link/identifier extraction,
   forum-aware ranking, deduplication, proposals, and configured stop conditions.
7. Add the allowlisted LLM tool broker. The selected local model may rank and
   propose the next tool, but only typed broker commands execute and every call
   remains budget-, authority-, and policy-bound.
8. Replace the mandatory manual preflight journey with **Run full audit** while
   retaining Transmission and individual discovery controls under Advanced.
9. Feed reviewed discoveries into evidence, graph, checkpoints, comparison,
   reporting, and remediation; preserve exact discovery chains throughout.
10. Run privacy, migration, contract, Python, Rust, frontend, packaging, launch,
    and concise changed-screen checks before updating completion status.

Required recovery tests cover person separation, restart-safe audit/frontier
state, pause/resume/cancel, duplicate suppression, recursive depth/budget stops,
tool authorization, proposal review, and restoration after focus/navigation.

## Delivery principles

- Use only synthetic identities and reserved `.invalid` domains in code, fixtures, tests, documentation examples, and screenshots.
- Keep the confidential references read-only, ignored, and outside every build, test, export, screenshot, and Git operation.
- Build the complete interaction model before the production backend.
- Preserve uncertainty, failed checks, contradictions, and provenance.
- Prefer local processing and default-deny external transmission.
- Do not mark a phase complete until its gate has objective evidence.

## Phase 0 — Discovery and architecture

Status: Complete

- [x] Inventory the complete supplied workspace.
- [x] Read every supplied file, including confidential references and Finder metadata.
- [x] Extract a confidential-safe requirements baseline.
- [x] Create and review ADR-001, threat model, privacy model, information architecture, and initial data model.
- [x] Publish the proposed repository structure.
- [x] Install privacy guardrails before repository initialisation.
- [x] Run the privacy check and verify confidential paths are ignored.

Gate:

- Requirements trace to the master brief.
- Stack trade-offs and rejected alternatives are documented.
- No generated file contains private-reference identity data.
- Confidential paths are demonstrably ignored and untracked.

## Phase 1 — UI system and interactive prototype

Status: Complete

- [x] Establish design tokens, typography, icons, surfaces, states, motion, and accessibility rules.
- [x] Build the Tauri-ready React application shell and responsive navigation.
- [x] Build all UI surfaces listed in `docs/requirements.md`.
- [x] Implement the four complete synthetic journeys with deterministic local state.
- [x] Label simulated execution data clearly.
- [x] Add keyboard navigation, focus handling, accessible names, contrast checks, and reduced motion.
- [x] Add component, route-smoke, interaction, accessibility, and visual tests.
- [x] Run locally and inspect real interactions.
- [x] Capture each major screen at 1440×900, 1728×1117, and 1100×800.
- [x] Record findings in `SCREENSHOT_REVIEW.md`, fix defects, and recapture.

Gate:

- Production build and automated UI tests pass.
- Every major surface and representative state has screenshot evidence at all three viewports.
- Full audit, targeted trace, re-audit, and impersonation flows can be demonstrated with synthetic data.
- No critical visual, keyboard, accessibility, overflow, privacy, or reduced-motion defect remains.
- Full backend work has not begun prematurely.

## Phase 2 — Local foundation

Status: Complete and tested

- [x] Add the authenticated Python sidecar with a bounded one-shot bootstrap, per-launch session, exact Host/Origin/contract checks, replay protection, parent supervision, and redacted structured logging.
- [x] Generate canonical OpenAPI, TypeScript contracts, and the Rust route allowlist from the Pydantic source of truth; expose only truthful route-specific local boundaries.
- [x] Add SQLAlchemy, forward-only Alembic migrations, fail-closed SQLCipher persistence, typed settings with revision checks, transactional audit/outbox records, auto-lock policy, and bounded synthetic task lifecycle foundations.
- [x] Add capability-brokered import/export plans and authenticated encrypted backup/restore foundations using synthetic tests only.
- [x] Implement Rust macOS Keychain custody with opaque references, zeroising key material, and tested create/get/delete behavior.
- [x] Prove a pinned arm64 CommonCrypto SQLCipher build and a bounded native arm64 PyInstaller sidecar with authenticated loopback, private UDS, and inherited FD-198 runtime probes.
- [x] Integrate the frozen sidecar into a local Tauri packaging-spike app as an exact `externalBin` sibling and verify UDS-only startup, zero TCP listeners, cleared inherited environment, exact launch arguments, `0700` runtime directory, `0600` socket, nested ad-hoc signatures, normal quit cleanup, and SIGKILL parent cleanup.
- [x] Implement the secure, one-use Rust-to-Python key lease and wire synthetic-tested Keychain-compatible vault create/unlock/lock through route-specific shell commands; no key enters arguments, environment variables, HTTP, logs, or frontend state.
- [x] Add native 300-second idle locking, application-focus tracking, macOS workspace sleep/wake/screen/session notifications, synchronous lease revocation, coalesced locked-sidecar restart, and delayed-Keychain cancellation coverage. Physical sleep and the real Keychain prompt remain manual validation gates.
- [x] Detect unexpected ready-sidecar exit, revoke the old session immediately, and retry locked startup at most three times in a rolling 60-second window with bounded backoff; retain a recoverable failed state when the budget is exhausted.
- [x] Add authenticated, bounded event replay from the encrypted outbox and a Rust-owned Tauri relay that withholds cursors and payloads, tolerates duplicate IDs, requests scoped refetch after gaps or cursor expiry, ignores unknown additive variants safely, and retains its opaque cursor across lock/restart pauses.
- [x] Harden durable synthetic jobs with authoritative lease owner/revision checks, bounded progress, concurrent-claim exclusion, cooperative claim stop, explicit pause/cancel recovery, deterministic persisted retry delay, transactional attempt/outbox recovery, and completion-race reconciliation without false success.
- [x] Add forward-only migration `0002_job_dependencies` and enforce a bounded durable dependency DAG with recursive-CTE cycle rejection, success/terminal eligibility, explicit block/cancel propagation, transactional outbox records, and encrypted `0001` → `0002` upgrade coverage.
- [x] Embed the reviewed Alembic configuration and migrations in the PyInstaller sidecar, resolve them only from the private extraction root, and prove real frozen UDS vault creation produces an encrypted database at schema head `0002_job_dependencies`.
- [x] Enforce backup source/envelope limits before allocation, strict canonical metadata and exact ciphertext lengths, durable nonce non-reuse, and recovery of every database-swap boundary exercised by the foundation.
- [x] Exercise fail-closed startup child exit and readiness rejection, including credential/capability revocation and owned-child termination, in addition to ready-child crash recovery.
- [x] Connect only the narrow capability/session/lock foundation to the existing UI while preserving explicit simulated-versus-real labels; do not begin provider or real-intake work.

Gate: passed for the master prompt's local-foundation scope. `make phase2-check` passes with 140 Python tests, 57 automated Rust tests, 18 frontend tests, privacy, formatting, lint, types, contracts, and production web build. The exact rebuilt arm64 frozen sidecar and Tauri package also pass encrypted migration, authenticated UDS-only startup, normal shutdown, abrupt-parent cleanup, and nested ad-hoc signature checks. Physical sleep/wake, the manual platform-Keychain prompt, production key rotation, Developer ID/hardened-runtime signing, notarisation, and clean-machine validation remain explicit Phase 9 release gates and are not claimed here.

## Phase 3 — Intake and identity compiler

Status: Complete and tested at the explicit synthetic local gate

- [x] Accept consent-confirmed pasted text and one selected `.txt`, `.md`, `.csv`, `.json`, or `.vcf` file up to 1 MiB.
- [x] Validate extension, declared media type, canonical base64, exact size, SHA-256, UTF-8, structure, and parser budgets before persistence.
- [x] Parse untrusted structured input in a bounded spawned worker with time, memory, IPC, nesting, row, cell, and output limits.
- [x] Detect and fully redact restricted values, including short, phrase, escaped, and overlapping forms, before ordinary extraction; persist only quarantine descriptors, never restricted values.
- [x] Extract, normalise, deduplicate, mask, classify, and provenance-link deterministic candidates.
- [x] Add optional bounded local rule enrichment and preserve a deterministic-only mode; no LLM or remote service is required or contacted.
- [x] Add profile-scoped encrypted persistence through `0005_graph_edge_origins`, keyed fingerprints, append-only review decisions with durable before/after policy state, graph nodes/edges, source/run/segment-linked support and contradiction observations, and optimistic revision checks.
- [x] Expose six narrow authenticated Phase 3 routes and generated Rust/TypeScript contracts; require an unlocked vault, exact profile scope, bounded responses, and idempotency on side effects.
- [x] Connect native profile creation, paste/file intake, entity review, and decisions to the existing Intake and Entities screens. Browser mode remains explicitly synthetic.
- [x] Make intake side effects crash-safe and replayable with a durable reservation/result record, 24-hour replay window, bounded 60-second retry ambiguity, and safe file retry.
- [x] Default sources to contentless persistence, opportunistically purge expired temporary source content, suppress rejected/excluded entities from graph reads, and enforce lossless `LOCAL_ONLY` mapping plus policy invariants in repositories and database triggers.
- [x] Preserve duplicate-source edge provenance, return complete support/contradiction counts with bounded evidence samples, and fail the `0005` migration closed if legacy edge provenance cannot be verified and backfilled honestly.
- [x] Verify the synthetic end-to-end path, malicious inputs, restricted-value handling, cross-profile rejection, provenance, decision audit, package migration, and normal/abrupt packaged cleanup.
- [x] Connect the native Graph screen to the persisted bounded graph snapshot, including support/contradiction counts, sampled source provenance, truncation, lock clearing, and synthetic browser fallback.
- [x] Add selectable AI settings across encrypted settings, generated API, Rust commands, and desktop Settings for loopback Ollama/OpenAI-compatible runtimes, plus an optional OpenAI Responses provider with an ephemeral per-request key and explicit model ID. Selected-model intake enrichment remains review-only with restricted-value-redacted input and deterministic fallback.
- [x] Add bounded local corpus and workspace reasoning for summary, organisation, questions, connections, and gap analysis. Model and deterministic results are review-only and carry exact document/segment or workspace-source citations, projection limits, and explicit fallback state.
- [x] Expose complete entity provenance through bounded summary origins plus a stable, profile-scoped exact-origin pagination operation.

Historical gate: **passed for the explicit synthetic local scope at `0005_graph_edge_origins`**. The 265-Python/63-Rust/41-frontend counts and frozen/package hashes recorded in `TEST_RESULTS.md` remain Phase 3 evidence only. Native Graph, selectable local-AI settings, and selected-model intake enrichment were added afterward and passed the now-historical 45-operation aggregate, rebuilt frozen-sidecar, and packaged-app gates at `0008_phase6_audit_remediation`. Real personal data and release readiness are not claimed.

## Phase 4 — Search compiler and initial adapters

Status: Network-free planning, two bounded public-search providers, official HIBP checks, and deterministic multi-identifier planning implemented; full Phase 4 remains incomplete

- [x] Compile inspectable query plans with hard total/per-provider budgets and explicit PLANNED, APPROVAL_REQUIRED, NOT_CHECKED, and BLOCKED cells.
- [x] Add the encrypted `0006_query_policy_core` schema for a vault-scoped provider catalog, profile-scoped runs/checks, budget use, one-time approvals, and a minimised transmission ledger.
- [x] Expose generated provider-catalog, plan, and dry-run operations through Rust and the Transmission UI.
- [x] Restrict the current catalog to network-free `DRY_RUN` and `MANUAL_LOCAL` providers; Rust and Python reject external providers, identifier transmission, non-local access basis, processing regions, and network-capable manifests.
- [x] Add explicitly authorised bounded public discovery through DuckDuckGo HTML and unauthenticated GitHub-user search with exact result URLs/source identifiers and honest blocked/challenged/rate-limited failure states.
- [x] Add official HIBP account/domain checks with explicit self-audit authorization, ephemeral request keys, exact source attribution, honest plan/auth/rate-limit states, and separate authorization for direct identifier transmission.
- [x] Add a deterministic, non-executing multi-identifier investigation planner that shows exact routes, transmission classes, ordering, and unmet prerequisites before any provider request.
- [x] Add fixed manual research portals to the Discovery Console without automating or bypassing authentication, CAPTCHA, paywalls, or rate limits.
- [x] Add a local advanced query composer with an exact visible query, structured `site`, `filetype`, `intitle`, `inurl`, exclusion, and date fields, optional raw provider-specific operators, user-opened browser handoffs, and optional loading into the existing bounded DuckDuckGo form. It performs no scraping or evidence import.
- [ ] Add archive, regional public-record, authorised-account, and other providers only after separate adapter/policy gates.
- [ ] Complete retry, cancellation/resume, cost, coverage, and external approval workflows for operational adapters.

Gate: policy-denied values never cross an adapter boundary; retries, blocks, cancellation, resume, costs, and coverage statuses are real and tested.

## Phase 5 — Evidence and attribution

Status: Atomic public capture, cited audit analysis, reviewed canonical promotion, and broad exact-source provenance are implemented at the 57-operation source head; phase not complete

- [x] Model immutable bounded SCREENSHOT/HTML/PDF/RAW_JSON/URL_REFERENCE originals, SHA-256 verification/deduplication, safe URL metadata, manual local import, and linked redacted derivatives behind a storage protocol.
- [x] Implement versioned configurable integer attribution scoring with closed positive/negative signals, contradictions, missing evidence, confidence bands, recommended evidence, and mandatory separate human review.
- [x] Add forward-only encrypted schema `0007_phase5_evidence_attribution` and profile-scoped durable repositories for immutable findings, evidence originals/derivatives, multi-finding deduplication links, assessments, signal evidence, missing evidence, and append-only human decisions.
- [x] Expose bounded authenticated read-only finding list/detail operations through generated contracts, strict Rust/Tauri commands, and the native Findings list/detail UI; browser mode remains synthetic.
- [x] Add bounded vault profile listing and a native profile switcher so an existing active/draft profile can be selected again after a webview reload without persisting the active selection in frontend storage.
- [x] Add authenticated, bounded manual-local evidence import, caller-confirmed redacted-derivative creation, and append-only human-attribution decision mutations through generated contracts, strict Rust/Tauri commands, and the native finding detail UI.
- [x] Let a fresh native profile create its first bounded manual finding and atomic neutral, review-required assessment using server UUIDs/timestamps and no evidence, human decision, or network action.
- [x] Add policy-checked atomic capture of one explicitly reviewed public-discovery result into an exact-URL `URL_REFERENCE` artifact, finding, neutral assessment, and link with rollback, deduplication, URL-hash binding, and raw-query minimisation.
- [x] Traverse exact sources across public results/captures, entities, graph observations, findings, AI results, and reports; preserve source hashes/opaque mappings even where a redacted report removes the literal URL.
- [ ] Add evidence-backed assessment recalculation beyond the neutral bootstrap, evidence streaming/viewing, retention, and dependency-aware purge.
- [ ] Connect broader operational adapter-produced findings and complete any remaining provenance traversal in future provider/remediation surfaces.

Gate: tamper detection, deduplication, redacted derivatives, attribution explanations, and provenance traversal pass end-to-end tests.

## Phase 6 — Monitoring and remediation

Status: Comparison, remediation, checkpoints, and exact-source reports are implemented; operational scheduling and durable report lifecycle remain incomplete

- [x] Model immutable bounded run snapshots, stable finding fingerprints/lifecycle, deterministic NEW/CHANGED/REMOVED/UNCHANGED/REAPPEARED diffs, and explicit incomplete comparisons that preserve NOT_CHECKED/BLOCKED coverage.
- [x] Model finding-linked remediation cases, local/draft/explicit-approval-only actions, deadlines, optimistic revisions, append-only history, provider responses, evidence links, and reappearance reopening without any send operation.
- [x] Add ten immutable, profile-scoped SQLCipher tables at `0008` for audit snapshots/findings/coverage and revisioned remediation findings/evidence/provider responses/history, including hash-verified replay and cross-profile rejection.
- [x] Expose authenticated audit-run list/selected-run comparison and remediation list/detail through generated contracts, strict native boundaries, and the native Compare and Removal Tracker screens; selected nonadjacent comparisons retain intervening lifecycle observations.
- [x] Add local-only remediation create, draft, require-approval, status, deadline, evidence-link, provider-response, and reappearance mutations with revision CAS and complete append-only history. No send, submit, dispatch, provider contact, or legal-advice operation exists.
- [x] Add user-triggered automatic local checkpoint materialisation from current contentless Phase 5 finding/evidence/assessment/decision metadata, explicit provider coverage, monotonic server sequence/time, canonical fingerprints, strict profile scope, and no provider or network execution.
- [x] Add deterministic in-memory local reports for a selected baseline/current pair in canonical JSON or inert Markdown, with default deterministic redaction, request-bound full-explicit approval, exact hashes/manifests, exact-source mappings, evidence-byte exclusion, native preview/copy/save, and no network/send/filesystem write in the core.
- [ ] Connect operational adapter ingestion and a scheduled/background snapshot pipeline; the current checkpoint still requires a user gesture and declared coverage.
- [ ] Add durable report/approval/artifact records, broader templates and formats, native destination brokering, retention/purge, and release-grade export tests.

Gate: two synthetic audits compare correctly; remediation history and export redaction are tested; no action is sent automatically.

## Phase 7 — Authorised account connectors

Status: Not started

- Add minimum-scope, read-only Gmail and GitHub connectors, local exports, Keychain tokens, and revocation.

Gate: connector isolation, scope display, token custody, revocation, minimised ingestion, and unrelated-data exclusion are verified.

## Phase 8 — Global provider expansion

Status: Not started

- Add regional public records, lawful broker adapters, image providers, and broader source coverage.
- Benchmark coverage, cost, retention risk, and failure semantics.

Gate: each adapter has reviewed terms/access basis, jurisdiction metadata, risk controls, coverage tests, and a manual fallback.

## Phase 9 — Hardening and release

Status: In progress; local candidate hardening/package proof passed, production release work remains

- Complete security, privacy, dependency, performance, accessibility, and legal-boundary reviews.
- Implement and crash-test independently versioned production database-key and backup-key rotation before real-data release.
- Run the isolated real macOS Keychain round trip and physical sleep/wake lifecycle check with explicit user approval.
- Propagate one production Developer ID through PyInstaller internals and every nested Tauri artifact, restore the hardened runtime, and validate on a clean supported macOS 14 arm64 Mac without Homebrew.
- Produce SBOM, signed application, notarised installer, signed updates, backup/restore documentation, and release candidate.

Gate: all release tests pass; limitations and residual risks are current; packaging contains no private or runtime data.

## Immediate execution sequence

Phases 0–3 are closed at their defined historical gates. The next sequence is:

1. Preserve the completed historical **45-operation/43-path** aggregate, frozen-sidecar, local-package, and targeted-visual candidate gate under its exact identities. Keep every earlier `0005`/`0006`/`0007`/`0008` artifact identity as historical evidence rather than relabelling it.
2. Preserve the now-completed full multi-language aggregate, privacy, frozen-sidecar, and packaged-app lifecycle gates for the current **48-operation/46-path** local candidate under the exact identities recorded in `TEST_RESULTS.md`. This is ad-hoc local package proof, not release approval.
3. Preserve the accepted visual evidence and recheck only changed or failing surfaces. The 69-image baseline remains closed unless a later failure points to a shared regression.
4. Complete Phase 5 evidence viewing/streaming and retention/purge, then connect scheduled ingestion to the durable Phase 6 checkpoint boundary. Preserve user-triggered checkpoints and deterministic reports as local fallbacks.
5. Add OAuth credentials and minimum-scope authorised Gmail/GitHub connectors, then expand public providers behind individual policy, failure-semantics, and provenance gates.
6. Complete production key rotation and physical lifecycle checks, then Developer ID signing, hardened runtime, notarisation, signed updates, and clean-machine validation.

The active source candidate contains **57 operations across 55 paths (4 GET, 53 POST)** at schema head `0011_profile_purge`. Its complete gate passes **498 Python tests with 4 intentional skips**, **95 Rust tests with one manual Keychain ignore**, **148/148 frontend tests across 36 files**, Ruff across 171 files, strict mypy across 94 files, generated contracts, a 440-candidate privacy scan, fresh frozen/staged inspection, and packaged normal/abrupt lifecycle verification. It adds persistent named-person audits, a seven-provider automatic public frontier, cited selected-local-AI analysis, canonical proposal promotion, exact-source continuity, restart recovery, and confirmed physical profile deletion. Current identities are `dccaaa5…` staged, `74325b3…` packaged-sidecar, and `08491aa…` desktop; `5ca6b790…`, `4ba7fd0…`, and `ca68fdd4…` remain historical 48-operation identities and are not relabelled. The official HIBP and optional OpenAI limitations recorded above remain unchanged. Phases 4–9 remain incomplete for the functional and production items listed above.
