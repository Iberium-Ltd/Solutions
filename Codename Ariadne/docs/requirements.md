# Codename Ariadne — Requirements Baseline

Status: Baseline extracted on 2026-07-11  
Authority: `Instructions/CODEX_MASTER_PROMPT_ARIADNE.md` and the user's execution brief  
Privacy note: this document contains no identity data from `Instructions/private_reference/`.

## 1. Product intent

Codename Ariadne is a local-first personal digital-exposure intelligence application for defensive self-audits and explicitly authorised investigations. Ariadne Core is the correlation, provenance, and attribution layer. The product must turn user-supplied identity clues into a reviewed identity graph; compile controlled, jurisdiction-aware searches; preserve evidence; explain attribution; compare audit runs; and manage remediation over time.

The application must be global, modular, reproducible, human-controlled, evidence-driven, privacy-preserving, and candid about uncertainty. It must remain useful when the only starting point is one legacy identifier.

## 2. Non-negotiable safety boundary

Permitted activity is limited to public or lawfully accessible sources, official APIs, ordinary public browser interaction, read-only access to user-owned accounts, user-provided exports and files, authorised repositories, archives, official breach-notification services, and approved image-search providers.

The product must not implement credential testing, password-reset probing, authentication or CAPTCHA bypass, exploitation, malware, phishing, session theft, access-control evasion, stolen-data access, false accounts, paywall circumvention, harassment, automatic accusation, or automatic submission of deletion, legal, or impersonation reports. A blocked automated path must become a transparent manual-import or guided-capture path.

## 3. Required delivery order

1. Inspect and read the complete supplied workspace.
2. Extract requirements without reproducing confidential identifiers.
3. Create and validate planning, architecture, threat, and privacy documents.
4. Decide and document the technology stack and repository structure.
5. Scaffold the repository with privacy controls already active.
6. Build the complete high-fidelity UI with synthetic data.
7. Run the UI locally and exercise the synthetic journeys.
8. Capture each major surface at 1440×900, 1728×1117, and 1100×800.
9. Review screenshots in writing, fix defects, and recapture.
10. Only after the UI quality gate, begin the full backend phases.

A phase is complete only when applicable software runs, relevant tests pass, real interactions have been inspected, screenshots exist where required, and remaining defects are either fixed or explicitly documented.

## 4. Phase 1 interface scope

The interactive prototype must include:

| ID | Surface | Minimum proof |
|---|---|---|
| UI-01 | Application shell and navigation | Responsive shell, active route, keyboard-visible focus |
| UI-02 | Mission-control dashboard | Coverage, live run summary, alerts, next actions, no fake unlabeled data |
| UI-03 | New-audit flow | Audit type, scope, profile, permissions, budget, review |
| UI-04 | Free-text and file intake | Paste area, supported types, local-processing notice, quarantine feedback |
| UI-05 | Extracted-entity review | Edit, classify, approve, exclude, sensitivity and transmission controls |
| UI-06 | Tool launcher | All named tools, filtering, capability/risk summaries |
| UI-07 | Live operations console | Simulated state clearly labelled in Phase 1; task/provider status and controls |
| UI-08 | Findings inbox | Confidence, visibility, status, provenance, review queues |
| UI-09 | Identity and provenance graph | Interactive graph, filters, why-connected explanation, evidence access |
| UI-10 | Geographic view | Coarse private locations by default, source/confidence/time context |
| UI-11 | Result detail and evidence | Source, capture metadata, hash, attribution signals and contradictions |
| UI-12 | Impersonation case | Timeline, careful classifications, evidence gaps, draft-only reporting |
| UI-13 | Audit comparison | NEW, CHANGED, REMOVED, REAPPEARED and other diff states |
| UI-14 | Remediation board | Actions, deadlines, evidence, provider response, reappearance |
| UI-15 | Provider registry / Source Radar | Jurisdiction, health, terms, retention, access basis, transmission risk |
| UI-16 | Jurisdiction and transmission controls | Local/EU/world/custom policy and exact preflight disclosures |
| UI-17 | Settings and privacy | Auto-lock, local AI, retention, redaction, connectors, motion |
| UI-18 | State laboratory | Representative empty, loading, failure, and blocked/manual-action states |
| UI-19 | Reduced-motion mode | OS preference and explicit override remove nonessential motion |

