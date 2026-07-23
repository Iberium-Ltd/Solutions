# Codename Ariadne — Test Results

Last updated: 2026-07-23
Current status: **streamlined foreground workflow, 57-operation/55-path source aggregate, frozen sidecar, and packaged macOS lifecycle pass**

No confidential-reference content, name, or claim is reproduced in these results. Tests use synthetic fixtures except for the aggregate-only, ephemeral local benchmark described below.

## Current 57-operation source candidate

The schema head is `0011_profile_purge`. The generated contract has **57
operations (4 GET, 53 POST; 55 distinct paths)**. The nine operations added
after the last packaged candidate are eight persistent identity-discovery
operations and one confirmed physical-profile deletion operation.

| Category | Current result |
|---|---|
| Python quality | Ruff passed across **171 files**; strict mypy passed across **94 source files** |
| Python full aggregate | **498 passed, 4 intentional skips in 473.34 seconds** |
| Generated contracts | OpenAPI/TypeScript/Rust generation and drift checks passed at **57 operations / 55 paths** |
| Rust | Format and strict all-target Clippy clean; **95 passed, 0 failed, 1 ignored** manual macOS Keychain test in **15.16 seconds** |
| Frontend | **152/152 passed across 38 files**; typecheck, lint, and production build passed |
| Focused workflow | **16/16 frontend workflow tests**, the backend profile-to-audit integration, and one complete native-renderer Playwright journey passed |
| Live local Qwen | Post-relocation opt-in `qwen3:30b` schema, summary, connections, and gap-analysis run: **4/4 passed in 127.90 seconds**; Ollama reported 45 GB at 100% GPU and opened the 18,556,685,856-byte model blob from the SSD |
| Focused screenshots | Nine 1720×1000 primary-journey screens captured and reviewed once; zero external requests/runtime problems and no blocking visual defect |
| Privacy | **445 candidate files passed** |
| Frozen/package | Schema-0011 frozen/staged inspection, deep strict ad-hoc signature, and normal/abrupt packaged lifecycle passed |

The streamlined-workflow tests verify explicit named-profile routing, refusal
of anonymous intake, profile-bound extraction, the terminal audit review gate,
and deterministic cited Markdown/JSON download. The backend integration covers
synthetic profile creation, intake, decisions, person persistence, automatic
audit execution, exact results, cited local AI, proposal promotion, and reopen.
The Playwright journey uses only synthetic name, username, URL, workplace, and
location clues and traverses every primary UI handoff through a downloaded
cited package.

The profile-deletion integration test creates a synthetic profile with ingested
identity data, rejects a mismatched confirmation name, deletes with the current
revision and exact name, and confirms that no row with that vault/profile scope
remains in any installed table. Renderer tests verify the fixed native command,
response scope, exact-name prompt, and navigation-memory reset.

## Current 57-operation frozen/package verification

```text
Schema/archive:   0011_profile_purge
Architecture:     arm64
Minimum macOS:    11.0
Frozen/staged:    21,053,600 bytes
Staged SHA-256:   dccaaa5d3c9a60b668ecd85cdd0d00a79c4b16aadd2c02995e43891478a9d7f5
```

Fresh frozen and staged inspections both passed authenticated development TCP
and packaged-style UDS workflows. Each reported exact schema head
`0011_profile_purge`; the UDS flow returned 200 for vault, profile, intake,
review, manual-finding, two-checkpoint, and report operations, while wrong-token
401, denied-origin 403, and replay 409 checks remained enforced.

| Package evidence | Current 57-operation result |
|---|---|
| Requested quit | 3,852 ms startup; exit 0; two sidecar processes; cleanup true; zero TCP |
| Abrupt parent exit | 2,532 ms startup; exit -9; two sidecar processes; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 21,053,584 bytes; arm64/minimum macOS 11.0; SHA-256 `74325b31abba5afb4f916051898c80431018cd4a0b8ae90a9f44f0183281d7b0`; CDHash `396892d4ec3a4784ceb924ddff682987ac65d852` |
| Desktop executable | 17,815,088 bytes; arm64/minimum macOS 14.0; SHA-256 `716052aab25cb30f2784c876e27f17c8ae2664f8b6f688a1db8377a57e06399d`; CDHash `a743997917251694713e1e44494d9aac94a5aa02` |
| Bundle | 38,032 KiB allocated; deep strict ad-hoc signature verification passed |

