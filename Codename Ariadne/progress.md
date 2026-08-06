# Codename Ariadne — Progress Estimate

Last updated: 2026-08-06
Estimated overall completion: **96%**
Confidence: **moderate**

This is a planning estimate, not a release claim. It may move up or down when testing exposes additional work.

Current scoped goal — streamlined foreground workflow: **100% implemented and
automatically verified and repackaged**. Named profile → intake → entity review → complete
audit → proposal review → cited package is covered. The rebuilt local package
was approved through the normal macOS Keychain sheet without exposing the
credential. Both remaining local profiles were then deleted through Ariadne's
confirmed UI; People reported no profiles, Mission Control reported no audit
data, and the vault stayed unlocked across navigation. This does not mean
production release readiness or unlimited provider coverage.

## Current position

| Phase | State | Estimated phase completion |
|---|---|---:|
| Phase 0 — Discovery and architecture | Complete and tested | 100% |
| Phase 1 — UI system and interactive prototype | Complete and tested | 100% |
| Phase 2 — Local foundation | Complete and tested | 100% |
| Phase 3 — Intake and identity compiler | Complete, persistent, and tested; named profiles now support confirmed physical deletion | 100% |
| Phase 4 — Search compiler and initial adapters | Durable one-command audit plus seven automatic public surfaces, HIBP state, retry/frontier orchestration, manual portals, and advanced query composition implemented | 95% |
| Phase 5 — Evidence and attribution | Exact result URLs, cited local-AI analysis, proposal review/promotion, and whole-profile purge implemented; general evidence streaming/retention remains | 96% |
| Phase 6 — Monitoring and remediation | Durable audit progress/history, pause/resume/cancel, comparison/remediation, checkpoints, reports, and terminal cited audit packages implemented; background scheduling is out of the current scope | 95% |
| Phase 7 — Authorised account connectors | Not started | 0% |
| Phase 8 — Global provider expansion | Seven credential-free public surfaces execute automatically; credentialed and specialist provider coverage remains | 42% |
| Phase 9 — Hardening and release | Current schema-0011 local package/lifecycle proof passes; production signing, notarisation, physical lifecycle, and clean-machine release work remain | 45% |

The active source candidate contains **58 operations across 56 paths (4 GET, 54 POST)** at schema head `0011_profile_purge`. A named person profile now retains reviewed identifiers, exact sources, audit history, durable frontier state, results, cited AI analysis, and review proposals. **Run full audit** executes DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate-transparency checks automatically within explicit budgets; optional HIBP remains authentication-gated. Positive proposal review can promote knowledge into canonical entities with exact source provenance. Profile deletion requires an exact-name confirmation, erases every profile-owned table in dependency order, removes linked jobs/idempotency records, and enables SQLite secure deletion. It deliberately avoids synchronous `VACUUM`, whose exclusive lock could reject a foreground purge while the unlocked app is reading. The local-model header control can now release an Ollama model without clearing the selected model.

The current gate has passed strict Python formatting/lint/type checking, **503
Python tests with 5 intentional skips**, regenerated-contract drift,
**92 Rust tests plus one manual Keychain ignore**, **164/164
frontend tests across 40 files**, the focused backend profile-to-audit
integration, and a complete primary-renderer Playwright journey. Retained audit
responses now fail per-route instead of killing Core or relocking the vault;
legacy local-model prose is normalized into the current bounded display
contract; a failed initial reopen shows retry/back controls instead of an
endless loader; and Geographic Map is correctly labelled vault-backed with
proper metric cards. After moving the complete Ollama model store to the
external SSD, a fresh **4/4 live `qwen3:30b`** run passed in **30.23 seconds**
with task-specific structured output, exact citation constraints, an 8K
context, and the model blob verified open from the SSD. A private, ignored
depth-2/request-budget-150 validation also completed 55/55 frontier tasks,
retained 20 exact-source results, and produced a 20-citation Qwen analysis
without copying its identifiers or sources into Git. Production build,
generated-contract drift, fresh schema-0011 frozen/staged inspection, and
normal/abrupt packaged-app lifecycle verification pass. Every 48-operation and
earlier package identity remains historical evidence and has not been
relabelled.

Native Mission Control, Operations, Case Desk, Source Coverage, Transmission
Preflight, Link Map, and notifications now project the active audit or show an
honest pre-audit empty state; they no longer present the Morgan Vale demo in a
native vault. Link Map uses a central profile hub, semantic identifier
clusters, reviewed evidence edges, and bounded exact-URL-cited `CONNECTION`
insights. Model edges remain provisional and require human review.

## What remains most significant

- Complete evidence viewing/streaming, retention/purge, and broader operational finding ingestion.
- Add background scheduling only if it becomes useful later; it is not part of
  the completed foreground workflow.
- Add durable report/approval/artifact records, destination brokering, and release-grade export validation.
- Add minimum-scope authorised connectors and specialist/credentialed provider coverage.
- Complete production key rotation, physical lifecycle/Keychain exercises, Developer ID signing, hardened runtime, notarisation, signed updates, and clean-machine release validation.

The estimate is **96%** for the wider intended single-user local product. The
current foreground workflow implementation is complete: persistent profile selection,
one-time intake/review, automatic public-provider execution, honest progress,
citations, selectable local AI, proposal review, exact sources, terminal
Markdown/JSON packaging, history, and deletion are implemented. Final
private-vault deletion and the honest pre-audit empty state are now verified.
The wider remaining work is provider breadth, general evidence streaming/retention,
durable saved-artifact management, and production distribution. This is not
100% overall and not public release readiness.

## Update policy

Update this file only after meaningful tested capability or a changed scope/risk assessment. It is valid to lower the percentage. Detailed evidence belongs in `STATUS.md` and `TEST_RESULTS.md`.