Phase 1 task progress is a deterministic in-memory simulation and must be labelled as such. Production progress later must be backed by real job state.

## 5. Required synthetic journeys

### Full audit

Create → import or paste → extract → review and approve → select sharing permissions → compile search plan → review query budget → start → monitor → review findings → resolve attribution → explore graph → preserve evidence → create remediation → export.

### Targeted trace

Choose email, username, phone, name, address, domain, URL, or image → enter one value → review jurisdiction exposure → select providers → run → monitor → inspect graph and evidence → save to a profile or retain as isolated.

### Re-audit

Open a prior run → rerun all or selected checks → compare snapshots → inspect NEW / CHANGED / REMOVED / REAPPEARED → update remediation.

### Impersonation investigation

Open a suspicious result → record claimed identity → compare identifiers and timeline → add ownership periods → preserve evidence → classify carefully → prepare, but never automatically submit, a report.

## 6. Named tools

The UI must expose clear labels for: Email Trace, Username Sweep, Name Search, Phone Trace, Address Search, Domain Scan, URL Inspector, Company Search, Image Match, Repository Scan, Archive Search, Public Records Search, Inbox Account Finder, GitHub Exposure Review, Local File Search, Evidence Capture, Compare Runs, Removal Tracker, Source Radar, Link Map, and Case Desk.

Each tool must eventually show inputs, normalised variants, selected adapters, provider jurisdictions, cost and duration estimates, a transmission summary, progress, raw and normalised results, and whether the result will be saved to a profile.

## 7. Independent evidence dimensions

The following must never be collapsed into one score:

- Check outcome.
- Public visibility or exposure class.
- Ownership or attribution state.
- Confidence.
- Sensitivity.
- Provenance.
- Current versus historical validity.

User confirmation can establish an ownership claim but does not prove current public visibility. Private connector metadata is not automatically public exposure. A display name is not necessarily an immutable handle. A conventional profile URL is not evidence of an account.

