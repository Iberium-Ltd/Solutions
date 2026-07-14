# Codename Ariadne — Typed Local API

- Status: target contract plus implemented 48-operation/46-path local candidate; full aggregate and native package verification passed, production release verification pending
- Date: 2026-07-14
- Contract source: Python 3.12, FastAPI, Pydantic 2, OpenAPI 3.1, generated TypeScript
- Scope: planned full API plus generated foundation, intake/identity, local/optional OpenAI reasoning, query planning, public/HIBP discovery and capture, evidence/attribution, monitoring/remediation, and reporting surface

## 1. Boundary and goals

The local API is the only domain boundary between the privileged desktop shell and Ariadne Core. It supports the Phase 1 UI contract without allowing the webview to contact external providers, open arbitrary files, hold secrets, or read the database.

The API must:

- Be strongly typed and versioned.
- Work over a private local transport only.
- Keep provider access, filesystem access, secrets, decryption, and policy checks outside the webview.
- Make long-running operations durable, observable, cancellable, and idempotent.
- Bind sensitive provider disclosure to an exact user approval.
- Stream redacted state changes without treating the stream as the source of truth.
- Preserve check outcome, attribution, visibility, confidence, sensitivity, provenance, and time as separate values.
- Never represent provider failure, blockage, or missing coverage as non-existence.

All examples are synthetic and use reserved invalid domains.

## 2. Runtime transport

### 2.1 Packaged application

~~~text
React / WKWebView
  → typed Tauri command
  → Rust capability and session boundary
  → 0600 Unix-domain socket
  → FastAPI / Ariadne Core
  → SQLCipher and encrypted evidence vault
~~~

The webview never receives the Unix socket path or service credential. Generated TypeScript invokes generated route-specific wrappers. Rust accepts only method/route pairs present in a compile-time generated allowlist that binds request schema hash, response schema hash, maximum sizes, required lock state, scope class, reveal class, and authorization class. Unknown paths, method substitution, arbitrary headers, and payloads that fail the bound schema are rejected before proxying. A single unconstrained generic invoke is prohibited. Rust attaches the authenticated local session and relays accepted results; events travel back through a dedicated Tauri event channel.

The core binds no TCP port in a packaged build. Provider traffic is initiated only by policy-checked adapter workers, never by the webview.

### 2.2 Development mode

Development may use a random loopback port with all of the following:

- Bind to 127.0.0.1 and the IPv6 loopback only; never a LAN interface.
- A high-entropy per-launch bearer held outside frontend storage.
- Exact Origin and Host allowlists; no wildcard CORS.
- An authenticated WebSocket with the same session.
- Short session expiry and replay protection.
- FastAPI interactive documentation disabled unless an explicit development flag is active.

The loopback mode is not a release fallback.

### 2.3 Versioning

The logical prefix is /v1. Additive fields and event variants are allowed within v1. Removing fields, changing meanings, weakening privacy defaults, or changing state transitions requires /v2 or a negotiated contract version.

The service exposes its versions through GET /v1/system/capabilities. The shell refuses an incompatible sidecar before opening a vault.

## 3. Contract generation

Pydantic models are authoritative. FastAPI generates OpenAPI 3.1, and a pinned generator creates:

- TypeScript request and response types.
- A typed route client used only by the Tauri bridge.
- JSON Schemas for persisted manifests and plugin-free adapter contracts.
- Zod adapters for immediate form feedback where useful.

Generated files are checked for drift in CI. Handwritten TypeScript may narrow presentation state but may not redefine service payloads. OpenAPI snapshots use synthetic schemas only and contain no runtime examples, tokens, local paths, or personal values.

### 3.1 Implemented current candidate boundary

The generated source contract contains **48 operations (4 GET, 44 POST; 46 distinct paths)**: six foundation routes, eight Phase 3/profile routes, six AI routes, three query-planning routes, five discovery routes, six Phase 5 routes, thirteen Phase 6 routes, and one reporting route. Contract generation, the complete Python/Rust/privacy aggregate, frontend typecheck/lint/build plus 143/143 tests across 36 files, frozen/staged inspection, and the local packaged lifecycle pass. Current identities are `5ca6b790…` staged, `4ba7fd0…` packaged-sidecar, and `ca68fdd4…` desktop. The historical 45-/40-/37-operation and `0005`/`0006`/`0007` identities remain separate and are not relabelled. This is local ad-hoc package proof, not production release approval. The remainder of this document is the broader target API and must not be read as implemented.

| Method and path | Request → response | Scope and boundary |
|---|---|---|
| `GET /v1/system/capabilities` | none → `SystemCapabilities` | launch session; any lock state |
| `GET /v1/session` | none → `SessionState` | launch session; any lock state |
| `POST /v1/events/replay` | `EventReplayRequest` → `EventReplayResult` | shell-internal; unlocked vault |
| `POST /v1/vaults` | `VaultCreateRequest` → `VaultLifecycleResult` | Keychain user gesture; no vault |
| `POST /v1/vaults/current/unlock` | `VaultUnlockRequest` → `VaultLifecycleResult` | Keychain user gesture; locked vault |
| `POST /v1/vaults/current/lock` | none → `VaultLifecycleResult` | user gesture; unlocked vault |
| `GET /v1/profiles` | none → `ProfileListResult` | vault; unlocked; shell-internal bounded resume list |
| `POST /v1/profiles` | `ProfileCreateRequest` → `ProfileSummary` | vault; unlocked; idempotent |
| `POST /v1/intake/paste` | `PasteIntakeRequest` → `IntakeReceipt` | profile; unlocked; consent; idempotent |
| `POST /v1/intake/file` | `FileIntakeRequest` → `IntakeReceipt` | profile; unlocked; file-picker gesture; idempotent |
| `POST /v1/intake/review` | `EntityReviewRequest` → `EntityReviewResult` | profile; unlocked; maximum 100 entities |
| `POST /v1/entities/decision` | `EntityDecisionRequest` → `EntitySummary` | profile; unlocked; idempotent revision CAS |
| `POST /v1/entities/origins` | `EntityOriginPageRequest` → `EntityOriginPageResult` | profile; unlocked; user gesture; stable exact-source pagination; at most 12 origins per page |
| `POST /v1/graph/snapshot` | `GraphSnapshotRequest` → `GraphSnapshot` | profile; unlocked; at most 500 nodes/250 edges; bounded evidence samples |
| `GET /v1/local-ai/settings` | none → `LocalAISettings` | vault; unlocked; endpoint/model settings only |
| `POST /v1/local-ai/settings` | `LocalAISettingsUpdateRequest` → `LocalAISettings` | vault; unlocked; expected-revision CAS |
| `POST /v1/local-ai/models` | `LocalAIEndpointRequest` → `LocalAIModelDiscoveryResult` | vault; unlocked; exact loopback endpoint |
| `POST /v1/local-ai/test` | `LocalAIEndpointRequest` → `LocalAIConnectionResult` | vault; unlocked; bounded loopback probe |
| `POST /v1/local-ai/corpus/analyze` | `LocalCorpusAIRequest` → `LocalCorpusAIResult` | profile; unlocked; user gesture; 1–20 hash-bound documents; deterministic, local model, or explicit OpenAI Responses; exact document/segment citations |
| `POST /v1/local-ai/workspace/analyze` | `LocalAIWorkspaceRequest` → `LocalAIWorkspaceResult` | profile; unlocked; user gesture; selected bounded scopes; deterministic, local model, or explicit OpenAI Responses; exact workspace-source citations; no raw evidence bytes |
| `POST /v1/query/providers` | `ProviderCatalogRequest` → `ProviderCatalogResult` | profile; unlocked; network-free local catalog only |
| `POST /v1/query/plans` | `QueryPlanRequest` → `QueryPlanResult` | profile; unlocked; persisted cells/budgets; no dispatch |
| `POST /v1/query/dry-run` | `QueryDryRunRequest` → `QueryPlanCell` | profile; unlocked; exact run/check/revision; local dry run only |
| `POST /v1/discovery/public/search` | `PublicDiscoverySearchRequest` → `PublicDiscoverySearchResult` | any lock state; user gesture; explicit self-audit authorization; DuckDuckGo HTML or GitHub users; at most 25 exact results |
| `POST /v1/discovery/public/capture` | `PublicDiscoveryCaptureRequest` → `PublicDiscoveryCaptureResult` | profile; unlocked; user gesture; atomic exact-URL artifact/finding/neutral-assessment capture; local encrypted persistence |
| `POST /v1/discovery/hibp/account` | `HibpAccountRequest` → `HibpAccountResult` | any lock state; user gesture; explicit self-audit; ephemeral HIBP key; k-anonymity or separately authorised direct email transmission; exact official sources |
| `POST /v1/discovery/hibp/domain` | `HibpDomainRequest` → `HibpDomainResult` | any lock state; user gesture; explicit self-audit; ephemeral HIBP key; provider-verified domain prerequisite; exact official sources |
| `POST /v1/discovery/investigation/plan` | `InvestigationPlanCompileRequest` → `InvestigationPlanResult` | any lock state; user gesture; at most 32 identifiers; deterministic route/prerequisite plan; executes no provider request |
| `POST /v1/phase5/findings/manual` | `Phase5ManualFindingCreateRequest` → `Phase5FindingDetailResult` | profile; unlocked; user gesture; atomic manual finding plus neutral initial assessment; no evidence/network |
| `POST /v1/phase5/findings/list` | `Phase5FindingListRequest` → `Phase5FindingListResult` | profile; unlocked; at most 100 persisted findings; metadata only |
| `POST /v1/phase5/findings/detail` | `Phase5FindingDetailRequest` → `Phase5FindingDetailResult` | profile; unlocked; bounded assessment, decision, and at most 64 artifact metadata records; no evidence bytes |
| `POST /v1/phase5/evidence/manual-import` | `Phase5ManualEvidenceImportRequest` → `Phase5ManualEvidenceImportResult` | profile; unlocked; user gesture; bounded canonical base64 and manual kind; local SQLCipher only |
| `POST /v1/phase5/evidence/redacted-derivative` | `Phase5RedactedDerivativeRequest` → `Phase5RedactedDerivativeResult` | profile; unlocked; user gesture; caller explicitly confirms supplied bytes are already redacted; local only |
| `POST /v1/phase5/attribution/decision` | `Phase5AttributionDecisionRequest` → `Phase5AttributionDecisionResult` | profile; unlocked; user gesture; exact assessment and expected previous decision/revision |
| `POST /v1/phase6/audits/local-checkpoint` | `Phase6LocalCheckpointRequest` → `Phase6LocalCheckpointResult` | profile; unlocked; user gesture; explicit coverage; contentless Phase 5 projection; no provider/network execution |
| `POST /v1/phase6/audits/list` | `Phase6AuditRunListRequest` → `Phase6AuditRunListResult` | profile; unlocked; at most 32 persisted snapshot summaries |
| `POST /v1/phase6/audits/compare` | `Phase6CompareRunsRequest` → `Phase6ComparisonResult` | profile; unlocked; ordered baseline/current; complete persisted interval retained for lifecycle |
| `POST /v1/phase6/remediation/list` | `Phase6RemediationListRequest` → `Phase6RemediationListResult` | profile; unlocked; at most 100 latest case summaries |
| `POST /v1/phase6/remediation/detail` | `Phase6RemediationDetailRequest` → `Phase6RemediationDetailResult` | profile; unlocked; bounded complete revision/history projection |
| `POST /v1/phase6/remediation/create` | `Phase6RemediationCreateRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; same-profile findings/evidence; local record only |
| `POST /v1/phase6/remediation/draft` | `Phase6RemediationDraftUpdateRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; expected-revision CAS |
| `POST /v1/phase6/remediation/require-approval` | `Phase6RemediationRequireApprovalRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; marks explicit approval required but sends nothing |
| `POST /v1/phase6/remediation/status` | `Phase6RemediationStatusTransitionRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; closed transition matrix and revision CAS |
| `POST /v1/phase6/remediation/deadline` | `Phase6RemediationDeadlineUpdateRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; set/clear future local deadline with revision CAS |
| `POST /v1/phase6/remediation/evidence` | `Phase6RemediationEvidenceLinkRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; same-profile immutable evidence references |
| `POST /v1/phase6/remediation/provider-response` | `Phase6RemediationProviderResponseRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; records a bounded local response summary; performs no provider I/O |
| `POST /v1/phase6/remediation/reappearance` | `Phase6RemediationReappearanceRequest` → `Phase6RemediationDetailResult` | profile; unlocked; user gesture; same-profile finding/evidence; revision CAS |
| `POST /v1/reports/generate` | `ReportGenerateRequest` → `ReportGenerateResult` | profile; unlocked; selected ordered runs; JSON/Markdown; REDACTED or approval-bound FULL_EXPLICIT; one in-memory artifact; local only |

All 48 method/path operations (46 distinct paths) carry generated request/response byte caps, exact lock state, scope class, reveal class, and authorization class. Rust permits only this generated route allowlist and independently validates profile, entity-origin, Graph, AI, query, discovery/HIBP/planner, Phase 5, Phase 6, and reporting payloads before exposing data to Tauri.

The four implemented Phase 3 side effects use durable vault-keyed idempotency records. The raw key is memory-only; the database stores its HMAC, a canonical request digest, reservation state, safe response JSON, and expiry. A digest mismatch conflicts, a completed result replays for 24 hours, and a reservation interrupted before completion remains ambiguous for at most 60 seconds. File retry binds the digest to metadata/hash rather than retaining file bytes. The webview keeps retry keys only in memory, so reload cannot automatically resume an earlier key.

Entity decisions preserve exact before/after review, sensitivity, temporal, search, and transmission policies, including lossless `LOCAL_ONLY`. False-positive/excluded entities must deny both search and transmission; highly-sensitive entities cannot be search-allowed or provider-allowlisted. Repository checks and database triggers enforce the same rule. The optional free-form reason is reduced to a keyed opaque code for persistence; human-readable reason history is not implemented. Graph snapshots omit rejected/excluded entities and their incident edges while retaining the underlying audit/provenance rows.

Every returned graph edge has verifiable source-scoped evidence. Each observation links to its intake source, segment ordinal, extraction run, disposition, span where available, timestamp, confidence, origin type, and explanation. Entity summaries return a bounded origin sample, while `POST /v1/entities/origins` exposes the complete stable origin set in profile-scoped pages of at most 12. Exact reprocessing deduplicates by keyed HMAC, but separate sources remain separate provenance.

AI routes retain loopback-only validation for Ollama and OpenAI-compatible local endpoints and never expose prompt text in settings/model/test responses. Corpus and workspace analysis support `SUMMARY`, `ORGANIZE`, `QUESTION`, `CONNECTIONS`, and `GAP_ANALYSIS` using deterministic execution, an explicitly selected local model such as Qwen, or optional OpenAI Responses. OpenAI execution requires a request-ephemeral `writeOnly` key and an explicit arbitrary model ID, calls the official Responses endpoint with `store: false`, and validates strict structured output before remapping citations to the bounded source catalog. The key is not a persisted setting. Each result is review-only and exposes exact source citations, included/available counts, projection truncation, fallback state, hashes, provider/model identity, and whether external network was used. Invalid or unsupported citations are rejected or removed; a model cannot create evidence, approve disclosure, or take an action. Automated provider/citation coverage passes, but no real paid-key live test is claimed.

The fixed external AI endpoint is `https://api.openai.com/v1/responses`; it is not caller-configurable.

