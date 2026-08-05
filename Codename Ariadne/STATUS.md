# Codename Ariadne — Project Status

Last updated: 2026-08-05
Overall state: **streamlined foreground identity-audit workflow complete and packaged at the 57-operation/55-path candidate; production release readiness remains incomplete**

## Implemented at the current source boundary

- The generated contract contains **57 narrow operations (4 GET, 53 POST; 55 distinct paths)** at schema head `0011_profile_purge`.
- The current frontend passes typecheck, lint, production build, and **154/154 Vitest tests across 38 files**.
- Native vault creation now leads to explicit named-profile creation or
  selection. Intake refuses to create a hidden generic profile, and the default
  native route enters the persistent People workspace.
- People is now the persistent product centre: one named profile retains identifiers, exact sources, audit history, results, cited AI analysis, review proposals, and durable progress without re-entering data in Discovery Console.
- **Run full audit** snapshots explicit depth/request/time/provider/model settings and automatically works through DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate-transparency surfaces. It supports durable crash recovery, pause/resume/cancel, exact terminal outcomes, and progress derived from frontier state rather than animation.
- A terminal completed or partial audit now ends in a review gate and a
  deterministic Markdown/JSON download containing exact source URLs, provider
  results, coverage/failures, proposals, cited AI analysis, receipts,
  truncation flags, byte count, and SHA-256.
- Selected local AI runs after the deterministic frontier and stores only source-grounded facts, connections, and next steps with exact result citations. If the selected model is unavailable or changes, Ariadne records an explicit deterministic fallback instead of inventing a model result.
- Positive proposal decisions promote reviewed knowledge into canonical entities and retain proposal-to-entity exact-source provenance.
- A native **Delete active local profile** action requires typing the exact profile name, refreshes the profile revision, physically purges all profile-scoped rows and linked jobs/idempotency results in one transaction, uses SQLite secure deletion, and vacuums freed pages. The accidental July 23 workspace was removed from the live app and placed in a recoverable user Trash backup.
- The Discovery Console combines bounded DuckDuckGo HTML and unauthenticated GitHub-user search, official HIBP account/domain checks, a deterministic multi-identifier planner, fixed manual portals, and a local advanced query composer. The composer shows the exact query assembled from `site`, `filetype`, `intitle`, `inurl`, exclusion, date, and optional raw provider-specific operators; it can create user-opened handoffs for Google, Bing, DuckDuckGo, Brave, Ecosia, Startpage, and Mojeek or load the query into the bounded DuckDuckGo form. It does not scrape, import evidence automatically, or bypass controls.
- HIBP keys are supplied only for the request. Direct email transmission requires explicit self-audit and direct-transmission authorization; domain enumeration requires provider verification. The planner is deterministic and non-executing, and exposes exact routes, transmission classes, ordering, and unmet prerequisites.
- An official HIBP direct synthetic live smoke returned `SUCCEEDED`/`COMPLETE`, HTTP 200, and exactly one breach with an exact source. The official k-anonymity endpoint returned HTTP 401 for the public test key because that capability is plan/subscription gated; no k-anonymity success is claimed.
- AI analysis supports deterministic execution, loopback Ollama/OpenAI-compatible models, and an optional OpenAI Responses provider. The OpenAI path accepts an ephemeral per-request key and arbitrary explicit model ID, sends `store: false`, requires strict structured output, and remaps citations to the bounded source catalog. Its implementation/tests pass, but no real paid-key live result is claimed.
- Font scale offers 90%, 100%, 110%, 125%, and 140%, and display density offers Auto, Laptop, Standard, and Ultrawide presets. These presentation preferences remain local to the desktop webview.
- Public capture, exact-source entity/graph/finding/AI/report provenance, durable evidence/attribution, audit comparison, remediation, user-triggered checkpoints, and deterministic local reports remain implemented. No remediation send/submit/dispatch operation exists.

## Historical confidential-safe benchmark evidence

An earlier ephemeral, local-only benchmark used two confidential reference documents without recording their content, names, or claims. Connections and gap analysis used `LOCAL_MODEL`; both documents were cited and every returned citation resolved. The run used no external network and persisted no benchmark input or output. Only these aggregate facts are retained.

## Verification state

### Current 57-operation source evidence

- Generated contract: **57 operations / 55 paths (4 GET, 53 POST)**; drift check passes.
- Python: Ruff passes across **169 files**, strict mypy across **93 source files**, and the full aggregate completes with **500 passed and 5 intentional skips**.
- Rust: format and strict all-target Clippy clean; **90 passed, 0 failed, 1 ignored** manual Keychain test in 13.33 seconds.
- Frontend: typecheck, lint, production build, and **154/154 Vitest tests across 38 files** pass.
- Focused end-to-end backend: the synthetic named-profile → intake → decision →
  audit execution → cited AI → proposal promotion → reopen workflow passes.
- Privacy: **442 candidate files passed**.
- Private ignored validation: a depth-2, request-budget-150 run completed all
  **55/55** frontier tasks, retained **20** exact-source results and **41**
  connected leads, and completed a Qwen post-analysis with **20 valid
  citations**. Only aggregate counts are documented; its identifiers, URLs,
  model text, vault, and screenshots remain outside Git.
- Live local Qwen after SSD relocation: fresh opt-in `qwen3:30b` run **4/4
  passed in 30.23 seconds**; Ollama reported a bounded 19 GB runtime, 8K
  context, and 100% GPU execution.
  The running `llama-server` held its 18,556,685,856-byte model blob open from
  `/Volumes/Predator SSD GM7000/LLMs/Ollama/models`.
