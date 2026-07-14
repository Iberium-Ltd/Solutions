# Codename Ariadne — Local Data Model

- Status: target architecture contract plus 45-operation source candidate at schema `0008_phase6_audit_remediation`; newest workflows add no migration and final package verification is pending
- Date: 2026-07-13
- Storage target: SQLCipher Community 4.17+ with SQLite 3.51.3 or newer, managed by SQLAlchemy 2 and Alembic
- Scope: single-device, multi-profile encrypted vault; target model plus implemented Phase 3–6 local cuts

## 1. Purpose

This schema supports the complete local-first lifecycle: authorised intake, reviewed identity data, jurisdiction-aware query planning, durable execution, explicit coverage outcomes, immutable evidence, explainable attribution, audit comparison, remediation, exports, and privacy governance.

The complete catalog remains a target design. Phase 3 is historically verified at `0005_graph_edge_origins`; network-free `0006_query_policy_core`, Phase 5 `0007_phase5_evidence_attribution`, and the 37-/40-operation `0008_phase6_audit_remediation` packages remain separately verified. Public discovery/capture, entity-origin pagination, and corpus/workspace local-AI reasoning use the existing `0008` schema or in-memory projections and add no migration. Their 45-operation source package gate is pending. Later target tables described here are not claimed as present unless included in an implemented cut below.

### 1.1 Implemented schema cut through Phase 3

Revision `0003_intake_identity_graph` follows `0002_job_dependencies` and creates these twelve profile-scoped tables:

- `intake_sources`, `intake_segments`, `quarantine_items`, and `extraction_runs`;
- `entities`, `entity_variants`, `entity_variant_decisions`, `entity_origins`, and `entity_decisions`; and
- `graph_nodes`, `graph_edges`, and `graph_edge_decisions`.

Revision `0004_decision_policy` then adds nullable before/after sensitivity, temporal, search, and transmission columns to legacy `entity_decisions` and installs insert/update triggers on `entities` and `entity_decisions`. Existing `0003` rows remain honestly unknown rather than receiving invented historical values; all newly written decisions require complete policy history. The triggers mirror repository checks: false-positive/excluded records deny search and transmission, and highly-sensitive records cannot be search-allowed or provider-allowlisted.

Revision `0005_graph_edge_origins` adds the thirteenth profile-scoped table, `graph_edge_origins`. Each support or contradiction observation is structurally bound to one graph edge, intake source, intake segment, and extraction run in the same vault/profile/source scope. A keyed observation HMAC deduplicates exact reprocessing while observations from separate sources remain separate provenance. Graph reads expose total support/contradiction counts and a bounded evidence sample with an explicit truncation flag.

The `0005` upgrade backfills only a live legacy edge whose source and target origins prove one shared source/segment/extraction run at the edge creation time. It fails closed if any live legacy edge remains without verified provenance; it does not invent an origin or silently discard the edge.

### 1.2 Candidate Phase 4 schema cut

Revision `0006_query_policy_core` follows `0005_graph_edge_origins` and adds six encrypted tables:

- `phase4_providers`: vault-scoped declarative provider/adapter metadata;
- `phase4_query_runs`: profile-scoped purpose, policy snapshot/HMAC, total/per-provider budgets, state, and revision;
- `phase4_provider_budget_usage`: exact run/provider consumption;
- `phase4_query_checks`: entity/provider/query cells with masked query, query HMAC, entity/policy snapshots, explicit state/outcome/reason, approval flag, and revision;
- `phase4_one_time_approvals`: exact check-bound, expiring, single-use token/binding HMACs; and
- `phase4_transmission_ledger`: minimised masked display, payload HMAC, purpose, jurisdiction/access basis, verdict, result code, and attempt time.

The current application catalog populates only local `DRY_RUN` and `MANUAL_LOCAL` providers. Service and Rust validation require no network access, no identifier transmission, no external flag, `LOCAL_ONLY` access basis, and no processing region. The schema can represent later modes only behind future reviewed migrations/policy gates; current runtime cannot use it for network dispatch.

### 1.3 Phase 5 evidence and attribution schema cut

Revision `0007_phase5_evidence_attribution` follows `0006_query_policy_core` and adds nine immutable, profile-scoped SQLCipher tables:

- `phase5_findings`: bounded provider-labelled finding projections with independent outcome, severity, visibility, and observation time;
- `phase5_evidence_originals`: bounded SCREENSHOT/HTML/PDF/RAW_JSON/URL_REFERENCE content or URL-reference material, SHA-256, safe capture/provenance metadata, and an encryption-required invariant;
- `phase5_finding_evidence`: a many-to-many link that lets one content-deduplicated original support multiple findings in the same profile without duplicating bytes;
- `phase5_evidence_derivatives`: immutable redacted derivative bytes linked to one original and a versioned redaction policy/summary;
- `phase5_attribution_assessments`: immutable versioned scores from -1000 to 1000, confidence bands, payload hashes, and mandatory human-review state;
- `phase5_attribution_signals` and `phase5_attribution_signal_evidence`: closed supporting/contradicting signals with bounded weights and same-profile evidence references;
- `phase5_attribution_missing_evidence`: bounded missing signals and ranked next-evidence recommendations; and
- `phase5_attribution_decisions`: append-only human states, exact assessment/model version, revision, supersession link, actor, time, and payload hash.

All relationships include vault/profile composite scope. Original content deduplicates by `(vault_id, profile_id, content_sha256)` and may then be linked to more than one finding. Attribution signals may reference only originals already linked to that finding. Migration-installed triggers reject update or delete of every Phase 5 row; revisions are represented by new assessment or decision rows rather than mutation.

The current read boundary lists at most 100 findings and returns detail for one finding with at most 64 artifact metadata records. It reconstructs originals through the domain validator, failing closed on a SHA-256 mismatch, and does not return stored evidence bytes. Packaged `0008` includes bounded manual-local import, explicitly caller-redacted derivatives, append-only human decisions, and one-transaction insertion of a server-ID/time manual finding plus neutral initial assessment. The latter closes the empty-profile bootstrap without adding tables or creating evidence/a human decision. Automated capture, operational assessment recalculation, evidence streaming/viewing, retention/purge, adapter-produced findings, and complete query-to-decision provenance are not exposed yet.

### 1.4 Phase 6 durable audit and remediation schema cut

Revision `0008_phase6_audit_remediation` follows `0007_phase5_evidence_attribution` and adds ten immutable, profile-scoped SQLCipher tables:

- `phase6_audit_snapshots`: bounded run identity, monotonic sequence/capture time, terminal run state, and canonical payload SHA-256;
- `phase6_audit_snapshot_findings`: ordered stable Phase 5 finding references with provider and content fingerprint;
- `phase6_audit_snapshot_coverage`: ordered provider coverage preserving COMPLETE, NOT_CHECKED, BLOCKED, and CHECK_FAILED independently;
- `phase6_remediation_revisions`: complete immutable case state per revision, previous-revision link, local/draft/explicit-approval disposition, status, deadline, draft, reappearance counters, times, and canonical payload SHA-256;
- `phase6_remediation_findings` and `phase6_remediation_evidence`: ordered same-profile Phase 5 finding/original references for each complete revision;
- `phase6_remediation_provider_responses` and `phase6_remediation_provider_response_evidence`: bounded locally recorded response summaries and their evidence links;
- `phase6_remediation_history`: exactly one append-only typed event per case revision, with local actor, status continuity, time, safe detail code, and optional bounded note; and
- `phase6_remediation_history_evidence`: ordered evidence references for each history event.

All child relationships include vault/profile scope and reference existing Phase 5 findings/evidence in that same profile. Every Phase 6 table has update/delete rejection triggers. Repository construction requires an open SQLCipher vault and exact existing profile. Replaying a snapshot or case verifies its canonical payload hash; the same immutable identity with different content fails closed. Remediation writes require the current revision, append one complete revision and history event, and reject stale or divergent histories.

Run comparison is derived deterministically rather than stored as a separate mutable result. The repository validates that baseline precedes current and loads the complete persisted interval through the selected current run. Thus a nonadjacent comparison retains intervening observations needed for lifecycle and REAPPEARED classification instead of comparing only two endpoints. The current package can append a user-triggered checkpoint from contentless Phase 5 materials and explicit provider coverage; canonical fingerprints include finding state, evidence/derivative metadata hashes, and latest assessment/decision state. This reuses the three audit tables and is not adapter-driven or scheduled. Remediation routes create/update local records only and define no send, submit, dispatch, or provider-contact operation.

Deterministic report generation is presently a read projection, not a schema cut. It reads bounded profile-scoped Phase 5/6 repositories and returns one in-memory JSON or Markdown artifact plus an exact manifest. No `reports`, `report_approvals`, or `report_artifacts` target table below is created or populated. Full-explicit approval is a request-bound UUID rather than a durable/expiring approval record; saving the artifact is a UI-owned local download outside the core transaction and retention model.

These implemented cuts are intentionally narrower than the final catalog:

- Intake is PROFILE scoped only; isolated audit-run and provider/evidence origins wait for their owning migrations.
- `entity_origins` currently requires exactly one local `intake_segment_id`; placeholder raw-result/evidence columns cannot be populated.
- Quarantine persists metadata descriptors only. Phase 3 stores no restricted plaintext blob and creates no entity or graph node for a restricted value. Normal intake segments are contentless by default; any explicitly retained temporary content has an expiry and is opportunistically purged.
- Entity uniqueness is keyed by `(vault_id, profile_id, entity_type, value_hmac)` for live rows. The HMAC key is a purpose-separated, request-scoped derivation from the unlocked vault key and is zeroised after repository use.
- Every child relationship includes vault/profile scope in its foreign key. Cross-profile source, origin, decision, node, and edge writes fail at both service and database boundaries.
- Entity and edge decisions are append-only, revision-linked records. Mutating the current aggregate requires an expected revision; durable idempotency rows store only a keyed token HMAC, request digest, safe result, and expiry. Completed Phase 3 results replay for 24 hours and incomplete reservations expire after 60 seconds.
- Graph nodes are PRIVATE_ONLY by default. Snapshot reads suppress rejected/excluded entities and incident edges, omit sensitive nodes unless explicitly requested, and remain bounded to 500 nodes and 250 returned edges. Edge support/contradiction counts are complete while response evidence is bounded; internal source/segment/run origins remain stored for audit.

The model is intentionally relational. Ariadne Core exposes graph-domain operations, while SQLite stores nodes, edges, evidence, and decisions with ordinary keys and indexes. A dedicated graph database is not required at the expected personal-audit scale.

Only synthetic examples may be used in development. Restricted values such as passwords, one-time codes, payment data, private keys, and identity-document numbers must never enter the normal entity, search, graph, log, model, report, or evidence-index paths.

## 2. Design invariants

1. **Vault isolation is structural.** Every user-data row carries a vault identifier and an explicit scope class. Subject data belongs to exactly one profile or one isolated audit run. Composite UNIQUE keys and composite foreign keys include those scopes, preventing accidental cross-vault, cross-profile, or profile-to-isolated joins.
2. **Human review precedes disclosure.** Extraction creates candidates, not approved search inputs. Search tasks may reference only reviewed entities or explicitly approved one-off tool inputs.
3. **Outcome is not attribution.** Check outcome, source visibility, ownership classification, confidence, sensitivity, provenance, and time are independent columns.
4. **No silent absence.** Every planned provider check ends in an explicit coverage outcome, including blocked, failed, unauthorised, and not-checked states.
5. **Evidence originals are immutable.** Corrections and redactions create derivative artifacts. They never overwrite the captured original.
6. **Every claim is traceable.** Findings, graph edges, entity candidates, and attribution signals retain links to their inputs, source results, evidence, producer, and transformation version.
7. **Every decision is historical.** User and automated decisions are append-only records. A current-state pointer is a convenience, not a replacement for history.
8. **Restricted data is structurally excluded.** Restricted material may exist briefly only in the encrypted quarantine store with no FTS entry, graph node, task input, model input, or external-transmission path.
9. **External disclosure is bound to approval.** A provider task must reference a valid approval whose payload digest, provider, purpose, jurisdiction, sensitivity, and run match the task.
10. **Secrets are not database values.** OAuth tokens and the independent per-vault database and backup keys live in macOS Keychain. The database stores only opaque Keychain references, key versions, and non-secret metadata.
11. **Local caches never become global identity caches.** Result, browser, model, and deduplication caches are vault- and profile-scoped unless they contain only public application metadata.
12. **Purge is explicit and dependency-aware.** Normal deletion uses retention state and purge jobs; cryptographic erasure removes the per-vault key. Ariadne does not claim guaranteed physical overwrite on APFS or SSD media.