The query-planning catalog remains deliberately network-free. Every returned query provider must be local-only, enabled, regionless, non-external, and unable to access a network or send identifiers. Discovery is a separate, narrow boundary: public search requires explicit self-audit authorization, supports only DuckDuckGo HTML and unauthenticated GitHub-user search, retains exact result source metadata, and fails honestly on access challenges or provider errors.

HIBP account/domain operations use official provider endpoints and an ephemeral API key. Account mode is either `K_ANONYMITY` or `DIRECT`; direct mode additionally requires explicit exact-identifier transmission authorization, while domain enumeration retains HIBP's verified-domain prerequisite. Provider attribution, official source URLs, upstream state/reason, and human-review flags remain in the response. A direct official synthetic smoke returned `SUCCEEDED`/`COMPLETE`, HTTP 200, and one exact breach source. A public test key received HTTP 401 from the official k-anonymity endpoint because the capability is plan/subscription gated; no successful k-anonymity result is claimed.

Investigation-plan compilation accepts at most 32 bounded identifier references and creates deterministic, non-executing steps for public search and HIBP. Every step names the exact route, provider, operation, transmission class, order, identifier hash/reference, and prerequisites. Compilation never contacts a provider. Fixed manual portals are user-opened references. The desktop's advanced query composer is local presentation logic, not a 49th API operation: it shows the exact structured/raw query, creates user-opened browser handoffs, and can load the query into the existing bounded DuckDuckGo form without scraping or importing evidence. No discovery surface bypasses authentication, CAPTCHA, paywalls, rate limits, plan requirements, or provider verification.

At `0007`, the Phase 5 repositories are SQLCipher-required and profile-scoped. Listing returns bounded finding summaries and pagination state. Detail returns the latest versioned assessment, supporting/contradicting artifact IDs, missing and recommended evidence, optional latest human decision, and bounded artifact provenance/integrity metadata. It never returns stored evidence bytes or converts a score into a human state. `0008` adds manual-local import, caller-confirmed redacted derivatives, append-only human decisions, and bounded manual finding plus neutral initial-assessment creation. The current source additionally captures one explicitly reviewed public result atomically as an exact-URL `URL_REFERENCE` artifact, finding, neutral assessment, and link. The response binds the literal URL to its SHA-256, stores only a keyed query reference, and rolls back every partial-failure boundary. Operational assessment recalculation, evidence streaming/viewing, retention/purge, and broader adapter ingestion remain target work.

The historical 40-operation package and current source contain thirteen Phase 6 routes that project or append encrypted, profile-scoped snapshots/remediation revisions. The thirteenth route, after a user gesture, automatically materialises a snapshot from bounded contentless Phase 5 state and explicit provider coverage. It hashes finding/evidence/derivative/assessment/decision metadata, allocates monotonic server sequence/time plus a UUID, and performs no provider or network work. It is not scheduled/background ingestion. Audit comparison still rejects equal/reordered/cross-profile runs and retains the complete interval. Remediation responses return complete immutable revision/history; no route sends/submits/dispatches an action or contacts a provider.

`POST /v1/reports/generate` reads the exact profile plus selected baseline/current snapshots, bounded current findings and contentless evidence metadata, and latest remediation cases. It returns one UTF-8 `report.json` or `report.md` artifact and a two-descriptor manifest. Canonical JSON and inert Markdown are deterministic for a fixed server generation time. `FULL_EXPLICIT` includes exact source URLs, raw URL SHA-256 values, artifact/provider/run identifiers, capture metadata, and signal-to-artifact mappings under a separate approval UUID. `REDACTED` removes literal URLs and sensitive text while retaining hashes, opaque source identifiers, provenance mappings, and explicit removal markers. Both modes exclude evidence bytes and active content. The core performs no filesystem write, destination selection, network request, or outbound action, and rejects an API response above 1,000,000 bytes. The approval/report/artifact are not durable database rows yet.

## 4. Common protocol

### 4.1 Media and sizes

- JSON requests and responses use application/json; charset=utf-8.
- The target design sends evidence and report bytes through a brokered stream, not base64 JSON.
- The target uses a Tauri-native picker and short-lived `file_broker_token`, never an arbitrary path. The current Phase 3 intake exception accepts at most 1 MiB of canonical base64 selected through a browser file input; the Phase 5 manual-import/caller-redacted exception accepts at most 10 MiB. Python and Rust/frontend boundaries revalidate exact shapes, bounds, and encodings; intake binds a caller hash, while Phase 5 computes the immutable SHA-256 in the core. This keeps paths out of the API but transiently places raw bytes/base64 in webview and command-serialization memory; it is not the preferred real-data boundary.
- Paste, note, and draft bodies have explicit byte limits.
- Local report requests are capped at 1,024 bytes; each generated artifact is capped at 1 MiB and the returned API model is additionally capped at 1,000,000 serialised bytes.
- Batch endpoints have explicit item and total-byte limits.
- Imported HTML is returned only as sanitised text or as an encrypted artifact stream with a safe external viewer policy.

### 4.2 Headers and command metadata

| Name | Use |
|---|---|
| Ariadne-Contract-Version | Required client contract major |
| Ariadne-Request-Id | UUID generated by the shell; safe for diagnostics |
| Ariadne-Idempotency-Key | Required for job creation and side-effecting retries |
| If-Match | Expected integer revision for mutable resources |
| Ariadne-Session | Added by the shell; never visible to application JavaScript in packaged mode |
| Ariadne-Event-Cursor | Last processed event sequence during reconnect |

Headers are never used to carry personal values, provider query text, absolute paths, OAuth tokens, or evidence content.

### 4.3 Primitive and enum types

The TypeScript below is illustrative generated shape; Pydantic remains authoritative.

~~~ts
type UUID = string & { readonly __brand: "UUID" };
type RFC3339 = string & { readonly __brand: "RFC3339" };
type OpaqueCursor = string & { readonly __brand: "OpaqueCursor" };
type Revision = number & { readonly __brand: "Revision" };
type ProbabilityMicros = number & { readonly __brand: "ProbabilityMicros" };
type MoneyMicros = number & { readonly __brand: "MoneyMicros" };

type Sensitivity =
  | "PUBLIC"
  | "SENSITIVE"
  | "HIGHLY_SENSITIVE"
  | "RESTRICTED";

type CheckOutcome =
  | "FOUND"
  | "NOT_FOUND"
  | "NOT_CHECKED"
  | "CHECK_FAILED"
  | "ACCESS_BLOCKED"
  | "AUTH_REQUIRED"
  | "RATE_LIMITED"
  | "PROVIDER_UNAVAILABLE"
  | "AMBIGUOUS"
  | "MANUAL_REVIEW_REQUIRED"
  | "AUTHORITATIVE_ABSENCE";

type AttributionClassification =
  | "CONFIRMED_MATCH"
  | "CONFIRMED_NON_MATCH"
  | "PROBABLE"
  | "POSSIBLE"
  | "UNRESOLVED"
  | "NEEDS_MORE_EVIDENCE"
  | "HISTORICAL_OWNERSHIP"
  | "CURRENT_OWNERSHIP"
  | "ACCOUNT_TAKEOVER"
  | "RECYCLED_USERNAME"
  | "MIRROR_OR_REPOST"
  | "UNRELATED_COLLISION"
  | "POSSIBLE_IMPERSONATION"
  | "CONFIRMED_IMPERSONATION"
  | "UNKNOWN";

