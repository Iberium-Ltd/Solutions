# Codename Ariadne — Next Steps

Last updated: 2026-07-23

This list records usability and functional work discovered during a real
authorised self-audit. It contains no audit subject values.

## Current primary-workflow acceptance

- [x] Native launch enters the named-profile workspace; vault creation routes to
  profile creation/selection rather than an anonymous intake.
- [x] Intake refuses to run without an explicitly selected named profile.
- [x] One import flows through entity review into the persistent People
  workspace without retyping reviewed identifiers.
- [x] **Start full audit** creates a durable run and automatically advances its
  bounded public-provider frontier with honest progress and pause/resume/cancel.
- [x] Terminal runs expose exact result URLs, cited local-AI output, proposals,
  failures, gaps, and execution receipts in one place.
- [x] After human review, a terminal run downloads a deterministic Markdown or
  JSON audit package with byte count and SHA-256.
- [x] Multiple named profiles, retained run history, and exact-name-confirmed
  local profile deletion are available.

Background scheduling is deliberately outside the current completion goal. The
unchecked sections below are follow-on breadth, specialist integrations,
release hardening, or advanced-tool improvements; they do not block the tested
profile → intake → review → full audit → review → package workflow.

## Completed in the persistent identity-audit restructure

- [x] Add a named People/profile workspace that reuses reviewed identifiers,
  exact sources, prior runs, results, proposals, and citations without manual
  re-entry.
- [x] Add a one-command **Run full audit** journey with explicit mode, depth,
  request, time, provider, and selected-local-model settings.
- [x] Persist frontier tasks, results, leads, proposals, receipts, terminal
  outcomes, stop reasons, and progress; support reload, pause, resume, cancel,
  and crash recovery.
- [x] Execute seven credential-free public surfaces automatically in one run:
  DuckDuckGo, GitHub, GitLab, npm, RDAP, Wayback CDX, and certificate
  transparency.
- [x] Run selected local AI after deterministic discovery and retain only cited
  facts, connections, and next steps with exact source URLs and an honest
  fallback when the model is unavailable.
- [x] Promote positively reviewed proposals into canonical entities while
  retaining proposal-to-entity source provenance.
- [x] Add confirmed physical profile deletion across the Python API, generated
  contracts, Rust/Tauri bridge, and desktop UI.

## Product direction — Audit-first, tools second

- [x] Make the default experience a single guided **Run full audit** workflow:
  import the source once, review only ambiguous items, choose an audit/security
  preset, approve the exact external scope, and let Ariadne complete the
  permitted work.
- [x] Treat Discovery Console, Query Composer, Transmission, individual provider
  forms, and other expert controls as optional **Advanced tools**, not mandatory
  steps in the primary journey.
- [ ] Offer clear execution presets such as **Local only**, **Approval at each
  disclosure**, and **Maximum authorised coverage**. Always show the exact data,
  providers, expected requests, and remaining manual prerequisites before the
  run begins.
- [x] Automatically perform deterministic extraction, eligible query planning,
  approved provider execution, result deduplication, exact-source capture,
  finding triage, cited AI analysis, gap analysis, follow-up planning,
  checkpoints, comparison, and report preparation as one resumable audit run.
- [ ] Pause only for meaningful decisions: ambiguous identity attribution,
  missing credentials, provider access requirements, sensitive disclosure,
  contradictory evidence, or final report/remediation approval.
- [x] Provide one honest progress view showing completed, running, queued,
  blocked, failed, skipped, and manual steps. Never represent a compiled plan or
  successful HTTP response as a completed finding.
- [x] End with a reviewable audit package: findings, exact sources, connections,
  uncertainty, coverage gaps, failed/blocked checks, suggested follow-ups,
  review decisions, execution receipts, and a cited report. Comparison and
  remediation remain optional specialist workflows.

## Priority 0 — Real profile and audit management

- [x] Replace the automatically named generic review profile with a proper
  **Create profile** step before intake.
- [ ] Let the user choose and later edit a clear profile name, description,
  purpose, tags, and optional notes without using the subject's sensitive values
  as internal identifiers.