This is local ad-hoc candidate proof. It is not Developer ID, hardened-runtime,
notarisation, signed-update, clean-machine, or public-release proof.

## Historical 48-operation source candidate

The schema remains `0008_phase6_audit_remediation`. The generated contract has
**48 operations (4 GET, 44 POST; 46 distinct paths)**. The three operations added
after the historical 45-operation package are official HIBP account/domain checks
and deterministic, non-executing investigation-plan compilation. The local
advanced-query composer and its approved-browser handoff add no API route.

| Category | Current result |
|---|---|
| Python quality | Ruff passed across **162 files**; strict mypy passed across **90 files** |
| Python full aggregate | **493 passed, 4 intentional live-provider skips in 1,694.11 seconds** |
| Generated contracts | Generator and OpenAPI/TypeScript/Rust drift checks passed at **48 operations / 46 paths** |
| Rust | Format and strict all-target Clippy clean; **95 passed, 0 failed, 1 ignored** manual macOS Keychain test in **22.31 seconds** |
| Frontend | **143/143 passed across 36 files**; typecheck, lint, and production build passed |
| Live local Qwen | Historical opt-in `qwen3:30b` run: **4/4 passed in 125.98 seconds** |
| Privacy | **425 candidate files passed** |
| Targeted browser gate | Final Chromium **2/2 passed in 15.1 seconds**; no external request, console/page error, failed request, or horizontal overflow |
| Frozen/package | Fresh frozen-sidecar inspection/staging and final ad-hoc Tauri package lifecycle/signature gates passed under the identities below |

The targeted visual review intentionally did not reload the accepted 69-screen
baseline. Its screenshot capture/review run passed **2/2 in 21.3 seconds**. Only
the changed query-composer surface and one Settings presentation were inspected;
neither showed a blocking defect.

The native approved-browser opener validates fixed portal, generated search, and
HIBP URLs independently in TypeScript and Rust before invoking macOS
`NSWorkspace`. It is not an API route, scraper, evidence importer, or access-control
bypass.

## Current 48-operation frozen/package verification

```text
Schema/archive:   0008_phase6_audit_remediation
Architecture:     arm64
Minimum macOS:    11.0
Frozen/staged:    20,946,896 bytes
Staged SHA-256:   5ca6b790878cc7f77b99cc21e75e49c2febf8208dccbf87cb523669515262df3
```

The initial frozen inspection completed its TCP verifier in **3,686 ms** and its
authenticated UDS workflow/cleanup verifier in **45,743 ms**. Staging reinspection
completed the same paths in **3,734 ms** and **66,387 ms**. Both workflow gates
passed. These are verifier durations, not application-readiness guarantees.

| Package evidence | Current 48-operation result |
|---|---|
| Requested quit | 3,290 ms startup; exit 0; two sidecar processes; cleanup true; zero TCP |
| Abrupt parent exit | 2,550 ms startup; exit -9; two sidecar processes; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,946,880 bytes; arm64/minimum macOS 11.0; SHA-256 `4ba7fd0a6f99135b96f412a4371c5f7783ffb6c4ae5cbe6ac1f8fd82d36d324b`; CDHash `bac9d49b49c770a460ddae9698a4e39a12a4b92c` |
| Desktop executable | 16,979,744 bytes; arm64/minimum macOS 14.0; SHA-256 `ca68fdd4957c7540716f4e7a9b0d54cea657e44cb2bdf68cc012d67cada3d3ec`; CDHash `f096565871d279b40f5196c51ae40a3e94cf9f3c` |
| Bundle | 37,108 KiB allocated; deep strict ad-hoc signature verification passed |