type AttributionRecommendation =
  | "PROBABLE"
  | "POSSIBLE"
  | "UNRESOLVED"
  | "NEEDS_MORE_EVIDENCE"
  | "UNKNOWN";

type JobState =
  | "DRAFT"
  | "QUEUED"
  | "WAITING_APPROVAL"
  | "RUNNING"
  | "PAUSE_REQUESTED"
  | "PAUSED"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "SUCCEEDED"
  | "PARTIAL"
  | "FAILED"
  | "BLOCKED";

interface Money {
  micros: MoneyMicros;
  currency: string;
}

interface ProtectedValue {
  display: string;
  sensitivity: Exclude<Sensitivity, "RESTRICTED">;
  revealable: boolean;
}

type SafeDisplayArg =
  | { key: "count"; integerValue: number }
  | { key: "durationMs"; integerValue: number }
  | { key: "provider"; resourceId: UUID }
  | { key: "resource"; resourceId: UUID }
  | { key: "catalogCode"; catalogCode: string };

interface SafeMessage {
  messageCode: string;
  args: SafeDisplayArg[];
}

type ResourceScope =
  | { kind: "VAULT" }
  | { kind: "PROFILE"; profileId: UUID }
  | { kind: "ISOLATED_RUN"; auditRunId: UUID };

interface ResourceMeta {
  id: UUID;
  vaultId: UUID;
  scope: ResourceScope;
  createdAt: RFC3339;
  updatedAt: RFC3339;
  revision: Revision;
}

interface Page<T> {
  items: T[];
  nextCursor?: OpaqueCursor;
  totalEstimate?: number;
}
~~~

ProbabilityMicros is an integer from 0 through 1,000,000. Currency is an ISO 4217 code. RESTRICTED is accepted only by quarantine-specific schemas and is impossible in entity, graph, query, adapter, event, report, or model-input schemas. SafeMessage.messageCode, catalogCode, and each permitted argument shape are generated from a closed application catalog; provider/model text cannot become a display argument.

### 4.4 Success and asynchronous responses

Ordinary reads return their typed resource directly. A command that creates durable work returns:

~~~ts
interface JobAccepted {
  job: JobSummary;
  acceptedAt: RFC3339;
  idempotentReplay: boolean;
}

interface MutationResult<T> {
  resource: T;
  auditEventId: UUID;
}
~~~

HTTP 202 is used for accepted durable work. The logical Tauri client exposes the same status in a typed result rather than making UI code inspect raw HTTP.

### 4.5 Errors

~~~ts
interface ApiError {
  error: {
    code: ApiErrorCode;
    message: SafeMessage;
    requestId: UUID;
    retryable: boolean;
    fieldErrors?: Array<{
      path: string;
      code: string;
      message: SafeMessage;
    }>;
    conflict?: {
      currentRevision: Revision;
    };
    action?: {
      kind:
        | "UNLOCK_VAULT"
        | "REVIEW_ENTITY"
        | "APPROVE_TRANSMISSION"
        | "OPEN_PROVIDER"
        | "MANUAL_CAPTURE"
        | "RETRY_LATER";
      targetId?: UUID;
    };
  };
}

type ApiErrorCode =
  | "INVALID_REQUEST"
  | "NOT_FOUND"
  | "REVISION_CONFLICT"
  | "VAULT_LOCKED"
  | "SESSION_EXPIRED"
  | "AUTHORIZATION_REQUIRED"
  | "POLICY_DENIED"
  | "RESTRICTED_VALUE_QUARANTINED"
  | "ENTITY_REVIEW_REQUIRED"
  | "TRANSMISSION_APPROVAL_REQUIRED"
  | "APPROVAL_EXPIRED"
  | "APPROVAL_MISMATCH"
  | "PROVIDER_DISABLED"
  | "PROVIDER_BLOCKED"
  | "RATE_LIMITED"
  | "TASK_STATE_CONFLICT"
  | "EVIDENCE_INTEGRITY_FAILED"
  | "FILE_BROKER_TOKEN_INVALID"
  | "LIMIT_EXCEEDED"
  | "UNSUPPORTED_MEDIA_TYPE"
  | "SERVICE_UNAVAILABLE"
  | "INTERNAL_ERROR";
~~~

The logical status is stable across Unix-socket, development HTTP, and typed
Tauri-command transports. UI code branches on `ApiErrorCode`; it does not parse
message text or pass through a provider's HTTP status.

| Logical status | Error codes | Meaning |
|---:|---|---|
| 400 | INVALID_REQUEST | Malformed syntax, schema, header, cursor, or unsupported command shape |
| 401 | SESSION_EXPIRED | The local core session is missing, expired, or no longer belongs to this sidecar launch |
| 403 | AUTHORIZATION_REQUIRED, POLICY_DENIED, TRANSMISSION_APPROVAL_REQUIRED, PROVIDER_DISABLED, PROVIDER_BLOCKED, FILE_BROKER_TOKEN_INVALID | The caller is authenticated but the requested capability, policy, approval, provider, or broker grant does not permit the operation |
| 404 | NOT_FOUND | No resource exists in the authenticated vault and explicit subject scope |
| 409 | REVISION_CONFLICT, ENTITY_REVIEW_REQUIRED, APPROVAL_EXPIRED, APPROVAL_MISMATCH, TASK_STATE_CONFLICT, EVIDENCE_INTEGRITY_FAILED | Current durable state conflicts with the requested transition or verified artifact state |
| 413 | LIMIT_EXCEEDED | A declared byte, item, depth, graph, inclusion, or batch limit was exceeded |
| 415 | UNSUPPORTED_MEDIA_TYPE | The brokered content type is unsupported or conflicts with validated content |
| 422 | RESTRICTED_VALUE_QUARANTINED | Structurally valid input was classified as restricted and diverted from normal processing |
| 423 | VAULT_LOCKED | The command requires an unlocked vault or an active reveal capability |
| 429 | RATE_LIMITED | A local or provider rate budget blocks the attempt; retry metadata remains typed and bounded |
| 500 | INTERNAL_ERROR | An unexpected local failure; release responses contain no raw exception detail |
| 503 | SERVICE_UNAVAILABLE | The sidecar, required local subsystem, or provider capability is temporarily unavailable |

Authentication, lock, size, and media checks occur before request bodies can be
echoed into diagnostics. `AUTHORIZATION_REQUIRED` is a product-authority or
scope decision and therefore maps to 403; expired sidecar authentication maps
to 401. `VAULT_LOCKED` uses 423 so lock state is never confused with a missing
resource. Retryability is still taken from the typed error, not inferred from
the numeric status alone.

Validation errors never echo a rejected secret or full input. Provider errors are mapped to stable local codes and redacted metadata. INTERNAL_ERROR carries only a request ID in release builds.

### 4.6 Pagination, filters, and sorting

- Collection endpoints use an opaque cursor.
- Default and maximum page sizes are server-controlled.
- Sort fields are allowlisted; arbitrary SQL-like expressions are rejected.
- All collection requests have explicit vault scope from the authenticated session and explicit profile scope where applicable.
- A missing profile scope never means all profiles unless the route is documented as a vault-wide aggregate.
- Free-text filters are local-only and never sent to providers.

### 4.7 Optimistic concurrency and idempotency

PATCH, classification, policy, and case-transition commands require If-Match. A stale revision returns REVISION_CONFLICT and the current revision without disclosing the current protected value.

Job-creating POST routes require Ariadne-Idempotency-Key. The key is scoped to vault, route, actor, and canonical request digest. Reusing a key with a different body fails. Retrying the same body returns the original job or mutation result.

Provider dispatch additionally atomically consumes a transmission approval use. An approval cannot be replayed for a different provider, payload digest, purpose, policy revision, jurisdiction snapshot, sensitivity, or run.

## 5. Core resource schemas

These shapes show the stable API contract. Detail endpoints may add typed nested views; list endpoints return summaries.

### 5.1 Profile and authorisation

~~~ts
interface Profile extends ResourceMeta {
  scope: { kind: "PROFILE"; profileId: UUID };
  displayLabel: ProtectedValue;
  purpose: ProtectedValue;
  status: "DRAFT" | "ACTIVE" | "ARCHIVED" | "PURGE_PENDING";
  correlationBoundary: "ISOLATED" | "EXPLICIT_LINKS_ONLY";
  authorization?: AuthorizationSummary;
}

interface ProfileCreate {
  displayLabel: string;
  purpose: string;
  defaultSensitivity: Exclude<Sensitivity, "RESTRICTED">;
}

interface AuthorizationCreate {
  authorityType:
    | "SELF"
    | "EXPLICIT_CONSENT"
    | "ACCOUNT_OWNER"
    | "OTHER_DOCUMENTED";
  scope: {
    dataClasses: string[];
    operations: string[];
    providerModes: Array<"LOCAL_ONLY" | "EU_ONLY" | "WORLDWIDE" | "CUSTOM">;
  };
  expiresAt?: RFC3339;
  attestationConfirmed: true;
}
~~~

### 5.2 Intake and extraction

~~~ts
type IntakeSourceInput =
  | {
      kind: "PASTE";
      displayName: string;
      content: string;
      consentConfirmed: true;
    }
  | {
      kind: "FILE";
      displayName: string;
      fileBrokerToken: string;
      consentConfirmed: true;
    }
  | {
      kind: "AUTHORIZED_EXPORT";
      displayName: string;
      fileBrokerToken: string;
      consentConfirmed: true;
    };

interface IntakeSource extends ResourceMeta {
  kind: "PASTE" | "FILE" | "EXPORT" | "CONNECTOR" | "MANUAL_EVIDENCE";
  displayName: string;
  detectedMime: string;
  byteSize: number;
  state: "READY" | "PARSING" | "REVIEW_REQUIRED" | "QUARANTINED" | "COMPLETE" | "FAILED";
  quarantineCount: number;
}

interface ExtractionStart {
  engines: Array<"DETERMINISTIC" | "LOCAL_MODEL">;
  localModelId?: string;
  retainRawSource: boolean;
}
~~~

Paste content is accepted only by this request schema, excluded from body logging, fully redacted for restricted values before persistence, and never returned by list endpoints. Normal sources are contentless by default, and repository entry opportunistically purges expired temporary source content.

### 5.3 Entities

~~~ts
interface EntitySummary extends ResourceMeta {
  scope: { kind: "PROFILE"; profileId: UUID };
  entityType: string;
  value: ProtectedValue;
  reviewState:
    | "UNREVIEWED"
    | "CONFIRMED"
    | "PROBABLE"
    | "POSSIBLE"
    | "FALSE_POSITIVE"
    | "EXCLUDED";
  temporalState: "CURRENT" | "HISTORICAL" | "UNKNOWN";
  searchPolicy:
    | "SEARCH_ALLOWED"
    | "APPROVAL_REQUIRED"
    | "STORE_ONLY"
    | "SEARCH_DENIED";
  transmissionPolicy:
    | "LOCAL_ONLY"
    | "APPROVAL_REQUIRED"
    | "PROVIDER_ALLOWLIST"
    | "TRANSMISSION_DENIED";
  originCount: number;
  graphNodeId?: UUID;
}