Check outcomes are: `FOUND`, `NOT_FOUND`, `NOT_CHECKED`, `CHECK_FAILED`, `ACCESS_BLOCKED`, `AUTH_REQUIRED`, `RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, `AMBIGUOUS`, `MANUAL_REVIEW_REQUIRED`, and `AUTHORITATIVE_ABSENCE` only where an authoritative source supports that conclusion. Empty, blocked, failed, or unindexed checks never prove nonexistence.

## 8. Intake and entity governance

MVP inputs are pasted text and `.txt`, `.md`, `.csv`, `.json`, and `.vcf`. Parsing must validate MIME, encoding, size, and structure before deterministic extraction. Semantic or AI enrichment is optional and may not silently override deterministic evidence.

Users must review entities before search or transmission and can mark them confirmed, probable, possible, false positive, excluded, historical, current, sensitive, search permitted, store only, or do not transmit. All edits are auditable. Same-name and same-username records require corroboration before merging; negative signals and timeline conflicts remain first-class evidence.

## 9. Sensitivity and transmission

| Class | Examples | Default |
|---|---|---|
| Public | Public name, organisation, public username | Search may be allowed within the selected policy |
| Sensitive | Email, domain, historic username, query history | Confirm provider use |
| Highly sensitive | Full phone, exact address, date of birth, recovery link, private connector link | Explicit per-run approval |
| Restricted | Password, OTP, auth/reset link, bank/card data, identity document, private key | Quarantine; never log, search, prompt, export, or transmit |

Transmission modes are local-only (default), EU-only, worldwide, and custom allow/block lists. Before any sensitive transmission, the UI shows provider, operator and hosting jurisdiction, purpose, exact or masked payload, retention knowledge, cost, and risk. A ledger records the approved disclosure without needlessly duplicating plaintext.

## 10. Provider and adapter requirements

Every provider records identity, operator country, hosting regions, source type, access basis, authentication requirement, whether identifiers leave the device, retention notes, privacy and terms links, risk, removal route, and default-enabled state. Brokers and people-search providers are disabled by default and their claims remain lower confidence until corroborated.

Adapters share a stable lifecycle for metadata, health, estimate, search, fetch, and normalise. They require timeouts, bounded retries, rate limits, caching, idempotency, structured failures, enable/disable controls, mock and dry-run modes, cost accounting, jurisdiction metadata, and redaction-aware logs.

## 11. Graph, correlation, and provenance

The graph is a domain model rather than decoration. Nodes include people, aliases, usernames, contact points, locations, organisations, employment and education, domains and URLs, accounts, projects, files and images, findings, evidence, runs, providers, and remediation cases. Relationships include ownership and usage, recovery, employment and education, location, linking and mentions, authorship, mirrors/reposts, identity equivalence or contradiction, username history, discovery, evidence support or contradiction, and remediation.

Every relationship carries source, confidence, visibility, timestamp, evidence reference, human or automated origin, explanation, and contradictions. Ariadne Core must explain contributing signals, negative signals, missing evidence, confidence band, recommended next evidence, model/scoring version, and whether human review is required. It must never automatically attribute an account to a real person from a score alone.

## 12. Evidence, comparison, and remediation

Evidence may include screenshots, HTML, PDF, raw JSON, URL, UTC capture time, SHA-256, HTTP and redirect metadata, query, provider, run, viewport, method, local path, and encryption state. Originals are immutable, encrypted, hash-verified, content-deduplicated, excluded from Git, and distinct from redacted derivatives. A hash proves integrity after capture, not source truth.

Run comparison states are `NEW`, `CHANGED`, `REMOVED`, `REAPPEARED`, `REDIRECTED`, `DEINDEXED`, `ARCHIVED`, `FALSE_POSITIVE`, `UNCHANGED`, and `UNKNOWN`. Archived content remains distinct from live content.

Remediation supports monitoring, evidence preservation, owned-account deletion, source correction, lawful erasure or deindexing requests, impersonation reporting, contact, escalation, and marking legally persistent items. The app drafts actions and tracks their history, but sends nothing without explicit approval and does not present legal advice.

## 13. Privacy and security baseline

- Local-first, no telemetry by default, no real identity data in tracked or generated development material.
- Encryption at rest, macOS Keychain key custody, auto-lock, least privilege, safe rendering, strict CSP, and redacted structured logs.
- Isolated and bounded parsing/browser workers; hostile webpage and file content is data, never instructions.
- Cross-profile scoping in every row, blob, cache key, job, and export.
- Minimal connector ingestion: metadata first, message/file bodies only when explicitly preserved.
- Lockfiles, dependency and secret scanning, SBOM, signed/notarised release path, backup and restore tests.
- Safe export by default, exact private locations coarsened, screenshot OCR/privacy checks, and honest secure-deletion guidance for APFS/SSD snapshots.

## 14. Quality and acceptance

Testing covers extraction and normalisation, sensitivity and transmission policy, query compilation, correlation, deduplication, diffing, redaction and hashing, providers, adapters, migrations, evidence, graph updates, retry/cancel/resume, imports and exports, encryption, synthetic end-to-end journeys, failures and blocks, visual states and viewports, reduced motion, long content, accessibility, and repository privacy.

The first serious release additionally requires clean startup on the target Mac; real progress state; provenance for every result and graph connection; evidence capture and hashing; run comparison; remediation tracking; visible transmission risk; full and redacted exports; passing tests; documented limitations; and no claim of completeness.