- Primary renderer journey: one synthetic native Playwright flow passed from
  vault creation through named profile, representative identity-clue intake,
  review, automatic audit progress, exact-source review, cited AI review, and
  final package download with zero external requests or runtime problems.
- Focused workflow visual evidence: nine 1720×1000 screenshots were captured
  and reviewed once; no blocking defect remained.
- Targeted Chromium: final gate **2/2 passed in 15.1 seconds**, with no external request, error, failed request, or horizontal overflow; the earlier screenshot capture/review run passed 2/2 in 21.3 seconds, and inspection of only the changed query composer and one Settings image found no blocking defect.
- HIBP direct official synthetic smoke: `SUCCEEDED`/`COMPLETE`, HTTP 200, one exact breach source.
- HIBP k-anonymity public-key smoke: HTTP 401 correctly surfaced as an HIBP plan/subscription requirement; no successful result claimed.
- OpenAI Responses: implementation and automated provider/citation tests pass; **no real paid-key live test**.

Current 57-operation local package evidence:

- Frozen/staged sidecar: 21,061,664 bytes, arm64/minimum macOS 11.0, SHA-256 `780924ee5c553b38a80f05b4055e35f10051f66f573142b0ea611efb2c7ce5a9`.
- Signed packaged sidecar: 21,062,832 bytes, SHA-256 `e1ebcdd61b2f80d450a85b80d133f7a33e3a9ada3de504a233fb199e9e6432e9`, CDHash `8ce5b76633c65a4fcc6dd04f9c708fa77748a011`.
- Desktop executable: 17,770,320 bytes, arm64/minimum macOS 14.0, SHA-256 `f45a29dd2f54add9ef3b468d7d411e042fd3c489a1a9996e2a90f2fa13a57def`, CDHash `d971b7b15bb0d7e8e46a76452509ada570e014ae`.
- Deep strict ad-hoc bundle signature passed; requested/abrupt starts completed in 7,230/2,805 ms with exit 0/-9, two sidecars, cleanup, zero TCP, and `0700`/`0600` runtime modes.

### Historical 48- and 45-operation candidate evidence

The historical **45-operation/43-path** candidate remains preserved separately:

- Python: **450 passed, 4 skipped in 1,577.01 seconds**.
- Rust: format and Clippy clean; **89 passed, 1 ignored in 72.55 seconds**.
- Frontend: **122/122 tests across 29 files**, typecheck, lint, and production build.
- Live local Qwen: **4 passed in 123.30 seconds**, **8 guard tests in 19.23 seconds**, and **4 API tests in 50.83 seconds**.
- Privacy: **398 candidate files passed**.
- Frozen sidecar: 20,892,240 bytes, SHA-256 `b33e411e95c4147ed3a16fe7894f490bcb47884c23703a1888f648638267831f`.
- Packaged sidecar: 20,892,224 bytes, SHA-256 `536c16a851d11676438899b5edc07de2bef11efa704648618149581602f8e82f`.
- Desktop executable: 16,435,024 bytes, SHA-256 `d3eef7bac068674849b9c3489caafe4887f76d6b53ed90d48b202276c711819f`.

Those identities remain historical evidence only and are not relabelled as 48-operation package proof.

## Phase gates

| Phase | Current result |
|---|---|
| Phase 0 — Discovery and architecture | **Passed** |
| Phase 1 — UI-first prototype | **Passed**; 69/69 accepted historical synthetic screenshots |
| Phase 2 — Local foundation | **Passed** |
| Phase 3 — Intake and identity compiler | **Passed historically** at `0005_graph_edge_origins`; later provenance and AI additions are source-head work |
| Phase 4 — Search compiler and initial adapters | **Public search, HIBP, deterministic planning, manual portals, and local advanced query composition implemented**; broader providers and operational retry orchestration remain incomplete |
| Phase 5 — Evidence and attribution | **Atomic public capture and exact-source traversal implemented**; evidence viewing/streaming, retention/purge, and broader ingestion remain incomplete |
| Phase 6 — Monitoring and remediation | **Comparison, remediation, checkpoints, and exact-source reports implemented**; scheduling, operational ingestion, durable report lifecycle, and retention remain incomplete |
| Phase 7 — Authorised account connectors | **Not started**; OAuth credentials and Gmail/GitHub connector isolation remain follow-on work |
| Phase 8 — Global provider expansion | **Not started** beyond the bounded current discovery providers |
| Phase 9 — Hardening and release | **In progress**; current 57-operation local package proof passed, while production signing/notarisation, signed updates, physical lifecycle, and clean-machine validation remain |

## Important boundaries

- Exact sources are retained wherever the provider supplies them; an empty, blocked, unauthorised, rate-limited, or plan-gated check is not proof of nonexistence.
- Model output is review-only. A model cannot create evidence by assertion, approve disclosure, change policy, or take an external action.
- Selecting OpenAI Responses is an external transmission. The API key is per-request and `store: false` is requested, but provider-side network processing and policy still apply.
- No authorised Gmail/GitHub account connectors, operational scheduler, automated retention/purge service, or broad provider fleet exists yet.
- The app is a local development candidate, not a distributable release. Developer ID signing, hardened runtime/notarisation, update signing, and clean supported-Mac validation remain Phase 9 work.

## Next milestone

The current scoped goal is complete. Optional follow-on work is evidence
streaming/retention, authorised connectors, specialist providers, saved-artifact
management, and production release validation. Background scheduling is not a
current priority. Preserve earlier artifact identities as historical local
proof, not evidence for this source or a distributable release.