interface EntityDecisionCreate {
  decisionType:
    | "CONFIRM"
    | "REJECT"
    | "EXCLUDE"
    | "EDIT"
    | "CLASSIFY"
    | "POLICY_CHANGE";
  patch?: {
    canonicalValue?: string;
    sensitivity?: Exclude<Sensitivity, "RESTRICTED">;
    temporalState?: "CURRENT" | "HISTORICAL" | "UNKNOWN";
    searchPolicy?: EntitySummary["searchPolicy"];
    transmissionPolicy?: EntitySummary["transmissionPolicy"];
  };
  reason?: string;
}

interface EntityVariant {
  id: UUID;
  entityId: UUID;
  variantType: string;
  value: ProtectedValue;
  rank: number;
  estimatedRisk: "LOW" | "MEDIUM" | "HIGH";
  approvedForSearch: boolean;
}
~~~

Exact reveal is a separate local operation, requires an unlocked vault and a declared UI purpose, produces an audit event, and returns a short-lived response that the frontend must not persist.

### 5.4 Graph

~~~ts
interface GraphNode {
  id: UUID;
  nodeType: string;
  label: ProtectedValue;
  visibility:
    | "PUBLICLY_ATTRIBUTABLE"
    | "PUBLIC_PSEUDONYMOUS"
    | "PRIVATELY_LINKABLE"
    | "HISTORICAL_RESIDUE"
    | "PRIVATE_ONLY"
    | "UNKNOWN";
  confidence?: ProbabilityMicros;
  observedAt?: RFC3339;
  pinnedPosition?: { x: number; y: number };
}

interface GraphEdge {
  id: UUID;
  fromNodeId: UUID;
  toNodeId: UUID;
  edgeType: string;
  confidence: ProbabilityMicros;
  visibility: GraphNode["visibility"];
  observedAt: RFC3339;
  explanation: ProtectedValue;
  supportCount: number;
  contradictionCount: number;
  evidence: GraphEdgeEvidence[]; // bounded to eight
  evidenceTruncated: boolean;
}

interface GraphEdgeEvidence {
  sourceId: UUID;
  segmentOrdinal: number;
  disposition: "SUPPORTS" | "CONTRADICTS";
  confidenceMicros: ProbabilityMicros;
  visibility: GraphNode["visibility"];
  sourceSpanStart?: number;
  sourceSpanEnd?: number;
  observedAtUs: number;
  originType: "HUMAN" | "DETERMINISTIC" | "LOCAL_MODEL" | "PROVIDER";
  explanation: string;
}

interface GraphSnapshot {
  snapshotRevision: Revision;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  continuationCursor?: OpaqueCursor;
}

type CoarseGeometry =
  | { type: "Point"; coordinates: [number, number] }
  | { type: "Polygon"; coordinates: Array<Array<[number, number]>> }
  | { type: "MultiPolygon"; coordinates: Array<Array<Array<[number, number]>>> };

interface GeographicFeature {
  entityId: UUID;
  geometryKind: "COARSE_POINT" | "REGION";
  geometry: CoarseGeometry;
  precisionMeters?: number;
  privacyMode: "COARSE" | "REGION_ONLY";
  temporalState: "CURRENT" | "HISTORICAL" | "UNKNOWN";
  confidence: ProbabilityMicros;
  sourceCount: number;
}

interface GeographicSnapshot {
  scope: ResourceScope;
  features: GeographicFeature[];
  truncated: boolean;
  continuationCursor?: OpaqueCursor;
}
~~~

### 5.5 Providers and disclosure

~~~ts
interface ProviderSummary {
  id: UUID;
  providerKey: string;
  displayName: string;
  sourceType: string;
  providerClass: "STANDARD" | "OFFICIAL_REGISTER" | "PEOPLE_SEARCH" | "DATA_BROKER" | "AUTHORISED_CONNECTOR" | "LOCAL";
  dataBroker: boolean;
  accessBasis: string;
  operatorCountries: string[];
  hostingRegions: string[];
  sendsUserIdentifiers: boolean;
  retentionKnown: boolean;
  riskLevel: "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
  hasOfficialRemovalProcess: boolean;
  paidAccessStatus: "NOT_PAID" | "USER_CONFIRMED_PAID" | "UNKNOWN";
  requiresIndependentCorroboration: boolean;
  enabled: boolean;
  health: "HEALTHY" | "DEGRADED" | "BLOCKED" | "AUTH_REQUIRED" | "UNKNOWN";
  healthObservedAt?: RFC3339;
  healthStale: boolean;
}

interface DisclosurePreflightRequest {
  scope:
    | { kind: "PROFILE"; profileId: UUID; auditRunId: UUID }
    | { kind: "ISOLATED_RUN"; auditRunId: UUID };
  providerId: UUID;
  purpose: string;
  inputs: Array<
    | {
        kind: "ENTITY";
        entityId: UUID;
        variantId?: UUID;
        disclosureMode: "EXACT" | "MASKED" | "DERIVED";
      }
    | {
        kind: "ISOLATED_INPUT";
        isolatedInputId: UUID;
        disclosureMode: "EXACT" | "MASKED" | "DERIVED";
      }
  >;
}

interface DisclosurePreflight {
  preflightId: UUID;
  provider: ProviderSummary;
  payloads: Array<{
    preflightItemId: UUID;
    inputKind: "ENTITY" | "ISOLATED_INPUT";
    value: ProtectedValue;
    allowed: boolean;
    denialCode?: string;
  }>;
  jurisdictions: Array<{
    code: string;
    role: "OPERATOR" | "HOSTING" | "PROCESSING";
    declared: boolean;
  }>;
  retentionSummary: SafeMessage[];
  policyRevision: Revision;
  estimatedCost: Money;
  estimatedDurationMs?: number;
  warnings: SafeMessage[];
  expiresAt: RFC3339;
}

interface TransmissionApprovalCreate {
  preflightId: UUID;
  acceptedPreflightItemIds: UUID[];
  approvalConfirmed: true;
}

interface TransmissionApprovalSet {
  id: UUID;
  preflightId: UUID;
  providerId: UUID;
  items: Array<{
    approvalItemId: UUID;
    preflightItemId: UUID;
    useLimit: number;
    useCount: number;
  }>;
  approvedAt: RFC3339;
  expiresAt: RFC3339;
  revokedAt?: RFC3339;
  valid: boolean;
}
~~~

The preflight response may show an exact value only in the local reveal surface when necessary to make consent meaningful. It is never emitted in events or logs. Worldwide mode does not waive per-value highly sensitive approval.

### 5.6 Audits, plans, tasks, and coverage

~~~ts
type AuditCreate =
  | {
      profileId: UUID;
      correlationScope: "PROFILE";
      name: string;
      auditType: "FULL" | "TARGETED" | "SELECTED_TOOLS" | "MONITOR";
      purpose: string;
      authorizationId: UUID;
    }
  | {
      correlationScope: "ISOLATED";
      name: string;
      auditType: "TARGETED";
      purpose: string;
      authorizationAttestation: {
        authorityType: "SELF" | "ACCOUNT_OWNER" | "EXPLICIT_CONSENT";
        defensiveUseConfirmed: true;
      };
    };

type TargetedToolInput =
  | {
      kind: "SCALAR";
      inputType: "EMAIL" | "USERNAME" | "PHONE" | "NAME" | "ADDRESS" | "DOMAIN" | "URL" | "COMPANY_NUMBER";
      exactValue: string;
      sensitivity: Exclude<Sensitivity, "RESTRICTED">;
      reviewConfirmed: true;
    }
  | {
      kind: "BROKERED_FILE";
      inputType: "IMAGE" | "LOCAL_CORPUS" | "DOCUMENT";
      fileBrokerToken: string;
      displayName: string;
      sensitivity: Exclude<Sensitivity, "RESTRICTED">;
      reviewConfirmed: true;
    }
  | {
      kind: "EXISTING_ARTIFACT";
      inputType: "IMAGE" | "DOCUMENT";
      evidenceArtifactId: UUID;
      reviewConfirmed: true;
    };

interface TargetedToolRunCreate {
  toolKey: string;
  name: string;
  purpose: string;
  input: TargetedToolInput;
  correlationScope: "ISOLATED";
  authorizationAttestation: {
    authorityType: "SELF" | "ACCOUNT_OWNER" | "EXPLICIT_CONSENT";
    defensiveUseConfirmed: true;
  };
}

interface ToolCatalogItem {
  toolKey: string;
  displayName: string;
  description: string;
  supportedInputTypes: string[];
  requiredCapabilities: string[];
  supportsIsolatedRun: boolean;
}

interface TargetedToolRun extends ResourceMeta {
  scope: { kind: "ISOLATED_RUN"; auditRunId: UUID };
  auditId: UUID;
  auditRunId: UUID;
  toolKey: string;
  correlationScope: "ISOLATED";
  input:
    | {
        kind: "SCALAR";
        id: UUID;
        inputType: string;
        value: ProtectedValue;
        reviewedAt: RFC3339;
      }
    | {
        kind: "ARTIFACT";
        id: UUID;
        inputType: "IMAGE" | "LOCAL_CORPUS" | "DOCUMENT";
        artifactId: UUID;
        displayName: ProtectedValue;
        reviewedAt: RFC3339;
      };
  state: "DRAFT" | "PREPARING" | "REVIEW_REQUIRED" | "READY" | "QUARANTINED" | "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
  savedEntityId?: UUID;
}

interface TargetedToolRunAccepted {
  run: TargetedToolRun;
  preparationJob?: JobSummary;
}

interface QueryBudget {
  maxQueriesPerEntity: number;
  maxVariantsPerEntity: number;
  maxProviders: number;
  maxDurationMs?: number;
  maxCost: Money;
  maxSensitivity: Exclude<Sensitivity, "RESTRICTED">;
}

interface SearchPlanSummary extends ResourceMeta {
  auditRunId: UUID;
  version: number;
  state: "DRAFT" | "REVIEW_REQUIRED" | "APPROVED" | "SUPERSEDED";
  estimatedQueryCount: number;
  estimatedDurationMs?: number;
  estimatedCost: Money;
  approvalRequiredCount: number;
  blockedInputCount: number;
  warnings: SafeMessage[];
}

interface JobSummary extends ResourceMeta {
  auditRunId?: UUID;
  jobType: string;
  state: JobState;
  progress: ProbabilityMicros;
  progressMessageCode?: string;
  retryCount: number;
  retryLimit: number;
  scheduledAt: RFC3339;
  startedAt?: RFC3339;
  finishedAt?: RFC3339;
  errorCode?: string;
}

interface CoverageCell {
  providerId: UUID;
  capability?: string;
  queryClass?: string;
  jurisdiction?: string;
  expectedChecks: number;
  terminalChecks: number;
  aggregateState: "COMPLETE" | "PARTIAL" | "NOT_STARTED";
  outcomeCounts: Array<{
    outcome: CheckOutcome;
    count: number;
  }>;
  authoritative: boolean;
  limitationCode?: string;
  observedAt: RFC3339;
}

interface CoverageMatrix {
  auditRunId: UUID;
  cells: CoverageCell[];
  unresolvedLimitations: SafeMessage[];
  reportLanguage: string;
}
~~~

