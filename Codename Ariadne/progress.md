# Codename Ariadne — Progress Estimate

Last updated: 2026-07-23
Estimated overall completion: **96%**
Confidence: **moderate**

This is a planning estimate, not a release claim. It may move up or down when testing exposes additional work.

## Current position

| Phase | State | Estimated phase completion |
|---|---|---:|
| Phase 0 — Discovery and architecture | Complete and tested | 100% |
| Phase 1 — UI system and interactive prototype | Complete and tested | 100% |
| Phase 2 — Local foundation | Complete and tested | 100% |
| Phase 3 — Intake and identity compiler | Complete, persistent, and tested; named profiles now support confirmed physical deletion | 100% |
| Phase 4 — Search compiler and initial adapters | Durable one-command audit plus seven automatic public surfaces, HIBP state, retry/frontier orchestration, manual portals, and advanced query composition implemented | 95% |
| Phase 5 — Evidence and attribution | Exact result URLs, cited local-AI analysis, proposal review/promotion, and whole-profile purge implemented; general evidence streaming/retention remains | 96% |
| Phase 6 — Monitoring and remediation | Durable audit progress/history, pause/resume/cancel, comparison/remediation, checkpoints, and reports implemented; background scheduling and durable report lifecycle remain | 93% |
| Phase 7 — Authorised account connectors | Not started | 0% |
| Phase 8 — Global provider expansion | Seven credential-free public surfaces execute automatically; credentialed and specialist provider coverage remains | 42% |
| Phase 9 — Hardening and release | Current schema-0011 local package/lifecycle proof passes; production signing, notarisation, physical lifecycle, and clean-machine release work remain | 45% |

The active source candidate contains **57 operations across 55 paths (4 GET, 53 POST)** at schema head `0011_profile_purge`. A named person profile now retains reviewed identifiers, exact sources, audit history, durable frontier state, results, cited AI analysis, and review proposals. **Run full audit** executes DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate-transparency checks automatically within explicit budgets; optional HIBP remains authentication-gated. Positive proposal review can promote knowledge into canonical entities with exact source provenance. Profile deletion requires an exact-name confirmation, erases every profile-owned table in dependency order, removes linked jobs/idempotency records, enables SQLite secure deletion, and vacuums freed pages.

The current gate has passed strict Python formatting/lint/type checking, the full Python aggregate (**498 passed, 4 intentional skips**), **95 Rust tests plus one manual Keychain ignore**, **148/148 frontend tests across 36 files**, production build, generated-contract drift, a **440-file privacy scan**, fresh schema-0011 frozen/staged inspection, and normal/abrupt packaged-app lifecycle verification. Every 48-operation and earlier package identity remains historical evidence and has not been relabelled.

## What remains most significant

- Complete evidence viewing/streaming, retention/purge, and broader operational finding ingestion.
- Connect operational adapters and a scheduler to the durable Phase 6 checkpoint boundary.
- Add durable report/approval/artifact records, destination brokering, and release-grade export validation.
- Add minimum-scope authorised connectors and specialist/credentialed provider coverage.
- Complete production key rotation, physical lifecycle/Keychain exercises, Developer ID signing, hardened runtime, notarisation, signed updates, and clean-machine release validation.

The estimate is **96%** for the intended single-user local product: the primary persistent person/audit journey, real progress, automatic public-provider fleet, citations, selectable local AI, exact sources, and deletion are implemented. The remaining work is narrower but release-critical: connectors, a background scheduler, general retention/streaming, durable reporting, and production distribution. This is not 100% and not public release readiness.

## Update policy

Update this file only after meaningful tested capability or a changed scope/risk assessment. It is valid to lower the percentage. Detailed evidence belongs in `STATUS.md` and `TEST_RESULTS.md`.