This closes the local candidate package gate for the 48-operation source. It is
not Developer ID, hardened-runtime, notarisation, signed-update, clean-machine,
or public-release proof.

## Historical verified Phase 3 gate

These results belong to the closed Phase 3 artifact at `0005_graph_edge_origins`; they must not be used as evidence for the current 45-operation source candidate.

| Category | Historical Phase 3 result |
|---|---|
| Python core | **265/265 passed in 172.80 seconds** |
| Python quality | Ruff, strict mypy, SQLCipher driver, lock, and generated-contract drift passed |
| Rust | **63 passed, 0 failed, 1 ignored** manual macOS Keychain prompt test; format/Clippy passed |
| Frontend | **41/41 passed across 12 files**; typecheck, lint, and production build passed |
| Privacy | 286 candidate files in the aggregate; 292 in the then-final documentation rerun |
| Visual baseline | Phase 1 `pass-02b`: **69/69 accepted**; Phase 3 used two targeted captures |

Historical frozen/package artifact:

```text
Staged sidecar: 20,403,456 bytes
SHA-256:        c4a77933840a32d8751235eeeeea70a5d55f670869c7db8cd5499f04184cdf93
Minimum macOS:  11.0
Schema:         0005_graph_edge_origins
```

The historical UDS probe passed encrypted profile creation, intake, quarantine, and review. The packaged app passed zero-TCP normal/SIGKILL cleanup, `0700` runtime-directory and `0600` socket permissions, and `codesign --verify --deep --strict`. The signed sidecar and desktop identities remain recorded in the Phase 3 changelog/status history.

## Historical 45-operation source candidate

The schema remains `0008_phase6_audit_remediation`. The generated contract now has **45 operations (4 GET, 41 POST; 43 distinct paths)**. The five operations added after the historical 40-operation package are:

- `POST /v1/discovery/public/search`
- `POST /v1/discovery/public/capture`
- `POST /v1/entities/origins`
- `POST /v1/local-ai/corpus/analyze`
- `POST /v1/local-ai/workspace/analyze`

The local-AI operations can use a selectable loopback model such as Qwen or explicit deterministic execution. Both paths return review-only, source-cited results rather than autonomous decisions.

| Category | Current result |
|---|---|
| Python quality | Ruff format/check and strict mypy passed |
| Python full aggregate | **450 passed, 4 skipped in 1,577.01 seconds** |
| Generated contracts | Generator and OpenAPI/TypeScript/Rust drift checks passed at **45 operations / 43 paths** |
| Rust | Format and Clippy clean; **89 passed, 0 failed, 1 ignored in 72.55 seconds** |
| Frontend | **122/122 passed across 29 files**; typecheck, lint, and production build passed |
| Frontend concurrency note | One resource-heavy concurrent run exposed an isolated flaky failure; the same test passed alone and the final serial frontend gate passed |
| Live Qwen | **4 passed in 123.30 seconds**; **8 guard tests passed in 19.23 seconds**; **4 API tests passed in 50.83 seconds** |
| Privacy | **398 candidate files passed** |
| Frozen/package | Fresh frozen-sidecar inspection/staging and final ad-hoc Tauri package lifecycle/signature gates passed under the identities below |
| Visual review | Fresh-context Playwright capture **4/4 passed** at 1440×900; focused corrected entity-origin recapture **1/1 passed**; five artifacts retained; manual inspection found no blocking defect |

Focused verification covers exact URL/hash binding and atomic rollback for public capture; stable profile-scoped entity-origin pagination; source-catalog equality for corpus/workspace AI; rejection or removal of unsupported citations; exact report source mappings; deterministic fallback; and the absence of AI-driven external actions. The local-AI result contracts explicitly report whether projection was truncated and whether deterministic fallback occurred.

The final clean Rust run supersedes the earlier load-induced timeout/mutex cascade. Live-model tests are recorded separately because they require the explicitly selected local Qwen runtime and are not hidden inside deterministic fallback coverage.

### Confidential-safe local benchmark