### 5.7 Findings, evidence, and attribution

The interfaces below describe the broader target. The implemented Phase 5 projection deliberately uses a signed integer attribution score from -1000 to 1000, keeps `humanReviewRequired: true`, reports only metadata for linked immutable artifacts, and returns a human attribution state only when an append-only human decision exists. Its three current mutations use narrower generated schemas than the generic target interfaces below.

~~~ts
interface FindingSummary extends ResourceMeta {
  auditRunId: UUID;
  findingType: string;
  title: ProtectedValue;
  sourceDisplay: ProtectedValue;
  checkOutcome: CheckOutcome;
  reviewState: "UNREVIEWED" | "IN_REVIEW" | "SNOOZED" | "RESOLVED";
  visibility: GraphNode["visibility"];
  sensitivity: Exclude<Sensitivity, "RESTRICTED">;
  observedAt: RFC3339;
  humanDecision?: {
    classification: AttributionClassification;
    confidenceBand: "VERY_LOW" | "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
    decidedAt: RFC3339;
  };
  modelRecommendation?: {
    recommendation: AttributionRecommendation;
    confidenceBand: "VERY_LOW" | "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
  };
  evidenceCount: number;
}

interface EvidenceArtifact extends ResourceMeta {
  artifactKind: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  capturedAt: RFC3339;
  captureMethod: string;
  verificationState: "UNVERIFIED" | "VERIFIED" | "CORRUPT" | "MISSING";
  immutable: boolean;
  sourceDisplay?: ProtectedValue;
}

interface AttributionAssessment {
  id: UUID;
  findingId: UUID;
  candidateEntityId?: UUID;
  scoringModelVersion: string;
  score: ProbabilityMicros;
  confidenceBand: "VERY_LOW" | "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
  recommendedState: AttributionRecommendation;
  requiresHumanReview: boolean;
  missingEvidence: SafeMessage[];
  signals: AttributionSignal[];
}

interface AttributionSignal {
  id: UUID;
  signalType: string;
  polarity: "SUPPORTS" | "CONTRADICTS" | "NEUTRAL";
  contribution: number;
  explanation: ProtectedValue;
  deterministic: boolean;
  evidenceArtifactId?: UUID;
}

interface AttributionDecisionCreate {
  assessmentId: UUID;
  classification: AttributionClassification;
  reason: string;
  humanConfirmed: true;
}
~~~

No service response may describe a model recommendation as a confirmed match, non-match, ownership state, takeover, or impersonation without a separate human decision.

### 5.8 Reports and manifest-bound approval

~~~ts
interface ReportInclusionManifest {
  schemaVersion: number;
  auditRunId: UUID;
  reportType: "FULL" | "REDACTED" | "COVERAGE" | "EVIDENCE_MANIFEST" | "REMEDIATION";
  findingIds: UUID[];
  evidenceArtifactIds: UUID[];
  noteIds: UUID[];
  remediationCaseIds: UUID[];
  includeExactPrivateLocations: boolean;
  exactLocationApprovalId?: UUID;
  coverageRevision: Revision;
  redactionPolicyRevision: Revision;
  sourceRevisions: Array<{ resourceId: UUID; revision: Revision }>;
}

interface ReportPreview {
  previewId: UUID;
  manifest: ReportInclusionManifest;
  manifestDigest: string;
  sourceRevisionsDigest: string;
  redactionMode: "REDACTED_DEFAULT" | "CUSTOM" | "FULL_EXPLICIT";
  disclosureSummary: SafeMessage[];
  warnings: SafeMessage[];
  expiresAt: RFC3339;
}

interface ReportCreate {
  previewId: UUID;
  manifestDigest: string;
  redactionMode: "REDACTED_DEFAULT" | "CUSTOM" | "FULL_EXPLICIT";
}

interface FullReportApproval {
  manifestDigest: string;
  sourceRevisionsDigest: string;
  redactionPolicyRevision: Revision;
  disclosureConfirmed: true;
}
~~~

Changing any included object revision, coverage revision, manifest item, or redaction-policy revision invalidates the preview and full-report approval before rendering. Exact private locations default false and require a separate short-lived reveal approval bound to the same manifest when true.

### 5.9 Restore confirmation

~~~ts
interface RestorePreview {
  previewId: UUID;
  encryptedBundleDigest: string;
  bundleFormatVersion: number;
  targetVaultId: UUID;
  keyCompatibility: "COMPATIBLE" | "KEYCHAIN_AUTH_REQUIRED" | "INCOMPATIBLE";
  migrationRequired: boolean;
  replacementConsequences: SafeMessage[];
  expiresAt: RFC3339;
}

interface RestoreConfirmed {
  previewId: UUID;
  encryptedBundleDigest: string;
  replacementConfirmed: true;
}
~~~

Restore runs while the destination vault is locked. Rust obtains Keychain authorization out of band, verifies authentication and migrations in a staging directory, retains the prior encrypted vault until post-restore verification succeeds, and never returns key material or a Keychain handle to the webview.

### 5.10 Comparison and remediation operational views

The generated `0008` Phase 6 schemas are stricter and narrower than these broader target interfaces: immutable snapshot comparison has closed lifecycle/coverage enums, and remediation is a local revisioned record with no submission state or external action capability.

~~~ts
interface RunComparison extends ResourceMeta {
  baselineRunId: UUID;
  currentRunId: UUID;
  state: "DRAFT" | "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
  coverageCompatibility: "COMPARABLE" | "PARTIAL" | "INCOMPATIBLE";
  limitations: SafeMessage[];
  diffCounts: Partial<Record<
    "NEW" | "CHANGED" | "REMOVED" | "REAPPEARED" | "REDIRECTED" |
    "DEINDEXED" | "ARCHIVED" | "FALSE_POSITIVE" | "UNCHANGED" | "UNKNOWN",
    number
  >>;
}

interface RemediationCase extends ResourceMeta {
  findingId?: UUID;
  impersonationCaseId?: UUID;
  actionType: string;
  state: "DRAFT" | "PLANNED" | "AWAITING_APPROVAL" | "SUBMITTED_MANUALLY" | "WAITING" | "APPEAL" | "COMPLETED" | "REJECTED" | "IMPOSSIBLE";
  deadlineAt?: RFC3339;
  sourceRemovedAt?: RFC3339;
  indexRemovedAt?: RFC3339;
  cachePersistence: "UNKNOWN" | "PRESENT" | "PARTIAL" | "CLEARED" | "REAPPEARED";
  cacheLastCheckedAt?: RFC3339;
  reappearedAt?: RFC3339;
}
~~~

## 6. Endpoint catalog

This catalog is the planned full-product surface. Only the 37 method/path operations (35 distinct paths) in section 3.1 exist in the generated runtime allowlist; similar-looking singular target routes below (for example `POST /profile` or `POST /intake`) are not aliases and are not exposed.

Every route below is beneath /v1. Path IDs are UUIDs. Reads return the named response type. For readability, a synchronous mutation row names its resource payload; on the wire that payload is wrapped in MutationResult. Durable work returns JobAccepted, and 204 rows have no body.

### 6.1 Session, vault, and system

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /system/capabilities | none | SystemCapabilities | Contract, schema, cipher, feature, and event versions; no host inventory |
| GET /session | none | SessionState | Lock and compatibility state |
| POST /session/unlock | UnlockRequest | SessionState | Rust/Keychain mediated; no key material in body |
| POST /session/lock | LockRequest | 204 | Cancels reveal capabilities and closes decrypted streams |
| POST /session/reveal-capability | RevealCapabilityRequest | RevealCapability | Short-lived, purpose-bound, local-only |
| GET /vault | none | VaultSummary | Current authenticated vault only |
| POST /vault/backup | BackupCreate | JobAccepted | Encrypted bundle; destination chosen through Tauri |
| POST /vault/restore/verify | RestoreVerify | JobAccepted | Verification only; restore is a separate confirmed command |
| POST /vault/restore/preview | RestorePreviewRequest | RestorePreview | Requires locked vault; shows format, key, overwrite, and migration consequences |
| POST /vault/restore | RestoreConfirmed | JobAccepted | Manifest-bound irreversible confirmation; stages, verifies, then atomically replaces |
| POST /vault/purge/preview | PurgePreviewRequest | PurgePreview | Enumerates dependent data and consequences |
| POST /vault/purge | PurgeConfirmed | JobAccepted | Dedicated irreversible confirmation |

UnlockRequest carries an opaque shell-mediated Keychain authorization result, never a password-derived key or token exposed to JavaScript.

### 6.2 /profile

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /profile | ProfileListQuery | Page of Profile | Vault-wide summary; labels masked while locked |
| POST /profile | ProfileCreate | Profile | Creates isolated draft profile |
| GET /profile/{profileId} | none | Profile | Scoped detail |
| PATCH /profile/{profileId} | ProfilePatch plus If-Match | Profile | Optimistic concurrency |
| POST /profile/{profileId}/authorization | AuthorizationCreate | AuthorizationSummary | Append-only attestation |
| POST /profile/{profileId}/authorization/{id}/revoke | RevocationCreate | AuthorizationSummary | Cancels pending external tasks |
| POST /profile/{profileId}/archive | ArchiveRequest plus If-Match | Profile | Reversible |
| POST /profile/{profileId}/purge/preview | none | PurgePreview | Includes graph and evidence dependencies |
| POST /profile/{profileId}/purge | PurgeConfirmed | JobAccepted | Cannot cascade into another profile |

### 6.3 /intake

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /intake | IntakeSourceInput | IntakeSource | Explicit paste/file consent |
| GET /intake | IntakeListQuery | Page of IntakeSource | Profile scope required |
| GET /intake/{sourceId} | none | IntakeSourceDetail | No raw content in default response |
| POST /intake/{sourceId}/extract | ExtractionStart | JobAccepted | Deterministic first; optional local model |
| GET /intake/{sourceId}/segments | SegmentListQuery | Page of IntakeSegmentPreview | Sanitised, bounded previews |
| GET /intake/{sourceId}/quarantine | none | Page of QuarantineSummary | Masked reasons only |
| POST /intake/{sourceId}/quarantine/{itemId}/delete | QuarantineDelete plus If-Match | 204 | No recovery promise beyond app control |
| POST /intake/{sourceId}/quarantine/{itemId}/release | QuarantineRelease plus If-Match | JobAccepted | Re-scan required; cannot release RESTRICTED as entity |
| DELETE /intake/{sourceId} | DeleteRequest plus If-Match | JobAccepted | Dependency and retention aware |

### 6.4 /entities

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /entities | EntityListQuery | Page of EntitySummary | Filter by review, type, time, sensitivity, policy |
| GET /entities/{entityId} | none | EntityDetail | Masked by default |
| POST /entities/{entityId}/reveal | RevealRequest | SensitiveReveal | Unlocked, audited, short-lived; never RESTRICTED |
| POST /entities/{entityId}/decisions | EntityDecisionCreate plus If-Match | EntitySummary | Append-only decision |
| POST /entities/{entityId}/variants/compile | VariantCompileRequest | JobAccepted | Local only |
| GET /entities/{entityId}/variants | none | EntityVariant array | Masked by default |
| PATCH /entities/{entityId}/variants/{variantId} | VariantDecisionCreate plus If-Match | EntityVariant | Appends rank/approval decision history |
| POST /entities/merge | EntityMergeRequest | JobAccepted | Human-confirmed and reversible by decision history |
| POST /entities/{entityId}/split | EntitySplitRequest | JobAccepted | Provenance reassignment required |
| POST /entities/batch-decisions | BatchEntityDecision | BatchMutationResult | Bounded; per-item revision |
| GET /entities/{entityId}/origins | none | Page of EntityOrigin | Provenance |