- [ ] Support multiple named profiles in one vault with an obvious profile
  switcher, creation flow, archive state, duplicate warning, and deliberate
  merge/copy workflow.
- [x] Distinguish a long-lived subject profile from each individual audit run.
  A profile may contain many dated, named runs with their own scope, policy,
  providers, progress, results, checkpoints, and report.
- [x] Show **Create new profile**, **Continue existing profile**, and **Start new
  run for this profile** as explicit first-launch/intake choices.
- [ ] Allow safe profile and run renaming without changing immutable IDs,
  provenance, citations, or historical records.
- [x] Prevent accidental intake into the wrong active profile and require a clear
  profile/run confirmation before processing a file.

## Priority 0 — Durable history with explicit retention controls

- [ ] Retain imported source references, reviewed identifiers, policies,
  provenance, compiled plans, provider attempts, exact queries, coverage states,
  reviewed results, saved findings, evidence links, AI outputs/citations,
  checkpoints, comparisons, remediation records, and reports across runs by
  default.
- [ ] Reuse previously reviewed identifiers and decisions in later runs instead
  of requiring entry or classification again; present changes and conflicts for
  review.
- [ ] Deduplicate repeated imports and results while adding a new immutable
  observation showing when and how the item was seen again.
- [ ] Provide run history and timelines with filters for identifier, provider,
  result, finding, status, and date.
- [ ] Let the user override retention before a run with clear choices such as
  **Keep full history**, **Keep findings and provenance only**, **Ephemeral
  run**, and a custom policy.
- [ ] Provide explicit export, archive, purge, and cryptographic-erasure controls
  with dependency previews and confirmation. Never silently delete prior runs.
- [ ] Make saved history available to comparison and AI only within the selected
  vault/profile/run scope.

## Priority 0 — AI-assisted intake from the beginning

- [ ] Put AI configuration and model selection near the beginning of the guided
  audit, before extraction starts, with **Deterministic only**, **Local model**,
  and explicitly authorized external-model choices.
- [ ] Use the selected AI during intake to propose names, aliases, usernames,
  emails, domains, URLs, account relationships, time states, and structured row
  meanings that deterministic rules miss.
- [ ] Preserve the deterministic restricted-value scan before any model sees
  content. Send only the bounded, approved projection to the chosen model.
- [ ] Require every AI-proposed entity and relationship to include an exact
  source span, model/provider/version, confidence, explanation, and review
  status. AI suggestions must not silently become confirmed facts.
- [ ] Combine deterministic and AI extraction, deduplicate them, surface
  disagreements, and ask the user only about ambiguous or contradictory items.
- [ ] Carry the selected AI through planning, result organization, connection
  hypotheses, gap analysis, and final reporting while preserving citations.
- [ ] Show a prominent execution receipt stating whether the requested model ran,
  deterministic fallback was used, or enrichment failed. Never label fallback
  output as model-generated.
- [ ] Fix and verify the current intake-AI path: the real audit did not obtain
  working AI-assisted identification from the input file, so this capability is
  **not currently accepted as functional**.
- [ ] Add live local-model tests using labelled and unstructured TXT/CSV inputs,
  malformed model output, timeout/unavailable states, duplicate suggestions,
  exact-span validation, and restart/resume behavior.

## Priority 0 — Durable workflow state

- [ ] Move audit drafts, identifier selection, compiled plans, provider-step
  state, result review, and progress out of short-lived React component memory
  into the encrypted vault-backed workflow model.
- [ ] Preserve the complete active audit when switching Discovery Console tabs,
  navigating elsewhere in Ariadne, minimizing the window, switching focus to
  VS Code or another application, locking/unlocking the vault, or reopening the
  desktop app.
- [ ] Restore the exact route, active audit, selected step, filters, scroll
  position, and safe unsaved form state after an ordinary focus or navigation
  transition.
- [ ] Make explicit **Pause**, **Resume**, **Cancel**, and **Discard draft**
  actions; losing focus must never silently discard work.