An ephemeral benchmark read **two confidential reference documents** only in local process memory. Connections and gap analysis both completed with `LOCAL_MODEL`; both documents were cited and all citations resolved. No external network was used, nothing from the benchmark was persisted, and only these aggregate facts—not document content, names, or claims—were retained in this file.

## Historical 45-operation frozen/package verification

Fresh frozen output root: `/tmp/ariadne-frozen-sidecar-45op.slhsx2`

```text
Schema/archive:   0008_phase6_audit_remediation
Architecture:     arm64
Minimum macOS:    11.0
Staged size:      20,892,240 bytes
Staged SHA-256:   b33e411e95c4147ed3a16fe7894f490bcb47884c23703a1888f648638267831f
```

The initial frozen inspection completed its TCP verifier in 4,046 ms and its full UDS workflow/cleanup verifier in 100,505 ms; staging reinspection completed those verifier paths in 4,963 ms and 85,838 ms. These are full verifier durations, not readiness measurements. Both runs exited 0, enforced wrong-token 401, denied-origin 403, and replay 409, and the UDS workflow returned 200 for vault/profile/intake/review/manual-finding/two-checkpoint/report operations at exact schema head `0008_phase6_audit_remediation`. Architecture, minimum OS, dependencies, archive contents, migration assets, size, and strict ad-hoc signature checks passed.

| Package evidence | Current 45-operation result |
|---|---|
| Requested quit | 6,974 ms startup; exit 0; two sidecar processes; cleanup true; zero TCP |
| Abrupt parent exit | 5,511 ms startup; exit -9; two sidecar processes; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,892,224 bytes; arm64/minimum macOS 11.0; SHA-256 `536c16a851d11676438899b5edc07de2bef11efa704648618149581602f8e82f` |
| Desktop executable | 16,435,024 bytes; arm64/minimum macOS 14.0; SHA-256 `d3eef7bac068674849b9c3489caafe4887f76d6b53ed90d48b202276c711819f` |
| Signature | Deep bundle, main executable, and sidecar strict ad-hoc verification passed; bundle satisfies its designated requirement; main CDHash `b763b1e8fa50725303a152e684d987f535cc580a`; sidecar CDHash `5c3c20bf6ad6531c202f19186b65d30d72c03a7b` |
| Final reopen | Main plus two sidecar processes confirmed; process tree ready within 2 seconds after reopening the verified bundle |

This is a local ad-hoc candidate-package gate, not Developer ID, hardened-runtime, notarisation, signed-update, clean-machine, or public-release proof.

## Historical 40-operation source/package verification

Before the five current operations were added, the 40-operation source head passed **372 Python tests in 383.52 seconds**, **82 Rust tests with one ignored manual Keychain test**, **96 frontend tests across 23 files**, Chromium and WebKit route/accessibility smokes, all static/contract gates, and a **354-candidate privacy scan**. Those results and the package below remain valid evidence for that earlier source only.

```text
Schema/archive:   0008_phase6_audit_remediation
Architecture:     arm64
Minimum macOS:    11.0
Staged size:      20,694,992 bytes
Staged SHA-256:   96c368b90692e452de2b14a58994105a7838ce5ad06231169f9d5d381234a610
```

Frozen inspection passed the architecture, minimum-OS, dependency, archive, path/string denylist, schema, and 40-operation checks. Its authenticated UDS lifecycle returned 200 for manual finding creation, baseline checkpoint creation, current checkpoint creation, and local report generation.

| Package evidence | Historical 40-operation result |
|---|---|
| Requested quit | 4,116 ms startup; exit 0; two sidecar processes; cleanup true; zero TCP |
| Abrupt SIGKILL | 2,646 ms startup; exit -9; two sidecar processes; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,694,976 bytes; arm64/minimum macOS 11.0; SHA-256 `77338ee05e0f0b92e0483c0e9d936446b5a162285d9c75c09aa47ea4d0e69b94` |
| Desktop executable | 15,510,800 bytes; arm64/minimum macOS 14.0; SHA-256 `214ccd0f3fccfa9d42c2af7598d62f74693ec3cb01a7b585aac73a890e9fc053` |
| Signature | Deep bundle, main executable, and sidecar strict ad-hoc `codesign` verification passed |