### 6.5 /graph

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /graph | GraphQuery | GraphSnapshot | Profile scope, filters, node/edge cap |
| GET /graph/nodes/{nodeId} | none | GraphNodeDetail | Evidence and backing object |
| GET /graph/nodes/{nodeId}/neighborhood | NeighborhoodQuery | GraphSnapshot | Bounded depth and node count |
| POST /graph/edges | GraphEdgeCreate | GraphEdge | Manual edge; decision event recorded |
| PATCH /graph/edges/{edgeId} | GraphEdgePatch plus If-Match | GraphEdge | Creates edge decision |
| GET /graph/edges/{edgeId}/explanation | none | EdgeExplanation | Why connected, support, contradictions, missing evidence |
| POST /graph/layout | GraphLayoutPatch | GraphLayoutResult | Stores user-pinned positions only |
| POST /graph/export-view | GraphExportView | JobAccepted | Redacted by default; exact private locations excluded |
| GET /graph/geography | GeographyQuery | GeographicSnapshot | Coarse/region geometry by default; time and jurisdiction filters |

GraphQuery requires exactly one scope: profileId or an ISOLATED auditRunId. Isolated nodes cannot be joined to profile nodes until the user completes save-to-profile. Graph queries expose coarse location geometry by default and cannot request exact private coordinates without a reveal capability.

### 6.6 /providers

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /providers | ProviderListQuery | Page of ProviderSummary | Includes jurisdiction, risk, retention, health |
| GET /providers/{providerId} | none | ProviderDetail | Capabilities, policy, terms/privacy references |
| PATCH /providers/{providerId}/policy | ProviderPolicyPatch plus If-Match | ProviderPolicy | External providers disabled until explicit enablement |
| POST /providers/{providerId}/health-check | HealthCheckRequest | JobAccepted | Sends no identity value |
| GET /providers/{providerId}/health | HealthQuery | ProviderHealthSeries | Redacted operational data |
| POST /providers/preflight | DisclosurePreflightRequest | DisclosurePreflight | Persists expiring preview/items; no external call |
| POST /providers/approvals | TransmissionApprovalCreate | TransmissionApprovalSet | Local human confirmation of persisted preflight items |
| POST /providers/approvals/{approvalId}/revoke | RevocationCreate | TransmissionApprovalSet | Pending dispatch observes revocation |
| GET /providers/transmissions | TransmissionListQuery | Page of TransmissionRecord | Masked ledger |
| GET /providers/usage | UsageQuery | UsageSummary | Cost and quota only |

### 6.7 /tools

The tool routes are a typed convenience over TARGETED audits. They create an isolated audit/run/input set; execution, progress, findings, evidence, and coverage continue through the common areas.

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /tools | ToolCatalogQuery | ToolCatalogItem array | Stable tool keys, supported input types, capabilities, and local-only metadata |
| POST /tools/runs | TargetedToolRunCreate | TargetedToolRunAccepted | Scalar runs are ready immediately; brokered files return a preparation job and never expose paths |
| GET /tools/runs/{runId} | none | TargetedToolRunDetail | Variants, selected providers, estimate, transmission summary, and save state |
| POST /tools/runs/{runId}/plan | TargetedToolPlanCreate | JobAccepted | Local variants and inspectable search plan |
| POST /tools/runs/{runId}/input/reveal | RevealRequest | SensitiveReveal | Short-lived local reveal |
| POST /tools/runs/{runId}/save-to-profile | SaveToolRunToProfile plus If-Match | JobAccepted | Explicitly creates entity provenance; prior isolated results do not auto-correlate |

RESTRICTED inputs are quarantined before a run is created. A tool run still requires provider preflight and approval before external dispatch.

### 6.8 /audits

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /audits | AuditCreate | Audit | Valid authorization required |
| GET /audits | AuditListQuery | Page of AuditSummary | Profile scope |
| GET /audits/{auditId} | none | AuditDetail | Runs and current state |
| PATCH /audits/{auditId} | AuditPatch plus If-Match | Audit | No state bypass |
| POST /audits/{auditId}/runs | AuditRunCreate | AuditRun | DRY_RUN, MOCK, or approved live mode |
| GET /audits/{auditId}/runs/{runId} | none | AuditRunDetail | Aggregate progress and limits |
| POST /audits/{auditId}/runs/{runId}/plans | SearchPlanCompile | JobAccepted | Local compilation |
| GET /audits/{auditId}/runs/{runId}/plans/current | none | SearchPlanDetail | Inspectable tasks, cost, risk |
| POST /audits/{auditId}/runs/{runId}/plans/{planId}/approve | SearchPlanApproval plus If-Match | SearchPlanSummary | Does not replace provider approvals |
| POST /audits/{auditId}/runs/{runId}/start | AuditRunStart | JobAccepted | Validates plan, authority, budgets, approvals |
| POST /audits/{auditId}/runs/{runId}/pause | RunAction | AuditRun | Cooperative |
| POST /audits/{auditId}/runs/{runId}/resume | RunAction | AuditRun | Revalidates policy/authorization |
| POST /audits/{auditId}/runs/{runId}/cancel | RunAction | AuditRun | Terminal task results remain |
| GET /audits/{auditId}/runs/{runId}/coverage | CoverageQuery | CoverageMatrix | Includes unresolved limitations |
| POST /audits/compare | RunComparisonCreate | JobAccepted | Both runs must share authorised scope |
| GET /audits/comparisons/{comparisonId} | none | RunComparison | NEW through UNKNOWN states |

### 6.9 /tasks

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /tasks | TaskListQuery | Page of JobSummary | Run, state, provider, worker, time filters |
| GET /tasks/{taskId} | none | JobDetail | Inputs represented by IDs/masks |
| GET /tasks/{taskId}/attempts | none | JobAttempt array | Redacted |
| GET /tasks/{taskId}/log | TaskLogQuery | Page of TaskLogEntry | Structured safe message codes, not raw stdout |
| POST /tasks/{taskId}/pause | TaskAction | JobSummary | If supported |
| POST /tasks/{taskId}/resume | TaskAction | JobSummary | Policy recheck |
| POST /tasks/{taskId}/cancel | TaskAction | JobSummary | Cooperative |
| POST /tasks/{taskId}/retry | RetryRequest | JobAccepted | New attempt or replacement job per idempotency rule |
| POST /tasks/retry | BulkRetryRequest | BatchJobAccepted | Bounded selection |
| POST /tasks/{taskId}/skip-provider | SkipProviderRequest | JobSummary | Coverage becomes NOT_CHECKED with reason |

The log endpoint cannot export query text, entity values, response bodies, tokens, cookies, local paths, or raw exception text. Exported execution logs use the same schema.

### 6.10 /findings

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /findings | FindingListQuery | Page of FindingSummary | Dense inbox filters |
| GET /findings/{findingId} | none | FindingDetail | Versions, provenance, attribution summary |
| GET /findings/{findingId}/versions | none | FindingVersion array | Immutable observations |
| GET /findings/{findingId}/sources | none | FindingSource array | Query/provider/raw/evidence lineage |
| POST /findings/{findingId}/review-state | FindingReviewDecisionCreate plus If-Match | FindingSummary | Appends inbox decision; distinct from ownership |
| POST /findings/{findingId}/tags | TagAssignment | FindingSummary | Scoped |
| POST /findings/{findingId}/notes | NoteCreate | Note | Sanitised local note |
| POST /findings/{findingId}/preserve | PreserveFindingRequest | JobAccepted | Evidence capture |
| POST /findings/{findingId}/remediation | RemediationCaseCreate | RemediationCase | Draft only |

### 6.11 /evidence

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /evidence | EvidenceListQuery | Page of EvidenceArtifact | Metadata only |
| GET /evidence/{artifactId} | none | EvidenceArtifactDetail | Provenance and derivations |
| POST /evidence/capture | EvidenceCaptureRequest | JobAccepted | URL/task must pass network and authorization policy |
| POST /evidence/import | EvidenceImportRequest | JobAccepted | Tauri file token, MIME/size scan |
| POST /evidence/{artifactId}/verify | VerifyRequest | JobAccepted | Auth tag and hashes |
| POST /evidence/{artifactId}/redactions | RedactionCreate | JobAccepted | Creates derivative |
| POST /evidence/{artifactId}/ocr | OcrRequest | JobAccepted | Local and optional; output labelled inference |
| POST /evidence/{artifactId}/open | EvidenceOpenRequest | EvidenceStreamTicket | Short-lived decrypted stream through shell |
| PATCH /evidence/{artifactId}/retention | RetentionPatch plus If-Match | EvidenceArtifact | Legal hold is explicit |
| DELETE /evidence/{artifactId} | DeleteRequest plus If-Match | JobAccepted | Dependency preview may be required |

EvidenceOpenRequest declares purpose and preferred safe viewer. HTML never receives privileged active rendering.
Every evidence create/list request uses ResourceScope. ISOLATED_RUN evidence is linked only to that run; saving it to a profile is an explicit provenance-preserving copy/link decision, not an implicit scope change.

### 6.12 /attribution

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /attribution/assessments | AssessmentCreate | JobAccepted | Deterministic/versioned local scoring |
| GET /attribution/assessments/{assessmentId} | none | AttributionAssessment | Full support and contradiction list |
| GET /attribution/findings/{findingId} | none | AttributionTimeline | Assessment and decision history |
| POST /attribution/decisions | AttributionDecisionCreate | AttributionDecision | Human confirmation required for conclusive states |
| POST /attribution/decisions/{decisionId}/supersede | AttributionDecisionCreate plus If-Match | AttributionDecision | Preserves original |
| GET /attribution/models | none | ScoringModelSummary array | Weights/version/status |
| POST /attribution/assessments/{assessmentId}/next-evidence | none | NextEvidenceSuggestion array | Suggestions only; no automatic dispatch |

### 6.13 /impersonation

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /impersonation | ImpersonationCaseCreate | ImpersonationCase | Cautious language |
| GET /impersonation | ImpersonationListQuery | Page of ImpersonationCase | Profile scope |
| GET /impersonation/{caseId} | none | ImpersonationCaseDetail | Timeline and evidence dimensions |
| PATCH /impersonation/{caseId} | ImpersonationDecisionCreate plus If-Match | ImpersonationCase | Appends state/classification history |
| POST /impersonation/{caseId}/observations | ImpersonationObservationCreate | ImpersonationObservation | Typed dimension |
| POST /impersonation/{caseId}/classify | ImpersonationDecisionCreate plus If-Match | ImpersonationCase | Human-confirmed superseding decision |
| POST /impersonation/{caseId}/ownership-periods | OwnershipPeriodCreate | OwnershipPeriod | Explicit from/to period with provenance |
| POST /impersonation/{caseId}/close | CaseClose plus If-Match | ImpersonationCase | Reason required |
| POST /impersonation/{caseId}/remediation | RemediationCaseCreate | RemediationCase | Draft workflow |

