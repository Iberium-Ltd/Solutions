//! Closed Rust representation of the authenticated UI-to-core contract.
//!
//! The webview cannot choose an arbitrary method or path. Every command maps
//! through [`CoreRoute`] to generated capability metadata, and response types
//! reject unknown fields so contract drift fails closed at the shell boundary.

use std::fmt;

use serde::{Deserialize, Serialize};
use uuid::Uuid;
use zeroize::Zeroizing;

pub(super) const CONTRACT_VERSION: u16 = 1;
pub(super) const PROTOCOL_VERSION: u16 = 1;
pub(super) const MAX_BOOTSTRAP_BYTES: usize = 4 * 1024;
pub(super) const MAX_READINESS_BYTES: usize = 4 * 1024;
pub(super) const MAX_RESPONSE_BYTES: usize = 4 * 1024 * 1024;

const fn default_true() -> bool {
    true
}

const fn default_review_limit() -> u16 {
    100
}

const fn default_entity_origin_page_limit() -> u8 {
    12
}

const fn default_graph_nodes() -> u16 {
    200
}

const fn default_phase5_finding_limit() -> u16 {
    100
}

const fn default_phase6_run_limit() -> u8 {
    32
}

const fn default_phase6_case_limit() -> u8 {
    100
}

fn deserialize_required_nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

fn deserialize_canonical_uuid<'de, D>(deserializer: D) -> Result<Uuid, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = String::deserialize(deserializer)?;
    let parsed = Uuid::parse_str(&value).map_err(serde::de::Error::custom)?;
    if parsed.to_string() != value || parsed.get_variant() != uuid::Variant::RFC4122 {
        return Err(serde::de::Error::custom("UUID is not canonical RFC 4122"));
    }
    Ok(parsed)
}

fn deserialize_canonical_uuid_vec<'de, D>(deserializer: D) -> Result<Vec<Uuid>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let values = Vec::<String>::deserialize(deserializer)?;
    values
        .into_iter()
        .map(|value| {
            let parsed = Uuid::parse_str(&value).map_err(serde::de::Error::custom)?;
            if parsed.to_string() != value || parsed.get_variant() != uuid::Variant::RFC4122 {
                return Err(serde::de::Error::custom("UUID is not canonical RFC 4122"));
            }
            Ok(parsed)
        })
        .collect()
}

fn deserialize_required_nullable_canonical_uuid<'de, D>(
    deserializer: D,
) -> Result<Option<Uuid>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = Option::<String>::deserialize(deserializer)?;
    value
        .map(|value| {
            let parsed = Uuid::parse_str(&value).map_err(serde::de::Error::custom)?;
            if parsed.to_string() != value || parsed.get_variant() != uuid::Variant::RFC4122 {
                return Err(serde::de::Error::custom("UUID is not canonical RFC 4122"));
            }
            Ok(parsed)
        })
        .transpose()
}

pub(super) mod generated_allowlist {
    #![allow(dead_code)]

    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../packages/contracts/src/generated/route_allowlist.rs"
    ));
}

pub(super) struct SessionCredential {
    token: Zeroizing<String>,
}

impl SessionCredential {
    pub(super) fn generate() -> Result<Self, getrandom::Error> {
        use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};

        let mut bytes = Zeroizing::new([0_u8; 32]);
        getrandom::fill(bytes.as_mut())?;
        Ok(Self {
            token: Zeroizing::new(URL_SAFE_NO_PAD.encode(bytes.as_ref())),
        })
    }

    #[cfg(test)]
    pub(super) fn from_token_for_test(token: &str) -> Self {
        Self {
            token: Zeroizing::new(token.to_owned()),
        }
    }

    pub(super) fn expose(&self) -> &str {
        self.token.as_str()
    }
}

impl fmt::Debug for SessionCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SessionCredential([REDACTED])")
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct BootstrapMessage<'a> {
    pub(super) protocol_version: u16,
    pub(super) contract_version: u16,
    pub(super) session_token: &'a str,
    pub(super) parent_pid: u32,
    pub(super) startup_nonce: Uuid,
}

impl<'a> BootstrapMessage<'a> {
    pub(super) fn new(credential: &'a SessionCredential) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            contract_version: CONTRACT_VERSION,
            session_token: credential.expose(),
            parent_pid: std::process::id(),
            startup_nonce: Uuid::new_v4(),
        }
    }
}

pub(super) fn encode_json_line_bounded<T: Serialize>(
    value: &T,
    maximum: usize,
) -> Result<Zeroizing<Vec<u8>>, ContractError> {
    let mut encoded = Zeroizing::new(serde_json::to_vec(value)?);
    encoded.push(b'\n');
    if encoded.len() > maximum {
        return Err(ContractError::MessageTooLarge {
            actual: encoded.len(),
            maximum,
        });
    }
    Ok(encoded)
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "lowercase")]
pub(super) enum ReadinessTransport {
    Tcp,
    Uds,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReadinessMessage {
    pub(super) status: String,
    pub(super) transport: ReadinessTransport,
    pub(super) host: Option<String>,
    pub(super) port: Option<u16>,
    pub(super) socket_path: Option<String>,
    pub(super) contract_version: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum CoreRoute {
    Capabilities,
    ReplayEvents,
    Session,
    CreateVault,
    LockCurrentVault,
    UnlockCurrentVault,
    ListProfiles,
    CreateProfile,
    IntakePaste,
    IntakeFile,
    ReviewEntities,
    DecideEntity,
    EntityOrigins,
    GraphSnapshot,
    GetLocalAiSettings,
    UpdateLocalAiSettings,
    DiscoverLocalAiModels,
    TestLocalAiConnection,
    AnalyzeLocalAiWorkspace,
    AnalyzeLocalAiCorpus,
    CapturePublicDiscovery,
    SearchPublicDiscovery,
    CompileInvestigationPlan,
    SearchHibpAccount,
    SearchHibpDomain,
    QueryProviders,
    CreateQueryPlan,
    ExecuteQueryDryRun,
    ListPhase5Findings,
    GetPhase5Finding,
    CreatePhase5ManualFinding,
    ImportPhase5Evidence,
    CreatePhase5RedactedDerivative,
    AppendPhase5AttributionDecision,
    ListPhase6AuditRuns,
    CreatePhase6LocalCheckpoint,
    ComparePhase6Runs,
    ListPhase6RemediationCases,
    GetPhase6RemediationCase,
    CreatePhase6RemediationCase,
    UpdatePhase6RemediationDraft,
    RequirePhase6RemediationApproval,
    TransitionPhase6RemediationStatus,
    SetPhase6RemediationDeadline,
    LinkPhase6RemediationEvidence,
    RecordPhase6ProviderResponse,
    RecordPhase6Reappearance,
    GenerateLocalReport,
    GetIdentityWorkspace,
    UpdateIdentityPerson,
    CreateIdentitySource,
    CreateIdentityAudit,
    GetIdentityAudit,
    ExecuteIdentityAuditBatch,
    ControlIdentityAudit,
    DecideIdentityProposal,
}

impl CoreRoute {
    // Route IDs, methods, paths, lock state, authorization class, and byte
    // limits must agree with the generated allowlist. This hand-written enum
    // gives commands exhaustive dispatch without becoming a generic proxy.
    const fn route_id(self) -> &'static str {
        match self {
            Self::Capabilities => "system.capabilities.read",
            Self::ReplayEvents => "events.replay",
            Self::Session => "session.read",
            Self::CreateVault => "vault.create",
            Self::LockCurrentVault => "vault.current.lock",
            Self::UnlockCurrentVault => "vault.current.unlock",
            Self::ListProfiles => "profiles.list",
            Self::CreateProfile => "profile.create",
            Self::IntakePaste => "intake.paste",
            Self::IntakeFile => "intake.file",
            Self::ReviewEntities => "entities.review",
            Self::DecideEntity => "entity.decision",
            Self::EntityOrigins => "entity.origins",
            Self::GraphSnapshot => "graph.snapshot",
            Self::GetLocalAiSettings => "local_ai.settings.read",
            Self::UpdateLocalAiSettings => "local_ai.settings.update",
            Self::DiscoverLocalAiModels => "local_ai.models.discover",
            Self::TestLocalAiConnection => "local_ai.connection.test",
            Self::AnalyzeLocalAiWorkspace => "local_ai.workspace.analyze",
            Self::AnalyzeLocalAiCorpus => "local_ai.corpus.analyze",
            Self::CapturePublicDiscovery => "discovery.public.capture",
            Self::SearchPublicDiscovery => "discovery.public.search",
            Self::CompileInvestigationPlan => "discovery.investigation.plan",
            Self::SearchHibpAccount => "discovery.hibp.account",
            Self::SearchHibpDomain => "discovery.hibp.domain",
            Self::QueryProviders => "query.providers.read",
            Self::CreateQueryPlan => "query.plans.create",
            Self::ExecuteQueryDryRun => "query.dry_run.execute",
            Self::ListPhase5Findings => "phase5.findings.list",
            Self::GetPhase5Finding => "phase5.findings.detail",
            Self::CreatePhase5ManualFinding => "phase5.findings.manual.create",
            Self::ImportPhase5Evidence => "phase5.evidence.manual_import",
            Self::CreatePhase5RedactedDerivative => "phase5.evidence.redacted_derivative.create",
            Self::AppendPhase5AttributionDecision => "phase5.attribution.decision.append",
            Self::ListPhase6AuditRuns => "phase6.audits.list",
            Self::CreatePhase6LocalCheckpoint => "phase6.audits.local_checkpoint.create",
            Self::ComparePhase6Runs => "phase6.audits.compare",
            Self::ListPhase6RemediationCases => "phase6.remediation.list",
            Self::GetPhase6RemediationCase => "phase6.remediation.detail",
            Self::CreatePhase6RemediationCase => "phase6.remediation.create",
            Self::UpdatePhase6RemediationDraft => "phase6.remediation.draft.update",
            Self::RequirePhase6RemediationApproval => "phase6.remediation.approval.require",
            Self::TransitionPhase6RemediationStatus => "phase6.remediation.status.transition",
            Self::SetPhase6RemediationDeadline => "phase6.remediation.deadline.update",
            Self::LinkPhase6RemediationEvidence => "phase6.remediation.evidence.link",
            Self::RecordPhase6ProviderResponse => "phase6.remediation.provider_response.record",
            Self::RecordPhase6Reappearance => "phase6.remediation.reappearance.record",
            Self::GenerateLocalReport => "reports.generate",
            Self::GetIdentityWorkspace => "identity.workspace.read",
            Self::UpdateIdentityPerson => "identity.person.update",
            Self::CreateIdentitySource => "identity.source.create",
            Self::CreateIdentityAudit => "identity.audit.create",
            Self::GetIdentityAudit => "identity.audit.read",
            Self::ExecuteIdentityAuditBatch => "identity.audit.execute",
            Self::ControlIdentityAudit => "identity.audit.control",
            Self::DecideIdentityProposal => "identity.proposal.decision",
        }
    }

    pub(super) fn capability(self) -> &'static generated_allowlist::RouteCapability {
        generated_allowlist::ROUTE_CAPABILITIES
            .iter()
            .find(|capability| capability.route_id == self.route_id())
            .expect("generated core route allowlist drifted from the Rust command enum")
    }