## 3. Storage conventions

### 3.1 Common columns and scope union

Every user-data table, including append-only decisions, transmissions, event records, and audit history, has:

| Column | Type | Rule |
|---|---|---|
| id | TEXT | UUIDv7 in canonical lowercase form; never derived from a personal value |
| vault_id | TEXT | Required composite scope; references vaults |
| profile_id | TEXT nullable | Set only for PROFILE scope |
| scope_audit_run_id | TEXT nullable | Set only for ISOLATED_RUN scope |
| created_at_us | INTEGER | UTC Unix microseconds |
| updated_at_us | INTEGER nullable | UTC Unix microseconds; null for immutable append-only rows |
| revision | INTEGER nullable | Starts at 1 for mutable resources; null for immutable append-only rows |
| deleted_at_us | INTEGER nullable | Soft deletion marker pending policy-driven purge |

The scope CHECK is one of:

- PROFILE: profile_id is set and scope_audit_run_id is null.
- ISOLATED_RUN: scope_audit_run_id is set and profile_id is null.
- VAULT: both are null, allowed only for an enumerated vault-wide table.
- CATALOG: no vault or subject columns, allowed only for shipped non-user metadata such as the provider catalog and scoring-model definitions.

Every scoped table declares UNIQUE(vault_id, id). A profile-owned parent additionally declares UNIQUE(vault_id, profile_id, id); an isolated-compatible parent declares UNIQUE(vault_id, scope_audit_run_id, id). Child relationships use the matching composite FOREIGN KEY, not an ordinary index. A child with dual-compatible scope has two nullable composite foreign keys plus the exactly-one scope CHECK. SQLite foreign_keys is enabled on every connection, and migrations test cross-scope inserts directly against the database.

Profiles are scope roots and therefore store vault_id but not a self-referential profile_id. Audit runs are the roots for isolated scope. Tables that can be either profile- or isolated-run scoped are called dual-compatible below.

The API renders timestamps as RFC 3339 UTC strings and UUIDs as strings. Monetary amounts are integer micros plus ISO 4217 currency; floating-point currency is prohibited.

### 3.2 Sensitive values

SQLCipher encrypts the database, including WAL, indexes, and FTS tables. Within an unlocked vault:

- Exact entity values remain available only to the core service.
- Routine UI responses return a masked display and sensitivity label.
- A keyed HMAC fingerprint supports equality checks without creating a portable unsalted hash.
- Highly sensitive values are excluded from FTS unless the user explicitly enables local indexing.
- Restricted values never enter the entities table.
- Logs contain stable object IDs and reason codes, never values, query text, raw response bodies, tokens, or absolute user paths.

The `0007` milestone stores bounded evidence bytes as BLOBs inside the SQLCipher database, so database, WAL, and indexes share the existing vault encryption boundary. SHA-256 is revalidated when reconstructing an original, and all Phase 5 rows are immutable. `0008` keeps Phase 6 snapshot/remediation state inside the same encrypted boundary and adds canonical payload hashes plus immutable triggers for replay integrity. The broader target remains independently authenticated encrypted object files named by opaque UUID below the vault root for larger artifacts, rotation, and streaming; that object-store migration is not implemented and must preserve existing links and integrity metadata.

### 3.3 Enumerations

Enumerations are string-valued CHECK constraints, also generated into Pydantic, JSON Schema, and TypeScript.

| Dimension | Values |
|---|---|
| sensitivity | PUBLIC, SENSITIVE, HIGHLY_SENSITIVE, RESTRICTED |
| entity review | UNREVIEWED, CONFIRMED, PROBABLE, POSSIBLE, FALSE_POSITIVE, EXCLUDED |
| temporal state | CURRENT, HISTORICAL, UNKNOWN |
| search policy | SEARCH_ALLOWED, APPROVAL_REQUIRED, STORE_ONLY, SEARCH_DENIED |
| transmission policy | LOCAL_ONLY, APPROVAL_REQUIRED, PROVIDER_ALLOWLIST, TRANSMISSION_DENIED |
| check outcome | FOUND, NOT_FOUND, NOT_CHECKED, CHECK_FAILED, ACCESS_BLOCKED, AUTH_REQUIRED, RATE_LIMITED, PROVIDER_UNAVAILABLE, AMBIGUOUS, MANUAL_REVIEW_REQUIRED, AUTHORITATIVE_ABSENCE |
| attribution | CONFIRMED_MATCH, CONFIRMED_NON_MATCH, PROBABLE, POSSIBLE, UNRESOLVED, NEEDS_MORE_EVIDENCE, HISTORICAL_OWNERSHIP, CURRENT_OWNERSHIP, ACCOUNT_TAKEOVER, RECYCLED_USERNAME, MIRROR_OR_REPOST, UNRELATED_COLLISION, POSSIBLE_IMPERSONATION, CONFIRMED_IMPERSONATION, UNKNOWN |
| automated recommendation | PROBABLE, POSSIBLE, UNRESOLVED, NEEDS_MORE_EVIDENCE, UNKNOWN |
| confidence band | VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH |
| visibility | PUBLICLY_ATTRIBUTABLE, PUBLIC_PSEUDONYMOUS, PRIVATELY_LINKABLE, HISTORICAL_RESIDUE, PRIVATE_ONLY, UNKNOWN |
| job state | DRAFT, QUEUED, WAITING_APPROVAL, RUNNING, PAUSE_REQUESTED, PAUSED, CANCEL_REQUESTED, CANCELLED, SUCCEEDED, PARTIAL, FAILED, BLOCKED |
| diff state | NEW, CHANGED, REMOVED, REAPPEARED, REDIRECTED, DEINDEXED, ARCHIVED, FALSE_POSITIVE, UNCHANGED, UNKNOWN |

AUTHORITATIVE_ABSENCE is accepted only when the provider capability is marked authoritative for the exact scope that was queried.

## 4. Relationship overview

The diagram is split into two views only for legibility; together they describe one relational schema.

### 4.1 Identity, intake, graph, and execution