There is no automatic accusation or platform-report submission endpoint.
Every state or classification mutation appends an impersonation decision and updates the case’s current pointer atomically; no route overwrites decision history.

### 6.14 /remediation

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /remediation | RemediationCaseCreate | RemediationCase | Draft by default |
| GET /remediation | RemediationListQuery | Page of RemediationCase | Board filters |
| GET /remediation/{caseId} | none | RemediationCaseDetail | Deadlines, evidence, history |
| PATCH /remediation/{caseId} | RemediationCasePatch plus If-Match | RemediationCase | State machine enforced |
| POST /remediation/{caseId}/events | RemediationEventCreate | RemediationEvent | Append-only |
| POST /remediation/{caseId}/draft | DraftGenerateRequest | JobAccepted | Local template; not legal advice |
| POST /remediation/{caseId}/submission-package | SubmissionPackageCreate | JobAccepted | Generates reviewed files only |
| POST /remediation/{caseId}/mark-submitted | ManualSubmissionRecord plus If-Match | RemediationCase | Records user action |
| POST /remediation/{caseId}/close | CaseClose plus If-Match | RemediationCase | Outcome required |

An adapter that later sends a deletion or impersonation report requires a separate ADR, explicit per-action confirmation, and a new API capability. The initial contract deliberately has no send command.

### 6.15 /reports

| Method and path | Request | Response | Notes |
|---|---|---|---|
| POST /reports/preview | ReportPreviewRequest | ReportPreview | Redacted default and disclosure summary |
| POST /reports | ReportCreate | JobAccepted | Full mode requires separate explicit confirmation |
| GET /reports | ReportListQuery | Page of ReportSummary | Local metadata |
| GET /reports/{reportId} | none | ReportDetail | Includes limitations and artifact state |
| POST /reports/{reportId}/approve-full | FullReportApproval plus If-Match | ReportSummary | Exact scope and warnings |
| POST /reports/{reportId}/export | ReportExportRequest | JobAccepted | Tauri save destination |
| DELETE /reports/{reportId} | DeleteRequest plus If-Match | JobAccepted | Encrypted local artifact deletion |

Every audit report schema requires a coverage matrix, unresolved limitations, capture time, provider scope, and language that does not imply completeness.

### 6.16 /settings

| Method and path | Request | Response | Notes |
|---|---|---|---|
| GET /settings | SettingsQuery | SettingsView | Typed keys only |
| PATCH /settings | SettingsPatch plus If-Match | SettingsView | No secret setting values |
| GET /settings/privacy | none | PrivacySettingsView | Local/EU/world/custom, retention, AI, telemetry |
| PATCH /settings/privacy | PrivacySettingsPatch plus If-Match | PrivacySettingsView | Restricted invariant cannot be disabled |
| GET /settings/security | none | SecuritySettingsView | Auto-lock, backup, reveal policy |
| PATCH /settings/security | SecuritySettingsPatch plus If-Match | SecuritySettingsView | Cannot expose key material |
| GET /settings/connectors | none | ConnectorSummary array | Scopes and revocation state |
| POST /settings/connectors/{connectorId}/revoke | RevocationCreate | ConnectorSummary | Removes Keychain token |
| GET /settings/models | none | LocalModelSettings | No-LLM always available |
| PATCH /settings/models | LocalModelSettingsPatch plus If-Match | LocalModelSettings | Remote models disabled by default |

## 7. Live event protocol

### 7.1 Delivery semantics

The shell establishes one authenticated subscription per unlocked vault. Every durable resource mutation inserts its redacted event_outbox row in the same SQLite transaction; a relay publishes committed rows and marks first publication without deleting them. Events are:

- Ordered by a monotonically increasing sequence within the vault session.
- At-least-once; clients deduplicate by event ID.
- Redacted and bounded in size.
- Replayable from the encrypted event outbox using an opaque cursor that contains stream-session ID and sequence.
- Coalesced for high-frequency progress updates.
- Backed by durable resource state for important transitions.

The stream is a notification mechanism, not the domain source of truth. On a sequence gap, replay miss, expired cursor, reconnect, or event-schema mismatch, the client refetches the affected resource. The UI must never infer task success solely because progress reached 100 percent. At-least-once delivery applies only after the mutation and outbox row commit; events for rolled-back work do not exist.

### 7.2 Envelope

~~~ts
interface EventEnvelope<E extends AriadneEvent = AriadneEvent> {
  eventId: UUID;
  streamSessionId: UUID;
  sequence: number;
  emittedAt: RFC3339;
  contractVersion: 1;
  vaultId: UUID;
  scope: ResourceScope;
  contextAuditRunId?: UUID;
  resourceRevision?: Revision;
  traceId?: UUID;
  event: E;
}

type AriadneEvent =
  | { type: "session.locked"; payload: SessionLockedEvent }
  | { type: "session.expiring"; payload: SessionExpiringEvent }
  | { type: "intake.state"; payload: IntakeStateEvent }
  | { type: "intake.quarantined"; payload: IntakeQuarantinedEvent }
  | { type: "extraction.progress"; payload: ExtractionProgressEvent }
  | { type: "entity.created"; payload: EntityCreatedEvent }
  | { type: "entity.decision_recorded"; payload: EntityDecisionEvent }
  | { type: "graph.delta"; payload: GraphDeltaEvent }
  | { type: "provider.health"; payload: ProviderHealthEvent }
  | { type: "provider.rate_limit"; payload: ProviderRateLimitEvent }
  | { type: "transmission.approval_required"; payload: ApprovalRequiredEvent }
  | { type: "transmission.recorded"; payload: TransmissionRecordedEvent }
  | { type: "audit.run_state"; payload: AuditRunStateEvent }
  | { type: "audit.coverage_changed"; payload: CoverageChangedEvent }
  | { type: "task.state"; payload: TaskStateEvent }
  | { type: "task.progress"; payload: TaskProgressEvent }
  | { type: "task.log"; payload: TaskLogEvent }
  | { type: "finding.created"; payload: FindingCreatedEvent }
  | { type: "finding.updated"; payload: FindingUpdatedEvent }
  | { type: "evidence.state"; payload: EvidenceStateEvent }
  | { type: "attribution.review_required"; payload: AttributionReviewEvent }
  | { type: "impersonation.case_changed"; payload: CaseChangedEvent }
  | { type: "remediation.case_changed"; payload: CaseChangedEvent }
  | { type: "comparison.state"; payload: ComparisonStateEvent }
  | { type: "report.state"; payload: ReportStateEvent }
  | { type: "usage.changed"; payload: UsageChangedEvent }
  | { type: "system.warning"; payload: SystemWarningEvent };
~~~

Unknown event variants are ignored only when their declared compatibility is additive. An unknown major version closes the stream and triggers a compatibility screen.

### 7.3 Core event payloads

~~~ts
interface SessionLockedEvent {
  reason: "USER_REQUEST" | "AUTO_LOCK" | "SYSTEM_SLEEP" | "SESSION_EXPIRED" | "SECURITY_POLICY";
  lockedAt: RFC3339;
}

interface SessionExpiringEvent {
  expiresAt: RFC3339;
  remainingSeconds: number;
}

interface IntakeStateEvent {
  sourceId: UUID;
  previousState: string;
  state: string;
  errorCode?: string;
}

interface IntakeQuarantinedEvent {
  sourceId: UUID;
  quarantineItemId: UUID;
  reasonCode: string;
  itemCount: number;
}

interface ExtractionProgressEvent {
  sourceId: UUID;
  extractionRunId: UUID;
  progress: ProbabilityMicros;
  candidateCount: number;
  phaseCode: string;
}

interface EntityCreatedEvent {
  entityId: UUID;
  entityType: string;
  reviewState: EntitySummary["reviewState"];
  sensitivity: Exclude<Sensitivity, "RESTRICTED">;
}

interface EntityDecisionEvent {
  entityId: UUID;
  decisionId: UUID;
  decisionType: string;
  reviewState: EntitySummary["reviewState"];
}

interface TaskStateEvent {
  taskId: UUID;
  previousState: JobState;
  state: JobState;
  providerId?: UUID;
  checkOutcome?: CheckOutcome;
  errorCode?: string;
}

interface TaskProgressEvent {
  taskId: UUID;
  progress: ProbabilityMicros;
  phaseCode: string;
  completedUnits?: number;
  totalUnits?: number;
  estimatedRemainingMs?: number;
}

interface TaskLogEvent {
  taskId: UUID;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  message: SafeMessage;
  occurredAt: RFC3339;
}

interface GraphDeltaEvent {
  snapshotRevision: Revision;
  addedNodeIds: UUID[];
  updatedNodeIds: UUID[];
  removedNodeIds: UUID[];
  addedEdgeIds: UUID[];
  updatedEdgeIds: UUID[];
  removedEdgeIds: UUID[];
}

interface ApprovalRequiredEvent {
  preflightId: UUID;
  providerId: UUID;
  payloadCount: number;
  maximumSensitivity: Exclude<Sensitivity, "RESTRICTED">;
  expiresAt: RFC3339;
}

interface ProviderHealthEvent {
  providerId: UUID;
  health: ProviderSummary["health"];
  latencyMs?: number;
  observedAt: RFC3339;
}

interface ProviderRateLimitEvent {
  providerId: UUID;
  state: "AVAILABLE" | "THROTTLED" | "EXHAUSTED" | "UNKNOWN";
  remaining?: number;
  resetsAt?: RFC3339;
}

interface TransmissionRecordedEvent {
  transmissionAttemptId: UUID;
  providerId: UUID;
  taskId?: UUID;
  outcome:
    | "PREPARED"
    | "DENIED_BY_POLICY"
    | "CANCELLED"
    | "FAILED_BEFORE_SEND"
    | "SENT"
    | "PROVIDER_ACCEPTED"
    | "PROVIDER_REJECTED"
    | "RESPONSE_FAILED";
  attemptedAt: RFC3339;
  sentAt?: RFC3339;
}

interface AuditRunStateEvent {
  auditRunId: UUID;
  previousState: JobState;
  state: JobState;
  progress: ProbabilityMicros;
}

interface CoverageChangedEvent {
  auditRunId: UUID;
  changedProviderIds: UUID[];
  unresolvedLimitationCount: number;
}

interface FindingCreatedEvent {
  findingId: UUID;
  findingType: string;
  checkOutcome: CheckOutcome;
  sensitivity: Exclude<Sensitivity, "RESTRICTED">;
}

interface FindingUpdatedEvent {
  findingId: UUID;
  changedFields: string[];
  checkOutcome: CheckOutcome;
}

interface EvidenceStateEvent {
  artifactId: UUID;
  state: "CAPTURING" | "ENCRYPTING" | "VERIFYING" | "VERIFIED" | "CORRUPT" | "MISSING" | "PURGED";
  errorCode?: string;
}

interface AttributionReviewEvent {
  assessmentId: UUID;
  findingId: UUID;
  recommendedState: AttributionRecommendation;
  confidenceBand: "VERY_LOW" | "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";
}

interface CaseChangedEvent {
  caseId: UUID;
  caseType: "IMPERSONATION" | "REMEDIATION";
  state: string;
  nextActionCode?: string;
}

