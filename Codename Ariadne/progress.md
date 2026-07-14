# Codename Ariadne — Progress Estimate

Last updated: 2026-07-14  
Estimated overall completion: **95%**  
Confidence: **moderate**

This is a planning estimate, not a release claim. It may move up or down when testing exposes additional work.

## Current position

| Phase | State | Estimated phase completion |
|---|---|---:|
| Phase 0 — Discovery and architecture | Complete and tested | 100% |
| Phase 1 — UI system and interactive prototype | Complete and tested | 100% |
| Phase 2 — Local foundation | Complete and tested | 100% |
| Phase 3 — Intake and identity compiler | Complete and tested at the synthetic local gate | 100% |
| Phase 4 — Search compiler and initial adapters | Public search, HIBP, deterministic planning, manual portals, and local advanced query composition implemented; wider providers/retry orchestration remain | 88% |
| Phase 5 — Evidence and attribution | Atomic exact-source capture and provenance implemented; retention/purge and broader ingestion remain | 93% |
| Phase 6 — Monitoring and remediation | Comparison/remediation, local checkpoints, and reports implemented; scheduling and durable report lifecycle remain | 90% |
| Phase 7 — Authorised account connectors | Not started | 0% |
| Phase 8 — Global provider expansion | Not started beyond current bounded discovery providers | 8% |
| Phase 9 — Hardening and release | Current local package/lifecycle proof passes; production signing, notarisation, physical lifecycle, and clean-machine release work remain | 35% |

The active source candidate contains **48 operations across 46 paths (4 GET, 44 POST)**. The local advanced query composer adds no route: it shows the exact query, uses a TypeScript-and-Rust-validated native browser handoff, and performs no scraping or automatic evidence import. Generated contracts pass; the current gate includes **493 Python passes plus 4 intentional live-provider skips**, **95 Rust passes plus one manual Keychain ignore**, **143/143 frontend tests across 36 files**, a separate 4/4 live `qwen3:30b` run, and a 425-candidate privacy scan. Official HIBP direct synthetic live verification succeeded with one exact source; a public test key correctly encountered the k-anonymity endpoint's plan requirement. Optional OpenAI Responses support is implemented and automated-tested with an ephemeral per-request key, explicit model choice, `store: false`, strict structured output, and citation remapping, but has no real paid-key live test.

The complete current aggregate, frozen/staged inspection, ad-hoc packaged lifecycle, signature, zero-TCP, permission, cleanup, and targeted Chromium gates pass under the exact 48-operation identities recorded in `TEST_RESULTS.md`. Every 45-operation and earlier identity remains historical evidence and has not been relabelled.

## What remains most significant

- Complete evidence viewing/streaming, retention/purge, and broader operational finding ingestion.
- Connect operational adapters and a scheduler to the durable Phase 6 checkpoint boundary.
- Add durable report/approval/artifact records, destination brokering, and release-grade export validation.
- Add minimum-scope authorised connectors and broader provider coverage.
- Complete production key rotation, physical lifecycle/Keychain exercises, Developer ID signing, hardened runtime, notarisation, signed updates, and clean-machine release validation.

The estimate is **95%** because the current local aggregate and package gate now closes in addition to the core workflows, exact-source handling, bounded discovery, HIBP checks, selectable AI, and desktop interface. The remaining work is narrower but release-critical: connectors, scheduler, retention, durable reporting, and production distribution. This is not 100% and not release readiness.

## Update policy

Update this file only after meaningful tested capability or a changed scope/risk assessment. It is valid to lower the percentage. Detailed evidence belongs in `STATUS.md` and `TEST_RESULTS.md`.