These are local ad-hoc candidate-package results, not evidence for the current 45-operation source and not Developer ID, hardened-runtime, notarisation, clean-machine, or release proof. The earlier `0005`/`0006`/`0007` and 37-operation `0008` identities below also remain historical evidence.

## Historical 37-operation packaged-`0008` source aggregate

This preserved aggregate is the source that produced the earlier 37-operation `0008` package. It covers bounded Phase 5 writes, ten-table Phase 6 persistence, native Compare/Removal views, and local remediation mutations. It remains historical evidence and is not relabelled as the later 40-operation artifact or the current source candidate.

| Category | Recorded packaged-`0008` result |
|---|---|
| Python quality | Ruff format/check clean across **123 files**; strict mypy clean across **67 source files** |
| Python core | **350/350 passed in 271.18 seconds** |
| Generated contracts | Drift check clean; **37 operations (4 GET, 33 POST)** |
| Rust | **76 passed, 0 failed, 1 ignored** manual macOS Keychain prompt test; format/Clippy clean; focused mutation 3/3 and contract 9/9 |
| Frontend | **86/86 passed across 21 files**; typecheck, Oxlint, and production build clean |
| Privacy | **341 candidate files passed** after documentation updates |

## Historical 37-operation `0008` frozen/package verification

Frozen output root: `/tmp/ariadne-phase6-package.GDaFwQ`

```text
Schema/archive:   0008_phase6_audit_remediation
Architecture:     arm64
Minimum macOS:    11.0
Staged size:      20,639,264 bytes
Staged SHA-256:   e156e9ec31e95ef76f2f84779796176a422f1cc90d6cee624cdbdb61b024f3de
Initial TCP/UDS:  3,353 / 4,470 ms; exit 0
Staging TCP/UDS:  1,925 / 4,355 ms; same digest
```

The authenticated UDS probe reported exact schema head `0008_phase6_audit_remediation` and all ten Phase 6 tables. Frozen inspection passed architecture, minimum-OS, dependency, archive, path/string denylist, and 37-operation contract checks.

| Package evidence | Recorded `0008` result |
|---|---|
| Requested quit | 2,325 ms startup; exit 0; two sidecar processes; cleanup true; zero TCP |
| Abrupt SIGKILL | 1,927 ms startup; exit -9; two sidecar processes; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,639,248 bytes; arm64/minimum macOS 11.0; SHA-256 `359fd0403dc23a99ea3aa19d18c2b3e83b2bc3ed205a3d7ef4f858fc3e6a032d` |
| Desktop executable | 15,262,736 bytes; arm64/minimum macOS 14.0; SHA-256 `fc02daef7835b4225cee27f769feee9302764f040037acf0e86a23e388235fc9` |
| Bundle | 35,975,168 allocated bytes; 5 regular files / 9 entries; expected application identifier |
| Signature | Deep bundle, main executable, and sidecar strict ad-hoc `codesign` verification passed |

Dependency, path, and string denylists passed. The final repository privacy scan passed across 341 candidates. These are local ad-hoc development-package results, not Developer ID, hardened-runtime, notarisation, or clean-machine proof.

Verified `0007` evidence below remains historical and is not proof of `0008`.

## Verified `0007` source aggregate

The complete Phase 5 aggregate components were run independently and completed cleanly for schema head `0007_phase5_evidence_attribution`. This is a verified read milestone, not a completed Phase 5 gate.

| Category | Verified `0007` result |
|---|---|
| Privacy | **327 candidate files passed** |
| Python quality | Ruff format/check clean across **116 files**; strict mypy clean across **64 source files** |
| Python core | **329/329 passed in 143.30 seconds** |
| Generated contracts | Drift check clean |
| Rust | **68 passed, 0 failed, 1 ignored** manual macOS Keychain prompt test; format/Clippy clean |
| Frontend | **60/60 passed across 17 files**; typecheck, lint, and production build clean |