interface ComparisonStateEvent {
  comparisonId: UUID;
  state: "DRAFT" | "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
  progress: ProbabilityMicros;
}

interface ReportStateEvent {
  reportId: UUID;
  state: "DRAFT" | "PREVIEW_READY" | "APPROVED" | "RENDERING" | "READY" | "FAILED" | "PURGED";
  artifactId?: UUID;
  errorCode?: string;
}

interface UsageChangedEvent {
  auditRunId: UUID;
  requestCount: number;
  estimatedCost: Money;
  actualCost: Money;
}

interface SystemWarningEvent {
  warningCode: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  actionKind?:
    | "UNLOCK_VAULT"
    | "REVIEW_ENTITY"
    | "APPROVE_TRANSMISSION"
    | "OPEN_PROVIDER"
    | "MANUAL_CAPTURE"
    | "RETRY_LATER";
  targetId?: UUID;
}
~~~

TaskLogEvent.message is a generated discriminated schema per message code; it does not accept an open string map. Entity values, query strings, provider bodies, cookies, credentials, full URLs containing sensitive query parameters, absolute paths, and evidence excerpts fail event validation.

### 7.4 Event-to-screen mapping

| Screen | Primary events | Required resync |
|---|---|---|
| Mission Control | audit.run_state, task.state, finding.created, usage.changed | Audit run summary |
| Intake / Entity Review | intake.state, extraction.progress, entity.created, entity.decision_recorded | Intake and entity pages |
| Live Operations | task.state, task.progress, task.log, provider.health, provider.rate_limit | Task list and coverage matrix |
| Findings Inbox | finding.created, finding.updated, attribution.review_required | Findings page |
| Link Map | graph.delta | Graph snapshot or bounded neighborhood |
| Evidence View | evidence.state | Evidence detail |
| Case Desk | attribution.review_required, impersonation.case_changed | Assessment/case detail |
| Compare Runs | comparison.state | Comparison detail |
| Removal Tracker | remediation.case_changed | Remediation board |
| Provider Registry | provider.health, transmission.recorded | Provider/ledger views |
| Reports | report.state, audit.coverage_changed | Report detail and coverage |

## 8. State machines and command rules

### 8.1 Jobs

~~~text
DRAFT → QUEUED → RUNNING → SUCCEEDED
                 │        ↘ PARTIAL
                 │         ↘ FAILED
                 ├→ PAUSE_REQUESTED → PAUSED → QUEUED
                 ├→ CANCEL_REQUESTED → CANCELLED
                 ├→ WAITING_APPROVAL → QUEUED or CANCELLED
                 └→ BLOCKED → QUEUED, CANCELLED, or terminal PARTIAL
~~~

- Pause and cancellation are cooperative and become visible immediately as requested states.
- A provider request already sent cannot be unsent; its ledger record remains.
- Retry creates a new attempt only when input, policy, and approval remain valid. Otherwise it creates a replacement job after review.
- Failure is terminal for an attempt, not silently converted to NOT_FOUND.
- A run may finish PARTIAL when tasks are blocked, unauthorised, cancelled, or failed. Its coverage matrix explains every cell.

### 8.2 Audit plans and runs

A plan must move DRAFT → REVIEW_REQUIRED → APPROVED. Any change to selected inputs, variants, provider policy, query budget, or compiler version supersedes approval.

A live run starts only when:

1. A PROFILE run has valid profile authority, or an ISOLATED_RUN has a current defensive-use attestation bound to that run.
2. Every entity input is reviewed and search-permitted, or every isolated input is reviewed, policy-permitted, and—when file-backed—MIME/size/hash verified.
3. No restricted input exists.
4. Query and cost budgets validate.
5. Selected providers are enabled.
6. Required persisted preflight items, approval-set items, and task inputs match exactly and are unexpired.
7. The vault remains unlocked.

Resume repeats the checks. Local-only work may continue without external approval; external tasks wait visibly.

### 8.3 Evidence and reports

Evidence capture reaches VERIFIED only after encrypted write, authentication, and hash verification. A missing or corrupt artifact never returns a normal content stream.

Reports progress DRAFT → PREVIEW_READY → APPROVED when required → RENDERING → READY. Redacted is the default. A full report approval is bound to an exact inclusion manifest and expires if findings, notes, evidence, or redaction policy changes.

## 9. Privacy and security rules at the API boundary

### 9.1 Mandatory validation

- Reject RESTRICTED in every schema except quarantine decisions.
- Reject values that classify as restricted even if a caller labels them public.
- Reject an unreviewed, excluded, false-positive, search-denied, or transmit-denied entity as a provider input.
- Reject provider tasks without the exact enabled capability and policy.
- Reject arbitrary filesystem paths, file URLs, unsafe schemes, credentials in URLs, private/loopback/link-local targets, and redirect policy violations.
- Reject unbounded graph depth, import size, batch size, retries, concurrency, cost, and report inclusions.
- Reject conclusive automated attribution and any automatic external remediation submission.

### 9.2 Response minimisation

- Collection endpoints return ProtectedValue, not plaintext.
- Events never contain exact personal values.
- Raw results and evidence bytes require a dedicated scoped operation.
- Connector tokens, encryption keys, cookies, browser storage, Keychain contents, and provider secrets have no response schema.
- Jurisdiction, retention uncertainty, cost, purpose, and recipient are included wherever a disclosure decision is shown.
- Exact private locations are coarsened by default.
- False positives return minimal exclusion metadata rather than unrelated-person dossiers.

### 9.3 Logging and diagnostics

The HTTP middleware logs only request ID, route template, status, latency, payload byte count, actor class, and stable scoped object IDs where safe. It does not log:

- Query parameters that contain user search text.
- Request or response bodies.
- Headers containing session or idempotency material.
- Entity values, variants, query text, source excerpts, notes, drafts, or exact URLs.
- Provider bodies, OAuth data, evidence streams, or local paths.

Provider adapters return typed redacted errors. Support bundles use an explicit local preview and exclude vaults, evidence, screenshots, transmissions, and private paths by default.

### 9.4 Prompt-injection and active-content boundary

Imported and fetched content is data. It cannot select routes, call tools, approve transmissions, alter policy, or emit commands. Optional models receive typed minimum inputs and return typed inference only. HTML is never rendered with the Tauri bridge or application origin. Evidence viewing uses a sandboxed or external safe path with active content disabled.

## 10. Testing contract

Before the API phase can be accepted, automated tests must prove:

- OpenAPI, generated TypeScript, and Pydantic schemas do not drift.
- Every endpoint enforces the ResourceScope union, including negative cross-vault, cross-profile, profile-to-isolated, and isolated-run-to-isolated-run cases.
- Restricted values cannot be represented by normal request schemas and are quarantined when discovered.
- Provider preflight is local and dispatch fails on missing, stale, mismatched, reused, or revoked approval.
- Multi-item preflight, approval-set, task-input, and transmission-attempt manifests match exactly; the UI never approves a raw payload digest.
- Image and corpus tool inputs can enter only through brokered, MIME/size/hash-verified artifacts; path-like JSON input is rejected.
- Worldwide mode does not bypass highly sensitive approval.
- An invalid provider response cannot inject active HTML, event fields, logs, or commands.
- NOT_FOUND, CHECK_FAILED, ACCESS_BLOCKED, AUTH_REQUIRED, RATE_LIMITED, PROVIDER_UNAVAILABLE, NOT_CHECKED, and AUTHORITATIVE_ABSENCE remain distinct through storage, events, UI responses, and report output.
- A single coverage cell preserves mixed outcome counts and reconciles them to its expected check total.
- State-machine conflicts, pause, cancel, retry, crash recovery, and idempotent replay behave deterministically.
- Resource mutations and redacted outbox rows commit atomically; relay/replay tests tolerate duplicates, gaps, reconnects, cursor expiry, coalescing, slow consumers, and unknown additive variants.
- Event and log payload validators reject sensitive values, query text, tokens, paths, and raw errors.
- Reveal capabilities expire on timeout, lock, profile switch, and application background policy.
- Evidence streams fail closed on missing keys, corrupt tags, hash mismatch, lock, and expired tickets.
- Manual evidence import rejects unsupported kind/size/non-canonical encoding; caller-redacted derivatives require explicit confirmation; attribution decisions preserve assessment binding and append-only CAS history.
- Public discovery requires explicit self-audit authorization, preserves challenged/rate-limited/unavailable states, and cannot bypass access controls; atomic capture verifies the exact URL/hash/query reference and rolls back every partial-write boundary.
- HIBP account/domain requests require self-audit authority, keep API keys request-ephemeral, distinguish k-anonymity from separately authorised direct identifier transmission, preserve exact official sources, and surface plan/auth/verification/rate-limit/provider failures without converting them to absence.
- Investigation-plan compilation is deterministic and non-executing; every step retains exact identifier reference/hash, route, provider, transmission class, sequence, and unmet prerequisites.
- Entity-origin pagination rejects cross-profile scope, keeps stable ordering, returns no more than 12 exact origins, and reconciles `offset`, `limit`, `total`, and `hasMore`.
- Corpus/workspace AI validates input hashes and projection bounds, rejects fabricated source references, and requires every factual item, connection, next step, and cited section item to resolve to the exact returned source catalog.
- Local-model timeout or invalid output becomes an explicit deterministic fallback or safe failure and may not use an external network. OpenAI Responses is external only when explicitly requested with an ephemeral key/model; it must send `store: false`, pass strict structured validation/citation remapping, avoid persistence of the key or raw model input/output, and cannot approve disclosure or create evidence by assertion.
- Phase 6 comparison rejects equal, reversed, missing, and cross-profile selections while retaining intervening lifecycle observations; snapshot/remediation replay verifies canonical payload hashes.
- Every remediation mutation rejects stale revisions and cross-profile findings/evidence, appends one complete history revision, and exposes no send/submit/dispatch operation.
- Full-report approval invalidates after the inclusion manifest changes.
- Full-explicit reports preserve exact URLs and source mappings, while redacted reports remove literal URLs but retain hashes, opaque source identifiers, mappings, and explicit removal state.
- Automated recommendation schemas reject confirmed ownership, takeover, collision, and impersonation states, while human decisions retain supersession history.
- Finding inbox, variant, and impersonation edits append decisions rather than overwriting history.
- CORS, Origin, Host, session, Unix-socket permissions, loopback binding, and WebSocket authentication fail closed.
- Rust rejects any method/route/schema combination absent from the generated capability allowlist, including method substitution and oversized reveal requests.
- Privacy scanning finds no real data in schemas, fixtures, snapshots, generated clients, docs, or captured UI.

## 11. Deferred API decisions

The following require later ADRs or implementation spikes:

1. Exact Rust-to-sidecar framing and whether logical HTTP is translated inside Rust or served directly over ASGI on the Unix socket.
2. Event ring-buffer size, persistence duration, and Tauri channel framing.
3. Brokered decrypted-stream implementation and safe evidence viewer.
4. Standard for typed report manifests and encrypted export bundles.
5. Connector OAuth callback mediation and Keychain access prompts.
6. Adapter capability sandboxing and any future signed extension protocol.
7. Whether a later release may add externally submitted remediation actions; none exist in this v1 contract.

These choices may refine transport, but they may not expose the sidecar to the network, place secrets in the webview, weaken approval binding, or collapse uncertainty states.