    pub(super) fn path(self) -> &'static str {
        self.capability().path
    }

    #[cfg(test)]
    pub(super) fn from_method_and_path(method: &str, path: &str) -> Option<Self> {
        let capability = generated_allowlist::ROUTE_CAPABILITIES
            .iter()
            .find(|capability| capability.method == method && capability.path == path)?;
        match capability.route_id {
            "system.capabilities.read" => Some(Self::Capabilities),
            "events.replay" => Some(Self::ReplayEvents),
            "session.read" => Some(Self::Session),
            "vault.create" => Some(Self::CreateVault),
            "vault.current.lock" => Some(Self::LockCurrentVault),
            "vault.current.unlock" => Some(Self::UnlockCurrentVault),
            "profiles.list" => Some(Self::ListProfiles),
            "profile.create" => Some(Self::CreateProfile),
            "intake.paste" => Some(Self::IntakePaste),
            "intake.file" => Some(Self::IntakeFile),
            "entities.review" => Some(Self::ReviewEntities),
            "entity.decision" => Some(Self::DecideEntity),
            "entity.origins" => Some(Self::EntityOrigins),
            "graph.snapshot" => Some(Self::GraphSnapshot),
            "local_ai.settings.read" => Some(Self::GetLocalAiSettings),
            "local_ai.settings.update" => Some(Self::UpdateLocalAiSettings),
            "local_ai.models.discover" => Some(Self::DiscoverLocalAiModels),
            "local_ai.connection.test" => Some(Self::TestLocalAiConnection),
            "local_ai.workspace.analyze" => Some(Self::AnalyzeLocalAiWorkspace),
            "local_ai.corpus.analyze" => Some(Self::AnalyzeLocalAiCorpus),
            "discovery.public.capture" => Some(Self::CapturePublicDiscovery),
            "discovery.public.search" => Some(Self::SearchPublicDiscovery),
            "discovery.investigation.plan" => Some(Self::CompileInvestigationPlan),
            "discovery.hibp.account" => Some(Self::SearchHibpAccount),
            "discovery.hibp.domain" => Some(Self::SearchHibpDomain),
            "query.providers.read" => Some(Self::QueryProviders),
            "query.plans.create" => Some(Self::CreateQueryPlan),
            "query.dry_run.execute" => Some(Self::ExecuteQueryDryRun),
            "phase5.findings.list" => Some(Self::ListPhase5Findings),
            "phase5.findings.detail" => Some(Self::GetPhase5Finding),
            "phase5.findings.manual.create" => Some(Self::CreatePhase5ManualFinding),
            "phase5.evidence.manual_import" => Some(Self::ImportPhase5Evidence),
            "phase5.evidence.redacted_derivative.create" => {
                Some(Self::CreatePhase5RedactedDerivative)
            }
            "phase5.attribution.decision.append" => Some(Self::AppendPhase5AttributionDecision),
            "phase6.audits.list" => Some(Self::ListPhase6AuditRuns),
            "phase6.audits.local_checkpoint.create" => Some(Self::CreatePhase6LocalCheckpoint),
            "phase6.audits.compare" => Some(Self::ComparePhase6Runs),
            "phase6.remediation.list" => Some(Self::ListPhase6RemediationCases),
            "phase6.remediation.detail" => Some(Self::GetPhase6RemediationCase),
            "phase6.remediation.create" => Some(Self::CreatePhase6RemediationCase),
            "phase6.remediation.draft.update" => Some(Self::UpdatePhase6RemediationDraft),
            "phase6.remediation.approval.require" => Some(Self::RequirePhase6RemediationApproval),
            "phase6.remediation.status.transition" => Some(Self::TransitionPhase6RemediationStatus),
            "phase6.remediation.deadline.update" => Some(Self::SetPhase6RemediationDeadline),
            "phase6.remediation.evidence.link" => Some(Self::LinkPhase6RemediationEvidence),
            "phase6.remediation.provider_response.record" => {
                Some(Self::RecordPhase6ProviderResponse)
            }
            "phase6.remediation.reappearance.record" => Some(Self::RecordPhase6Reappearance),
            "reports.generate" => Some(Self::GenerateLocalReport),
            "identity.workspace.read" => Some(Self::GetIdentityWorkspace),
            "identity.person.update" => Some(Self::UpdateIdentityPerson),
            "identity.source.create" => Some(Self::CreateIdentitySource),
            "identity.audit.create" => Some(Self::CreateIdentityAudit),
            "identity.audit.read" => Some(Self::GetIdentityAudit),
            "identity.audit.execute" => Some(Self::ExecuteIdentityAuditBatch),
            "identity.audit.control" => Some(Self::ControlIdentityAudit),
            "identity.proposal.decision" => Some(Self::DecideIdentityProposal),
            _ => None,
        }
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct VaultCreateRequest {
    pub(super) display_name: String,
    pub(super) transaction_id: Uuid,
    pub(super) vault_id: Uuid,
    pub(super) manifest_digest: String,
    pub(super) database_key_ref: String,
    pub(super) backup_key_ref: String,
    pub(super) format_version: u32,
    pub(super) database_key_version: u32,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct VaultUnlockRequest {
    pub(super) transaction_id: Uuid,
    pub(super) vault_id: Uuid,
    pub(super) manifest_digest: String,
    pub(super) database_key_ref: String,
    pub(super) database_key_version: u32,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct EventReplayRequest {
    pub(super) cursor: Option<Uuid>,
    pub(super) max_events: u8,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct EventReplayResult {
    pub(super) disposition: EventReplayDisposition,
    pub(super) events: Vec<SafeCoreEvent>,
    pub(super) next_cursor: Option<Uuid>,
    pub(super) has_more: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(super) enum EventReplayDisposition {
    Ok,
    Gap,
    CursorExpired,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct SafeCoreEvent {
    pub(super) event_id: Uuid,
    pub(super) sequence: u64,
    pub(super) event_type: String,
    pub(super) resource_type: Option<String>,
    pub(super) resource_id: Option<Uuid>,
    pub(super) resource_revision: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreProfileCreateRequest {
    pub idempotency_key: String,
    pub display_label: String,
    pub purpose: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreProfileSummary {
    pub profile_id: Uuid,
    pub display_label: String,
    pub purpose: String,
    pub status: String,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreProfileListResult {
    pub profiles: Vec<CoreProfileSummary>,
    pub has_more: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiProvider {
    Ollama,
    OpenaiCompatible,
    OpenaiResponses,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiSettings {
    pub enabled: bool,
    pub provider: CoreLocalAiProvider,
    pub endpoint: String,
    pub selected_model: Option<String>,
    pub revision: u64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiSettingsUpdateRequest {
    pub enabled: bool,
    pub provider: CoreLocalAiProvider,
    pub endpoint: String,
    pub selected_model: Option<String>,
    pub expected_revision: u64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiEndpointRequest {
    pub provider: CoreLocalAiProvider,
    pub endpoint: String,
    pub selected_model: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiModelSummary {
    pub provider: CoreLocalAiProvider,
    pub model_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiModelDiscoveryResult {
    pub models: Vec<CoreLocalAiModelSummary>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiConnectionStatus {
    Available,
    ModelUnavailable,
    Timeout,
    Unavailable,
    InvalidResponse,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiIntakeStatus {
    NotRequested,
    Disabled,
    Succeeded,
    Timeout,
    Unavailable,
    InvalidResponse,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiConnectionResult {
    pub status: CoreLocalAiConnectionStatus,
    pub reachable: bool,
    pub model_count: u16,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub selected_model_available: Option<bool>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceTask {
    Summary,
    Organize,
    Question,
    Connections,
    GapAnalysis,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceScope {
    Entities,
    Graph,
    Findings,
    Remediation,
    AuditCoverage,
    Document,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceExecution {
    LocalModel,
    Deterministic,
    OpenaiResponses,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceDocumentKind {
    Paste,
    File,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceFallbackReason {
    RequestLimit,
    Timeout,
    Unavailable,
    UpstreamRejected,
    InvalidResponse,
    ResponseLimit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalAiWorkspaceConfidence {
    High,
    Medium,
    Low,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceDocument {
    pub kind: CoreLocalAiWorkspaceDocumentKind,
    pub display_name: String,
    pub declared_media_type: Option<String>,
    pub content: String,
    pub content_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceRequest {
    pub profile_id: Uuid,
    pub task: CoreLocalAiWorkspaceTask,
    pub question: Option<String>,
    pub scopes: Vec<CoreLocalAiWorkspaceScope>,
    #[serde(default)]
    pub include_sensitive_entities: bool,
    pub execution: CoreLocalAiWorkspaceExecution,
    pub model_id: Option<String>,
    pub openai_api_key: Option<Zeroizing<String>>,
    pub document: Option<CoreLocalAiWorkspaceDocument>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceSection {
    pub heading: String,
    pub items: Vec<CoreLocalAiWorkspaceSectionItem>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceSectionItem {
    pub text: String,
    pub evidence_refs: Vec<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceFact {
    pub statement: String,
    pub evidence_refs: Vec<String>,
    pub confidence: CoreLocalAiWorkspaceConfidence,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceConnection {
    pub from_ref: String,
    pub to_ref: String,
    pub relationship: String,
    pub supporting_refs: Vec<String>,
    pub contradiction_refs: Vec<String>,
    pub confidence: CoreLocalAiWorkspaceConfidence,
    pub rationale: String,
    pub verification_suggestion: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceNextStep {
    pub priority: u8,
    pub suggestion: String,
    pub rationale: String,
    pub supporting_refs: Vec<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceSource {
    #[serde(rename = "ref")]
    pub reference: String,
    pub kind: String,
    pub label: String,
    pub locator: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_url: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub content_sha256: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub provider_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_display_name: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub artifact_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub segment_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub segment_index: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub segment_locator: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_start: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_end: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extraction_run_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_kind: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_name: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_version: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub run_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub origin_kind: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub origin_type: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub observed_at_us: Option<u64>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub confidence_micros: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub disposition: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_url_sha256: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub capture_method: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub http_status: Option<u16>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub redirect_count: Option<u8>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceSourceCounts {
    pub entities: u32,
    pub graph_nodes: u32,
    pub graph_edges: u32,
    pub findings: u32,
    pub remediation_cases: u32,
    pub audit_runs: u32,
    pub document_segments: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalAiWorkspaceResult {
    pub profile_id: Uuid,
    pub task: CoreLocalAiWorkspaceTask,
    pub selected_scopes: Vec<CoreLocalAiWorkspaceScope>,
    pub requested_execution: CoreLocalAiWorkspaceExecution,
    pub execution_mode: CoreLocalAiWorkspaceExecution,
    pub fallback_reason: Option<CoreLocalAiWorkspaceFallbackReason>,
    pub provider: Option<CoreLocalAiProvider>,
    pub model_id: Option<String>,
    pub engine_version: String,
    pub title: String,
    pub summary: String,
    pub sections: Vec<CoreLocalAiWorkspaceSection>,
    pub facts: Vec<CoreLocalAiWorkspaceFact>,
    pub connections: Vec<CoreLocalAiWorkspaceConnection>,
    pub next_steps: Vec<CoreLocalAiWorkspaceNextStep>,
    pub sources: Vec<CoreLocalAiWorkspaceSource>,
    pub unanswered: Option<String>,
    pub limitations: Vec<String>,
    pub included_counts: CoreLocalAiWorkspaceSourceCounts,
    pub available_counts: CoreLocalAiWorkspaceSourceCounts,
    pub projection_truncated: bool,
    pub input_sha256: String,
    pub restricted_values_redacted: u16,
    pub local_only: bool,
    pub external_network_used: bool,
    pub raw_evidence_included: bool,
    pub review_only: bool,
    pub human_review_required: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CoreLocalCorpusMediaType {
    #[serde(rename = "text/plain")]
    Text,
    #[serde(rename = "text/markdown")]
    Markdown,
    #[serde(rename = "text/x-markdown")]
    XMarkdown,
    #[serde(rename = "text/csv")]
    Csv,
    #[serde(rename = "application/json")]
    Json,
    #[serde(rename = "text/vcard")]
    Vcard,
    #[serde(rename = "text/x-vcard")]
    XVcard,
}

impl CoreLocalCorpusMediaType {
    pub(super) const fn as_str(self) -> &'static str {
        match self {
            Self::Text => "text/plain",
            Self::Markdown => "text/markdown",
            Self::XMarkdown => "text/x-markdown",
            Self::Csv => "text/csv",
            Self::Json => "application/json",
            Self::Vcard => "text/vcard",
            Self::XVcard => "text/x-vcard",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiTask {
    Summary,
    Organize,
    Question,
    Connections,
    GapAnalysis,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiExecution {
    LocalModel,
    Deterministic,
    OpenaiResponses,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiFallbackReason {
    RequestLimit,
    ResponseLimit,
    Timeout,
    Unavailable,
    UpstreamRejected,
    InvalidResponse,
    Configuration,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiConfidence {
    High,
    Medium,
    Low,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiTextLabel {
    Organization,
    CitedSummary,
    Hypothesis,
    Limitation,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiReferenceKind {
    Segment,
    Entity,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreLocalCorpusAiContentOrigin {
    Deterministic,
    LocalModel,
    OpenaiResponses,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusDocumentRequest {
    pub display_name: String,
    pub declared_media_type: CoreLocalCorpusMediaType,
    pub content_base64: Zeroizing<String>,
    pub expected_size_bytes: usize,
    pub expected_sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiRequest {
    pub documents: Vec<CoreLocalCorpusDocumentRequest>,
    pub semantic_enrichment_enabled: bool,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    pub task: CoreLocalCorpusAiTask,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub question: Option<String>,
    pub execution: CoreLocalCorpusAiExecution,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_id: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub openai_api_key: Option<Zeroizing<String>>,
    pub max_segments: u16,
}

impl fmt::Debug for CoreLocalCorpusAiRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreLocalCorpusAiRequest([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiSourcePointer {
    pub document_id: String,
    pub document_name: String,
    pub segment_id: String,
    pub segment_index: u32,
    pub locator: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiSourceCatalogEntry {
    pub reference_id: String,
    pub reference_kind: CoreLocalCorpusAiReferenceKind,
    pub sources: Vec<CoreLocalCorpusAiSourcePointer>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiReviewNote {
    pub text: String,
    pub label: CoreLocalCorpusAiTextLabel,
    pub origin: CoreLocalCorpusAiContentOrigin,
    pub evidence_refs: Vec<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiSection {
    pub heading: String,
    pub items: Vec<CoreLocalCorpusAiReviewNote>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiFact {
    pub statement: String,
    pub evidence_refs: Vec<String>,
    pub confidence: CoreLocalCorpusAiConfidence,
    pub origin: CoreLocalCorpusAiContentOrigin,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiConnection {
    pub from_ref: String,
    pub to_ref: String,
    pub shared_entity_refs: Vec<String>,
    pub relationship: String,
    pub supporting_refs: Vec<String>,
    pub contradiction_refs: Vec<String>,
    pub confidence: CoreLocalCorpusAiConfidence,
    pub origin: CoreLocalCorpusAiContentOrigin,
    pub rationale: String,
    pub verification_suggestion: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiNextStep {
    pub priority: u8,
    pub suggestion: String,
    pub rationale: String,
    pub supporting_refs: Vec<String>,
    pub origin: CoreLocalCorpusAiContentOrigin,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiCounts {
    pub documents: u8,
    pub segments: u16,
    pub entities: u16,
    pub shared_entities: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalCorpusAiResult {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    pub corpus_id: String,
    pub input_manifest_sha256: String,
    pub input_sha256: String,
    pub task: CoreLocalCorpusAiTask,
    pub requested_execution: CoreLocalCorpusAiExecution,
    pub execution_mode: CoreLocalCorpusAiExecution,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub fallback_reason: Option<CoreLocalCorpusAiFallbackReason>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub provider: Option<CoreLocalAiProvider>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_id: Option<String>,
    pub engine_version: String,
    pub title: String,
    pub draft_summary: String,
    pub narrative_label: String,
    pub sections: Vec<CoreLocalCorpusAiSection>,
    pub facts: Vec<CoreLocalCorpusAiFact>,
    pub connections: Vec<CoreLocalCorpusAiConnection>,
    pub next_steps: Vec<CoreLocalCorpusAiNextStep>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub unanswered: Option<String>,
    pub uncertainties: Vec<CoreLocalCorpusAiReviewNote>,
    pub source_catalog: Vec<CoreLocalCorpusAiSourceCatalogEntry>,
    pub included_counts: CoreLocalCorpusAiCounts,
    pub available_counts: CoreLocalCorpusAiCounts,
    pub projection_truncated: bool,
    pub restricted_values_redacted: u16,
    pub local_only: bool,
    pub external_network_used: bool,
    pub raw_sources_retained: bool,
    pub persisted: bool,
    pub review_only: bool,
    pub human_review_required: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePublicDiscoveryProvider {
    DuckduckgoHtml,
    GithubUsers,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePublicDiscoveryState {
    NotChecked,
    Succeeded,
    RateLimited,
    AccessBlocked,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePublicDiscoveryReason {
    Complete,
    NoResults,
    PartialResults,
    SelfAuditAuthorizationRequired,
    RestrictedValue,
    UpstreamRateLimited,
    CaptchaOrChallenge,
    UpstreamAccessBlocked,
    RedirectRefused,
    Timeout,
    ResponseLimit,
    NetworkUnavailable,
    UpstreamUnavailable,
    UpstreamRejected,
    InvalidResponse,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePublicDiscoverySearchRequest {
    pub provider: CorePublicDiscoveryProvider,
    pub query: String,
    pub authorized_self_audit: bool,
    pub max_results: u8,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePublicDiscoveryResultItem {
    pub provider: CorePublicDiscoveryProvider,
    pub rank: u8,
    pub title: String,
    pub url: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub snippet: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_id: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePublicDiscoverySearchResult {
    pub provider: CorePublicDiscoveryProvider,
    pub state: CorePublicDiscoveryState,
    pub reason: CorePublicDiscoveryReason,
    pub results: Vec<CorePublicDiscoveryResultItem>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub total_estimate: Option<u64>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub rate_limit_remaining: Option<u64>,
    pub truncated: bool,
    pub external_request_made: bool,
    pub authorization_confirmed: bool,
    pub human_review_required: bool,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpAccountMode {
    #[default]
    KAnonymity,
    Direct,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpProvider {
    HaveIBeenPwnedV3,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpOperation {
    EmailKAnonymity,
    EmailDirect,
    VerifySubscribedDomain,
    DomainEnumeration,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpState {
    NotChecked,
    Succeeded,
    RateLimited,
    AccessBlocked,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpReason {
    Complete,
    NoResults,
    PartialResults,
    SelfAuditAuthorizationRequired,
    DirectTransmissionAuthorizationRequired,
    DomainNotProviderVerified,
    InvalidApiKey,
    UpstreamRateLimited,
    RedirectRefused,
    UpstreamAccessBlocked,
    Timeout,
    ResponseLimit,
    NetworkUnavailable,
    UpstreamUnavailable,
    UpstreamRejected,
    InvalidResponse,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreHibpIdentifierDisclosure {
    PartialSha1Prefix,
    DirectEmail,
    DirectDomain,
    None,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpAccountRequest {
    pub email: Zeroizing<String>,
    pub api_key: Zeroizing<String>,
    #[serde(default)]
    pub mode: CoreHibpAccountMode,
    pub authorized_self_audit: bool,
    #[serde(default)]
    pub authorized_direct_identifier_transmission: bool,
}

impl fmt::Debug for CoreHibpAccountRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreHibpAccountRequest([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpDomainRequest {
    pub domain: Zeroizing<String>,
    pub api_key: Zeroizing<String>,
    pub authorized_self_audit: bool,
}

impl fmt::Debug for CoreHibpDomainRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreHibpDomainRequest([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpRequestMetadata {
    pub sequence: u8,
    pub operation: CoreHibpOperation,
    pub method: String,
    pub request_url: String,
    pub endpoint_host: String,
    pub identifier_disclosure: CoreHibpIdentifierDisclosure,
    pub request_sha256: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub http_status: Option<u16>,
    pub response_bytes: usize,
    pub observed_at: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub retry_after_seconds: Option<u32>,
    pub api_key_sent: bool,
    pub redirects_followed: bool,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpBreachReference {
    pub name: String,
    pub source_url: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpDomainAccount {
    pub alias: String,
    pub breaches: Vec<CoreHibpBreachReference>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpAccountResult {
    pub provider: CoreHibpProvider,
    pub provider_home_url: String,
    pub api_documentation_url: String,
    pub attribution: String,
    pub license: String,
    pub state: CoreHibpState,
    pub reason: CoreHibpReason,
    pub requests: Vec<CoreHibpRequestMetadata>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub retry_after_seconds: Option<u32>,
    pub external_request_made: bool,
    pub authorization_confirmed: bool,
    pub human_review_required: bool,
    pub mode: CoreHibpAccountMode,
    pub breaches: Vec<CoreHibpBreachReference>,
    pub direct_transmission_authorized: bool,
}

impl fmt::Debug for CoreHibpAccountResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreHibpAccountResult([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreHibpDomainResult {
    pub provider: CoreHibpProvider,
    pub provider_home_url: String,
    pub api_documentation_url: String,
    pub attribution: String,
    pub license: String,
    pub state: CoreHibpState,
    pub reason: CoreHibpReason,
    pub requests: Vec<CoreHibpRequestMetadata>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub retry_after_seconds: Option<u32>,
    pub external_request_made: bool,
    pub authorization_confirmed: bool,
    pub human_review_required: bool,
    pub accounts: Vec<CoreHibpDomainAccount>,
    pub provider_verified_domain: bool,
    pub truncated: bool,
}

impl fmt::Debug for CoreHibpDomainResult {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreHibpDomainResult([REDACTED])")
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationIdentifierKind {
    Email,
    Username,
    Domain,
    Name,
    Url,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationProvider {
    DuckduckgoHtml,
    GithubUsers,
    HaveIBeenPwnedV3,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationOperation {
    PublicWebSearch,
    GithubUserSearch,
    HibpEmailKAnonymity,
    HibpEmailDirect,
    HibpVerifiedDomainEnumeration,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationTransmission {
    DirectPublicQuery,
    PartialSha1Prefix,
    DirectEmail,
    ProviderVerifiedDomain,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationPrerequisite {
    ExplicitSelfAuditAuthorization,
    HibpApiKey,
    HibpKAnonymitySubscription,
    DirectIdentifierTransmissionAuthorization,
    ProviderVerifiedDomain,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreInvestigationNotice {
    SelfAuditAuthorizationRequired,
    HibpApiKeyRequired,
    HibpEmailModeNotAuthorized,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreInvestigationIdentifierInput {
    pub identifier_ref: String,
    pub kind: CoreInvestigationIdentifierKind,
    pub value: Zeroizing<String>,
}

fn default_investigation_providers() -> Vec<CoreInvestigationProvider> {
    vec![
        CoreInvestigationProvider::DuckduckgoHtml,
        CoreInvestigationProvider::GithubUsers,
        CoreInvestigationProvider::HaveIBeenPwnedV3,
    ]
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreInvestigationPlanRequest {
    pub identifiers: Vec<CoreInvestigationIdentifierInput>,
    #[serde(default = "default_investigation_providers")]
    pub enabled_providers: Vec<CoreInvestigationProvider>,
    pub authorized_self_audit: bool,
    #[serde(default)]
    pub hibp_api_key_available: bool,
    #[serde(default)]
    pub hibp_k_anonymity_available: bool,
    #[serde(default)]
    pub authorized_direct_email_transmission: bool,
}

impl fmt::Debug for CoreInvestigationPlanRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreInvestigationPlanRequest([REDACTED])")
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreInvestigationPlanStep {
    pub step_id: String,
    pub identifier_ref: String,
    pub identifier_kind: CoreInvestigationIdentifierKind,
    pub identifier_sha256: String,
    pub provider: CoreInvestigationProvider,
    pub operation: CoreInvestigationOperation,
    pub execution_route: String,
    pub transmission: CoreInvestigationTransmission,
    pub prerequisites: Vec<CoreInvestigationPrerequisite>,
    pub sequence: u8,
    pub executes_during_compilation: bool,
    pub human_review_required: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreInvestigationPlanResult {
    pub plan_id: String,
    pub steps: Vec<CoreInvestigationPlanStep>,
    pub notices: Vec<CoreInvestigationNotice>,
    pub authorization_confirmed: bool,
    pub deterministic: bool,
    pub executed: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePublicDiscoveryCaptureRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    pub provider: CorePublicDiscoveryProvider,
    pub query: String,
    pub rank: u8,
    pub title: String,
    pub url: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub snippet: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_id: Option<String>,
    pub captured_at_us: u64,
    pub authorized_self_audit: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePublicDiscoveryCaptureResult {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub finding_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub artifact_id: Uuid,
    pub provider: CorePublicDiscoveryProvider,
    pub rank: u8,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_id: Option<String>,
    pub url: String,
    pub url_sha256: String,
    pub query_reference: String,
    pub captured_at_us: u64,
    pub evidence_kind: CorePhase5ArtifactKind,
    pub encrypted_at_rest: bool,
    pub local_only: bool,
    pub deduplicated: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreProviderCatalogRequest {
    pub profile_id: Uuid,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreQueryProviderSummary {
    pub provider_id: String,
    pub display_name: String,
    pub operator: String,
    pub adapter_mode: String,
    pub access_basis: String,
    pub processing_regions: Vec<String>,
    pub network_access: bool,
    pub sends_identifiers: bool,
    pub enabled: bool,
    pub retention_known: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreProviderCatalogResult {
    pub profile_id: Uuid,
    pub providers: Vec<CoreQueryProviderSummary>,
    pub external_provider_count: u16,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreQueryPolicyMode {
    LocalOnly,
    EuOnly,
    Custom,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreQueryCheckState {
    Planned,
    ApprovalRequired,
    NotChecked,
    Blocked,
    Dispatched,
    Succeeded,
    CheckFailed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreQueryCoverageOutcome {
    NotChecked,
    AccessBlocked,
    Dispatched,
    Succeeded,
    CheckFailed,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreQueryPlanRequest {
    pub profile_id: Uuid,
    pub purpose_code: String,
    pub provider_ids: Vec<String>,
    pub policy_mode: CoreQueryPolicyMode,
    #[serde(default)]
    pub allowed_provider_ids: Vec<String>,
    #[serde(default)]
    pub allowed_regions: Vec<String>,
    pub maximum_checks: u16,
    pub maximum_checks_per_provider: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreQueryPlanCell {
    pub check_id: Uuid,
    pub entity_id: Uuid,
    pub provider_id: String,
    pub masked_value: String,
    pub entity_type: String,
    pub query_class: String,
    pub state: CoreQueryCheckState,
    pub outcome: CoreQueryCoverageOutcome,
    pub reason_code: String,
    pub requires_approval: bool,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreQueryPlanResult {
    pub run_id: Uuid,
    pub profile_id: Uuid,
    pub policy_mode: CoreQueryPolicyMode,
    pub cells: Vec<CoreQueryPlanCell>,
    pub planned_count: u16,
    pub approval_required_count: u16,
    pub not_checked_count: u16,
    pub blocked_count: u16,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreQueryDryRunRequest {
    pub profile_id: Uuid,
    pub run_id: Uuid,
    pub check_id: Uuid,
    pub expected_revision: u64,
    #[serde(default)]
    pub approve_once: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5FindingListRequest {
    pub profile_id: Uuid,
    #[serde(default = "default_phase5_finding_limit")]
    pub limit: u16,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5FindingDetailRequest {
    pub profile_id: Uuid,
    pub finding_id: Uuid,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5ManualFindingCreateRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    pub title: String,
    pub summary: String,
    pub outcome: CorePhase5CheckOutcome,
    pub severity: CorePhase5Severity,
    pub visibility: CorePhase5Visibility,
    pub provider_id: String,
    pub provider_label: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5CheckOutcome {
    Found,
    NotFound,
    NotChecked,
    CheckFailed,
    AccessBlocked,
    AuthRequired,
    RateLimited,
    ProviderUnavailable,
    Ambiguous,
    ManualReviewRequired,
    AuthoritativeAbsence,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5Severity {
    Critical,
    High,
    Medium,
    Low,
    Info,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5Visibility {
    PubliclyAttributable,
    PublicPseudonymous,
    PrivatelyLinkable,
    HistoricalResidue,
    PrivateOnly,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5AttributionState {
    ConfirmedMatch,
    ConfirmedNonMatch,
    Probable,
    Possible,
    Unresolved,
    NeedsMoreEvidence,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5ConfidenceBand {
    VeryLow,
    Low,
    Medium,
    High,
    VeryHigh,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5PositiveSignal {
    ExactEmail,
    RecoveryRelationship,
    ExactLegalName,
    SameUncommonUsername,
    SamePhotograph,
    SameOrganisation,
    SameEducation,
    SameLocation,
    SameProject,
    SameLinkedDomain,
    SameWritingProfileLinks,
    ChronologicalCompatibility,
    UserConfirmation,
    ImmutablePlatformIdContinuity,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5NegativeSignal {
    ConflictingAge,
    ConflictingPhotograph,
    IncompatibleGeography,
    ActivityBeforePlausibleOwnership,
    DifferentImmutableAccountId,
    ContradictoryBiography,
    ExplicitUserExclusion,
    UsernameRecyclingEvidence,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5ArtifactKind {
    Screenshot,
    Html,
    Pdf,
    RawJson,
    UrlReference,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5CaptureMethod {
    BrowserCapture,
    HttpFetch,
    ProviderApi,
    ManualLocalImport,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5IntegrityStatus {
    Verified,
    NotVerified,
    Failed,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5FindingSummary {
    pub finding_id: Uuid,
    pub title: String,
    pub summary: String,
    pub outcome: CorePhase5CheckOutcome,
    pub severity: CorePhase5Severity,
    pub visibility: CorePhase5Visibility,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub attribution_state: Option<CorePhase5AttributionState>,
    pub confidence_band: CorePhase5ConfidenceBand,
    pub score: i32,
    pub human_review_required: bool,
    pub provider_label: String,
    pub artifact_count: u16,
    pub updated_at_us: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5FindingListResult {
    pub profile_id: Uuid,
    pub findings: Vec<CorePhase5FindingSummary>,
    pub has_more: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5PositiveContribution {
    pub signal: CorePhase5PositiveSignal,
    pub weight: u16,
    pub evidence_artifact_ids: Vec<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5NegativeContribution {
    pub signal: CorePhase5NegativeSignal,
    pub penalty: u16,
    pub evidence_artifact_ids: Vec<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5MissingEvidence {
    pub signal: CorePhase5PositiveSignal,
    pub potential_weight: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5AttributionAssessment {
    pub assessment_id: Uuid,
    pub case_id: Uuid,
    pub weight_profile_version: String,
    pub score: i32,
    pub confidence_band: CorePhase5ConfidenceBand,
    pub contributing_signals: Vec<CorePhase5PositiveContribution>,
    pub contradictions: Vec<CorePhase5NegativeContribution>,
    pub missing_evidence: Vec<CorePhase5MissingEvidence>,
    pub recommended_next_evidence: Vec<CorePhase5PositiveSignal>,
    pub human_review_required: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5EvidenceViewport {
    pub width: u16,
    pub height: u16,
    pub device_scale_micros: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5EvidenceArtifact {
    pub artifact_id: Uuid,
    pub kind: CorePhase5ArtifactKind,
    pub content_sha256: String,
    pub captured_at_us: u64,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_url: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub http_status: Option<u16>,
    pub redirect_count: u8,
    pub provider_id: String,
    pub run_id: Uuid,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub viewport: Option<CorePhase5EvidenceViewport>,
    pub capture_method: CorePhase5CaptureMethod,
    pub encrypted_at_rest: bool,
    pub integrity_status: CorePhase5IntegrityStatus,
    pub derivative_count: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5HumanDecision {
    pub decision_id: Uuid,
    pub assessment_id: Uuid,
    pub state: CorePhase5AttributionState,
    pub actor_label: String,
    pub decided_at_us: u64,
    pub weight_profile_version: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub supersedes_decision_id: Option<Uuid>,
    pub revision: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5FindingDetailResult {
    pub profile_id: Uuid,
    pub finding: CorePhase5FindingSummary,
    pub assessment: CorePhase5AttributionAssessment,
    pub artifacts: Vec<CorePhase5EvidenceArtifact>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub human_decision: Option<CorePhase5HumanDecision>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5ManualArtifactKind {
    Screenshot,
    Html,
    Pdf,
    RawJson,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5EvidenceMetadata {
    pub key: String,
    pub value: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5ManualEvidenceImportRequest {
    pub profile_id: Uuid,
    pub finding_id: Uuid,
    pub kind: CorePhase5ManualArtifactKind,
    pub content_base64: Zeroizing<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub viewport: Option<CorePhase5EvidenceViewport>,
    #[serde(default)]
    pub metadata: Vec<CorePhase5EvidenceMetadata>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5ManualEvidenceImportResult {
    pub profile_id: Uuid,
    pub finding_id: Uuid,
    pub artifact_id: Uuid,
    pub kind: CorePhase5ManualArtifactKind,
    pub content_sha256: String,
    pub captured_at_us: u64,
    pub capture_method: CorePhase5CaptureMethod,
    pub encrypted_at_rest: bool,
    pub local_only: bool,
    pub deduplicated: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5RedactedDerivativeRequest {
    pub profile_id: Uuid,
    pub original_artifact_id: Uuid,
    pub redacted_content_base64: Zeroizing<String>,
    pub already_redacted: bool,
    pub redaction_policy_version: String,
    pub redaction_summary_code: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase5RedactionMode {
    CallerSupplied,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5RedactedDerivativeResult {
    pub profile_id: Uuid,
    pub original_artifact_id: Uuid,
    pub derivative_id: Uuid,
    pub content_sha256: String,
    pub created_at_us: u64,
    pub redaction_policy_version: String,
    pub redaction_summary_code: String,
    pub redaction_mode: CorePhase5RedactionMode,
    pub encrypted_at_rest: bool,
    pub local_only: bool,
    pub deduplicated: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5AttributionDecisionRequest {
    pub profile_id: Uuid,
    pub finding_id: Uuid,
    pub assessment_id: Uuid,
    pub state: CorePhase5AttributionState,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub expected_previous_decision_id: Option<Uuid>,
    pub expected_previous_revision: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase5AttributionDecisionResult {
    pub profile_id: Uuid,
    pub finding_id: Uuid,
    pub assessment_id: Uuid,
    pub decision_id: Uuid,
    pub state: CorePhase5AttributionState,
    pub actor_label: String,
    pub decided_at_us: u64,
    pub weight_profile_version: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub supersedes_decision_id: Option<Uuid>,
    pub revision: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6SnapshotRunState {
    Completed,
    Partial,
    Cancelled,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6ProviderCoverageState {
    Complete,
    NotChecked,
    Blocked,
    CheckFailed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6FindingDiffState {
    New,
    Changed,
    Removed,
    Unchanged,
    Reappeared,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6ComparisonIncompleteReason {
    BaselineRunIncomplete,
    CurrentRunIncomplete,
    BaselineCoverageIncomplete,
    CurrentCoverageIncomplete,
    UnresolvedAbsence,
    HistoryGap,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6AuditRunListRequest {
    pub profile_id: Uuid,
    #[serde(default = "default_phase6_run_limit")]
    pub limit: u8,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6AuditRunSummary {
    pub run_id: Uuid,
    pub sequence: u64,
    pub captured_at_us: u64,
    pub run_state: CorePhase6SnapshotRunState,
    pub finding_count: u16,
    pub provider_count: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6AuditRunListResult {
    pub profile_id: Uuid,
    pub runs: Vec<CorePhase6AuditRunSummary>,
    pub has_more: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6LocalCheckpointCoverage {
    pub provider_id: String,
    pub state: CorePhase6ProviderCoverageState,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6LocalCheckpointRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    pub run_state: CorePhase6SnapshotRunState,
    pub provider_coverage: Vec<CorePhase6LocalCheckpointCoverage>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6LocalCheckpointResult {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub run_id: Uuid,
    pub sequence: u64,
    pub captured_at_us: u64,
    pub run_state: CorePhase6SnapshotRunState,
    pub finding_count: u16,
    pub provider_count: u16,
    pub local_only: bool,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6CompareRunsRequest {
    pub profile_id: Uuid,
    pub baseline_run_id: Uuid,
    pub current_run_id: Uuid,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6FindingDiff {
    pub stable_id: Uuid,
    pub provider_id: String,
    pub state: CorePhase6FindingDiffState,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub previous_fingerprint: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub current_fingerprint: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6UnresolvedAbsence {
    pub stable_id: Uuid,
    pub provider_id: String,
    pub previous_fingerprint: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub current_coverage: Option<CorePhase6ProviderCoverageState>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6ProviderCoverageComparison {
    pub provider_id: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub baseline_state: Option<CorePhase6ProviderCoverageState>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub current_state: Option<CorePhase6ProviderCoverageState>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6LifecycleEvent {
    pub run_id: Uuid,
    pub sequence: u64,
    pub run_state: CorePhase6SnapshotRunState,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub provider_coverage: Option<CorePhase6ProviderCoverageState>,
    pub observed: bool,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub content_fingerprint: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6FindingLifecycle {
    pub stable_id: Uuid,
    pub provider_id: String,
    pub events: Vec<CorePhase6LifecycleEvent>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6ComparisonResult {
    pub profile_id: Uuid,
    pub baseline_run_id: Uuid,
    pub current_run_id: Uuid,
    pub diffs: Vec<CorePhase6FindingDiff>,
    pub unresolved_absences: Vec<CorePhase6UnresolvedAbsence>,
    pub coverage: Vec<CorePhase6ProviderCoverageComparison>,
    pub lifecycles: Vec<CorePhase6FindingLifecycle>,
    pub incomplete_comparison: bool,
    pub incomplete_reasons: Vec<CorePhase6ComparisonIncompleteReason>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6RemediationAction {
    Monitor,
    PreserveEvidence,
    DeleteOwnedAccount,
    RequestCorrection,
    DraftErasureOrDeindex,
    DraftImpersonationReport,
    Contact,
    Escalate,
    MarkLegallyPersistent,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6ActionDisposition {
    LocalOnly,
    Draft,
    RequireExplicitApproval,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6RemediationStatus {
    Open,
    InProgress,
    AwaitingExplicitApproval,
    Monitoring,
    Resolved,
    Closed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CorePhase6RemediationEventType {
    CaseCreated,
    DraftUpdated,
    ApprovalRequired,
    StatusChanged,
    DeadlineChanged,
    EvidenceLinked,
    ProviderResponseRecorded,
    ReappearanceRecorded,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationListRequest {
    pub profile_id: Uuid,
    #[serde(default = "default_phase6_case_limit")]
    pub limit: u8,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationDetailRequest {
    pub profile_id: Uuid,
    pub case_id: Uuid,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationCreateRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid_vec")]
    pub finding_ids: Vec<Uuid>,
    pub action: CorePhase6RemediationAction,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub deadline_at_us: Option<u64>,
    #[serde(deserialize_with = "deserialize_canonical_uuid_vec")]
    pub evidence_references: Vec<Uuid>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub draft_text: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationDraftUpdateRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    pub draft_text: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationRequireApprovalRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationStatusTransitionRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    pub target_status: CorePhase6RemediationStatus,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub note: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationDeadlineUpdateRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub deadline_at_us: Option<u64>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationEvidenceLinkRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    #[serde(deserialize_with = "deserialize_canonical_uuid_vec")]
    pub evidence_references: Vec<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationProviderResponseRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    pub provider_id: String,
    pub response_code: String,
    pub summary: String,
    #[serde(deserialize_with = "deserialize_canonical_uuid_vec")]
    pub evidence_references: Vec<Uuid>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationReappearanceRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub case_id: Uuid,
    pub expected_revision: u16,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub finding_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid_vec")]
    pub evidence_references: Vec<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationCaseSummary {
    pub case_id: Uuid,
    pub finding_ids: Vec<Uuid>,
    pub action: CorePhase6RemediationAction,
    pub action_disposition: CorePhase6ActionDisposition,
    pub status: CorePhase6RemediationStatus,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub deadline_at_us: Option<u64>,
    pub reappearance_count: u32,
    pub revision: u16,
    pub updated_at_us: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationListResult {
    pub profile_id: Uuid,
    pub cases: Vec<CorePhase6RemediationCaseSummary>,
    pub has_more: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6ProviderResponse {
    pub provider_id: String,
    pub response_code: String,
    pub summary: String,
    pub received_at_us: u64,
    pub evidence_references: Vec<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationHistoryEntry {
    pub revision: u16,
    pub event_type: CorePhase6RemediationEventType,
    pub actor_label: String,
    pub occurred_at_us: u64,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub previous_status: Option<CorePhase6RemediationStatus>,
    pub current_status: CorePhase6RemediationStatus,
    pub detail_code: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub subject_id: Option<String>,
    pub evidence_references: Vec<Uuid>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub note: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationCase {
    pub case_id: Uuid,
    pub finding_ids: Vec<Uuid>,
    pub action: CorePhase6RemediationAction,
    pub action_disposition: CorePhase6ActionDisposition,
    pub status: CorePhase6RemediationStatus,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub deadline_at_us: Option<u64>,
    pub reappearance_count: u32,
    pub revision: u16,
    pub updated_at_us: u64,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub draft_text: Option<String>,
    pub evidence_references: Vec<Uuid>,
    pub provider_responses: Vec<CorePhase6ProviderResponse>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub last_reappearance_at_us: Option<u64>,
    pub created_at_us: u64,
    pub history: Vec<CorePhase6RemediationHistoryEntry>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePhase6RemediationDetailResult {
    pub profile_id: Uuid,
    pub case: CorePhase6RemediationCase,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreReportArtifactFormat {
    Json,
    Markdown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreReportExportMode {
    Redacted,
    FullExplicit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CoreLocalReportSchema {
    #[serde(rename = "ariadne.local-report")]
    AriadneLocalReport,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalReportGenerateRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub baseline_run_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub current_run_id: Uuid,
    pub artifact_format: CoreReportArtifactFormat,
    pub mode: CoreReportExportMode,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub full_export_approval_id: Option<Uuid>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalReportArtifactDescriptor {
    pub filename: String,
    pub media_type: String,
    pub byte_count: usize,
    pub sha256: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalReportManifest {
    pub schema: CoreLocalReportSchema,
    pub version: u8,
    pub mode: CoreReportExportMode,
    pub generated_at_us: u64,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub full_export_approval_id: Option<Uuid>,
    pub artifacts: Vec<CoreLocalReportArtifactDescriptor>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalReportArtifact {
    pub filename: String,
    pub media_type: String,
    pub byte_count: usize,
    pub sha256: String,
    pub schema: CoreLocalReportSchema,
    pub version: u8,
    pub mode: CoreReportExportMode,
    pub content: Zeroizing<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreLocalReportGenerateResult {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub baseline_run_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub current_run_id: Uuid,
    pub local_only: bool,
    pub artifact: CoreLocalReportArtifact,
    pub manifest: CoreLocalReportManifest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityAuditMode {
    FullRescan,
    Incremental,
    NewIdentifiersOnly,
    FailedAndBlockedRetry,
    SelectedIdentities,
    SelectedProviders,
    ChangeMonitoring,
    MaximumCoverage,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityAuditState {
    Draft,
    Ready,
    Running,
    Paused,
    Completed,
    Partial,
    Cancelled,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityAuditStage {
    Knowledge,
    Planning,
    Searching,
    Extracting,
    Correlating,
    AiAnalysis,
    Review,
    Checkpoint,
    Complete,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityTaskState {
    Planned,
    Ready,
    Queued,
    Running,
    SucceededEmpty,
    SucceededResults,
    Blocked,
    RateLimited,
    AuthRequired,
    FailedRetryable,
    FailedTerminal,
    Skipped,
    Cancelled,
    ReviewRequired,
    Reviewed,
    Saved,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityTaskType {
    SearchWeb,
    SearchProvider,
    SearchSite,
    SearchDomain,
    SearchUsername,
    FetchUrl,
    ParseHtml,
    ExtractLinks,
    ExtractIdentifiers,
    QueryArchive,
    QueryGithub,
    QueryRegistry,
    QueryDns,
    QueryCertificateTransparency,
    RunUsernameEnumeration,
    RunMetadataExtraction,
    RunOcr,
    HashImage,
    CompareImages,
    CaptureScreenshot,
    CaptureHtml,
    CaptureDocument,
    GenerateQueryVariants,
    AnalyseDocument,
    CompareSources,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentitySourceType {
    Website,
    Subpage,
    SocialProfile,
    ForumProfile,
    ForumThread,
    Comment,
    MemberPage,
    GitRepository,
    PackageRegistry,
    Document,
    Pdf,
    PublicRecord,
    Archive,
    SearchResult,
    Media,
    ManualUrl,
    Other,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityAuditControlAction {
    Pause,
    Resume,
    Cancel,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreIdentityProposalDecision {
    Confirm,
    ConfirmHistorical,
    Probable,
    SearchDeeper,
    Reject,
    Unrelated,
    Merge,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityWorkspaceRequest {
    pub profile_id: Uuid,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityPersonUpdateRequest {
    pub profile_id: Uuid,
    pub expected_profile_revision: u64,
    pub expected_details_revision: u64,
    pub display_name: String,
    pub purpose: String,
    pub notes: String,
    pub tags: Vec<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentitySourceCreateRequest {
    pub profile_id: Uuid,
    pub url: String,
    pub source_type: CoreIdentitySourceType,
    pub title: Option<String>,
    pub notes: String,
    pub authorized_self_audit: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityAuditCreateRequest {
    pub profile_id: Uuid,
    pub name: String,
    pub mode: CoreIdentityAuditMode,
    pub provider_ids: Vec<String>,
    pub max_depth: u8,
    pub request_budget: u16,
    pub time_budget_seconds: u32,
    pub cost_budget_micros: u64,
    pub use_local_ai: bool,
    pub authorized_self_audit: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityAuditExecuteRequest {
    pub profile_id: Uuid,
    pub audit_id: Uuid,
    pub maximum_tasks: u8,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityAuditControlRequest {
    pub profile_id: Uuid,
    pub audit_id: Uuid,
    pub expected_revision: u64,
    pub action: CoreIdentityAuditControlAction,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityProposalDecisionRequest {
    pub profile_id: Uuid,
    pub audit_id: Uuid,
    pub proposal_id: Uuid,
    pub expected_revision: u64,
    pub decision: CoreIdentityProposalDecision,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityPersonDetails {
    pub profile_id: Uuid,
    pub display_name: String,
    pub purpose: String,
    pub status: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub profile_revision: u64,
    pub details_revision: u64,
    pub identity_count: u32,
    pub source_count: u32,
    pub audit_count: u32,
    pub unresolved_proposal_count: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentitySource {
    pub source_id: Uuid,
    pub source_type: CoreIdentitySourceType,
    pub url: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub title: Option<String>,
    pub notes: String,
    pub relationship_state: String,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub parent_source_id: Option<Uuid>,
    pub first_seen_at_us: u64,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub last_checked_at_us: Option<u64>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub http_status: Option<u16>,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityTaskStateCount {
    pub state: CoreIdentityTaskState,
    pub count: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityAuditSummary {
    pub audit_id: Uuid,
    pub name: String,
    pub mode: CoreIdentityAuditMode,
    pub state: CoreIdentityAuditState,
    pub stage: CoreIdentityAuditStage,
    pub provider_ids: Vec<String>,
    pub use_local_ai: bool,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub selected_model: Option<String>,
    pub max_depth: u8,
    pub request_budget: u16,
    pub total_tasks: u32,
    pub terminal_tasks: u32,
    pub result_count: u32,
    pub lead_count: u32,
    pub proposal_count: u32,
    pub progress_micros: u32,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub stop_reason: Option<String>,
    pub task_states: Vec<CoreIdentityTaskStateCount>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub started_at_us: Option<u64>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub finished_at_us: Option<u64>,
    pub created_at_us: u64,
    pub updated_at_us: u64,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityWorkspace {
    pub person: CoreIdentityPersonDetails,
    pub sources: Vec<CoreIdentitySource>,
    pub audits: Vec<CoreIdentityAuditSummary>,
    pub has_more_sources: bool,
    pub has_more_audits: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityFrontierTask {
    pub task_id: Uuid,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub lead_id: Option<Uuid>,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub parent_task_id: Option<Uuid>,
    pub task_type: CoreIdentityTaskType,
    pub provider_id: String,
    pub masked_payload: String,
    pub priority: u8,
    pub information_gain_micros: u32,
    pub depth: u8,
    pub state: CoreIdentityTaskState,
    pub attempt_count: u32,
    pub retry_limit: u8,
    pub result_count: u32,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub stop_reason: Option<String>,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityDiscoveryResult {
    pub result_id: Uuid,
    pub task_id: Uuid,
    pub provider_id: String,
    pub rank: u32,
    pub category: String,
    pub url: String,
    pub title: String,
    pub snippet: String,
    pub observed_at_us: u64,
    pub review_state: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityDiscoveryLead {
    pub lead_id: Uuid,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub parent_lead_id: Option<Uuid>,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub source_id: Option<Uuid>,
    pub lead_type: String,
    pub display_value: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_url: Option<String>,
    pub provider_id: String,
    pub depth: u8,
    pub supporting_signals: Vec<String>,
    pub contradictions: Vec<String>,
    pub confidence_micros: u32,
    pub ownership_state: String,
    pub temporal_state: String,
    pub review_state: String,
    pub expansion_state: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityKnowledgeProposal {
    pub proposal_id: Uuid,
    pub lead_id: Uuid,
    pub entity_type: String,
    pub display_value: String,
    pub source_url: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_start: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_end: Option<u32>,
    pub supporting_signals: Vec<String>,
    pub contradictions: Vec<String>,
    pub confidence_micros: u32,
    pub temporal_state: String,
    pub review_state: String,
    pub recommended_actions: Vec<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_provider: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_id: Option<String>,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityToolReceipt {
    pub receipt_id: Uuid,
    #[serde(deserialize_with = "deserialize_required_nullable_canonical_uuid")]
    pub task_id: Option<Uuid>,
    pub tool_name: CoreIdentityTaskType,
    pub authorization_state: String,
    pub execution_state: String,
    pub result_code: String,
    pub result_count: u32,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_provider: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub model_id: Option<String>,
    pub started_at_us: u64,
    pub finished_at_us: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIdentityAuditDetail {
    pub profile_id: Uuid,
    pub audit: CoreIdentityAuditSummary,
    pub tasks: Vec<CoreIdentityFrontierTask>,
    pub results: Vec<CoreIdentityDiscoveryResult>,
    pub leads: Vec<CoreIdentityDiscoveryLead>,
    pub proposals: Vec<CoreIdentityKnowledgeProposal>,
    pub receipts: Vec<CoreIdentityToolReceipt>,
    pub has_more_tasks: bool,
    pub has_more_results: bool,
    pub has_more_leads: bool,
    pub has_more_proposals: bool,
    pub has_more_receipts: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CorePasteIntakeRequest {
    pub profile_id: Uuid,
    pub idempotency_key: String,
    pub display_name: String,
    pub content: Zeroizing<String>,
    pub consent_confirmed: bool,
    #[serde(default)]
    pub retain_raw_source: bool,
    #[serde(default = "default_true")]
    pub semantic_enrichment_enabled: bool,
}

impl fmt::Debug for CorePasteIntakeRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CorePasteIntakeRequest([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreFileIntakeRequest {
    pub profile_id: Uuid,
    pub idempotency_key: String,
    pub display_name: String,
    pub declared_media_type: String,
    pub expected_size_bytes: usize,
    pub expected_sha256: String,
    pub content_base64: Zeroizing<String>,
    pub consent_confirmed: bool,
    #[serde(default)]
    pub retain_raw_source: bool,
    #[serde(default = "default_true")]
    pub semantic_enrichment_enabled: bool,
}

impl fmt::Debug for CoreFileIntakeRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CoreFileIntakeRequest([REDACTED])")
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreIntakeReceipt {
    pub source_id: Uuid,
    pub profile_id: Uuid,
    pub state: String,
    pub source_kind: String,
    pub segment_count: u32,
    pub candidate_count: u32,
    pub duplicate_count: u32,
    pub quarantine_count: u32,
    pub revision: u64,
    pub local_ai_status: CoreLocalAiIntakeStatus,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub local_ai_provider: Option<CoreLocalAiProvider>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub local_ai_model: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub local_ai_engine_version: Option<String>,
    pub local_ai_suggestion_count: u16,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityReviewRequest {
    pub profile_id: Uuid,
    pub source_id: Option<Uuid>,
    #[serde(default = "default_review_limit")]
    pub limit: u16,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreSensitivity {
    Public,
    Sensitive,
    HighlySensitive,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreReviewState {
    Unreviewed,
    Confirmed,
    Probable,
    Possible,
    FalsePositive,
    Excluded,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreTemporalState {
    Current,
    Historical,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreSearchPolicy {
    Allow,
    RequireApproval,
    StoreOnly,
    Deny,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreTransmissionPolicy {
    LocalOnly,
    PolicyControlled,
    RequireEachApproval,
    Never,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreEntityDecisionType {
    Confirm,
    Reject,
    Exclude,
    Classify,
    PolicyChange,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityOrigin {
    pub source_id: Uuid,
    pub source_display_name: String,
    pub source_sha256: String,
    pub segment_id: Uuid,
    pub segment_index: u32,
    pub segment_locator: String,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_start: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_end: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extraction_run_id: Option<Uuid>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_kind: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_name: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub extractor_version: Option<String>,
    pub origin_kind: String,
    pub observed_at_us: u64,
    pub confidence_micros: u32,
    pub explanation: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityOriginPageRequest {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub entity_id: Uuid,
    #[serde(default)]
    pub offset: u32,
    #[serde(default = "default_entity_origin_page_limit")]
    pub limit: u8,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityOriginPageResult {
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub profile_id: Uuid,
    #[serde(deserialize_with = "deserialize_canonical_uuid")]
    pub entity_id: Uuid,
    pub offset: u32,
    pub limit: u8,
    pub origins: Vec<CoreEntityOrigin>,
    pub total: u64,
    pub has_more: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntitySummary {
    pub entity_id: Uuid,
    pub entity_type: String,
    pub display_value: String,
    pub sensitivity: CoreSensitivity,
    pub review_state: CoreReviewState,
    pub temporal_state: CoreTemporalState,
    pub search_policy: CoreSearchPolicy,
    pub transmission_policy: CoreTransmissionPolicy,
    pub confidence_micros: u32,
    pub provenance_label: String,
    pub origins: Vec<CoreEntityOrigin>,
    pub origins_truncated: bool,
    pub revision: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityReviewResult {
    pub profile_id: Uuid,
    pub entities: Vec<CoreEntitySummary>,
    pub quarantine_count: u32,
    pub has_more: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreEntityDecisionRequest {
    pub profile_id: Uuid,
    pub entity_id: Uuid,
    pub idempotency_key: String,
    pub expected_revision: u64,
    pub decision_type: CoreEntityDecisionType,
    pub review_state: CoreReviewState,
    pub sensitivity: CoreSensitivity,
    pub temporal_state: CoreTemporalState,
    pub search_policy: CoreSearchPolicy,
    pub transmission_policy: CoreTransmissionPolicy,
    pub reason: Option<Zeroizing<String>>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreGraphSnapshotRequest {
    pub profile_id: Uuid,
    #[serde(default = "default_graph_nodes")]
    pub max_nodes: u16,
    #[serde(default)]
    pub include_sensitive: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreGraphNode {
    pub node_id: Uuid,
    pub node_type: String,
    pub display_label: String,
    pub sensitivity: CoreSensitivity,
    pub entity_id: Option<Uuid>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreGraphEvidenceDisposition {
    Supports,
    Contradicts,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreGraphVisibility {
    PubliclyAttributable,
    PublicPseudonymous,
    PrivatelyLinkable,
    HistoricalResidue,
    PrivateOnly,
    Unknown,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreGraphEdgeEvidence {
    pub source_id: Uuid,
    pub segment_ordinal: u32,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_start: Option<u32>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    pub source_span_end: Option<u32>,
    pub disposition: CoreGraphEvidenceDisposition,
    pub confidence_micros: u32,
    pub visibility: CoreGraphVisibility,
    pub observed_at_us: u64,
    pub origin_type: String,
    pub explanation: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreGraphEdge {
    pub edge_id: Uuid,
    pub from_node_id: Uuid,
    pub to_node_id: Uuid,
    pub edge_type: String,
    pub confidence_micros: u32,
    pub origin_type: String,
    pub explanation: String,
    pub support_count: u32,
    pub contradiction_count: u32,
    pub evidence: Vec<CoreGraphEdgeEvidence>,
    pub evidence_truncated: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreGraphSnapshot {
    pub profile_id: Uuid,
    pub nodes: Vec<CoreGraphNode>,
    pub edges: Vec<CoreGraphEdge>,
    pub truncated: bool,
}

macro_rules! impl_redacted_debug {
    ($($name:ty),+ $(,)?) => {
        $(
            impl fmt::Debug for $name {
                fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                    formatter.write_str(concat!(stringify!($name), "([REDACTED])"))
                }
            }
        )+
    };
}

impl_redacted_debug!(
    CoreIdentityWorkspaceRequest,
    CoreIdentityPersonUpdateRequest,
    CoreIdentitySourceCreateRequest,
    CoreIdentityAuditCreateRequest,
    CoreIdentityAuditExecuteRequest,
    CoreIdentityAuditControlRequest,
    CoreIdentityProposalDecisionRequest,
    CoreIdentityPersonDetails,
    CoreIdentitySource,
    CoreIdentityTaskStateCount,
    CoreIdentityAuditSummary,
    CoreIdentityWorkspace,
    CoreIdentityFrontierTask,
    CoreIdentityDiscoveryResult,
    CoreIdentityDiscoveryLead,
    CoreIdentityKnowledgeProposal,
    CoreIdentityToolReceipt,
    CoreIdentityAuditDetail,
    CoreProfileSummary,
    CoreProfileListResult,
    CoreIntakeReceipt,
    CoreEntityOrigin,
    CoreEntityOriginPageResult,
    CoreEntitySummary,
    CoreEntityReviewResult,
    CoreGraphNode,
    CoreGraphEdgeEvidence,
    CoreGraphEdge,
    CoreGraphSnapshot,
    CoreLocalAiWorkspaceDocument,
    CoreLocalAiWorkspaceRequest,
    CoreLocalAiWorkspaceSection,
    CoreLocalAiWorkspaceSectionItem,
    CoreLocalAiWorkspaceFact,
    CoreLocalAiWorkspaceConnection,
    CoreLocalAiWorkspaceNextStep,
    CoreLocalAiWorkspaceSource,
    CoreLocalAiWorkspaceSourceCounts,
    CoreLocalAiWorkspaceResult,
    CoreQueryProviderSummary,
    CoreProviderCatalogResult,
    CoreQueryPlanCell,
    CoreQueryPlanResult,
    CorePhase5FindingSummary,
    CorePhase5FindingListResult,
    CorePhase5PositiveContribution,
    CorePhase5NegativeContribution,
    CorePhase5MissingEvidence,
    CorePhase5AttributionAssessment,
    CorePhase5EvidenceViewport,
    CorePhase5EvidenceArtifact,
    CorePhase5HumanDecision,
    CorePhase5FindingDetailResult,
    CorePhase5ManualFindingCreateRequest,
    CorePhase5EvidenceMetadata,
    CorePhase5ManualEvidenceImportRequest,
    CorePhase5ManualEvidenceImportResult,
    CorePhase5RedactedDerivativeRequest,
    CorePhase5RedactedDerivativeResult,
    CorePhase5AttributionDecisionResult,
    CorePhase6AuditRunSummary,
    CorePhase6AuditRunListResult,
    CorePhase6LocalCheckpointCoverage,
    CorePhase6LocalCheckpointRequest,
    CorePhase6LocalCheckpointResult,
    CorePhase6FindingDiff,
    CorePhase6UnresolvedAbsence,
    CorePhase6ProviderCoverageComparison,
    CorePhase6LifecycleEvent,
    CorePhase6FindingLifecycle,
    CorePhase6ComparisonResult,
    CorePhase6RemediationCreateRequest,
    CorePhase6RemediationDraftUpdateRequest,
    CorePhase6RemediationStatusTransitionRequest,
    CorePhase6RemediationProviderResponseRequest,
    CorePhase6RemediationCaseSummary,
    CorePhase6RemediationListResult,
    CorePhase6ProviderResponse,
    CorePhase6RemediationHistoryEntry,
    CorePhase6RemediationCase,
    CorePhase6RemediationDetailResult,
    CoreLocalReportGenerateRequest,
    CoreLocalReportArtifactDescriptor,
    CoreLocalReportManifest,
    CoreLocalReportArtifact,
    CoreLocalReportGenerateResult,
);

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreVaultLifecycleResult {
    pub vault_id: Uuid,
    pub lock_state: SessionLockState,
    pub vault_state: VaultState,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreCapabilities {
    pub versions: CoreVersions,
    pub transport: CoreTransport,
    pub cipher: CoreCipher,
    pub features: Vec<CoreFeature>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreVersions {
    pub contract: u16,
    pub schema: String,
    pub events: u16,
    pub core: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreTransport {
    DevLoopback,
    UnixSocket,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreCipher {
    pub required: String,
    pub available: bool,
    pub sqlite_version: Option<String>,
    pub cipher_version: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreFeature {
    pub key: String,
    pub status: CoreFeatureStatus,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CoreFeatureStatus {
    Available,
    NotImplemented,
    Unavailable,
    Degraded,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoreSession {
    pub lock_state: SessionLockState,
    pub vault_state: VaultState,
    pub compatibility: CompatibilityState,
    pub authenticated_transport: bool,
    pub session_expires_at: Option<String>,
    pub active_reveal_capabilities: u32,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SessionLockState {
    Locked,
    Unlocked,
    Locking,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum VaultState {
    NoVault,
    Locked,
    Unlocked,
    Unavailable,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CompatibilityState {
    Compatible,
    Incompatible,
    Unknown,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CoreCommandResponse<T> {
    pub request_id: Uuid,
    pub data: T,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CoreCommandError {
    pub code: &'static str,
    pub message: String,
    pub request_id: Uuid,
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum ContractError {
    #[error("local protocol message is too large ({actual} bytes; maximum {maximum})")]
    MessageTooLarge { actual: usize, maximum: usize },
    #[error("local protocol JSON is invalid")]
    Json(#[from] serde_json::Error),
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    const TEST_TOKEN: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

    #[test]
    fn bootstrap_is_bounded_and_credential_debug_is_redacted() {
        let credential = SessionCredential::from_token_for_test(TEST_TOKEN);
        let bootstrap = BootstrapMessage::new(&credential);
        let encoded = encode_json_line_bounded(&bootstrap, MAX_BOOTSTRAP_BYTES).unwrap();

        assert!(encoded.len() <= MAX_BOOTSTRAP_BYTES);
        assert!(encoded.ends_with(b"\n"));
        assert_eq!(format!("{credential:?}"), "SessionCredential([REDACTED])");
        assert!(!format!("{credential:?}").contains(TEST_TOKEN));
    }

    #[test]
    fn oversized_json_line_fails_closed() {
        let oversized = json!({ "padding": "x".repeat(MAX_BOOTSTRAP_BYTES) });
        let error = encode_json_line_bounded(&oversized, MAX_BOOTSTRAP_BYTES).unwrap_err();
        assert!(matches!(error, ContractError::MessageTooLarge { .. }));
    }

    #[test]
    fn local_ai_workspace_contract_is_closed_and_redacts_document_content() {
        let request_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "task": "QUESTION",
            "question": "Which synthetic records are connected?",
            "scopes": ["GRAPH", "DOCUMENT"],
            "includeSensitiveEntities": false,
            "execution": "LOCAL_MODEL",
            "modelId": "synthetic-model:latest",
            "document": {
                "kind": "PASTE",
                "displayName": "Pasted text",
                "declaredMediaType": "text/plain",
                "content": "Synthetic workspace content",
                "contentSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
        });
        let request: CoreLocalAiWorkspaceRequest =
            serde_json::from_value(request_value.clone()).unwrap();
        assert_eq!(
            format!("{request:?}"),
            "CoreLocalAiWorkspaceRequest([REDACTED])"
        );
        assert!(!format!("{request:?}").contains("Synthetic workspace content"));

        let mut unknown_field = request_value.clone();
        unknown_field["allowCloudFallback"] = json!(true);
        assert!(serde_json::from_value::<CoreLocalAiWorkspaceRequest>(unknown_field).is_err());
        let mut open_task = request_value;
        open_task["task"] = json!("AUTONOMOUS_ACTION");
        assert!(serde_json::from_value::<CoreLocalAiWorkspaceRequest>(open_task).is_err());
    }

    #[test]
    fn graph_edge_evidence_uses_closed_enums_and_redacted_debug() {
        let evidence: CoreGraphEdgeEvidence = serde_json::from_value(json!({
            "sourceId": "00000000-0000-0000-0000-000000000001",
            "segmentOrdinal": 3,
            "sourceSpanStart": null,
            "sourceSpanEnd": null,
            "disposition": "SUPPORTS",
            "confidenceMicros": 900_000,
            "visibility": "PRIVATE_ONLY",
            "observedAtUs": 1_700_000_000_000_000_u64,
            "originType": "DETERMINISTIC",
            "explanation": "Synthetic supporting observation"
        }))
        .unwrap();

        let debug = format!("{evidence:?}");
        assert_eq!(debug, "CoreGraphEdgeEvidence([REDACTED])");
        assert!(!debug.contains("Synthetic supporting observation"));
        let mut missing_nullable_span = serde_json::to_value(&evidence).unwrap();
        missing_nullable_span
            .as_object_mut()
            .unwrap()
            .remove("sourceSpanStart");
        assert!(
            serde_json::from_value::<CoreGraphEdgeEvidence>(missing_nullable_span).is_err(),
            "mandatory nullable provenance fields must be present"
        );
        assert!(
            serde_json::from_value::<CoreGraphEdgeEvidence>(json!({
                "sourceId": "00000000-0000-0000-0000-000000000001",
                "segmentOrdinal": 3,
                "sourceSpanStart": null,
                "sourceSpanEnd": null,
                "disposition": "SUPPORTS",
                "confidenceMicros": 900_000,
                "visibility": "INTERNET_VISIBLE",
                "observedAtUs": 1_700_000_000_000_000_u64,
                "originType": "DETERMINISTIC",
                "explanation": "Synthetic supporting observation"
            }))
            .is_err()
        );
    }

    #[test]
    fn phase5_artifact_contract_requires_explicit_nullables_and_closed_enums() {
        let artifact: CorePhase5EvidenceArtifact = serde_json::from_value(json!({
            "artifactId": "00000000-0000-0000-0000-000000000001",
            "kind": "RAW_JSON",
            "contentSha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "capturedAtUs": 1_700_000_000_000_000_u64,
            "sourceUrl": null,
            "httpStatus": null,
            "redirectCount": 0,
            "providerId": "synthetic-provider",
            "runId": "00000000-0000-0000-0000-000000000002",
            "viewport": null,
            "captureMethod": "PROVIDER_API",
            "encryptedAtRest": true,
            "integrityStatus": "VERIFIED",
            "derivativeCount": 0
        }))
        .unwrap();
        assert_eq!(
            format!("{artifact:?}"),
            "CorePhase5EvidenceArtifact([REDACTED])"
        );

        let mut missing_nullable = serde_json::to_value(&artifact).unwrap();
        missing_nullable
            .as_object_mut()
            .unwrap()
            .remove("sourceUrl");
        assert!(serde_json::from_value::<CorePhase5EvidenceArtifact>(missing_nullable).is_err());

        let mut open_enum = serde_json::to_value(&artifact).unwrap();
        open_enum["integrityStatus"] = json!("ASSUMED_VALID");
        assert!(serde_json::from_value::<CorePhase5EvidenceArtifact>(open_enum).is_err());
    }

    #[test]
    fn phase5_write_contract_redacts_bytes_and_requires_nullable_viewport() {
        let request: CorePhase5ManualEvidenceImportRequest = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "findingId": "00000000-0000-4000-8000-000000000002",
            "kind": "HTML",
            "contentBase64": "c3ludGhldGlj",
            "viewport": null,
            "metadata": []
        }))
        .unwrap();
        assert_eq!(
            format!("{request:?}"),
            "CorePhase5ManualEvidenceImportRequest([REDACTED])"
        );
        assert!(!format!("{request:?}").contains("c3ludGhldGlj"));

        let mut missing_nullable = serde_json::to_value(&request).unwrap();
        missing_nullable.as_object_mut().unwrap().remove("viewport");
        assert!(
            serde_json::from_value::<CorePhase5ManualEvidenceImportRequest>(missing_nullable)
                .is_err()
        );
    }

    #[test]
    fn phase5_manual_finding_contract_is_closed_canonical_and_redacted() {
        let request_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "title": "Synthetic local finding",
            "summary": "Synthetic summary with no personal information.",
            "outcome": "MANUAL_REVIEW_REQUIRED",
            "severity": "LOW",
            "visibility": "UNKNOWN",
            "providerId": "synthetic-provider",
            "providerLabel": "Synthetic provider"
        });
        let request: CorePhase5ManualFindingCreateRequest =
            serde_json::from_value(request_value.clone()).unwrap();
        let debug = format!("{request:?}");
        assert_eq!(debug, "CorePhase5ManualFindingCreateRequest([REDACTED])");
        assert!(!debug.contains("Synthetic local finding"));

        let mut noncanonical = request_value.clone();
        noncanonical["profileId"] = json!("00000000-0000-4000-8000-00000000000A");
        assert!(
            serde_json::from_value::<CorePhase5ManualFindingCreateRequest>(noncanonical).is_err()
        );
        let mut open_outcome = request_value.clone();
        open_outcome["outcome"] = json!("AUTOMATICALLY_CONFIRMED");
        assert!(
            serde_json::from_value::<CorePhase5ManualFindingCreateRequest>(open_outcome).is_err()
        );
        let mut unknown_field = request_value;
        unknown_field["networkEnabled"] = json!(true);
        assert!(
            serde_json::from_value::<CorePhase5ManualFindingCreateRequest>(unknown_field).is_err()
        );
    }

    #[test]
    fn phase6_local_checkpoint_contract_is_closed_and_redacted() {
        let request_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "runState": "PARTIAL",
            "providerCoverage": [{
                "providerId": "synthetic-provider",
                "state": "CHECK_FAILED"
            }]
        });
        let request: CorePhase6LocalCheckpointRequest =
            serde_json::from_value(request_value.clone()).unwrap();
        assert_eq!(
            format!("{request:?}"),
            "CorePhase6LocalCheckpointRequest([REDACTED])"
        );

        let mut unknown_field = request_value.clone();
        unknown_field["networkEnabled"] = json!(true);
        assert!(serde_json::from_value::<CorePhase6LocalCheckpointRequest>(unknown_field).is_err());
        let mut open_coverage = request_value.clone();
        open_coverage["providerCoverage"][0]["state"] = json!("UNKNOWN");
        assert!(serde_json::from_value::<CorePhase6LocalCheckpointRequest>(open_coverage).is_err());
        let mut noncanonical_uuid = request_value;
        noncanonical_uuid["profileId"] = json!("00000000-0000-4000-8000-00000000000A");
        assert!(
            serde_json::from_value::<CorePhase6LocalCheckpointRequest>(noncanonical_uuid).is_err()
        );

        let result: CorePhase6LocalCheckpointResult = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "runId": "00000000-0000-4000-8000-000000000002",
            "sequence": 2,
            "capturedAtUs": 1_700_000_000_000_000_u64,
            "runState": "PARTIAL",
            "findingCount": 1,
            "providerCount": 1,
            "localOnly": true
        }))
        .unwrap();
        assert_eq!(
            format!("{result:?}"),
            "CorePhase6LocalCheckpointResult([REDACTED])"
        );
    }

    #[test]
    fn phase6_history_contract_is_closed_nullable_and_redacted() {
        let history: CorePhase6RemediationHistoryEntry = serde_json::from_value(json!({
            "revision": 1,
            "eventType": "CASE_CREATED",
            "actorLabel": "Local user",
            "occurredAtUs": 1_700_000_000_000_000_u64,
            "previousStatus": null,
            "currentStatus": "OPEN",
            "detailCode": "CASE_CREATED",
            "subjectId": null,
            "evidenceReferences": [],
            "note": "Synthetic local note"
        }))
        .unwrap();
        assert_eq!(
            format!("{history:?}"),
            "CorePhase6RemediationHistoryEntry([REDACTED])"
        );
        assert!(!format!("{history:?}").contains("Synthetic local note"));

        let mut missing_nullable = serde_json::to_value(&history).unwrap();
        missing_nullable.as_object_mut().unwrap().remove("note");
        assert!(
            serde_json::from_value::<CorePhase6RemediationHistoryEntry>(missing_nullable).is_err()
        );
        let mut open_enum = serde_json::to_value(&history).unwrap();
        open_enum["eventType"] = json!("SENT_AUTOMATICALLY");
        assert!(serde_json::from_value::<CorePhase6RemediationHistoryEntry>(open_enum).is_err());
    }

    #[test]
    fn phase6_mutation_contracts_are_closed_explicit_nullable_and_redacted() {
        let create_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "findingIds": ["00000000-0000-4000-8000-000000000002"],
            "action": "REQUEST_CORRECTION",
            "deadlineAtUs": null,
            "evidenceReferences": ["00000000-0000-4000-8000-000000000003"],
            "draftText": "Synthetic draft text"
        });
        let create: CorePhase6RemediationCreateRequest =
            serde_json::from_value(create_value.clone()).unwrap();
        let create_debug = format!("{create:?}");
        assert_eq!(
            create_debug,
            "CorePhase6RemediationCreateRequest([REDACTED])"
        );
        assert!(!create_debug.contains("Synthetic draft text"));

        let mut missing_deadline = create_value.clone();
        missing_deadline
            .as_object_mut()
            .unwrap()
            .remove("deadlineAtUs");
        assert!(
            serde_json::from_value::<CorePhase6RemediationCreateRequest>(missing_deadline).is_err()
        );
        let mut missing_draft = create_value.clone();
        missing_draft.as_object_mut().unwrap().remove("draftText");
        assert!(
            serde_json::from_value::<CorePhase6RemediationCreateRequest>(missing_draft).is_err()
        );
        let mut open_action = create_value;
        open_action["action"] = json!("AUTOMATIC_SEND");
        assert!(serde_json::from_value::<CorePhase6RemediationCreateRequest>(open_action).is_err());

        let mut noncanonical_uuid = serde_json::to_value(&create).unwrap();
        noncanonical_uuid["profileId"] = json!("00000000-0000-4000-8000-00000000000A");
        assert!(
            serde_json::from_value::<CorePhase6RemediationCreateRequest>(noncanonical_uuid)
                .is_err()
        );

        let draft: CorePhase6RemediationDraftUpdateRequest = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "caseId": "00000000-0000-4000-8000-000000000004",
            "expectedRevision": 1,
            "draftText": "Synthetic revised draft"
        }))
        .unwrap();
        assert_eq!(
            format!("{draft:?}"),
            "CorePhase6RemediationDraftUpdateRequest([REDACTED])"
        );

        let status_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "caseId": "00000000-0000-4000-8000-000000000004",
            "expectedRevision": 1,
            "targetStatus": "IN_PROGRESS",
            "note": "Synthetic status note"
        });
        let status: CorePhase6RemediationStatusTransitionRequest =
            serde_json::from_value(status_value.clone()).unwrap();
        assert_eq!(
            format!("{status:?}"),
            "CorePhase6RemediationStatusTransitionRequest([REDACTED])"
        );
        let mut missing_note = status_value;
        missing_note.as_object_mut().unwrap().remove("note");
        assert!(
            serde_json::from_value::<CorePhase6RemediationStatusTransitionRequest>(missing_note)
                .is_err()
        );

        let provider: CorePhase6RemediationProviderResponseRequest =
            serde_json::from_value(json!({
                "profileId": "00000000-0000-4000-8000-000000000001",
                "caseId": "00000000-0000-4000-8000-000000000004",
                "expectedRevision": 1,
                "providerId": "synthetic-provider",
                "responseCode": "REQUEST_RECEIVED",
                "summary": "Synthetic provider summary",
                "evidenceReferences": []
            }))
            .unwrap();
        let provider_debug = format!("{provider:?}");
        assert_eq!(
            provider_debug,
            "CorePhase6RemediationProviderResponseRequest([REDACTED])"
        );
        assert!(!provider_debug.contains("Synthetic provider summary"));

        let mut deadline_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "caseId": "00000000-0000-4000-8000-000000000004",
            "expectedRevision": 1,
            "deadlineAtUs": null
        });
        deadline_value
            .as_object_mut()
            .unwrap()
            .remove("deadlineAtUs");
        assert!(
            serde_json::from_value::<CorePhase6RemediationDeadlineUpdateRequest>(deadline_value)
                .is_err()
        );
    }

    #[test]
    fn local_report_contract_is_closed_canonical_and_redacted() {
        let request_value = json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "baselineRunId": "00000000-0000-4000-8000-000000000002",
            "currentRunId": "00000000-0000-4000-8000-000000000003",
            "artifactFormat": "MARKDOWN",
            "mode": "FULL_EXPLICIT",
            "fullExportApprovalId": "00000000-0000-4000-8000-000000000004"
        });
        let request: CoreLocalReportGenerateRequest =
            serde_json::from_value(request_value.clone()).unwrap();
        assert_eq!(
            format!("{request:?}"),
            "CoreLocalReportGenerateRequest([REDACTED])"
        );

        let mut missing_approval = request_value.clone();
        missing_approval
            .as_object_mut()
            .unwrap()
            .remove("fullExportApprovalId");
        assert!(
            serde_json::from_value::<CoreLocalReportGenerateRequest>(missing_approval).is_err()
        );
        let mut noncanonical = request_value.clone();
        noncanonical["profileId"] = json!("00000000-0000-4000-8000-00000000000A");
        assert!(serde_json::from_value::<CoreLocalReportGenerateRequest>(noncanonical).is_err());
        let mut open_format = request_value.clone();
        open_format["artifactFormat"] = json!("HTML");
        assert!(serde_json::from_value::<CoreLocalReportGenerateRequest>(open_format).is_err());
        let mut unknown_field = request_value;
        unknown_field["send"] = json!(true);
        assert!(serde_json::from_value::<CoreLocalReportGenerateRequest>(unknown_field).is_err());

        let content = "# Synthetic local report\n";
        let sha256 = "d61fb72359c524f681bae4506c8849aeecdb244969e09630d067ee4b64b7209d";
        let result: CoreLocalReportGenerateResult = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "baselineRunId": "00000000-0000-4000-8000-000000000002",
            "currentRunId": "00000000-0000-4000-8000-000000000003",
            "localOnly": true,
            "artifact": {
                "filename": "report.md",
                "mediaType": "text/markdown; charset=utf-8",
                "byteCount": content.len(),
                "sha256": sha256,
                "schema": "ariadne.local-report",
                "version": 1,
                "mode": "FULL_EXPLICIT",
                "content": content
            },
            "manifest": {
                "schema": "ariadne.local-report",
                "version": 1,
                "mode": "FULL_EXPLICIT",
                "generatedAtUs": 1_700_000_000_000_000_u64,
                "fullExportApprovalId": "00000000-0000-4000-8000-000000000004",
                "artifacts": [{
                    "filename": "report.json",
                    "mediaType": "application/json",
                    "byteCount": 2,
                    "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
                }, {
                    "filename": "report.md",
                    "mediaType": "text/markdown; charset=utf-8",
                    "byteCount": content.len(),
                    "sha256": sha256
                }]
            }
        }))
        .unwrap();
        let debug = format!("{result:?}");
        assert_eq!(debug, "CoreLocalReportGenerateResult([REDACTED])");
        assert!(!debug.contains(content));
    }

    #[test]
    fn hibp_and_investigation_requests_are_closed_and_redacted() {
        let key = "0123456789abcdef0123456789abcdef";
        let email = "synthetic.user@example.invalid";
        let account: CoreHibpAccountRequest = serde_json::from_value(json!({
            "email": email,
            "apiKey": key,
            "authorizedSelfAudit": true
        }))
        .unwrap();
        assert_eq!(account.mode, CoreHibpAccountMode::KAnonymity);
        let debug = format!("{account:?}");
        assert_eq!(debug, "CoreHibpAccountRequest([REDACTED])");
        assert!(!debug.contains(key));
        assert!(!debug.contains(email));

        let mut unknown = json!({
            "domain": "example.invalid",
            "apiKey": key,
            "authorizedSelfAudit": true,
            "persistApiKey": true
        });
        assert!(serde_json::from_value::<CoreHibpDomainRequest>(unknown.clone()).is_err());
        unknown.as_object_mut().unwrap().remove("persistApiKey");
        let domain: CoreHibpDomainRequest = serde_json::from_value(unknown).unwrap();
        assert_eq!(format!("{domain:?}"), "CoreHibpDomainRequest([REDACTED])");

        let plan: CoreInvestigationPlanRequest = serde_json::from_value(json!({
            "identifiers": [{
                "identifierRef": "synthetic-email",
                "kind": "EMAIL",
                "value": email
            }],
            "authorizedSelfAudit": true
        }))
        .unwrap();
        assert_eq!(plan.enabled_providers.len(), 3);
        let debug = format!("{plan:?}");
        assert_eq!(debug, "CoreInvestigationPlanRequest([REDACTED])");
        assert!(!debug.contains(email));
        assert_eq!(
            serde_json::to_value(CoreHibpProvider::HaveIBeenPwnedV3).unwrap(),
            json!("HAVE_I_BEEN_PWNED_V3")
        );
        assert_eq!(
            serde_json::to_value(CoreHibpAccountMode::KAnonymity).unwrap(),
            json!("K_ANONYMITY")
        );
    }

    #[test]
    fn route_allowlist_contains_only_route_specific_boundaries() {
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/events/replay"),
            Some(CoreRoute::ReplayEvents)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("GET", "/v1/system/capabilities"),
            Some(CoreRoute::Capabilities)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("GET", "/v1/session"),
            Some(CoreRoute::Session)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/vaults"),
            Some(CoreRoute::CreateVault)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/vaults/current/lock"),
            Some(CoreRoute::LockCurrentVault)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/vaults/current/unlock"),
            Some(CoreRoute::UnlockCurrentVault)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("GET", "/v1/profiles"),
            Some(CoreRoute::ListProfiles)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/profiles"),
            Some(CoreRoute::CreateProfile)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/intake/paste"),
            Some(CoreRoute::IntakePaste)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/intake/file"),
            Some(CoreRoute::IntakeFile)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/intake/review"),
            Some(CoreRoute::ReviewEntities)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/entities/decision"),
            Some(CoreRoute::DecideEntity)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/entities/origins"),
            Some(CoreRoute::EntityOrigins)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/graph/snapshot"),
            Some(CoreRoute::GraphSnapshot)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("GET", "/v1/local-ai/settings"),
            Some(CoreRoute::GetLocalAiSettings)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/local-ai/settings"),
            Some(CoreRoute::UpdateLocalAiSettings)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/local-ai/models"),
            Some(CoreRoute::DiscoverLocalAiModels)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/local-ai/test"),
            Some(CoreRoute::TestLocalAiConnection)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/local-ai/workspace/analyze"),
            Some(CoreRoute::AnalyzeLocalAiWorkspace)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/local-ai/corpus/analyze"),
            Some(CoreRoute::AnalyzeLocalAiCorpus)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/query/providers"),
            Some(CoreRoute::QueryProviders)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/query/plans"),
            Some(CoreRoute::CreateQueryPlan)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/query/dry-run"),
            Some(CoreRoute::ExecuteQueryDryRun)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/findings/list"),
            Some(CoreRoute::ListPhase5Findings)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/findings/detail"),
            Some(CoreRoute::GetPhase5Finding)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/findings/manual"),
            Some(CoreRoute::CreatePhase5ManualFinding)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/evidence/manual-import"),
            Some(CoreRoute::ImportPhase5Evidence)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/evidence/redacted-derivative"),
            Some(CoreRoute::CreatePhase5RedactedDerivative)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase5/attribution/decision"),
            Some(CoreRoute::AppendPhase5AttributionDecision)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/audits/list"),
            Some(CoreRoute::ListPhase6AuditRuns)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/audits/local-checkpoint"),
            Some(CoreRoute::CreatePhase6LocalCheckpoint)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/audits/compare"),
            Some(CoreRoute::ComparePhase6Runs)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/list"),
            Some(CoreRoute::ListPhase6RemediationCases)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/detail"),
            Some(CoreRoute::GetPhase6RemediationCase)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/create"),
            Some(CoreRoute::CreatePhase6RemediationCase)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/draft"),
            Some(CoreRoute::UpdatePhase6RemediationDraft)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/require-approval"),
            Some(CoreRoute::RequirePhase6RemediationApproval)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/status"),
            Some(CoreRoute::TransitionPhase6RemediationStatus)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/deadline"),
            Some(CoreRoute::SetPhase6RemediationDeadline)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/evidence"),
            Some(CoreRoute::LinkPhase6RemediationEvidence)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/provider-response"),
            Some(CoreRoute::RecordPhase6ProviderResponse)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/phase6/remediation/reappearance"),
            Some(CoreRoute::RecordPhase6Reappearance)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/reports/generate"),
            Some(CoreRoute::GenerateLocalReport)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/workspace"),
            Some(CoreRoute::GetIdentityWorkspace)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/person"),
            Some(CoreRoute::UpdateIdentityPerson)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/source"),
            Some(CoreRoute::CreateIdentitySource)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/audits"),
            Some(CoreRoute::CreateIdentityAudit)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/audits/detail"),
            Some(CoreRoute::GetIdentityAudit)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/audits/execute"),
            Some(CoreRoute::ExecuteIdentityAuditBatch)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/audits/control"),
            Some(CoreRoute::ControlIdentityAudit)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/identity/proposals/decision"),
            Some(CoreRoute::DecideIdentityProposal)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/discovery/public/capture"),
            Some(CoreRoute::CapturePublicDiscovery)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/discovery/public/search"),
            Some(CoreRoute::SearchPublicDiscovery)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/discovery/investigation/plan"),
            Some(CoreRoute::CompileInvestigationPlan)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/discovery/hibp/account"),
            Some(CoreRoute::SearchHibpAccount)
        );
        assert_eq!(
            CoreRoute::from_method_and_path("POST", "/v1/discovery/hibp/domain"),
            Some(CoreRoute::SearchHibpDomain)
        );
        let capture_capability = CoreRoute::CapturePublicDiscovery.capability();
        assert_eq!(capture_capability.required_lock_state, "UNLOCKED");
        assert_eq!(capture_capability.scope_class, "PROFILE");
        assert_eq!(capture_capability.max_request_bytes, 8_192);
        assert_eq!(capture_capability.max_response_bytes, 4_096);
        let public_discovery_capability = CoreRoute::SearchPublicDiscovery.capability();
        assert_eq!(public_discovery_capability.required_lock_state, "ANY");
        assert_eq!(public_discovery_capability.scope_class, "NONE");
        assert_eq!(public_discovery_capability.max_request_bytes, 8_192);
        assert_eq!(public_discovery_capability.max_response_bytes, 262_144);
        let investigation_capability = CoreRoute::CompileInvestigationPlan.capability();
        assert_eq!(investigation_capability.required_lock_state, "ANY");
        assert_eq!(investigation_capability.scope_class, "NONE");
        assert_eq!(investigation_capability.max_request_bytes, 40_960);
        assert_eq!(investigation_capability.max_response_bytes, 262_144);
        for route in [CoreRoute::SearchHibpAccount, CoreRoute::SearchHibpDomain] {
            let capability = route.capability();
            assert_eq!(capability.required_lock_state, "ANY");
            assert_eq!(capability.scope_class, "NONE");
            assert_eq!(capability.max_request_bytes, 4_096);
            assert_eq!(capability.max_response_bytes, 1_048_576);
        }
        let report_capability = CoreRoute::GenerateLocalReport.capability();
        assert_eq!(report_capability.max_request_bytes, 1_024);
        assert_eq!(report_capability.max_response_bytes, 1_000_000);
        let entity_origins_capability = CoreRoute::EntityOrigins.capability();
        assert_eq!(entity_origins_capability.required_lock_state, "UNLOCKED");
        assert_eq!(entity_origins_capability.scope_class, "PROFILE");
        assert_eq!(entity_origins_capability.max_request_bytes, 512);
        assert_eq!(entity_origins_capability.max_response_bytes, 1_048_576);
        let manual_finding_capability = CoreRoute::CreatePhase5ManualFinding.capability();
        assert_eq!(manual_finding_capability.max_request_bytes, 4_096);
        assert_eq!(manual_finding_capability.max_response_bytes, 1_048_576);
        assert_eq!(CoreRoute::from_method_and_path("POST", "/v1/session"), None);
        assert_eq!(
            CoreRoute::from_method_and_path("GET", "/v1/providers"),
            None
        );
    }

    #[test]
    fn rust_command_enum_exactly_matches_generated_route_metadata() {
        let manual_routes = [
            CoreRoute::Capabilities,
            CoreRoute::ReplayEvents,
            CoreRoute::Session,
            CoreRoute::CreateVault,
            CoreRoute::LockCurrentVault,
            CoreRoute::UnlockCurrentVault,
            CoreRoute::ListProfiles,
            CoreRoute::CreateProfile,
            CoreRoute::IntakePaste,
            CoreRoute::IntakeFile,
            CoreRoute::ReviewEntities,
            CoreRoute::DecideEntity,
            CoreRoute::EntityOrigins,
            CoreRoute::GraphSnapshot,
            CoreRoute::GetLocalAiSettings,
            CoreRoute::UpdateLocalAiSettings,
            CoreRoute::DiscoverLocalAiModels,
            CoreRoute::TestLocalAiConnection,
            CoreRoute::AnalyzeLocalAiWorkspace,
            CoreRoute::AnalyzeLocalAiCorpus,
            CoreRoute::CapturePublicDiscovery,
            CoreRoute::SearchPublicDiscovery,
            CoreRoute::CompileInvestigationPlan,
            CoreRoute::SearchHibpAccount,
            CoreRoute::SearchHibpDomain,
            CoreRoute::QueryProviders,
            CoreRoute::CreateQueryPlan,
            CoreRoute::ExecuteQueryDryRun,
            CoreRoute::ListPhase5Findings,
            CoreRoute::GetPhase5Finding,
            CoreRoute::CreatePhase5ManualFinding,
            CoreRoute::ImportPhase5Evidence,
            CoreRoute::CreatePhase5RedactedDerivative,
            CoreRoute::AppendPhase5AttributionDecision,
            CoreRoute::ListPhase6AuditRuns,
            CoreRoute::CreatePhase6LocalCheckpoint,
            CoreRoute::ComparePhase6Runs,
            CoreRoute::ListPhase6RemediationCases,
            CoreRoute::GetPhase6RemediationCase,
            CoreRoute::CreatePhase6RemediationCase,
            CoreRoute::UpdatePhase6RemediationDraft,
            CoreRoute::RequirePhase6RemediationApproval,
            CoreRoute::TransitionPhase6RemediationStatus,
            CoreRoute::SetPhase6RemediationDeadline,
            CoreRoute::LinkPhase6RemediationEvidence,
            CoreRoute::RecordPhase6ProviderResponse,
            CoreRoute::RecordPhase6Reappearance,
            CoreRoute::GenerateLocalReport,
            CoreRoute::GetIdentityWorkspace,
            CoreRoute::UpdateIdentityPerson,
            CoreRoute::CreateIdentitySource,
            CoreRoute::CreateIdentityAudit,
            CoreRoute::GetIdentityAudit,
            CoreRoute::ExecuteIdentityAuditBatch,
            CoreRoute::ControlIdentityAudit,
            CoreRoute::DecideIdentityProposal,
        ];
        assert_eq!(
            manual_routes.len(),
            generated_allowlist::ROUTE_CAPABILITIES.len()
        );

        for capability in generated_allowlist::ROUTE_CAPABILITIES {
            let route = CoreRoute::from_method_and_path(capability.method, capability.path)
                .expect("generated route has no route-specific Rust command");
            assert_eq!(route.capability(), capability);
            if capability.method == "GET" || route == CoreRoute::LockCurrentVault {
                assert_eq!(capability.max_request_bytes, 0);
            } else {
                assert!(capability.max_request_bytes > 0);
            }
            if matches!(
                route,
                CoreRoute::ListProfiles
                    | CoreRoute::CreateProfile
                    | CoreRoute::IntakePaste
                    | CoreRoute::IntakeFile
                    | CoreRoute::ReviewEntities
                    | CoreRoute::DecideEntity
                    | CoreRoute::EntityOrigins
                    | CoreRoute::GraphSnapshot
                    | CoreRoute::GetLocalAiSettings
                    | CoreRoute::UpdateLocalAiSettings
                    | CoreRoute::DiscoverLocalAiModels
                    | CoreRoute::TestLocalAiConnection
                    | CoreRoute::AnalyzeLocalAiWorkspace
                    | CoreRoute::AnalyzeLocalAiCorpus
                    | CoreRoute::CapturePublicDiscovery
                    | CoreRoute::QueryProviders
                    | CoreRoute::CreateQueryPlan
                    | CoreRoute::ExecuteQueryDryRun
                    | CoreRoute::ListPhase5Findings
                    | CoreRoute::GetPhase5Finding
                    | CoreRoute::CreatePhase5ManualFinding
                    | CoreRoute::ImportPhase5Evidence
                    | CoreRoute::CreatePhase5RedactedDerivative
                    | CoreRoute::AppendPhase5AttributionDecision
                    | CoreRoute::ListPhase6AuditRuns
                    | CoreRoute::CreatePhase6LocalCheckpoint
                    | CoreRoute::ComparePhase6Runs
                    | CoreRoute::ListPhase6RemediationCases
                    | CoreRoute::GetPhase6RemediationCase
                    | CoreRoute::CreatePhase6RemediationCase
                    | CoreRoute::UpdatePhase6RemediationDraft
                    | CoreRoute::RequirePhase6RemediationApproval
                    | CoreRoute::TransitionPhase6RemediationStatus
                    | CoreRoute::SetPhase6RemediationDeadline
                    | CoreRoute::LinkPhase6RemediationEvidence
                    | CoreRoute::RecordPhase6ProviderResponse
                    | CoreRoute::RecordPhase6Reappearance
                    | CoreRoute::GenerateLocalReport
                    | CoreRoute::GetIdentityWorkspace
                    | CoreRoute::UpdateIdentityPerson
                    | CoreRoute::CreateIdentitySource
                    | CoreRoute::CreateIdentityAudit
                    | CoreRoute::GetIdentityAudit
                    | CoreRoute::ExecuteIdentityAuditBatch
                    | CoreRoute::ControlIdentityAudit
                    | CoreRoute::DecideIdentityProposal
            ) {
                assert_eq!(capability.required_lock_state, "UNLOCKED");
            }
            assert!(capability.max_response_bytes <= MAX_RESPONSE_BYTES);
        }
    }
}