- [ ] Keep sensitive draft values encrypted/core-side rather than using browser
  local storage. The webview should receive only the minimum data needed for the
  visible step.
- [ ] Add lifecycle tests for tab changes, route changes, app blur/focus,
  minimize/restore, vault lock/unlock, normal restart, abrupt termination, and
  sidecar recovery during an active audit.

## Priority 0 — Remove repeated data entry

- [ ] Add **Load reviewed entities from active profile** to Discovery Console.
- [ ] Build the plan core-side from confirmed, search-eligible entity IDs so raw
  values do not need to be returned to the webview merely to populate a form.
- [ ] Preserve each entity's review state, temporal state, sensitivity, search
  policy, transmission policy, and exact source references in the compiled
  plan.
- [ ] Default to eligible confirmed entities, with clear inclusion controls and
  explicit reasons for skipped, denied, historical, or uncertain entities.
- [ ] Support more than eight identifiers through bounded batches or pagination;
  the current limit is too small for an ordinary profile.
- [ ] Deduplicate equivalent identifiers and provider operations automatically.
- [ ] Add tests proving that profile-to-plan handoff cannot cross vault/profile
  scope or include denied and excluded entities.

## Priority 0 — Make a compiled plan usable

- [ ] Preserve the draft and compiled plan while switching between **Plan &
  combine**, **Public search**, and **Breach exposure**.
- [ ] Do not destroy the plan when a user selects **Load**, changes tabs, or
  temporarily opens another application to consult notes or guidance.
- [ ] Record per-step state: not started, ready, approval required, running,
  succeeded, empty, blocked, failed, reviewed, and saved.
- [ ] Add **Run next eligible step** and a bounded **Run approved steps** flow.
  External requests must remain explicit and reviewable.
- [ ] Return to the plan after each handoff instead of forcing reconstruction.
- [ ] Show the original reviewed entity reference and source provenance beside
  every result without exposing unrelated values.
- [ ] Allow useful results to be saved atomically as findings directly from the
  plan workflow.

## Priority 0 — Clarify the audit journey

- [ ] After Entity Review, offer two explicit choices:
  **Start live discovery** and **Run local policy preflight**.
- [ ] Stop presenting the network-free Transmission screen as though it were the
  required next step for a live audit.
- [ ] Add an in-app guided audit checklist covering intake, review, baseline,
  discovery, evidence review, AI analysis, follow-up searches, comparison, and
  reporting.
- [ ] Clearly distinguish planning success from an executed online search and
  from a relevant finding.

## Priority 1 — Discovery coverage and capture

- [ ] Add a review queue for browser-handoff URLs and manual portal exports.
- [ ] Preserve exact engine, query, timestamp, result URL, and capture status.
- [ ] Add provider-specific query templates for names, usernames, emails,
  domains, URLs, and known contextual clues.
- [ ] Add resumable retry/rate-limit handling and honest coverage summaries.
- [ ] Add authorised connectors only where stable APIs and credentials are
  available; do not automate CAPTCHA, authentication, paywall, or access-control
  bypass.

## Priority 1 — Audit completion

- [ ] Create a baseline checkpoint automatically when a live audit begins.
- [ ] Create a final checkpoint after reviewed discovery work.
- [ ] Feed findings, exact sources, coverage gaps, and failed checks into AI
  Workspace without manual duplication.
- [ ] Generate a final cited summary, connections review, gap analysis,
  comparison, remediation queue, and report from the active audit.

## Current self-audit continuation

- [ ] Execute public-web searches for each confirmed username.
- [ ] Execute GitHub-user searches for each confirmed username.
- [ ] Search confirmed names using exact phrases plus distinguishing context.
- [ ] Search confirmed emails as exact phrases across available engines.
- [ ] Run authorised HIBP checks only when an eligible API key/plan is available.
- [ ] Save only relevant exact-source results as findings.
- [ ] Review findings and Link Map connections.
- [ ] Run AI Workspace Summary, Connections, and Gap Analysis with citations.
- [ ] Execute justified follow-up searches from the gap analysis.
- [ ] Create the final checkpoint, compare it with baseline, and generate the
  report.