This aggregate covers durable encrypted Phase 5 repositories, profile listing/resume, generated authenticated read operations, Rust response validation, and native Findings list/detail behavior. It does not prove mutation workflows, operational provider-produced findings, or complete provenance traversal. The separately identified `0007` package evidence follows.

## Verified `0007` frozen/package verification

```text
Schema/archive:   0007_phase5_evidence_attribution
Architecture:     arm64
Staged size:      20,550,480 bytes
Staged SHA-256:   5d4856853db1e8194d2a3930830081bcdba50c31457acca151b0ea972c5059a4
```

| Package evidence | Verified `0007` result |
|---|---|
| Requested quit | 2,556 ms startup; cleanup true; zero TCP |
| Abrupt SIGKILL | 1,921 ms startup; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,550,464 bytes; SHA-256 `fe0e7d5bc7aebe1aa83b21745612b68d82c444a0f7af10b43ac58ecdb2d4a47c` |
| Desktop executable | 14,124,624 bytes; SHA-256 `2cd7cc41ff1c4bc6ce71e9dab1b9efe91c21ab8ffdabb59ca330bf6dd0604e0b` |
| Signature | arm64 `codesign --verify --deep --strict` passed |

The package reported schema/archive `0007_phase5_evidence_attribution`, exposed no TCP listener, preserved the private runtime modes, and cleaned up after both requested and abrupt exits. The matching final privacy scan passed across 327 candidate files.

## Preserved `0006` candidate aggregate

`make phase4-check` completed cleanly for the previously packaged `0006` source:

| Category | Preserved `0006` result |
|---|---|
| Privacy | **313 candidate files passed** |
| Python quality | Ruff format/check clean across **109 files**; strict mypy clean across **61 source files** |
| Python core | **317/317 passed in 267.50 seconds** |
| Generated contracts | Drift check clean |
| Rust | **65 passed, 0 failed, 1 ignored** manual macOS Keychain prompt test; format/Clippy clean |
| Frontend | **49/49 passed across 14 files**; typecheck, lint, and production build clean |

This aggregate covers the earlier `0006` source and is paired with the separately identified frozen-sidecar and packaged-app evidence below. It is retained as historical package evidence and is not relabelled as proof of `0007`.

## Preserved `0006` frozen/package verification

Frozen output root: `/tmp/ariadne-frozen-sidecar.OxSKIb`

```text
Schema:           0006_query_policy_core
Architecture:     arm64
Minimum macOS:    11.0
Staged size:      20,481,200 bytes
Staged SHA-256:   bd522b5b10a92cca552f4b062723bf3d016c01ab0dcb2fad2c9d9112eaebce67
UDS startup:      7,866 ms
Workflow:         passed
```

The final package was rebuilt after the Settings review-requirement copy changed to present tense:

| Package evidence | Preserved `0006` result |
|---|---|
| Requested quit | 2,767 ms startup; cleanup true; zero TCP |
| Abrupt SIGKILL | 2,532 ms startup; cleanup true; zero TCP |
| Runtime permissions | `0700` directory; `0600` socket in both runs |
| Signed packaged sidecar | 20,481,184 bytes; SHA-256 `eb4eae99e52d2c08efa918f61fa20fcee4a2fcffa9dba87892075138923a73bd` |
| Desktop executable | 13,803,520 bytes; SHA-256 `9e14c54b34ab5eaf307838e25488957b34ecb5f86cb526bff8914a8d0c4b26b3` |
| Signature | `codesign --verify --deep --strict` passed |

The `0006` final privacy scan after its source and documentation updates was clean across 313 candidates.

## Implementation evidence

The repository contains the following tested slices. Package evidence applies only where explicitly stated:

| Area | Candidate behavior | Evidence state |
|---|---|---|
| Schema | Forward-only `0011_profile_purge` after persistent identity-audit/AI revisions `0009`/`0010` and historical `0008` | Current contract, full aggregate, frozen sidecar, and package gates pass at 57 operations/55 paths |
| Persistent identity audits | Named profiles retain knowledge, configuration, frontier tasks, exact results/sources, proposals, receipts, progress, and cited selected-local-AI analyses across routes/restarts | Repository/API/Rust/frontend tests, full aggregate, frozen UDS, and package gates pass |
| Automatic provider fleet | One explicit run works through bounded DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate-transparency tasks with honest failure/coverage states | Provider unit/integration tests, durable frontier tests, complete source aggregate, and packaged candidate pass |
| Profile deletion | Exact-name and revision-confirmed native action physically removes all profile-scoped rows plus linked jobs/idempotency state, with secure delete and vacuum | Backend whole-schema deletion integration, generated/Rust boundary validation, renderer interaction test, full aggregate, and package build pass |
| Native Graph | Persisted snapshot/provenance through Python → Rust → Tauri → Graph screen; bounded evidence/truncation and lock clearing | Focused, aggregate, and packaged candidate gates passed |
| Local-AI settings | Encrypted selectable Ollama/OpenAI-compatible loopback settings, model discovery, connection test, exact generated/Rust/UI boundary | Focused, aggregate, and packaged candidate gates passed |
| Selected-model intake | Restricted-value-redacted model input, review-only probable suggestions, provenance, deterministic fallback on disabled/error/timeout/invalid response | Focused, aggregate, and packaged candidate gates passed |
| Corpus/workspace AI | Selectable local model or deterministic execution for summary, organisation, questions, connections, and gap analysis; exact cited source catalog; bounded projection; no external network/persistence | Full aggregate, live-Qwen/guard/API slices, Rust/frontend boundaries, confidential-safe aggregate benchmark, and package gates pass |
| Query policy | Encrypted local provider catalog, inspectable plan cells, budgets, coverage outcomes, approvals/ledger schema, network-free dry run | Focused, aggregate, frozen, and packaged network-free candidate gates passed |
| Public discovery | Explicitly authorised bounded DuckDuckGo HTML and GitHub-user searches with exact URL/provider/source identifiers and honest failure states | Python/Rust/frontend, full aggregate, frozen, and package gates pass |
| HIBP and planning | Official account/domain checks plus deterministic non-executing investigation planning with exact source/transmission metadata | Python/Rust/frontend, full aggregate, frozen, and package gates pass; provider authentication, subscription, domain-verification, and rate limits still apply |
| Approved-browser handoff | Fixed portal, generated search, and HIBP URLs are independently validated in TypeScript and Rust before native `NSWorkspace` opening | Focused Rust/frontend tests and current package build pass; no API route, scraping, or evidence import |
| Atomic public capture | One exact reviewed result creates URL_REFERENCE artifact, finding, neutral assessment, and link transactionally; URL hash and query-reference minimisation enforced | Rollback, idempotency/deduplication, profile isolation, boundary, aggregate, frozen, and package gates pass |
| Phase 5 persistence | SQLCipher-required profile-scoped findings, immutable originals/derivatives, multi-finding dedup links, persisted assessment signals/missing evidence, and append-only human decisions | Migration, repository, encrypted persistence, profile isolation, integrity, and aggregate tests passed |
| Phase 5 read boundary | Bounded profile list/resume and finding list/detail through authenticated Python, generated contracts, strict Rust/Tauri commands, and native Findings views | Aggregate Python/Rust/frontend/contracts gates passed; evidence bytes are not returned |
| Phase 5 write boundary | Manual-local import, caller-redacted derivatives, append-only decisions, and atomic public URL capture through authenticated Python/Rust/Tauri/native UI | Aggregate/frozen/package gates pass; retention/purge remains absent |
| Entity origins | Stable profile-scoped exact-source origin paging with source, segment, extraction-run, span, origin, timestamp, confidence, and explanation fields | Repository/API/Rust/frontend, aggregate, frozen, package, and targeted visual gates pass |
| Attribution | Closed positive/negative signals, versioned integer weights, explainable bounded score, missing/next evidence, mandatory separate human review | Persisted reads, neutral bootstrap assessment, and append-only human-decision mutation pass; operational assessment recalculation remains unimplemented |
| Audit comparison | Immutable hashed snapshots/lifecycles, five deterministic diff states, conclusive reappearance, coverage-preserving incomplete results, full interval for selected nonadjacent runs | Migration/repository/API/frontend aggregates pass; no operational snapshot-ingestion route |
| Remediation | Durable finding/evidence/provider-response links, bounded drafts/deadlines, revision CAS/history, reappearance reopening, no send operation | Migration/repository/API/Rust/frontend aggregates pass; no external action |
| Fresh-profile bootstrap | One bounded manual finding plus atomic neutral assessment, server IDs/time, mandatory human review, no evidence/decision/network side effect | Full source aggregate, focused tests, frozen UDS 200 response, and current package lifecycle pass |
| Local checkpoints | User-triggered contentless Phase 5 projection, canonical fingerprint, explicit coverage, monotonic sequence/time, immutable snapshot | Full source aggregate, focused tests, two ordered frozen UDS 200 responses, and current package lifecycle pass; no adapter or scheduler |
| Local reports | Selected-run JSON/inert Markdown, deterministic default redaction, full-explicit approval binding, exact manifest/hash/source mappings, no evidence bytes/network/send | Current aggregate, exact-provenance, frozen UDS, and package gates pass; durable report catalog/retention remains pending |