~~~mermaid
erDiagram
    VAULTS ||--|| VAULT_CRYPTO : protects
    VAULTS ||--o{ SETTINGS : owns
    VAULTS ||--o{ PROFILES : contains
    PROFILES ||--o{ PROFILE_AUTHORIZATIONS : establishes
    PROFILES ||--o{ INTAKE_SOURCES : receives
    INTAKE_SOURCES ||--o{ INTAKE_SEGMENTS : divides
    INTAKE_SOURCES ||--o{ QUARANTINE_ITEMS : isolates
    INTAKE_SOURCES ||--o{ EXTRACTION_RUNS : processes
    JOBS ||--o| EXTRACTION_RUNS : executes
    EXTRACTION_RUNS ||--o{ ENTITY_ORIGINS : emits
    PROFILES ||--o{ ENTITIES : describes
    ENTITIES ||--o{ ENTITY_VARIANTS : normalises
    ENTITY_VARIANTS ||--o{ ENTITY_VARIANT_DECISIONS : reviewed_by
    ENTITIES ||--o{ ENTITY_DECISIONS : reviews
    ENTITIES ||--o{ ENTITY_ORIGINS : traces
    ENTITIES ||--o{ LOCATION_GEOMETRIES : locates
    GRAPH_NODES ||--o{ GRAPH_EDGES : source
    GRAPH_NODES ||--o{ GRAPH_EDGES : target
    GRAPH_EDGES ||--o{ GRAPH_EDGE_ORIGINS : observed_by
    INTAKE_SOURCES ||--o{ GRAPH_EDGE_ORIGINS : supplies
    INTAKE_SEGMENTS ||--o{ GRAPH_EDGE_ORIGINS : locates
    EXTRACTION_RUNS ||--o{ GRAPH_EDGE_ORIGINS : emits
    GRAPH_EDGES ||--o{ GRAPH_EDGE_EVIDENCE : supported_by
    GRAPH_EDGES ||--o{ GRAPH_EDGE_DECISIONS : reviewed_by
    ENTITIES o|--o| GRAPH_NODES : represented_as
    PROVIDERS ||--o{ PROVIDER_JURISDICTIONS : operates_in
    PROVIDERS ||--o{ PROVIDER_CAPABILITIES : offers
    PROVIDERS ||--o{ PROVIDER_POLICIES : governed_by
    PROVIDERS ||--o{ CONNECTOR_ACCOUNTS : authorises
    PROVIDERS ||--o{ PROVIDER_HEALTH_SNAPSHOTS : monitored_by
    PROFILES o|--o{ AUDITS : scopes
    AUDITS ||--o{ AUDIT_RUNS : executes
    AUDIT_RUNS ||--o{ ISOLATED_INPUTS : contains
    AUDIT_RUNS ||--o{ SEARCH_PLANS : compiles
    SEARCH_PLANS ||--o{ SEARCH_PLAN_INPUTS : uses
    ENTITIES ||--o{ SEARCH_PLAN_INPUTS : supplies
    ISOLATED_INPUTS ||--o{ SEARCH_PLAN_INPUTS : supplies
    AUDIT_RUNS ||--o{ JOBS : schedules
    JOBS ||--o{ JOB_ATTEMPTS : retries
    JOBS ||--o{ JOB_DEPENDENCIES : parent
    JOBS ||--o| SEARCH_TASKS : specialises
    SEARCH_TASKS ||--o{ TASK_INPUTS : transmits
    ENTITY_VARIANTS ||--o{ TASK_INPUTS : supplies
    ISOLATED_INPUTS ||--o{ TASK_INPUTS : supplies
    SEARCH_TASKS ||--o{ RAW_RESULTS : returns
    AUDIT_RUNS ||--o{ COVERAGE_RECORDS : measures
    PROVIDERS ||--o{ COVERAGE_RECORDS : covers
    COVERAGE_RECORDS ||--o{ COVERAGE_OUTCOME_COUNTS : preserves
    RAW_RESULTS ||--o{ FINDING_SOURCES : normalises
    FINDINGS ||--o{ FINDING_SOURCES : derives
    FINDINGS ||--o{ FINDING_VERSIONS : versions
    FINDINGS ||--o{ FINDING_REVIEW_DECISIONS : triaged_by

    VAULTS {
        TEXT id PK
        TEXT display_name
        TEXT state
        INTEGER auto_lock_seconds
    }
    PROFILES {
        TEXT id PK
        TEXT vault_id FK
        TEXT display_label
        TEXT status
    }
    ENTITIES {
        TEXT id PK
        TEXT profile_id FK
        TEXT entity_type
        TEXT canonical_value
        TEXT sensitivity
        TEXT review_state
    }
    GRAPH_NODES {
        TEXT id PK
        TEXT profile_id FK
        TEXT node_type
        TEXT display_label
        TEXT visibility
    }
    GRAPH_EDGES {
        TEXT id PK
        TEXT from_node_id FK
        TEXT to_node_id FK
        TEXT edge_type
        INTEGER confidence_micros
    }
    GRAPH_EDGE_ORIGINS {
        TEXT id PK
        TEXT graph_edge_id FK
        TEXT intake_source_id FK
        TEXT intake_segment_id FK
        TEXT extraction_run_id FK
        TEXT disposition
        TEXT observation_hmac
    }
    PROVIDERS {
        TEXT id PK
        TEXT provider_key UK
        TEXT display_name
        TEXT risk_level
    }
    AUDIT_RUNS {
        TEXT id PK
        TEXT audit_id FK
        TEXT mode
        TEXT state
        INTEGER started_at_us
    }
    JOBS {
        TEXT id PK
        TEXT audit_run_id FK
        TEXT job_type
        TEXT state
        INTEGER progress_micros
    }
    SEARCH_TASKS {
        TEXT job_id PK
        TEXT provider_id FK
        TEXT query_class
        TEXT check_outcome
    }
    FINDINGS {
        TEXT id PK
        TEXT audit_run_id FK
        TEXT check_outcome
        TEXT current_version_id FK
    }
~~~

### 4.2 Evidence, attribution, cases, disclosure, and governance

~~~mermaid
erDiagram
    FINDINGS ||--o{ FINDING_EVIDENCE : supported_by
    FINDING_VERSIONS ||--o{ FINDING_EVIDENCE : captured_as
    EVIDENCE_ARTIFACTS ||--o{ FINDING_EVIDENCE : proves
    EVIDENCE_ARTIFACTS ||--o{ GRAPH_EDGE_EVIDENCE : supports
    EVIDENCE_ARTIFACTS ||--o{ EVIDENCE_DERIVATIONS : original
    EVIDENCE_ARTIFACTS ||--o{ EVIDENCE_DERIVATIONS : derivative
    SCORING_MODELS ||--o{ ATTRIBUTION_ASSESSMENTS : scores
    FINDINGS ||--o{ ATTRIBUTION_ASSESSMENTS : assesses
    ATTRIBUTION_ASSESSMENTS ||--o{ ATTRIBUTION_SIGNALS : explains
    ATTRIBUTION_ASSESSMENTS ||--o{ ATTRIBUTION_DECISIONS : reviewed_by
    ATTRIBUTION_ASSESSMENTS ||--o{ IMPERSONATION_CASES : opens
    IMPERSONATION_CASES ||--o{ IMPERSONATION_OBSERVATIONS : records
    IMPERSONATION_CASES ||--o{ IMPERSONATION_DECISIONS : classified_by
    IMPERSONATION_CASES ||--o{ OWNERSHIP_PERIODS : timelines
    FINDINGS ||--o{ IMPERSONATION_OBSERVATIONS : concerns
    AUDIT_RUNS ||--o{ RUN_COMPARISONS : baseline
    AUDIT_RUNS ||--o{ RUN_COMPARISONS : current
    RUN_COMPARISONS ||--o{ FINDING_DIFFS : contains
    FINDINGS ||--o{ FINDING_DIFFS : old_finding
    FINDINGS ||--o{ FINDING_DIFFS : new_finding
    FINDINGS ||--o{ REMEDIATION_CASES : remediates
    IMPERSONATION_CASES ||--o{ REMEDIATION_CASES : escalates
    REMEDIATION_CASES ||--o{ REMEDIATION_EVENTS : tracks
    TRANSMISSION_PREFLIGHTS ||--o{ TRANSMISSION_PREFLIGHT_ITEMS : contains
    TRANSMISSION_PREFLIGHTS ||--o{ TRANSMISSION_APPROVAL_SETS : approved_as
    TRANSMISSION_APPROVAL_SETS ||--o{ TRANSMISSION_APPROVAL_ITEMS : contains
    TRANSMISSION_PREFLIGHT_ITEMS ||--o| TRANSMISSION_APPROVAL_ITEMS : approves
    SEARCH_TASKS ||--o{ SEARCH_TASK_APPROVALS : consumes
    TRANSMISSION_APPROVAL_ITEMS ||--o{ SEARCH_TASK_APPROVALS : binds
    SEARCH_TASKS ||--o{ TRANSMISSION_LEDGER : attempts
    TRANSMISSION_LEDGER ||--o{ TRANSMISSION_EVENTS : records
    TRANSMISSION_LEDGER ||--o{ TRANSMISSION_ATTEMPT_ITEMS : contains
    TRANSMISSION_APPROVAL_ITEMS ||--o{ TRANSMISSION_ATTEMPT_ITEMS : discloses
    PROVIDERS ||--o{ TRANSMISSION_PREFLIGHTS : previews
    PROVIDERS ||--o{ TRANSMISSION_LEDGER : receives
    PROVIDERS ||--o{ API_USAGE : bills
    JOBS ||--o{ ERRORS : encounters
    AUDIT_RUNS ||--o{ REPORTS : reports
    REPORTS ||--o{ REPORT_APPROVALS : approved_by
    REPORTS ||--o{ REPORT_ARTIFACTS : produces
    EVIDENCE_ARTIFACTS ||--o{ REPORT_ARTIFACTS : stores
    VAULTS ||--o{ BACKUP_RECORDS : backs_up
    VAULTS ||--o{ EVENT_STREAM_SESSIONS : streams
    EVENT_STREAM_SESSIONS ||--o{ EVENT_OUTBOX : replays
    TAGS ||--o{ OBJECT_TAGS : labels
    NOTES ||--o{ NOTE_REVISIONS : versions
    VAULTS ||--o{ AUDIT_EVENTS : audits

    EVIDENCE_ARTIFACTS {
        TEXT id PK
        TEXT object_key UK
        TEXT artifact_kind
        TEXT sha256_plaintext
        TEXT encryption_version
        INTEGER captured_at_us
    }
    ATTRIBUTION_ASSESSMENTS {
        TEXT id PK
        TEXT finding_id FK
        TEXT model_id FK
        INTEGER score_micros
        TEXT confidence_band
    }
    ATTRIBUTION_DECISIONS {
        TEXT id PK
        TEXT assessment_id FK
        TEXT classification
        TEXT actor_type
        INTEGER decided_at_us
    }
    IMPERSONATION_CASES {
        TEXT id PK
        TEXT assessment_id FK
        TEXT classification
        TEXT state
    }
    REMEDIATION_CASES {
        TEXT id PK
        TEXT finding_id FK
        TEXT action_type
        TEXT state
        INTEGER deadline_at_us
    }
    TRANSMISSION_APPROVAL_SETS {
        TEXT id PK
        TEXT preflight_id FK
        TEXT manifest_hmac
        INTEGER expires_at_us
    }
    TRANSMISSION_LEDGER {
        TEXT id PK
        TEXT approval_set_id FK
        TEXT provider_id FK
        TEXT current_outcome
        INTEGER attempted_at_us
        INTEGER sent_at_us
    }
    REPORTS {
        TEXT id PK
        TEXT audit_run_id FK
        TEXT report_type
        TEXT redaction_mode
        TEXT state
    }
~~~

### 4.3 Required-domain crosswalk

| Required domain | Physical tables |
|---|---|
| Profiles | profiles, profile_authorizations |
| Entities and variants | entities, entity_variants, entity_variant_decisions, entity_origins, location_geometries |
| Relationships and decisions | graph_nodes, graph_edges, graph_edge_origins, graph_edge_evidence, graph_edge_decisions, entity_decisions |
| Source providers and jurisdictions | providers, provider_jurisdictions, provider_capabilities, provider_policies, provider_health_snapshots |
| Audit runs and search plans | audits, audit_runs, isolated_inputs, search_plans, search_plan_inputs |
| Search tasks and durable execution | jobs, job_dependencies, job_attempts, idempotency_records, search_tasks, task_inputs, coverage_records, coverage_outcome_counts |
| Raw results and findings | raw_results, findings, finding_versions, finding_sources, finding_review_decisions |
| Evidence | evidence_artifacts, evidence_derivations, finding_evidence |
| Attribution | scoring_models, attribution_assessments, attribution_signals, attribution_decisions |
| Impersonation | impersonation_cases, impersonation_observations, impersonation_decisions, ownership_periods |
| Monitoring and remediation | run_comparisons, finding_diffs, remediation_cases, remediation_events |
| Transmissions, API use, and errors | transmission_preflights, transmission_preflight_items, transmission_approval_sets, transmission_approval_items, search_task_approvals, transmission_ledger, transmission_attempt_items, transmission_events, api_usage, errors |
| Settings and encryption | settings_aggregates, settings, vault_crypto |
| Tags, notes, reports, and audit history | tags, object_tags, notes, note_revisions, reports, report_approvals, report_artifacts, audit_events, event_stream_sessions, event_outbox, backup_records |

## 5. Schema catalog

The tables below list domain-specific columns. Common scope, timestamp, revision, and soft-deletion columns from section 3 are implicit.

### 5.1 Vault, encryption, settings, and profiles

#### vaults

One row per encrypted Ariadne vault.

| Column | Type | Notes |
|---|---|---|
| display_name | TEXT | Local label; sensitive because it may reveal purpose |
| state | TEXT | LOCKED, UNLOCKED, MIGRATING, RECOVERY_REQUIRED |
| format_version | INTEGER | Vault bundle format |
| auto_lock_seconds | INTEGER | Zero is not allowed in release defaults |
| last_opened_at_us | INTEGER nullable | Local operational metadata |
| purge_requested_at_us | INTEGER nullable | Starts dependency-aware purge |

#### vault_crypto

One-to-one with vaults. Contains key versions and opaque Keychain references,
but no key bytes, wrapped keys, recovery secret, or Keychain authorization
material. ADR-002 defines independent database and backup keys.

| Column | Type | Notes |
|---|---|---|
| vault_id | TEXT PK/FK | Shared primary key |
| database_key_version | INTEGER | Active per-vault SQLCipher key generation |
| database_keychain_ref | TEXT | Opaque non-secret reference to the database-key item |
| backup_key_version | INTEGER | Active per-vault backup-envelope key generation |
| backup_keychain_ref | TEXT | Opaque non-secret reference to the separate backup-key item |
| sqlcipher_profile | TEXT | Cipher/KDF parameter profile |
| backup_cipher | TEXT | AES_256_GCM for the bounded Phase 2 envelope |
| evidence_cipher | TEXT | XCHACHA20_POLY1305 or AES_256_GCM |
| database_key_rotated_at_us | INTEGER nullable | Last verified database-key rotation |
| backup_key_rotated_at_us | INTEGER nullable | Last verified backup-key rotation |

#### settings

Typed vault- or profile-scoped settings. Secret values are rejected.

| Column | Type | Notes |
|---|---|---|
| profile_id | TEXT nullable | Null means vault-wide |
| setting_key | TEXT | Allowlisted key |
| value_json | TEXT | Validated against setting schema |
| schema_version | INTEGER | Enables migration |
| source | TEXT | DEFAULT, USER, POLICY |

SQLite treats nulls as distinct inside an ordinary UNIQUE constraint, so
settings use two partial unique indexes rather than
`UNIQUE(vault_id, profile_id, setting_key)`:

- unique `(vault_id, setting_key)` where `profile_id IS NULL`; and
- unique `(vault_id, profile_id, setting_key)` where `profile_id IS NOT NULL`.

#### settings_aggregates

One mutable aggregate row provides the compare-and-swap revision used by each
vault- or profile-scoped `SettingsView`. A settings patch updates its typed
`settings` rows, increments this aggregate's common `revision`, appends the
audit event, and inserts the redacted outbox event in one transaction.

| Column | Type | Notes |
|---|---|---|
| profile_id | TEXT nullable | Null for the vault-wide aggregate; otherwise the exact profile settings scope |
| schema_version | INTEGER | Version of the aggregate settings contract |
| settings_digest | TEXT | Keyed digest of canonical typed settings for change binding, never a secret value |

There is one vault aggregate and at most one aggregate per profile, enforced by
partial unique indexes on `(vault_id)` where `profile_id IS NULL` and on
`(vault_id, profile_id)` where `profile_id IS NOT NULL`. Effective views that
merge vault defaults with profile overrides expose both source revisions;
`If-Match` always targets the one explicit scope being patched.

#### profiles

Separates authorised subjects and prevents correlation by default.

| Column | Type | Notes |
|---|---|---|
| display_label | TEXT | Local label; never seeded from confidential material |
| purpose | TEXT | Defensive purpose summary |
| status | TEXT | DRAFT, ACTIVE, ARCHIVED, PURGE_PENDING |
| default_sensitivity | TEXT | Baseline for new candidates |
| correlation_boundary | TEXT | ISOLATED by default; explicit linking requires a decision |

#### profile_authorizations

Append-only record of authority and scope.

| Column | Type | Notes |
|---|---|---|
| profile_id | TEXT FK | Subject scope |
| authority_type | TEXT | SELF, EXPLICIT_CONSENT, ACCOUNT_OWNER, OTHER_DOCUMENTED |
| scope_json | TEXT | Allowed data and operations |
| attested_at_us | INTEGER | Required before an audit can run |
| expires_at_us | INTEGER nullable | Expired authority blocks new tasks |
| revoked_at_us | INTEGER nullable | Revocation cancels pending external work |
| note_id | TEXT nullable | Optional local explanation |

### 5.2 Intake, quarantine, and extraction

#### intake_sources

Represents one explicit paste, selected file, authorised export, or manual evidence import.

| Column | Type | Notes |
|---|---|---|
| source_kind | TEXT | PASTE, FILE, EXPORT, CONNECTOR, MANUAL_EVIDENCE |
| display_name | TEXT | Sanitised basename or synthetic local label |
| broker_handle | TEXT nullable | Short-lived Tauri file-broker handle; never an arbitrary path |
| declared_mime | TEXT nullable | User/extension indication |
| detected_mime | TEXT | Sniffed MIME |
| byte_size | INTEGER | Checked before parsing |
| sha256 | TEXT | Integrity/deduplication |
| retention_state | TEXT | TEMPORARY, RETAINED, PURGE_PENDING |
| retention_expires_at_us | INTEGER nullable | Required for temporary raw intake |
| consent_confirmed_at_us | INTEGER | Explicit import confirmation |

#### intake_segments

Bounded parse units with byte/row coordinates and no active content.

| Column | Type | Notes |
|---|---|---|
| intake_source_id | TEXT FK | Parent |
| ordinal | INTEGER | Stable ordering |
| segment_kind | TEXT | TEXT, RECORD, CONTACT, JSON_VALUE, FILE_MEMBER |
| content_text | TEXT nullable | Sanitised plaintext inside SQLCipher |
| content_hmac | TEXT | Keyed equality fingerprint |
| locator_json | TEXT | Non-executable byte/row/member locator |
| language | TEXT nullable | BCP 47 where detected |

#### quarantine_items

Restricted or unsafe material isolated before ordinary processing.

| Column | Type | Notes |
|---|---|---|
| intake_source_id | TEXT FK | Origin |
| reason_code | TEXT | RESTRICTED_VALUE, MIME_MISMATCH, ACTIVE_CONTENT, SIZE_LIMIT, MALFORMED, UNSAFE_ARCHIVE |
| opaque_blob_key | TEXT nullable | Authenticated encrypted quarantine object |
| mime_type | TEXT nullable | Safely sniffed type |
| byte_size_plaintext | INTEGER nullable | Enforced limit |
| byte_size_ciphertext | INTEGER nullable | Storage verification |
| sha256_plaintext | TEXT nullable | Protected by SQLCipher; never printed |
| sha256_ciphertext | TEXT nullable | Storage integrity |
| encryption_version | TEXT nullable | Authenticated object format |
| key_version | INTEGER nullable | Vault key generation |
| masked_preview | TEXT nullable | Must not reconstruct the value |
| state | TEXT | PENDING_REVIEW, DELETED, RELEASED_AS_SAFE |
| retention_expires_at_us | INTEGER | Short mandatory deadline |
| reviewed_at_us | INTEGER nullable | Human review |
| deletion_verified_at_us | INTEGER nullable | Application-level deletion check |

Quarantine rows have no FTS, graph, search-task, report, or model relationship.

#### extraction_runs

| Column | Type | Notes |
|---|---|---|
| intake_source_id | TEXT FK | Input |
| job_id | TEXT unique FK | Durable extraction job used for restart and event correlation |
| engine_kind | TEXT | DETERMINISTIC, LOCAL_MODEL |
| engine_name | TEXT | Extractor identifier |
| engine_version | TEXT | Reproducibility |
| configuration_hash | TEXT | Rules/model configuration |
| state | TEXT | Job-like state |
| started_at_us | INTEGER nullable | Timing |
| finished_at_us | INTEGER nullable | Timing |

The API retainRawSource choice updates intake_sources.retention_state and retention_expires_at_us in the same transaction that creates the extraction job. It never applies to quarantined restricted bytes.

### 5.3 Entities, variants, provenance, and review

#### entities

Identity claims approved or awaiting review.

| Column | Type | Notes |
|---|---|---|
| entity_type | TEXT | PERSON, ALIAS, USERNAME, EMAIL, TELEPHONE, ADDRESS, LOCATION, ORGANISATION, EMPLOYMENT, EDUCATION, DOMAIN, URL, PLATFORM_ACCOUNT, COMPANY, PROJECT, IMAGE, DOCUMENT, DATE, IP_ADDRESS, COORDINATE, COMPANY_NUMBER, PLATFORM_ID, POSTAL_CODE, WALLET_ADDRESS, OTHER |
| canonical_value | TEXT | Never RESTRICTED |
| display_mask | TEXT | Safe routine display |
| value_hmac | TEXT | Vault-keyed fingerprint |
| sensitivity | TEXT | Independent handling class |
| review_state | TEXT | Human review state |
| temporal_state | TEXT | CURRENT, HISTORICAL, UNKNOWN |
| valid_from_us | INTEGER nullable | Claim period |
| valid_to_us | INTEGER nullable | Claim period |
| search_policy | TEXT | Per-entity search rule |
| transmission_policy | TEXT | Per-entity disclosure rule |
| graph_node_id | TEXT nullable unique | Optional graph representation |
| current_decision_id | TEXT nullable | Convenience pointer |

No uniqueness rule merges values across profiles. Within a profile, a partial unique index on profile_id, entity_type, value_hmac excludes soft-deleted rows and is advisory: a reviewed decision may keep intentionally distinct historical entities.

#### entity_variants

Locally generated, budgeted variants.

| Column | Type | Notes |
|---|---|---|
| entity_id | TEXT FK | Canonical entity |
| variant_type | TEXT | EXACT, CASE, SEPARATOR, TRANSLITERATION, DIACRITIC, NATIONAL_FORMAT, E164, LOCAL_PART, DOMAIN, CONTROLLED_TYPO, OTHER |
| value | TEXT | Never transmitted automatically |
| value_hmac | TEXT | Keyed fingerprint |
| generator | TEXT | Rule/model identifier |
| generator_version | TEXT | Reproducibility |
| rank | INTEGER | Planner priority |
| estimated_risk | TEXT | LOW, MEDIUM, HIGH |
| approved_for_search | INTEGER | Boolean; defaults false except policy-safe exact forms |

#### entity_variant_decisions

Append-only changes to rank, approval, exclusion, or generator status. Each row stores variant_id, decision_type, before/after JSON, actor, reason, decided_at_us, and supersedes_decision_id where applicable. entity_variants.current_decision_id is a convenience pointer updated atomically.

#### entity_origins

Provenance join with exactly one source pointer populated.

| Column | Type | Notes |
|---|---|---|
| entity_id | TEXT FK | Candidate or reviewed entity |
| extraction_run_id | TEXT nullable FK | Producer; may coexist with the source pointer |
| intake_segment_id | TEXT nullable FK | Local source |
| raw_result_id | TEXT nullable FK | Provider source |
| evidence_artifact_id | TEXT nullable FK | Preserved source |
| origin_kind | TEXT | USER_INPUT, DETERMINISTIC, LOCAL_MODEL, PROVIDER, MANUAL |
| confidence_micros | INTEGER | 0 to 1,000,000 |
| explanation | TEXT | Concise provenance, not hidden reasoning |
| observed_at_us | INTEGER | Observation time |

Exactly one source pointer—intake_segment_id, raw_result_id, or evidence_artifact_id—is required. extraction_run_id identifies the producer and is independent, preserving the engine-to-source chain.

#### entity_decisions

Append-only field and classification edits.

| Column | Type | Notes |
|---|---|---|
| entity_id | TEXT FK | Subject |
| decision_type | TEXT | CONFIRM, REJECT, EXCLUDE, EDIT, MERGE, SPLIT, CLASSIFY, POLICY_CHANGE |
| before_json | TEXT nullable | Sensitive, scoped snapshot |
| after_json | TEXT | Validated patch/snapshot |
| actor_type | TEXT | LOCAL_USER, DETERMINISTIC_RULE, LOCAL_MODEL |
| actor_version | TEXT nullable | Model/rule version |
| reason | TEXT nullable | User-facing explanation |
| decided_at_us | INTEGER | Append-only time |

### 5.4 Relational graph

#### graph_nodes

| Column | Type | Notes |
|---|---|---|
| node_type | TEXT | Master-prompt graph type enumeration |
| display_label | TEXT | Masked according to reveal context |
| sensitivity | TEXT | Used by graph filters |
| visibility | TEXT | Independent source visibility |
| scope_audit_run_id | TEXT nullable FK | Required instead of profile_id for an ISOLATED graph |
| entity_id | TEXT nullable unique | Entity-backed node |
| finding_id | TEXT nullable unique | Finding-backed node |
| evidence_artifact_id | TEXT nullable unique | Evidence-backed node |
| backing_audit_run_id | TEXT nullable unique | Run-backed node |
| provider_id | TEXT nullable | Provider-backed node |
| remediation_case_id | TEXT nullable unique | Case-backed node |
| position_json | TEXT nullable | User-pinned layout only |

A CHECK constraint requires exactly one graph scope: profile_id or scope_audit_run_id. Another CHECK permits at most one backing object. Domain-service transactions prevent unbacked nodes except explicit user-created grouping nodes.

#### graph_edges

| Column | Type | Notes |
|---|---|---|
| from_node_id | TEXT FK | Scoped source |
| to_node_id | TEXT FK | Scoped target |
| edge_type | TEXT | OWNS, USED, RECOVERY_FOR, EMPLOYED_BY, STUDIED_AT, LIVED_AT, LOCATED_IN, LINKS_TO, MENTIONS, AUTHORED, CREATED, MIRRORS, REPOSTS, SAME_AS, POSSIBLY_SAME_AS, NOT_SAME_AS, PREVIOUS_USERNAME, CURRENT_USERNAME, FOUND_BY, SUPPORTED_BY, CONTRADICTED_BY, REMOVAL_REQUEST_FOR |
| confidence_micros | INTEGER | 0 to 1,000,000 |
| visibility | TEXT | Independent dimension |
| valid_from_us | INTEGER nullable | Relationship time |
| valid_to_us | INTEGER nullable | Relationship time |
| observed_at_us | INTEGER | Evidence time |
| origin_type | TEXT | HUMAN, DETERMINISTIC, LOCAL_MODEL, PROVIDER |
| explanation | TEXT | Why the edge exists |
| current_decision_id | TEXT nullable | Convenience pointer |

Both endpoints must belong to the same profile or the same ISOLATED audit run. Mixed profile/isolated and cross-profile edges are prohibited in this schema; any future cross-profile feature requires a separate privacy review and ADR.

#### graph_edge_origins (implemented Phase 3)

| Column | Type | Notes |
|---|---|---|
| graph_edge_id | TEXT FK | Profile-scoped edge |
| intake_source_id | TEXT FK | Source that produced this observation |
| intake_segment_id | TEXT FK | Segment in the same source |
| extraction_run_id | TEXT FK | Extraction run for the same source |
| disposition | TEXT | SUPPORTS or CONTRADICTS |
| confidence_micros | INTEGER | 0 to 1,000,000 for this observation |
| visibility | TEXT | Visibility at observation time |
| source_span_start/end | INTEGER nullable | Optional bounded source span pair |
| observed_at_us | INTEGER | Observation time |
| origin_type | TEXT | HUMAN, DETERMINISTIC, LOCAL_MODEL, PROVIDER |
| explanation | TEXT | Bounded provenance explanation; protected from routine repr |
| observation_hmac | TEXT | Keyed deduplication of the complete observation identity |
| created_at_us | INTEGER | Persistence time |

Composite foreign keys require edge, source, segment, and extraction run to share vault/profile scope and require segment/run to belong to the declared source. Exact reprocessing deduplicates on `(vault_id, profile_id, graph_edge_id, observation_hmac)`; the source/run/segment identifiers are part of the HMAC input, so equivalent observations from distinct sources remain distinct. Snapshot responses provide complete support and contradiction counts, at least one bounded evidence sample per returned edge, and `evidenceTruncated` when the sample is smaller than the total.

The target `graph_edge_evidence` table below remains a later evidence-vault feature; it is not a replacement name for the implemented intake provenance table.

#### graph_edge_evidence

| Column | Type | Notes |
|---|---|---|
| edge_id | TEXT FK | Edge |
| evidence_artifact_id | TEXT nullable FK | Preserved artifact |
| finding_id | TEXT nullable FK | Finding |
| raw_result_id | TEXT nullable FK | Raw source |
| role | TEXT | SUPPORTS, CONTRADICTS, CONTEXT |
| excerpt | TEXT nullable | Minimal, sanitised supporting excerpt |
| observed_at_us | INTEGER | Time |

Exactly one evidence source pointer is required.

#### graph_edge_decisions

Append-only confirmation, rejection, correction, or exclusion of an edge, using actor, reason, before/after, and decision time fields equivalent to entity_decisions.

#### location_geometries

Typed map representation for ADDRESS or LOCATION entities: entity_id, geometry_kind POINT or REGION, exact_geometry_json nullable, coarse_geometry_json, precision_meters, privacy_mode EXACT_LOCAL_ONLY, COARSE, REGION_ONLY, or HIDDEN, temporal state, valid interval, provenance, and confidence. Exact private geometry is SQLCipher-protected, omitted from ordinary graph/map responses, and never included in product screenshots or default exports.

### 5.5 Provider registry and connectors

#### providers

Application catalog metadata; contains no identity values.

| Column | Type | Notes |
|---|---|---|
| provider_key | TEXT unique | Stable adapter-facing key |
| display_name | TEXT | Human-readable |
| source_type | TEXT | Search API, public page, official register, local corpus, and so on |
| provider_class | TEXT | STANDARD, OFFICIAL_REGISTER, PEOPLE_SEARCH, DATA_BROKER, AUTHORISED_CONNECTOR, LOCAL |
| is_data_broker | INTEGER | Enforceable broker policy flag |
| access_basis | TEXT | PUBLIC_API, PUBLIC_WEB, USER_AUTHORIZED, USER_EXPORT, LOCAL_ONLY |
| requires_user_auth | INTEGER | Boolean |
| sends_user_identifiers | INTEGER | Boolean |
| retention_notes | TEXT | UNKNOWN is explicit |
| privacy_policy_url | TEXT nullable | HTTPS URL |
| terms_url | TEXT nullable | HTTPS URL |
| removal_process_url | TEXT nullable | HTTPS URL |
| has_official_removal_process | INTEGER | Explicit even when URL is unknown |
| risk_level | TEXT | LOW, MEDIUM, HIGH, VERY_HIGH |
| enabled_by_default | INTEGER | False for external providers; false for brokers |
| adapter_version | TEXT | Contract version |

A CHECK requires enabled_by_default = false when is_data_broker is true. Preflight snapshots paid_access_status and the corroboration requirement; broker-derived attribution cannot enter a high-confidence band without an independent non-broker signal.

#### provider_jurisdictions

| Column | Type | Notes |
|---|---|---|
| provider_id | TEXT FK | Provider |
| jurisdiction_type | TEXT | OPERATOR_COUNTRY, HOSTING_REGION, PROCESSING_REGION |
| country_or_region_code | TEXT | ISO country/region code |
| declared | INTEGER | False means inferred and visibly labelled |
| effective_from_us | INTEGER nullable | Registry history |
| effective_to_us | INTEGER nullable | Registry history |

#### provider_capabilities

| Column | Type | Notes |
|---|---|---|
| provider_id | TEXT FK | Provider |
| capability_key | TEXT | SEARCH, FETCH, ARCHIVE, CAPTURE, AUTHORITATIVE_LOOKUP, REMOVAL_GUIDE |
| entity_types_json | TEXT | Supported types |
| outcome_support_json | TEXT | Supported outcome taxonomy |
| authoritative_scope_json | TEXT nullable | Required for authoritative absence |
| rate_limit_json | TEXT | Declarative limits |
| cost_model_json | TEXT | Estimate model |
| allowed_domains_json | TEXT | Network capability boundary |

#### provider_policies

Vault-local enablement and disclosure rules.

| Column | Type | Notes |
|---|---|---|
| provider_id | TEXT FK | Provider |
| mode | TEXT | DISABLED, LOCAL_ONLY, EU_ONLY, WORLDWIDE, CUSTOM |
| enabled | INTEGER | Explicit user state |
| allowed_entity_types_json | TEXT | Allowlist |
| blocked_entity_types_json | TEXT | Blocklist |
| max_sensitivity | TEXT | Never RESTRICTED |
| require_each_approval | INTEGER | Mandatory for high sensitivity |
| paid_access_status | TEXT | NOT_PAID, USER_CONFIRMED_PAID, UNKNOWN |
| requires_independent_corroboration | INTEGER | Forced true for broker/people-search claims |
| policy_revision | INTEGER | Binds approvals |

#### connector_accounts

| Column | Type | Notes |
|---|---|---|
| provider_id | TEXT FK | Connector provider |
| profile_id | TEXT FK | Scope |
| account_label | TEXT | Masked local label |
| keychain_token_ref | TEXT | Opaque reference only |
| scopes_json | TEXT | Exact read-only scopes |
| state | TEXT | CONNECTED, EXPIRED, REVOKED, ERROR |
| authorised_at_us | INTEGER | Time |
| expires_at_us | INTEGER nullable | Token/session expiry |
| revoked_at_us | INTEGER nullable | Revocation |

#### provider_health_snapshots

Time-series health, latency, rate-limit, and availability data. It never stores query values or raw provider errors.

| Column | Type | Notes |
|---|---|---|
| provider_id | TEXT FK | Provider |
| health_state | TEXT | HEALTHY, DEGRADED, BLOCKED, AUTH_REQUIRED, UNAVAILABLE, UNKNOWN |
| latency_ms | INTEGER nullable | Bounded observation |
| rate_limit_state | TEXT | AVAILABLE, THROTTLED, EXHAUSTED, UNKNOWN |
| remaining_requests | INTEGER nullable | Provider-declared |
| resets_at_us | INTEGER nullable | Provider-declared |
| error_code | TEXT nullable | Stable redacted code |
| observed_at_us | INTEGER | Freshness |
| expires_at_us | INTEGER | Staleness boundary |

Index provider_id, observed_at_us descending. Provider responses expose observed_at and stale explicitly.

### 5.6 Audits, plans, durable jobs, and coverage

#### audits

Long-lived audit definition.

| Column | Type | Notes |
|---|---|---|
| name | TEXT | Local synthetic/user label |
| audit_type | TEXT | FULL, TARGETED, SELECTED_TOOLS, MONITOR |
| correlation_scope | TEXT | PROFILE or ISOLATED; only TARGETED may be isolated |
| purpose | TEXT | Declared purpose |
| status | TEXT | DRAFT, ACTIVE, ARCHIVED |
| authorization_id | TEXT nullable FK | Valid profile authority; null only for an isolated targeted run with an explicit run attestation |
| baseline_run_id | TEXT nullable | Optional comparison baseline |

profile_id may be null only when audit_type is TARGETED, correlation_scope is ISOLATED, and each run stores a current defensive-use attestation. Isolated data cannot enter a profile graph until the user explicitly saves it.

#### audit_runs

Immutable run identity plus evolving state.

| Column | Type | Notes |
|---|---|---|
| audit_id | TEXT FK | Audit |
| run_number | INTEGER | Monotonic within audit |
| mode | TEXT | DRY_RUN, MOCK, LIVE_LOCAL, LIVE_APPROVED |
| correlation_scope | TEXT | PROFILE or ISOLATED |
| state | TEXT | Job-style aggregate state |
| authorization_snapshot_json | TEXT | Profile authority or explicit isolated self-audit attestation |
| policy_snapshot_json | TEXT | Exact provider/transmission policy revision |
| query_budget_json | TEXT | Max queries, variants, providers, time, cost, sensitivity |
| started_at_us | INTEGER nullable | Timing |
| finished_at_us | INTEGER nullable | Timing |
| limitation_summary | TEXT nullable | Unresolved coverage limits |

#### isolated_inputs

One-off input for a targeted tool run that the user has not saved into a profile.

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Must have ISOLATED correlation scope |
| input_type | TEXT | Email, username, phone, name, address, domain, URL, image, company number, local corpus, or other supported input |
| input_kind | TEXT | SCALAR, ARTIFACT, LOCAL_CORPUS |
| exact_value | TEXT nullable | SQLCipher-protected scalar only; never RESTRICTED |
| input_artifact_id | TEXT nullable FK | Brokered and validated image/document artifact |
| input_manifest_json | TEXT nullable | Bounded corpus member IDs and policy, never arbitrary paths |
| display_mask | TEXT | Routine UI/event form |
| value_hmac | TEXT | Vault-keyed equality fingerprint |
| sensitivity | TEXT | Handling class |
| search_policy | TEXT | Review and approval rule |
| transmission_policy | TEXT | Disclosure rule |
| state | TEXT | PREPARING, REVIEW_REQUIRED, READY, QUARANTINED, EXPIRED |
| reviewed_at_us | INTEGER | Explicit input confirmation |
| retention_expires_at_us | INTEGER nullable | Short default when kept isolated |
| saved_entity_id | TEXT nullable FK | Set only after explicit save-to-profile |

A CHECK requires exactly the representation allowed by input_kind. Images and local corpora are never JSON strings or paths: a Tauri-brokered import creates a validated encrypted artifact first, with MIME, size, hash, and retention policy. Saving creates a new entity and an entity_origin that references the targeted run; it does not silently expand correlation for earlier tasks.

#### search_plans

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Run |
| version | INTEGER | Recompilation history |
| compiler_version | TEXT | Reproducibility |
| state | TEXT | DRAFT, REVIEW_REQUIRED, APPROVED, SUPERSEDED |
| estimated_query_count | INTEGER | Budget preview |
| estimated_duration_ms | INTEGER nullable | Estimate |
| estimated_cost_micros | INTEGER | Estimate |
| currency | TEXT | ISO 4217 |
| risk_summary_json | TEXT | Sensitive providers and approvals |
| approved_at_us | INTEGER nullable | Human approval |

#### search_plan_inputs

Many-to-many join between a plan and either reviewed entities/variants or a reviewed isolated_input. A CHECK constraint requires exactly one input family. The row records purpose, selected variant IDs, query classes, and a per-input query limit.

#### jobs

Durable queue base for intake, search, fetch, evidence capture, OCR, hashing, model inference, comparison, report, backup, and purge work.

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT nullable FK | Run, when applicable |
| parent_job_id | TEXT nullable FK | Aggregate parent |
| job_type | TEXT | Typed worker operation |
| state | TEXT | Durable state machine |
| priority | INTEGER | Bounded scheduler priority |
| progress_micros | INTEGER | 0 to 1,000,000 |
| progress_message_code | TEXT nullable | Localised, non-sensitive |
| scheduled_at_us | INTEGER | Availability |
| lease_owner | TEXT nullable | Ephemeral worker ID |
| lease_expires_at_us | INTEGER nullable | Crash recovery |
| retry_count | INTEGER | Bounded |
| retry_limit | INTEGER | Bounded |
| cancel_requested_at_us | INTEGER nullable | Cooperative cancellation |
| idempotency_record_id | TEXT nullable FK | Safe reference to the command record; the raw client key is never stored |
| input_manifest_json | TEXT | IDs and policy references, not unrestricted payloads |

#### job_dependencies

Directed acyclic dependencies use `job_id`, `depends_on_job_id`, `required_state`, and `failure_policy`. Fan-in is capped at 64, and cycle detection runs in the service with recursive-CTE validation tests.

#### job_attempts

Append-only attempt timings, worker kind, outcome, redacted result metadata, and optional error_id.

#### idempotency_records

Durable command deduplication for job-creating and side-effecting API requests.
The record is created in the same transaction as its job or resource mutation
and initial outbox row.

| Column | Type | Notes |
|---|---|---|
| actor_class | TEXT | Closed local actor class; never a token or display name |
| route_key | TEXT | Stable generated method/route identifier, not an arbitrary URL |
| key_hmac | TEXT | Vault-keyed HMAC of the client idempotency key; raw key is never stored |
| request_digest | TEXT | Digest of the canonical validated request and bound scope |
| state | TEXT | PENDING, COMPLETED, FAILED |
| result_resource_type | TEXT nullable | Allowlisted safe result type for synchronous mutation replay |
| result_resource_id | TEXT nullable | Stable local ID; no protected value |
| result_resource_revision | INTEGER nullable | Revision returned by the original mutation |
| response_status | INTEGER nullable | Stable logical status; no response body is persisted here |
| completed_at_us | INTEGER nullable | Set when the original transaction has a durable result |
| expires_at_us | INTEGER | At least the referenced job and retry lifetime |

Unique: `(vault_id, actor_class, route_key, key_hmac)`. Reuse with the same
`request_digest` resolves to the existing job through
`jobs.idempotency_record_id` or to the safe resource reference. Reuse with a
different digest is a conflict. A partial unique index makes non-null
`jobs.idempotency_record_id` one-to-one. Idempotency records contain no request
body, response body, session credential, personal value, or raw key.

#### search_tasks

One-to-one job extension for a provider query.

| Column | Type | Notes |
|---|---|---|
| job_id | TEXT PK/FK | Shared identity |
| search_plan_id | TEXT FK | Approved plan |
| provider_id | TEXT FK | Provider |
| capability_id | TEXT FK | Declared capability |
| query_class | TEXT | EXACT, VARIANT, CORRELATION, PLATFORM, CONTENT_TYPE, TEMPORAL, LANGUAGE, GEOGRAPHIC, ARCHIVE, IMAGE, PUBLIC_RECORD, ACCOUNT_EXPORT, CODE_REPOSITORY |
| query_text | TEXT | Encrypted in SQLCipher; never logged or streamed |
| query_hmac | TEXT | Idempotency/cache key |
| sensitivity | TEXT | Maximum input sensitivity |
| approval_manifest_hmac | TEXT nullable | Convenience binding; actual items are in search_task_approvals |
| check_outcome | TEXT nullable | Final explicit outcome |
| result_count | INTEGER nullable | Null until completed |
| provider_request_id | TEXT nullable | Sanitised provider correlation ID |

#### task_inputs

| Column | Type | Notes |
|---|---|---|
| search_task_id | TEXT FK | Task |
| entity_id | TEXT nullable FK | Approved source entity |
| entity_variant_id | TEXT nullable FK | Exact selected variant |
| isolated_input_id | TEXT nullable FK | Reviewed one-off input |
| purpose | TEXT | Bound purpose |
| payload_hmac | TEXT | Must match approval |
| disclosure_mode | TEXT | EXACT, MASKED, DERIVED |

A CHECK constraint requires either entity_id, with an optional matching variant, or isolated_input_id. Profile and isolated scopes cannot be mixed in one search task.

#### coverage_records

One row for each expected run/provider/capability/query-class cell, including cells never executed.

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Run |
| provider_id | TEXT FK | Provider |
| capability_id | TEXT nullable FK | Capability |
| query_class | TEXT nullable | Coverage dimension |
| jurisdiction_code | TEXT nullable | Relevant region |
| expected_checks | INTEGER | Planned |
| terminal_checks | INTEGER | Checks with a final explicit outcome |
| aggregate_state | TEXT | COMPLETE, PARTIAL, NOT_STARTED |
| authoritative | INTEGER | Capability/scope validated |
| limitation_code | TEXT nullable | Why coverage is incomplete |
| observed_at_us | INTEGER | Freshness |

#### coverage_outcome_counts

One row per coverage_record_id and check_outcome, with outcome_count. Counts include NOT_CHECKED for budget-, policy-, cancellation-, or user-skipped work. The sum of all outcome_count rows must equal expected_checks once a run is terminal; terminal_checks equals the sum excluding still-pending work. A cell can therefore preserve FOUND, NOT_FOUND, ACCESS_BLOCKED, and CHECK_FAILED simultaneously without collapsing them.

### 5.7 Raw results and findings

#### raw_results

| Column | Type | Notes |
|---|---|---|
| search_task_id | TEXT FK | Origin |
| provider_id | TEXT FK | Denormalised for safe scoped queries |
| result_ordinal | INTEGER | Provider order |
| source_url | TEXT nullable | Normalised URL |
| source_url_hmac | TEXT nullable | Keyed dedupe |
| http_status | INTEGER nullable | Fetch status |
| received_at_us | INTEGER | Time |
| body_artifact_id | TEXT nullable FK | Encrypted raw artifact, if retention approved |
| metadata_json | TEXT | Allowlisted response metadata |
| normaliser_version | TEXT | Reproducibility |
| retention_expires_at_us | INTEGER nullable | Short by default |

Unique: search_task_id, result_ordinal.

#### findings

Stable finding identity across versions.

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Discovery run |
| finding_type | TEXT | ACCOUNT, MENTION, DOCUMENT, IMAGE, RECORD, DOMAIN, PROFILE, OTHER |
| canonical_key_hmac | TEXT | Scoped dedupe |
| check_outcome | TEXT | Usually FOUND; remains independent |
| visibility | TEXT | Source visibility |
| sensitivity | TEXT | Handling |
| inbox_state | TEXT | UNREVIEWED, IN_REVIEW, SNOOZED, RESOLVED |
| first_observed_at_us | INTEGER | Time |
| last_observed_at_us | INTEGER | Time |
| current_version_id | TEXT nullable FK | Current snapshot |
| current_attribution_decision_id | TEXT nullable FK | Current human classification |
| current_review_decision_id | TEXT nullable FK | Current inbox workflow decision |
| graph_node_id | TEXT nullable unique | Graph representation |

#### finding_versions

Append-only snapshots.

| Column | Type | Notes |
|---|---|---|
| finding_id | TEXT FK | Stable parent |
| version_number | INTEGER | Monotonic |
| title | TEXT | Sanitised display |
| source_url | TEXT nullable | URL |
| content_hash | TEXT nullable | Noise-normalised content hash |
| image_phash | TEXT nullable | Optional perceptual hash |
| observed_fields_json | TEXT | Typed versioned fields |
| observation_time_us | INTEGER | Source observation |
| producer | TEXT | Adapter/normaliser/manual |
| producer_version | TEXT | Reproducibility |

#### finding_sources

Many-to-many provenance from finding versions to raw results, provider, search task, and optional evidence, with role PRIMARY, CORROBORATING, CONTRADICTING, or CONTEXT.

#### finding_review_decisions

Append-only inbox workflow decisions with finding_id, before_state, after_state, actor, reason, snooze_until_us, decided_at_us, and supersedes_decision_id. Inbox state is operational triage and is never used as attribution or check outcome.

### 5.8 Evidence vault target

The catalog below is the larger object-store target. The implemented `0007` tables and bounded SQLCipher-BLOB exception are defined in section 1.3; target names such as `evidence_artifacts` must not be mistaken for additional current tables.

#### evidence_artifacts

| Column | Type | Notes |
|---|---|---|
| artifact_kind | TEXT | SCREENSHOT, HTML, PDF, RAW_JSON, TEXT, IMAGE, HTTP_METADATA, MANUAL_FILE, REPORT |
| object_key | TEXT unique | Opaque relative encrypted-vault key |
| original_filename | TEXT nullable | Sanitised; hidden by default |
| mime_type | TEXT | Verified |
| byte_size_plaintext | INTEGER | Limits/integrity |
| byte_size_ciphertext | INTEGER | Integrity |
| sha256_plaintext | TEXT | Deduplication/integrity, protected by SQLCipher |
| sha256_ciphertext | TEXT | Storage integrity |
| encryption_version | TEXT | Cipher/header format |
| key_version | INTEGER | Vault key generation |
| captured_at_us | INTEGER | UTC |
| capture_method | TEXT | PLAYWRIGHT, MANUAL_IMPORT, PROVIDER_API, GENERATED_REPORT |
| source_url | TEXT nullable | Provenance |
| http_status | INTEGER nullable | Provenance |
| redirect_chain_json | TEXT nullable | Sanitised chain |
| viewport_json | TEXT nullable | Screenshot context |
| query_task_id | TEXT nullable FK | Origin |
| immutable | INTEGER | True for originals |
| verification_state | TEXT | UNVERIFIED, VERIFIED, CORRUPT, MISSING |
| retention_state | TEXT | RETAINED, EXPIRING, LEGAL_HOLD, PURGE_PENDING |

#### evidence_derivations

Links original_artifact_id to derivative_artifact_id with operation REDACTION, OCR, THUMBNAIL, FORMAT_CONVERSION, or REPORT_RENDER; includes tool/version/configuration hash. A derivative cannot become an original.

#### finding_evidence

Links findings or finding versions to evidence with role SUPPORTS, CONTRADICTS, CONTEXT, or ORIGINAL_CAPTURE and an optional minimal excerpt.

### 5.9 Explainable attribution and impersonation target

The generic catalog below remains the broader design. Current `0007` persistence uses the `phase5_attribution_*` tables in section 1.3, a score range of -1000 to 1000, closed signal enums, and a separate append-only human decision chain.

#### scoring_models

Versioned Ariadne Core scoring configuration: model key, semantic version, weights JSON, threshold JSON, algorithm hash, status, and activation time. It contains configuration, not personal data.

#### attribution_assessments

| Column | Type | Notes |
|---|---|---|
| finding_id | TEXT FK | Claim under review |
| candidate_entity_id | TEXT nullable FK | Proposed identity |
| scoring_model_id | TEXT FK | Versioned model |
| score_micros | INTEGER | 0 to 1,000,000 |
| confidence_band | TEXT | Explainable band |
| recommended_state | TEXT | Narrow automated-recommendation enum only |
| requires_human_review | INTEGER | True for ownership/impersonation |
| missing_evidence_json | TEXT | Suggested next checks |
| assessed_at_us | INTEGER | Time |

A database CHECK excludes confirmed match/non-match, ownership, takeover, recycled-username, collision, mirror/repost, and impersonation classifications from recommended_state. Those values exist only in human attribution_decisions. Broker-derived assessments also enforce the provider policy’s independent-corroboration rule.

#### attribution_signals

| Column | Type | Notes |
|---|---|---|
| assessment_id | TEXT FK | Assessment |
| signal_type | TEXT | Exact email, chronology conflict, user exclusion, and other registered signals |
| polarity | TEXT | SUPPORTS, CONTRADICTS, NEUTRAL |
| weight_micros | INTEGER | Signed contribution |
| evidence_artifact_id | TEXT nullable FK | Evidence |
| entity_id | TEXT nullable FK | Source entity |
| finding_version_id | TEXT nullable FK | Source observation |
| explanation | TEXT | User-readable |
| deterministic | INTEGER | Distinguishes inference |

#### attribution_decisions

Append-only human decisions with classification, actor, reason, decided_at, supersedes_decision_id, and the assessment version reviewed. The service rejects conclusive automated actors.

#### impersonation_cases

| Column | Type | Notes |
|---|---|---|
| assessment_id | TEXT nullable FK | Trigger |
| claimed_entity_id | TEXT FK | Authorised profile identity |
| suspected_account_entity_id | TEXT nullable FK | Account under review |
| classification | TEXT | Historical/current ownership, takeover, recycled, collision, mirror/repost, possible/confirmed impersonation, unknown |
| state | TEXT | OPEN, INVESTIGATING, READY_FOR_REVIEW, CLOSED |
| caution_label | TEXT | Non-accusatory UI copy key |
| opened_at_us | INTEGER | Time |
| closed_at_us | INTEGER nullable | Time |
| graph_node_id | TEXT nullable unique | Optional graph representation |

#### impersonation_observations

Typed evidence dimensions: name use, photo use, employment/education use, relationship use, identity claim, post-ownership activity, immutable account ID, username history, prior ownership evidence, and confused-third-party reports. Each observation includes polarity, time, source, and evidence reference.

#### impersonation_decisions

Append-only case state and classification history with case_id, before/after state, before/after classification, actor, reason, decided_at_us, and supersedes_decision_id. impersonation_cases.current_decision_id points to the latest valid human decision; direct classification overwrites are prohibited.

#### ownership_periods

Explicit claimed ownership intervals for an account or username: case_id, account_entity_id, owner_entity_id, period_type CURRENT_OWNED, HISTORICAL_OWNED, SUSPECTED_TAKEOVER, or UNKNOWN, from_us, to_us, confidence, source kind, evidence_artifact_id, and decision_id. Open intervals are permitted, overlapping confirmed intervals are rejected unless a decision records shared ownership.

### 5.10 Diffing and remediation target

The generic catalog below remains the broader design. Current `0008` persistence uses the ten `phase6_*` tables in section 1.4 and derives comparisons from immutable snapshots instead of persisting the target `run_comparisons`/`finding_diffs` aggregates. Its remediation taxonomy is deliberately local-only and narrower than the target external workflow.

#### run_comparisons

| Column | Type | Notes |
|---|---|---|
| baseline_run_id | TEXT FK | Older run |
| current_run_id | TEXT FK | Newer run |
| comparison_version | TEXT | Algorithm |
| noise_rules_hash | TEXT | Reproducibility |
| baseline_coverage_hash | TEXT | Coverage/provider snapshot compatibility |
| current_coverage_hash | TEXT | Coverage/provider snapshot compatibility |
| coverage_compatibility | TEXT | COMPARABLE, PARTIAL, INCOMPATIBLE |
| limitation_snapshot_json | TEXT | Gaps that affect diff interpretation |
| state | TEXT | DRAFT, RUNNING, COMPLETE, PARTIAL, FAILED |
| completed_at_us | INTEGER nullable | Time |

#### finding_diffs

| Column | Type | Notes |
|---|---|---|
| comparison_id | TEXT FK | Parent |
| baseline_finding_id | TEXT nullable FK | Old |
| current_finding_id | TEXT nullable FK | New |
| diff_state | TEXT | Required diff taxonomy |
| changed_fields_json | TEXT | Structured diff, no dynamic noise |
| confidence_micros | INTEGER | Match confidence |
| reviewed_state | TEXT | UNREVIEWED, CONFIRMED, CORRECTED |

#### remediation_cases

| Column | Type | Notes |
|---|---|---|
| finding_id | TEXT nullable FK | Target |
| impersonation_case_id | TEXT nullable FK | Optional source case |
| action_type | TEXT | IGNORE, MONITOR, PRESERVE_EVIDENCE, DELETE_OWNED_ACCOUNT, CORRECT_SOURCE, GDPR_ERASURE, LOCAL_LAW_DELETION, DEINDEX, REPORT_IMPERSONATION, CONTACT_OWNER, ESCALATE, LEGALLY_PERSISTENT |
| state | TEXT | DRAFT, PLANNED, AWAITING_APPROVAL, SUBMITTED_MANUALLY, WAITING, APPEAL, COMPLETED, REJECTED, IMPOSSIBLE |
| jurisdiction_code | TEXT nullable | Relevant law/provider |
| legal_basis | TEXT nullable | User-entered; not legal advice |
| deadline_at_us | INTEGER nullable | Tracking |
| source_removed_at_us | INTEGER nullable | Outcome |
| index_removed_at_us | INTEGER nullable | Separate outcome |
| cache_persistence_state | TEXT | UNKNOWN, PRESENT, PARTIAL, CLEARED, REAPPEARED |
| cache_last_checked_at_us | INTEGER nullable | Monitoring freshness |
| reappeared_at_us | INTEGER nullable | Monitoring |
| graph_node_id | TEXT nullable unique | Optional graph representation |

#### remediation_events

Append-only timeline with event type, occurred time, provider response summary, template version, evidence link, deadline change, appeal state, and actor. Draft content is stored encrypted; no table or job automatically submits it.

### 5.11 Disclosure, cost, and errors

#### transmission_preflights

Persisted, local-only disclosure preview header.

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Bound profile or isolated run |
| provider_id | TEXT FK | Exact recipient |
| provider_policy_revision | INTEGER | Invalidated by policy change |
| purpose | TEXT | Exact purpose |
| jurisdiction_snapshot_json | TEXT | Operator, hosting, and processing shown |
| retention_snapshot | TEXT | Including UNKNOWN |
| paid_access_snapshot | TEXT | User/provider status shown |
| risk_snapshot_json | TEXT | Warnings and broker/corroboration policy |
| estimated_cost_micros | INTEGER | Preview |
| currency | TEXT | ISO 4217 |
| manifest_hmac | TEXT | Canonical header and items |
| created_at_us | INTEGER | Preview time |
| expires_at_us | INTEGER | Short-lived |
| invalidated_at_us | INTEGER nullable | Policy/input change |

#### transmission_preflight_items

One row per proposed payload. Exactly one of entity_id, entity_variant_id, or isolated_input_id is populated, with disclosure_mode, masked display, payload_hmac, sensitivity, allowed, denial_code, and per-item warning codes. Item IDs are opaque and are what the UI approves; payload HMACs never need to leave the core.

#### transmission_approval_sets

Human approval of a persisted preflight manifest.

| Column | Type | Notes |
|---|---|---|
| preflight_id | TEXT FK | Exact preview |
| manifest_hmac | TEXT | Must still match preflight |
| approved_by | TEXT | LOCAL_USER for sensitive disclosure |
| approved_at_us | INTEGER | Time |
| expires_at_us | INTEGER | Cannot outlive preflight/policy |
| revoked_at_us | INTEGER nullable | Revocation |
| invalidation_reason | TEXT nullable | Policy, input, authority, or jurisdiction change |

#### transmission_approval_items

One row per accepted preflight item: approval_set_id, preflight_item_id unique, use_limit, use_count, first_used_at_us, and last_used_at_us. Unaccepted or policy-denied items have no row. Use counts are consumed atomically.

#### search_task_approvals

Many-to-many binding between a search task and every transmission_approval_item it consumes. The task’s selected input set and the approval-item set must match exactly. This replaces the former singular approval_id assumption.

#### transmission_ledger

One mutable attempt header per actual or denied provider dispatch; append-only transmission_events are authoritative history.

| Column | Type | Notes |
|---|---|---|
| search_task_id | TEXT nullable FK | Task |
| provider_id | TEXT FK | Intended recipient |
| approval_set_id | TEXT nullable FK | Null only when policy needs no approval |
| purpose | TEXT | Bound purpose |
| jurisdiction_snapshot_json | TEXT | At attempt time |
| attempted_at_us | INTEGER | Always present |
| sent_at_us | INTEGER nullable | Null when nothing left the device |
| completed_at_us | INTEGER nullable | Terminal provider outcome |
| current_outcome | TEXT | PREPARED, DENIED_BY_POLICY, CANCELLED, FAILED_BEFORE_SEND, SENT, PROVIDER_ACCEPTED, PROVIDER_REJECTED, RESPONSE_FAILED |
| provider_request_id | TEXT nullable | Sanitised |
| bytes_sent | INTEGER nullable | Null before send |
| bytes_received | INTEGER nullable | Cost/collection transparency |

#### transmission_attempt_items

Joins a transmission_ledger attempt to each approval item or policy-safe public input, recording masked display, payload class, payload_hmac, and sensitivity. It never duplicates plaintext.

#### transmission_events

Append-only lifecycle rows with attempt_id, sequence, event_type, occurred_at_us, redacted error_code, provider status, bytes counters, and event metadata. SENT and a later PROVIDER_ACCEPTED are two events for one attempt, never two disclosures.

Denied or failed-before-send attempts have attempted_at_us but no sent_at_us. They remain visible without implying transmission.

#### api_usage

Provider, audit run, task, request count, response bytes, rate-limit counters, estimated/actual cost micros, currency, billable status, and observation time. No query value or raw provider body.

#### errors

Structured, redacted errors.

| Column | Type | Notes |
|---|---|---|
| job_id | TEXT nullable FK | Context |
| provider_id | TEXT nullable FK | Context |
| error_code | TEXT | Stable taxonomy |
| category | TEXT | VALIDATION, POLICY, NETWORK, PROVIDER, PARSER, STORAGE, CRYPTO, INTERNAL |
| retryable | INTEGER | Scheduler input |
| user_message_key | TEXT | Localised safe message |
| diagnostic_json | TEXT | Allowlisted non-sensitive fields |
| fingerprint | TEXT | Deduplicates without raw message |
| occurred_at_us | INTEGER | Time |
| resolved_at_us | INTEGER nullable | Resolution |

### 5.12 Reports, annotations, and audit history

#### reports

| Column | Type | Notes |
|---|---|---|
| audit_run_id | TEXT FK | Source |
| report_type | TEXT | FULL, REDACTED, COVERAGE, EVIDENCE_MANIFEST, REMEDIATION |
| redaction_mode | TEXT | REDACTED_DEFAULT, CUSTOM, FULL_EXPLICIT |
| schema_version | INTEGER | Reproducible |
| inclusion_manifest_json | TEXT | Exact typed object/version inclusion set |
| inclusion_manifest_hmac | TEXT | Approval and idempotency binding |
| source_revisions_json | TEXT | Finding, note, evidence, coverage, and policy revisions |
| redaction_policy_revision | INTEGER | Invalidates stale preview/approval |
| state | TEXT | DRAFT, PREVIEW_READY, APPROVED, RENDERING, READY, FAILED, PURGED |
| limitation_snapshot | TEXT | Always included for audit reports |
| current_approval_id | TEXT nullable FK | Required before rendering full report |
| invalidated_at_us | INTEGER nullable | Source or policy change |
| invalidation_reason | TEXT nullable | Stable code |

#### report_approvals

Append-only approval rows with report_id, inclusion_manifest_hmac, source_revisions_hmac, redaction_policy_revision, actor LOCAL_USER, approved_at_us, expires_at_us, invalidated_at_us, and invalidation_reason. Rendering compares all bindings in the same transaction that creates the report job.

#### report_artifacts

Joins report to generated encrypted evidence artifact, format, checksum, size, destination class, and export time. Unencrypted destinations are user-owned and are never silently duplicated.

#### tags and object_tags

Tags are profile-scoped labels with name, colour token, and description. object_tags links tags to allowlisted target types and IDs. Database triggers validate target existence and identical vault/profile scope.

#### notes and note_revisions

Notes have an allowlisted target type/ID, sensitivity, current_revision_id, and author. note_revisions are append-only content snapshots. Imported active content is never rendered; Markdown is parsed through a strict sanitiser.

#### audit_events

Append-only security and product event log:

| Column | Type | Notes |
|---|---|---|
| event_type | TEXT | Allowlisted event |
| actor_type | TEXT | LOCAL_USER, SYSTEM, WORKER, LOCAL_MODEL |
| actor_id | TEXT nullable | Stable local identifier |
| target_type | TEXT | Allowlisted domain type |
| target_id | TEXT nullable | Stable ID |
| before_digest | TEXT nullable | Digest, not a value |
| after_digest | TEXT nullable | Digest, not a value |
| metadata_json | TEXT | Allowlisted, redacted |
| occurred_at_us | INTEGER | Monotonic ordering uses id as tie-breaker |
| previous_event_hash | TEXT nullable | Optional local tamper-evident chain |
| event_hash | TEXT | Hash of canonical event form |

Audit hashes make later modification detectable; they do not protect against a fully compromised unlocked process.

#### event_stream_sessions

Defines a replay sequence namespace with id, vault_id, started_at_us, closed_at_us, next_sequence, minimum_retained_sequence, and contract_version. It is VAULT scoped and contains no subject values.

#### event_outbox

Transactional, redacted event records:

| Column | Type | Notes |
|---|---|---|
| stream_session_id | TEXT FK | Sequence namespace |
| sequence | INTEGER | Unique and monotonic within session |
| event_id | TEXT unique | Client dedupe |
| event_type | TEXT | Closed generated union |
| scope_kind | TEXT | VAULT, PROFILE, ISOLATED_RUN |
| profile_id | TEXT nullable FK | Profile scope |
| scope_audit_run_id | TEXT nullable FK | Isolated scope |
| resource_type | TEXT nullable | Refetch target |
| resource_id | TEXT nullable | Refetch target |
| resource_revision | INTEGER nullable | Gap reconciliation |
| payload_json | TEXT | Event-schema validated and redacted |
| created_at_us | INTEGER | Commit time |
| published_at_us | INTEGER nullable | First relay |
| expires_at_us | INTEGER | Bounded replay retention |

Resource mutation and outbox insert occur in the same SQLite transaction. Relay acknowledgement never deletes immediately; retention advances minimum_retained_sequence only after the configured replay window. Audit events remain the long-lived accountability log and are not used as a substitute for the event outbox.

#### backup_records

backup_records tracks encrypted backup bundle version, destination class,
ciphertext hash, backup-key version, the non-secret 96-bit envelope nonce,
declared plaintext/ciphertext sizes, creation/verification/restore times,
retention expiry, and state. A unique index on vault, backup-key version, and
nonce reserves a nonce even when creation fails, preventing reuse. It never
stores key bytes or the destination absolute path in routine logs. Phase 2
records also enforce the bounded AES-256-GCM envelope defined by ADR-002.

## 6. Required indexes and constraints

At minimum:

- Foreign keys enabled for every connection; defer only the documented cyclic current-state pointers.
- UNIQUE(vault_id, id) on every scoped parent, plus matching UNIQUE(vault_id, profile_id, id) or UNIQUE(vault_id, scope_audit_run_id, id) on subject parents; every child uses the matching composite foreign key.
- entities: profile_id, entity_type, value_hmac; review_state; sensitivity; temporal bounds.
- entity_variants: entity_id, rank and entity_id, value_hmac.
- graph_edges: from_node_id, edge_type; to_node_id, edge_type; observed_at_us.
- graph_edge_origins: unique edge/observation_hmac; edge/created_at_us; composite source/segment/run scope.
- providers: provider_key unique; jurisdictions by provider and effective period.
- jobs: state, scheduled_at_us, priority; lease_expires_at_us; audit_run_id, state.
- jobs: unique idempotency_record_id where it is not null.
- idempotency_records: unique vault/actor/route/key_hmac; state and expires_at_us.
- search_tasks: provider_id, check_outcome; query_hmac; search_plan_id.
- coverage_records: unique run/provider/capability/query_class/jurisdiction cell; coverage_outcome_counts unique cell/outcome.
- raw_results: unique task/ordinal; source_url_hmac; retention_expires_at_us.
- findings: run and check_outcome; canonical_key_hmac; last_observed_at_us.
- finding_versions: unique finding/version number; content_hash.
- evidence_artifacts: object_key unique; sha256_plaintext; retention state.
- transmission_ledger: provider/attempted time, provider/sent time, task, and current outcome.
- transmission_preflights: provider/run/expiry and manifest_hmac; approval items unique approval-set/preflight-item; ledger by attempted_at_us and sent_at_us.
- event_outbox: unique stream-session/sequence and event_id; expiry and unpublished rows.
- backup_records: unique vault/backup-key-version/nonce; state, retention expiry, and ciphertext hash.
- phase6_audit_snapshots: unique vault/profile/run, sequence, and capture time; timeline by profile/sequence/time; child findings/coverage ordered and profile-bound.
- phase6_remediation_revisions: unique vault/profile/case/revision; latest case and status/update-time indexes; child findings/evidence/responses/history bound to the exact complete revision.
- remediation_cases: state, deadline; finding; reappearance time.
- audit_events: occurred_at_us, id and target type/ID.

CHECK constraints enforce micro-probabilities from 0 through 1,000,000; non-negative sizes and costs; valid time ranges; exactly-one subject scope; exactly-one provenance source pointer where specified; non-RESTRICTED entities, isolated inputs, and tasks; narrow automated recommendations; and terminal-state timing requirements. Coverage completion and preflight/approval/task manifest equality use transaction-time triggers plus service assertions and are exercised directly in database tests.

Any semantic uniqueness key containing a nullable column uses exhaustive
partial unique indexes or a validated non-null normalised key. An ordinary
SQLite UNIQUE constraint containing nullable columns is never treated as
sufficient. Migration tests insert every null/non-null branch directly and
prove the intended duplicate is rejected.

Delete actions default to RESTRICT for immutable evidence, decisions, transmissions, and audit events. Temporary parse segments and unstarted plans may cascade only through an explicit service transaction. A purge job enumerates and verifies all dependent rows and artifacts before deleting the vault key.

## 7. Full-text search

SQLite FTS5 is a derived index, never the source of truth.

- entity_search_fts indexes only locally approved PUBLIC or SENSITIVE entity display/canonical fields.
- finding_search_fts indexes sanitised titles and selected observed fields.
- note_search_fts follows note sensitivity and profile scope.
- HIGHLY_SENSITIVE indexing is off by default.
- RESTRICTED, raw connector bodies, raw HTML, query text, transmission payloads, and evidence bytes are never indexed.
- FTS rows are rebuilt from source rows after restore or key rotation and are included inside SQLCipher.
- Every search repository call includes vault plus the explicit profile or isolated-run scope before returning results.

## 8. Transaction and concurrency model

SQLite runs in WAL mode only after the packaging spike proves the required fixed SQLite build and SQLCipher combination. The core service uses:

- One serialized writer queue.
- A bounded read pool.
- Short transactions.
- BEGIN IMMEDIATE for job lease, approval-use increment, and current-decision swaps.
- Compare-and-swap on revision for interactive edits.
- Savepoints for batch normalisation.
- Idempotency keys for job creation, evidence capture, report rendering, and external task dispatch.

The canonical request digest and HMAC of each client idempotency key are stored
in `idempotency_records`; raw keys are memory-only. Job creation keeps its
idempotency record, job, and initial outbox event in one transaction. Phase 3
interactive side effects first durably reserve a deterministic resource ID,
then persist a safe result for replay: a crash before completion leaves a
bounded 60-second ambiguity window, while completed results replay for 24 hours.
File retry digests safe file metadata and content hash without storing bytes in
the idempotency record.

Provider I/O and artifact encryption happen outside write transactions. Metadata is committed atomically only after the encrypted artifact has been fsynced and verified. Crash recovery reconciles orphan encrypted objects and missing rows without exposing plaintext.

## 9. Migration, backup, and verification

Alembic migrations are forward-only in release builds and run after an encrypted pre-migration backup. Startup verifies:

1. SQLCipher is active rather than silently opening plaintext SQLite.
2. SQLite is the approved fixed version.
3. Foreign keys, WAL policy, secure temp directory, and busy timeout are active.
4. Schema and vault format versions are compatible.
5. Evidence key version and object headers are supported.
6. Integrity check and a sample artifact authentication check succeed.

Tests must cover migrations from every supported release, locked-vault failure, WAL and temporary-file plaintext scans, bit-flipped evidence, interrupted writes, job recovery, approval races, cross-profile queries, purge, encrypted backup restore, and FTS rebuild.

The verified Phase 3 migration tests upgrade encrypted `0001`/`0002` vaults through `0003_intake_identity_graph` and `0004_decision_policy` to `0005_graph_edge_origins`. They preserve honest nullable decision history, backfill only verifiable joint edge origins, fail closed for an unverifiable live legacy edge, and passed aggregate/frozen UDS verification at `0005`.

The preserved `0006` migration tests extend that path through the six Phase 4 tables and remain paired with their own aggregate/frozen/package identities. Verified `0007` migration tests add the nine-table immutable profile-scoped Phase 5 cut, encrypted-repository requirement, cross-profile rejection, dedup/link integrity, assessment evidence linkage, and append-only decision revisions; its separately identified frozen PyInstaller UDS/package evidence passes under its own identities.

Current migration tests retain source head `0008_phase6_audit_remediation`, require exactly the ten Phase 6 tables, and cover forward `0007` → `0008` migration, immutable and bounded snapshot/remediation storage, canonical payload replay, full selected-run lifecycle intervals, exact revision/history continuity, stale CAS, and cross-profile references. The historical 40-operation frozen UDS/package proof passes under its own identities. The five newer routes add no migration; their replacement package proof remains pending. No historical `0005`, `0006`, `0007`, or 37-/40-operation `0008` hash is reused.

## 10. Retention and minimisation

- Raw intake and provider bodies expire quickly unless the user selects evidence preservation.
- Findings retain the minimum content required for provenance and comparison.
- False positives retain only an exclusion fingerprint, classification, and enough provenance to prevent rediscovery.
- Highly sensitive values and biometric derivatives receive shorter configurable retention.
- Provider transmissions, coverage, and human decisions remain while their run exists because they are necessary for reproducibility and accountability.
- Target durable full and redacted reports are separate artifacts with separate retention. Current source returns one selected in-memory JSON/Markdown artifact and persists neither report nor retention metadata.
- Connector revocation removes the Keychain token and marks local connector metadata revoked.
- Purging a profile cannot cascade into another profile. Cross-profile graph edges are prohibited, and purge tests must preserve that invariant.

## 11. Open implementation decisions

These are intentionally deferred to later ADRs and spikes:

1. Migration from bounded `0007` SQLCipher evidence BLOBs to an authenticated streaming object format, including XChaCha20-Poly1305 versus AES-256-GCM and its key-rotation envelope.
2. Whether selected highly sensitive entity fields receive application-layer field encryption in addition to SQLCipher.
3. Final FTS tokenisers and language strategy.
4. Practical graph limits beyond the implemented 500-node/2,000-edge API cap.
5. Tamper-evident audit-event chaining and optional local signing key.
6. Streaming/portable large-vault backup, evidence-object inclusion, cross-device key recovery, and physical-erasure guidance beyond the bounded Phase 2 envelope in ADR-002.
7. Migration from the current bounded browser-mediated selected-file bytes to opaque native broker handles before real-data intake.

No deferred choice relaxes the invariants in section 2.