The 57-operation source, aggregate, frozen sidecar, and local package gates pass.
None of these results proves operational assessment recalculation, general
evidence streaming/viewing, scheduled ingestion, durable report
retention/destination handling, authorised account connectors, or an outbound
remediation action. Whole-profile purge is implemented; policy-scheduled
selective retention remains target work.

## Artifact interpretation

The `0006` candidate artifact gate remains complete for its explicit synthetic,
local, network-free scope. The `c4a779…` sidecar is historical Phase 3 evidence;
`bd522b…` and its packaged identities prove `0006`; `5d4856…` plus
`fe0e7d…`/`2cd7cc…` prove `0007`; `e156e9…` plus
`359fd0…`/`fc02da…` prove the historical 37-operation `0008`;
`96c368…` plus `77338e…`/`214ccd…` prove the historical 40-operation
milestone; `b33e411e…` plus `536c16a8…`/`d3eef7ba…` prove the
historical 45-operation candidate; and `5ca6b790…` plus
`4ba7fd0…`/`ca68fdd4…` prove the historical 48-operation candidate. Current
`dccaaa5…` staged, `74325b3…` packaged-sidecar, and `08491aa…` desktop
identities prove the 57-operation local candidate. No identity has been
relabelled.

## Visual evidence

The accepted Phase 1 69-image matrix remains the broad synthetic visual baseline and was not reloaded. The final targeted Chromium gate passed 2/2 in 15.1 seconds without external requests, errors, failed requests, or horizontal overflow; its earlier screenshot capture/review run passed 2/2 in 21.3 seconds. Manual inspection was limited to the newly changed query-composer surface and one Settings presentation; neither showed a blocking defect. The older five-artifact 45-operation review remains historical evidence under `apps/desktop/artifacts/ui-screenshots/final-targeted-20260713-01`.

## Interpretation

- Phase 3 remains closed for its historical explicit synthetic local scope.
- Seven bounded public surfaces, durable retry/restart state, atomic exact-URL
  capture, and cited selected-local-AI analysis are implemented; credentialed
  specialist providers and authorised account connectors remain incomplete.
- Phase 5 now has exact-source public capture, provenance traversal, canonical
  proposal promotion, and confirmed whole-profile purge in addition to its
  historical durable storage/write milestones. General evidence
  viewing/streaming and selective retention remain. Phase 6
  comparison/remediation/checkpoint/reporting remains implemented; scheduling
  and a durable release-grade report lifecycle remain pending.
- Passing tests do not authorize bypassing access controls, external legal action, or release distribution.
