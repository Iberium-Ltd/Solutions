//! Lifecycle and capability boundary for the Python core sidecar.
//!
//! The supervisor owns the child, its unguessable session credential, validated
//! endpoint, key-lease channel, and lock state. No webview command receives a
//! generic HTTP primitive; each request uses a closed route and validates its
//! bounded response before returning data to the UI.

use std::{
    collections::{HashMap, HashSet, VecDeque},
    ffi::OsString,
    net::IpAddr,
    path::{Path, PathBuf},
    process::Stdio,
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use reqwest::{
    Client, Method, StatusCode,
    header::{ACCEPT, CONTENT_TYPE, HOST, HeaderMap, HeaderValue, ORIGIN},
    redirect::Policy,
};
use serde::{Serialize, de::DeserializeOwned};
use sha2::{Digest, Sha256};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, Command},
    time::timeout,
};
use uuid::Uuid;
use zeroize::Zeroizing;

use crate::security::KeyCustody;

use super::contract::{
    BootstrapMessage, CONTRACT_VERSION, ContractError, CoreCapabilities, CoreCommandError,
    CoreCommandResponse, CoreEntityDecisionRequest, CoreEntityDecisionType, CoreEntityOrigin,
    CoreEntityOriginPageRequest, CoreEntityOriginPageResult, CoreEntityReviewRequest,
    CoreEntityReviewResult, CoreEntitySummary, CoreFileIntakeRequest, CoreGraphEvidenceDisposition,
    CoreGraphSnapshot, CoreGraphSnapshotRequest, CoreHibpAccountMode, CoreHibpAccountRequest,
    CoreHibpAccountResult, CoreHibpBreachReference, CoreHibpDomainRequest, CoreHibpDomainResult,
    CoreHibpIdentifierDisclosure, CoreHibpOperation, CoreHibpProvider, CoreHibpReason,
    CoreHibpRequestMetadata, CoreHibpState, CoreIdentityAiAnalysis,
    CoreIdentityAuditControlRequest, CoreIdentityAuditCreateRequest, CoreIdentityAuditDetail,
    CoreIdentityAuditExecuteRequest, CoreIdentityAuditSummary, CoreIdentityDiscoveryLead,
    CoreIdentityDiscoveryResult, CoreIdentityFrontierTask, CoreIdentityKnowledgeProposal,
    CoreIdentityPersonUpdateRequest, CoreIdentityProposalDecisionRequest, CoreIdentitySource,
    CoreIdentitySourceCreateRequest, CoreIdentityTaskState, CoreIdentityToolReceipt,
    CoreIdentityWorkspace, CoreIdentityWorkspaceRequest, CoreIntakeReceipt,
    CoreInvestigationIdentifierKind, CoreInvestigationNotice, CoreInvestigationOperation,
    CoreInvestigationPlanRequest, CoreInvestigationPlanResult, CoreInvestigationPlanStep,
    CoreInvestigationPrerequisite, CoreInvestigationProvider, CoreInvestigationTransmission,
    CoreLocalAiConnectionResult, CoreLocalAiConnectionStatus, CoreLocalAiEndpointRequest,
    CoreLocalAiIntakeStatus, CoreLocalAiModelDiscoveryResult, CoreLocalAiProvider,
    CoreLocalAiSettings, CoreLocalAiSettingsUpdateRequest, CoreLocalAiWorkspaceConnection,
    CoreLocalAiWorkspaceDocument, CoreLocalAiWorkspaceDocumentKind, CoreLocalAiWorkspaceExecution,
    CoreLocalAiWorkspaceFact, CoreLocalAiWorkspaceNextStep, CoreLocalAiWorkspaceRequest,
    CoreLocalAiWorkspaceResult, CoreLocalAiWorkspaceScope, CoreLocalAiWorkspaceSection,
    CoreLocalAiWorkspaceSource, CoreLocalAiWorkspaceSourceCounts, CoreLocalAiWorkspaceTask,
    CoreLocalCorpusAiConnection, CoreLocalCorpusAiContentOrigin, CoreLocalCorpusAiCounts,
    CoreLocalCorpusAiExecution, CoreLocalCorpusAiFact, CoreLocalCorpusAiNextStep,
    CoreLocalCorpusAiReferenceKind, CoreLocalCorpusAiRequest, CoreLocalCorpusAiResult,
    CoreLocalCorpusAiReviewNote, CoreLocalCorpusAiSection, CoreLocalCorpusAiSourceCatalogEntry,
    CoreLocalCorpusAiSourcePointer, CoreLocalCorpusAiTask, CoreLocalCorpusAiTextLabel,
    CoreLocalCorpusDocumentRequest, CoreLocalCorpusMediaType, CoreLocalReportArtifact,
    CoreLocalReportArtifactDescriptor, CoreLocalReportGenerateRequest,
    CoreLocalReportGenerateResult, CoreLocalReportSchema, CorePasteIntakeRequest,
    CorePhase5ArtifactKind, CorePhase5AttributionAssessment, CorePhase5AttributionDecisionRequest,
    CorePhase5AttributionDecisionResult, CorePhase5CaptureMethod, CorePhase5CheckOutcome,
    CorePhase5ConfidenceBand, CorePhase5EvidenceArtifact, CorePhase5EvidenceViewport,
    CorePhase5FindingDetailRequest, CorePhase5FindingDetailResult, CorePhase5FindingListRequest,
    CorePhase5FindingListResult, CorePhase5FindingSummary, CorePhase5ManualArtifactKind,
    CorePhase5ManualEvidenceImportRequest, CorePhase5ManualEvidenceImportResult,
    CorePhase5ManualFindingCreateRequest, CorePhase5PositiveSignal,
    CorePhase5RedactedDerivativeRequest, CorePhase5RedactedDerivativeResult, CorePhase5Severity,
    CorePhase5Visibility, CorePhase6ActionDisposition, CorePhase6AuditRunListRequest,
    CorePhase6AuditRunListResult, CorePhase6AuditRunSummary, CorePhase6CompareRunsRequest,
    CorePhase6ComparisonResult, CorePhase6FindingDiff, CorePhase6FindingDiffState,
    CorePhase6FindingLifecycle, CorePhase6LifecycleEvent, CorePhase6LocalCheckpointRequest,
    CorePhase6LocalCheckpointResult, CorePhase6ProviderCoverageComparison,
    CorePhase6ProviderResponse, CorePhase6RemediationAction, CorePhase6RemediationCase,
    CorePhase6RemediationCaseSummary, CorePhase6RemediationCreateRequest,
    CorePhase6RemediationDeadlineUpdateRequest, CorePhase6RemediationDetailRequest,
    CorePhase6RemediationDetailResult, CorePhase6RemediationDraftUpdateRequest,
    CorePhase6RemediationEventType, CorePhase6RemediationEvidenceLinkRequest,
    CorePhase6RemediationHistoryEntry, CorePhase6RemediationListRequest,
    CorePhase6RemediationListResult, CorePhase6RemediationProviderResponseRequest,
    CorePhase6RemediationReappearanceRequest, CorePhase6RemediationRequireApprovalRequest,
    CorePhase6RemediationStatus, CorePhase6RemediationStatusTransitionRequest,
    CorePhase6SnapshotRunState, CorePhase6UnresolvedAbsence, CoreProfileCreateRequest,
    CoreProfileDeleteRequest, CoreProfileDeleteResult, CoreProfileListResult, CoreProfileSummary,
    CoreProviderCatalogRequest, CoreProviderCatalogResult, CorePublicDiscoveryCaptureRequest,
    CorePublicDiscoveryCaptureResult, CorePublicDiscoveryProvider, CorePublicDiscoveryReason,
    CorePublicDiscoverySearchRequest, CorePublicDiscoverySearchResult, CorePublicDiscoveryState,
    CoreQueryCheckState, CoreQueryCoverageOutcome, CoreQueryDryRunRequest, CoreQueryPlanCell,
    CoreQueryPlanRequest, CoreQueryPlanResult, CoreQueryPolicyMode, CoreReportArtifactFormat,
    CoreReportExportMode, CoreReviewState, CoreRoute, CoreSearchPolicy, CoreSensitivity,
    CoreSession, CoreTransmissionPolicy, CoreVaultLifecycleResult, EventReplayRequest,
    EventReplayResult, MAX_BOOTSTRAP_BYTES, MAX_READINESS_BYTES, MAX_RESPONSE_BYTES,
    ReadinessMessage, ReadinessTransport, SessionCredential, SessionLockState, VaultCreateRequest,
    VaultState, VaultUnlockRequest, encode_json_line_bounded,
};
use super::key_lease::{KeyLeaseBroker, KeyLeaseError, KeyLeaseHandle, LeaseOperation};
use super::vault_manifest::{VaultManifest, VaultManifestError, validate_create_destination};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const KEYCHAIN_REQUEST_TIMEOUT: Duration = Duration::from_secs(125);
const LOCAL_AI_WORKSPACE_REQUEST_TIMEOUT: Duration = Duration::from_secs(65);
const LOCAL_AI_CORPUS_REQUEST_TIMEOUT: Duration = Duration::from_secs(105);
const PUBLIC_DISCOVERY_REQUEST_TIMEOUT: Duration = Duration::from_secs(25);
const HIBP_REQUEST_TIMEOUT: Duration = Duration::from_secs(25);
const PHASE5_LIST_REQUEST_TIMEOUT: Duration = Duration::from_secs(15);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(3);
const CRASH_MONITOR_INTERVAL: Duration = Duration::from_millis(250);
const CRASH_RESTART_WINDOW: Duration = Duration::from_secs(60);
const CRASH_RESTART_BACKOFF: [Duration; 3] = [
    Duration::from_millis(250),
    Duration::from_millis(500),
    Duration::from_secs(1),
];
const SESSION_HEADER: &str = "Ariadne-Session";
const CONTRACT_HEADER: &str = "Ariadne-Contract-Version";
const REQUEST_ID_HEADER: &str = "Ariadne-Request-Id";
const PACKAGED_SIDECAR_FILENAME: &str = "ariadne-core";
const MAX_PHASE3_FILE_BYTES: usize = 1024 * 1024;
const MAX_PHASE3_FILE_BASE64_BYTES: usize = MAX_PHASE3_FILE_BYTES.div_ceil(3) * 4;
const MAX_PASTED_TEXT_CHARACTERS: usize = 262_144;
const MAX_REVIEW_ENTITIES: usize = 100;
const MAX_ENTITY_ORIGINS: usize = 32;
const MAX_ENTITY_ORIGIN_PAGE_SIZE: usize = 12;
const MAX_ENTITY_ORIGIN_OFFSET: u32 = 100_000_000;
const MAX_PROFILES: usize = 100;
const MAX_GRAPH_NODES: usize = 500;
const MAX_GRAPH_EDGES: usize = 250;
const MAX_GRAPH_EDGE_EVIDENCE: usize = 8;
const MAX_GRAPH_EVIDENCE: usize = 500;
const MAX_LOCAL_AI_WORKSPACE_DOCUMENT_BYTES: usize = 64 * 1024;
const MAX_LOCAL_CORPUS_DOCUMENTS: usize = 20;
const MAX_LOCAL_CORPUS_DOCUMENT_BYTES: usize = 1024 * 1024;
const MAX_LOCAL_CORPUS_TOTAL_BYTES: usize = 4 * 1024 * 1024;
const MAX_LOCAL_CORPUS_SOURCE_CATALOG: usize = 512;
const MAX_PUBLIC_DISCOVERY_RESULTS: usize = 25;
const MAX_HIBP_BREACHES: usize = 1_024;
const MAX_HIBP_DOMAIN_ACCOUNTS: usize = 2_000;
const MAX_HIBP_RESPONSE_BYTES: usize = 1_048_576;
const MAX_HIBP_RETRY_AFTER_SECONDS: u32 = 86_400;
const MAX_INVESTIGATION_IDENTIFIERS: usize = 32;
const MAX_INVESTIGATION_STEPS: usize = 128;
const MAX_QUERY_PROVIDERS: usize = 8;
const MAX_QUERY_PLAN_CELLS: usize = 200;
const MAX_PHASE5_FINDINGS: usize = 100;
const MAX_PHASE5_ARTIFACTS: usize = 64;
const MAX_PHASE5_ARTIFACT_COUNT: u16 = 1_000;
const MAX_PHASE5_SIGNAL_EVIDENCE: usize = 16;
const MAX_PHASE5_POSITIVE_SIGNALS: usize = 14;
const MAX_PHASE5_NEGATIVE_SIGNALS: usize = 8;
const MAX_PHASE5_RECOMMENDED_SIGNALS: usize = 5;
const MAX_PHASE5_ARTIFACT_BYTES: usize = 10 * 1_024 * 1_024;
const MAX_PHASE5_METADATA_ENTRIES: usize = 32;
const MAX_PHASE5_METADATA_TOTAL_CHARS: usize = 4_096;
const ALL_PHASE5_POSITIVE_SIGNALS: [CorePhase5PositiveSignal; 14] = [
    CorePhase5PositiveSignal::ExactEmail,
    CorePhase5PositiveSignal::RecoveryRelationship,
    CorePhase5PositiveSignal::ExactLegalName,
    CorePhase5PositiveSignal::SameUncommonUsername,
    CorePhase5PositiveSignal::SamePhotograph,
    CorePhase5PositiveSignal::SameOrganisation,
    CorePhase5PositiveSignal::SameEducation,
    CorePhase5PositiveSignal::SameLocation,
    CorePhase5PositiveSignal::SameProject,
    CorePhase5PositiveSignal::SameLinkedDomain,
    CorePhase5PositiveSignal::SameWritingProfileLinks,
    CorePhase5PositiveSignal::ChronologicalCompatibility,
    CorePhase5PositiveSignal::UserConfirmation,
    CorePhase5PositiveSignal::ImmutablePlatformIdContinuity,
];
const MAX_PHASE6_RUNS: usize = 32;
const MAX_PHASE6_DIFFS: usize = 4_000;
const MAX_PHASE6_COVERAGE: usize = 256;
const MAX_PHASE6_LIFECYCLES: usize = 4_000;
const MAX_PHASE6_LIFECYCLE_EVENTS: usize = 32;
const MAX_PHASE6_CASES: usize = 100;
const MAX_PHASE6_FINDING_LINKS: usize = 64;
const MAX_PHASE6_EVIDENCE_REFERENCES: usize = 64;
const MAX_PHASE6_PROVIDER_RESPONSES: usize = 32;
const MAX_PHASE6_HISTORY_ENTRIES: usize = 256;
const MAX_LOCAL_REPORT_ARTIFACT_BYTES: usize = 1_024 * 1_024;
const MAX_LOCAL_REPORT_RESPONSE_BYTES: usize = 1_000_000;
const MAX_IDENTITY_SOURCES: usize = 200;
const MAX_IDENTITY_AUDITS: usize = 64;
const MAX_IDENTITY_TASKS: usize = 500;
const MAX_IDENTITY_RESULTS: usize = 500;
const MAX_IDENTITY_LEADS: usize = 500;
const MAX_IDENTITY_PROPOSALS: usize = 250;
const MAX_IDENTITY_RECEIPTS: usize = 500;
const MAX_IDENTITY_AI_INSIGHTS: usize = 100;
const MAX_IDENTITY_AI_CITATIONS: usize = 200;
const IDENTITY_REQUEST_TIMEOUT: Duration = Duration::from_secs(45);
const MAX_SAFE_JAVASCRIPT_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone)]
pub struct CoreSupervisor {
    inner: Arc<Mutex<SupervisorInner>>,
    vault_root: Arc<PathBuf>,
    active_operations: Arc<AtomicUsize>,
    vault_request_gate: Arc<tokio::sync::Mutex<()>>,
    shutting_down: Arc<AtomicBool>,
    #[cfg(test)]
    development_home: Arc<Option<PathBuf>>,
}

impl Default for CoreSupervisor {
    fn default() -> Self {
        Self::new()
    }
}

impl CoreSupervisor {
    pub fn new() -> Self {
        Self::with_vault_root(PathBuf::new())
    }

    pub(crate) fn with_vault_root(vault_root: PathBuf) -> Self {
        Self {
            inner: Arc::new(Mutex::new(SupervisorInner::default())),
            vault_root: Arc::new(vault_root),
            active_operations: Arc::new(AtomicUsize::new(0)),
            vault_request_gate: Arc::new(tokio::sync::Mutex::new(())),
            shutting_down: Arc::new(AtomicBool::new(false)),
            #[cfg(test)]
            development_home: Arc::new(None),
        }
    }

    #[cfg(test)]
    fn with_test_home(home: PathBuf) -> Self {
        let vault_root = home
            .join("Library/Application Support/app.codenameariadne.desktop")
            .join("vault");
        Self {
            inner: Arc::new(Mutex::new(SupervisorInner::default())),
            vault_root: Arc::new(vault_root),
            active_operations: Arc::new(AtomicUsize::new(0)),
            vault_request_gate: Arc::new(tokio::sync::Mutex::new(())),
            shutting_down: Arc::new(AtomicBool::new(false)),
            development_home: Arc::new(Some(home)),
        }
    }

    pub async fn start(&self) -> Result<(), CoreError> {
        if self.shutting_down.load(Ordering::Acquire) {
            return Err(CoreError::StartupCancelled);
        }
        {
            let mut inner = self.lock();
            match inner.state {
                CoreLifecycleState::NotStarted
                | CoreLifecycleState::Stopped
                | CoreLifecycleState::Failed => {
                    inner.state = CoreLifecycleState::Starting;
                    inner.last_error_code = None;
                }
                state => return Err(CoreError::InvalidLifecycleState(state)),
            }
        }

        let result = self.start_sidecar(RuntimeMode::current()).await;
        if let Err(error) = &result {
            self.mark_failed(error);
        }
        result
    }

    async fn start_sidecar(&self, mode: RuntimeMode) -> Result<(), CoreError> {
        // Readiness is not process survival. The child becomes Ready only after
        // bootstrap, key-lease handshake, endpoint validation, capability
        // version agreement, and proof that the new session starts locked.
        let credential = Arc::new(SessionCredential::generate().map_err(CoreError::Random)?);
        let bootstrap = BootstrapMessage::new(&credential);
        let bootstrap_bytes = encode_json_line_bounded(&bootstrap, MAX_BOOTSTRAP_BYTES)?;
        let (mut key_lease_broker, key_lease_handle, key_lease_child) =
            KeyLeaseBroker::socket_pair(bootstrap.startup_nonce)?;
        let mut command = match mode {
            RuntimeMode::Development => {
                let spec = DevelopmentSpawnSpec::from_manifest_dir()?;
                #[cfg(test)]
                let spec = match self.development_home.as_ref().as_ref() {
                    Some(home) => {
                        let mut configured = spec;
                        configured
                            .explicit_environment
                            .push((OsString::from("HOME"), home.as_os_str().to_owned()));
                        configured
                    }
                    None => spec,
                };
                spec.command()
            }
            RuntimeMode::Packaged => PackagedSpawnSpec::from_current_executable()?.command(),
        };
        key_lease_child.configure_command(&mut command);
        let mut child = command.spawn().map_err(CoreError::Spawn)?;
        drop(key_lease_child);

        let stdout = child
            .stdout
            .take()
            .ok_or(CoreError::MissingChildPipe("stdout"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or(CoreError::MissingChildPipe("stderr"))?;
        let mut readiness_reader = BufReader::new(stdout);

        let stderr_task = tokio::spawn(drain_stream(stderr));

        let mut stdin = child
            .stdin
            .take()
            .ok_or(CoreError::MissingChildPipe("stdin"))?;
        let bootstrap_result = async {
            stdin.write_all(bootstrap_bytes.as_ref()).await?;
            stdin.flush().await
        }
        .await;
        if let Err(error) = bootstrap_result {
            request_child_termination(&mut child);
            stderr_task.abort();
            return Err(CoreError::BootstrapWrite(error));
        }
        drop(stdin);
        drop(bootstrap_bytes);

        let mut child_slot = Some(child);
        let installed = {
            let mut inner = self.lock();
            if inner.state == CoreLifecycleState::Starting {
                inner.child = child_slot.take();
                inner.credential = Some(Arc::clone(&credential));
                true
            } else {
                false
            }
        };

        if !installed {
            if let Some(mut child) = child_slot {
                request_child_termination(&mut child);
            }
            stderr_task.abort();
            return Err(CoreError::StartupCancelled);
        }

        let key_lease_task = tokio::task::spawn_blocking(move || {
            key_lease_broker.accept_hello()?;
            Ok::<KeyLeaseBroker, KeyLeaseError>(key_lease_broker)
        });
        let readiness_task = timeout(
            STARTUP_TIMEOUT,
            read_bounded_line(&mut readiness_reader, MAX_READINESS_BYTES),
        );
        let (key_lease_result, readiness_result) = tokio::join!(key_lease_task, readiness_task);
        let key_lease_broker = key_lease_result
            .map_err(|_| CoreError::KeyLeaseWorker)?
            .map_err(CoreError::KeyLease)?;
        let readiness_bytes = readiness_result.map_err(|_| CoreError::ReadinessTimeout)??;

        let readiness: ReadinessMessage =
            serde_json::from_slice(&readiness_bytes).map_err(|_| {
                CoreError::InvalidReadiness("readiness JSON does not match the contract")
            })?;
        let endpoint = CoreEndpoint::from_readiness(readiness, mode)?;
        let client = endpoint.build_client()?;

        tokio::spawn(drain_stream(readiness_reader));

        let (_, capabilities) = request_route::<CoreCapabilities>(
            &client,
            &endpoint,
            &credential,
            CoreRoute::Capabilities,
        )
        .await?;
        if capabilities.versions.contract != CONTRACT_VERSION {
            return Err(CoreError::ContractVersionMismatch {
                expected: CONTRACT_VERSION,
                actual: capabilities.versions.contract,
            });
        }
        let (_, session) =
            request_route::<CoreSession>(&client, &endpoint, &credential, CoreRoute::Session)
                .await?;
        if session.lock_state != SessionLockState::Locked
            || !matches!(
                session.vault_state,
                VaultState::NoVault | VaultState::Locked
            )
        {
            return Err(CoreError::InvalidReadiness(
                "new sidecar did not start in a locked state",
            ));
        }

        let mut inner = self.lock();
        if inner.state != CoreLifecycleState::Starting {
            return Err(CoreError::StartupCancelled);
        }
        inner.endpoint = Some(endpoint);
        inner.client = Some(client);
        inner.key_lease_broker = Some(key_lease_broker);
        inner.key_lease_handle = Some(key_lease_handle);
        inner.vault_unlocked = false;
        inner.restart_scheduled = false;
        inner.state = CoreLifecycleState::Ready;
        Ok(())
    }

    pub async fn capabilities(
        &self,
    ) -> Result<CoreCommandResponse<CoreCapabilities>, CoreCommandError> {
        self.execute(CoreRoute::Capabilities).await
    }

    pub async fn session(&self) -> Result<CoreCommandResponse<CoreSession>, CoreCommandError> {
        self.execute(CoreRoute::Session).await
    }

    pub(crate) fn vault_is_unlocked(&self) -> bool {
        let inner = self.lock();
        inner.state == CoreLifecycleState::Ready && inner.vault_unlocked
    }

    pub(super) async fn replay_events(
        &self,
        cursor: Option<Uuid>,
    ) -> Result<Option<EventReplayResult>, CoreError> {
        let runtime = {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
                return Ok(None);
            }
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };
        let request = EventReplayRequest {
            cursor,
            max_events: 32,
        };
        let (_, replay) = request_route_with_json::<EventReplayResult, _>(
            &runtime.0,
            &runtime.1,
            &runtime.2,
            CoreRoute::ReplayEvents,
            &request,
        )
        .await?;
        validate_event_replay(&replay)?;
        Ok(Some(replay))
    }

    pub fn spawn_crash_monitor(&self) {
        let supervisor = self.clone();
        tauri::async_runtime::spawn(async move {
            let mut ticker = tokio::time::interval(CRASH_MONITOR_INTERVAL);
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
            loop {
                ticker.tick().await;
                if supervisor.shutting_down.load(Ordering::Acquire) {
                    return;
                }
                let Some(exit) = supervisor.observe_child_exit() else {
                    continue;
                };
                if let Some(child) = exit.child_to_terminate {
                    terminate_child(child).await;
                }
                if exit.restart {
                    supervisor.recover_after_unexpected_exit().await;
                }
            }
        });
    }

    pub async fn create_vault(
        &self,
        display_name: String,
        key_custody: KeyCustody,
    ) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        let result = self.create_vault_inner(display_name, key_custody).await;
        if let Err(error) = &result {
            self.mark_failed(error);
        }
        result.map_err(|error| error.into_command_error(fallback_request_id))
    }

    async fn create_vault_inner(
        &self,
        display_name: String,
        key_custody: KeyCustody,
    ) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreError> {
        validate_display_name(&display_name)?;
        validate_create_destination(self.vault_root.as_path())?;

        let vault_id = Uuid::new_v4();
        let database_reference = crate::security::key_custody::KeyReference::new_vault();
        let backup_reference = crate::security::key_custody::KeyReference::new_vault();
        let manifest = VaultManifest::new(vault_id, database_reference, backup_reference)?;
        let operation = self.take_lease_operation(CoreLifecycleState::Creating)?;
        let descriptor = operation.handle.authorize(
            manifest.vault_id(),
            manifest.manifest_digest(),
            manifest.database_key_ref(),
            manifest.database_key_version(),
            LeaseOperation::DatabaseCreateV1,
        )?;
        let body = VaultCreateRequest {
            display_name,
            transaction_id: descriptor.transaction_id,
            vault_id: manifest.vault_id(),
            manifest_digest: manifest.digest_hex(),
            database_key_ref: manifest.database_key_ref().opaque_reference(),
            backup_key_ref: manifest.backup_key_ref().opaque_reference(),
            format_version: manifest.format_version(),
            database_key_version: manifest.database_key_version(),
        };

        let database_created = Arc::new(AtomicBool::new(false));
        let backup_created = Arc::new(AtomicBool::new(false));
        let database_created_worker = Arc::clone(&database_created);
        let backup_created_worker = Arc::clone(&backup_created);
        let custody_worker = key_custody.clone();
        let policy = self.clone();
        let mut broker = operation.broker;
        let broker_task = tokio::task::spawn_blocking(move || {
            broker.run_authorized(
                move |requested| {
                    if requested != database_reference {
                        return Err(KeyLeaseError::BindingMismatch);
                    }
                    let database_key = custody_worker
                        .create_key(&database_reference)
                        .map_err(|_| KeyLeaseError::KeyUnavailable)?;
                    database_created_worker.store(true, Ordering::Release);
                    match custody_worker.create_key(&backup_reference) {
                        Ok(backup_key) => {
                            drop(backup_key);
                            backup_created_worker.store(true, Ordering::Release);
                            Ok(database_key)
                        }
                        Err(_) => {
                            let _ = custody_worker.delete_key(&database_reference);
                            database_created_worker.store(false, Ordering::Release);
                            Err(KeyLeaseError::KeyUnavailable)
                        }
                    }
                },
                move || policy.state_is(CoreLifecycleState::Creating),
            )
        });
        let request = request_route_with_json::<CoreVaultLifecycleResult, _>(
            &operation.client,
            &operation.endpoint,
            &operation.credential,
            CoreRoute::CreateVault,
            &body,
        );
        let (broker_join, response) = tokio::join!(broker_task, request);
        let broker_result = broker_join
            .map_err(|_| CoreError::KeyLeaseWorker)?
            .map_err(CoreError::KeyLease);
        if broker_result.is_err() {
            if backup_created.load(Ordering::Acquire) {
                let _ = key_custody.delete_key(&backup_reference);
            }
            if database_created.load(Ordering::Acquire) {
                let _ = key_custody.delete_key(&database_reference);
            }
        }
        broker_result?;
        let (request_id, data) = response?;
        validate_unlocked_response(&data, manifest.vault_id())?;
        let persisted = VaultManifest::load_for_unlock(self.vault_root.as_path())?;
        if persisted.vault_id() != manifest.vault_id()
            || persisted.database_key_ref() != manifest.database_key_ref()
            || persisted.backup_key_ref() != manifest.backup_key_ref()
            || persisted.digest_hex() != manifest.digest_hex()
        {
            return Err(CoreError::InvalidVaultResponse);
        }
        self.finish_lease_operation(CoreLifecycleState::Creating)?;
        Ok(CoreCommandResponse { request_id, data })
    }

    pub async fn unlock_current_vault(
        &self,
        key_custody: KeyCustody,
    ) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        let result = self.unlock_current_vault_inner(key_custody).await;
        if let Err(error) = &result {
            self.mark_failed(error);
        }
        result.map_err(|error| error.into_command_error(fallback_request_id))
    }

    async fn unlock_current_vault_inner(
        &self,
        key_custody: KeyCustody,
    ) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreError> {
        let manifest = VaultManifest::load_for_unlock(self.vault_root.as_path())?;
        let operation = self.take_lease_operation(CoreLifecycleState::Unlocking)?;
        let descriptor = operation.handle.authorize(
            manifest.vault_id(),
            manifest.manifest_digest(),
            manifest.database_key_ref(),
            manifest.database_key_version(),
            LeaseOperation::DatabaseUnlockV1,
        )?;
        let body = VaultUnlockRequest {
            transaction_id: descriptor.transaction_id,
            vault_id: manifest.vault_id(),
            manifest_digest: manifest.digest_hex(),
            database_key_ref: manifest.database_key_ref().opaque_reference(),
            database_key_version: manifest.database_key_version(),
        };
        let database_reference = manifest.database_key_ref();
        let custody_worker = key_custody;
        let policy = self.clone();
        let mut broker = operation.broker;
        let broker_task = tokio::task::spawn_blocking(move || {
            broker.run_authorized(
                move |requested| {
                    if requested != database_reference {
                        return Err(KeyLeaseError::BindingMismatch);
                    }
                    custody_worker
                        .get_key(&database_reference)
                        .map_err(|_| KeyLeaseError::KeyUnavailable)
                },
                move || policy.state_is(CoreLifecycleState::Unlocking),
            )
        });
        let request = request_route_with_json::<CoreVaultLifecycleResult, _>(
            &operation.client,
            &operation.endpoint,
            &operation.credential,
            CoreRoute::UnlockCurrentVault,
            &body,
        );
        let (broker_join, response) = tokio::join!(broker_task, request);
        broker_join
            .map_err(|_| CoreError::KeyLeaseWorker)?
            .map_err(CoreError::KeyLease)?;
        let (request_id, data) = response?;
        validate_unlocked_response(&data, manifest.vault_id())?;
        self.finish_lease_operation(CoreLifecycleState::Unlocking)?;
        Ok(CoreCommandResponse { request_id, data })
    }

    pub async fn lock_current_vault(
        &self,
    ) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        let (client, endpoint, credential) = {
            let mut inner = self.lock();
            if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
                return Err(
                    CoreError::NotReady(inner.state).into_command_error(fallback_request_id)
                );
            }
            inner.state = CoreLifecycleState::Locking;
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };
        let response = request_route::<CoreVaultLifecycleResult>(
            &client,
            &endpoint,
            &credential,
            CoreRoute::LockCurrentVault,
        )
        .await;
        self.stop().await;
        let restart = self.start().await;
        match (response, restart) {
            (Ok((request_id, data)), Ok(()))
                if data.lock_state == SessionLockState::Locked
                    && data.vault_state == VaultState::Locked =>
            {
                Ok(CoreCommandResponse { request_id, data })
            }
            (Err(error), _) => Err(error.into_command_error(fallback_request_id)),
            (_, Err(error)) => Err(error.into_command_error(fallback_request_id)),
            _ => Err(CoreError::InvalidVaultResponse.into_command_error(fallback_request_id)),
        }
    }

    pub async fn create_profile(
        &self,
        request: CoreProfileCreateRequest,
    ) -> Result<CoreCommandResponse<CoreProfileSummary>, CoreCommandError> {
        validate_profile_create_request(&request)?;
        self.execute_unlocked_with_json(CoreRoute::CreateProfile, &request, |profile| {
            validate_profile_summary(profile)
        })
        .await
    }

    pub async fn list_profiles(
        &self,
    ) -> Result<CoreCommandResponse<CoreProfileListResult>, CoreCommandError> {
        self.execute_unlocked(CoreRoute::ListProfiles, validate_profile_list_result)
            .await
    }

    pub async fn delete_profile(
        &self,
        request: CoreProfileDeleteRequest,
    ) -> Result<CoreCommandResponse<CoreProfileDeleteResult>, CoreCommandError> {
        validate_profile_delete_request(&request)?;
        let profile_id = request.profile_id;
        self.execute_unlocked_with_json(CoreRoute::DeleteProfile, &request, move |result| {
            validate_profile_delete_result(result, profile_id)
        })
        .await
    }

    pub async fn intake_paste(
        &self,
        request: CorePasteIntakeRequest,
    ) -> Result<CoreCommandResponse<CoreIntakeReceipt>, CoreCommandError> {
        validate_paste_intake_request(&request)?;
        let profile_id = request.profile_id;
        self.execute_unlocked_with_json(CoreRoute::IntakePaste, &request, move |receipt| {
            validate_intake_receipt(receipt, profile_id, "PASTE")
        })
        .await
    }

    pub async fn intake_file(
        &self,
        request: CoreFileIntakeRequest,
    ) -> Result<CoreCommandResponse<CoreIntakeReceipt>, CoreCommandError> {
        validate_file_intake_request(&request)?;
        let profile_id = request.profile_id;
        self.execute_unlocked_with_json(CoreRoute::IntakeFile, &request, move |receipt| {
            validate_intake_receipt(receipt, profile_id, "FILE")
        })
        .await
    }

    pub async fn review_entities(
        &self,
        request: CoreEntityReviewRequest,
    ) -> Result<CoreCommandResponse<CoreEntityReviewResult>, CoreCommandError> {
        validate_entity_review_request(&request)?;
        let profile_id = request.profile_id;
        let limit = usize::from(request.limit);
        self.execute_unlocked_with_json(CoreRoute::ReviewEntities, &request, move |result| {
            validate_entity_review_result(result, profile_id, limit)
        })
        .await
    }

    pub async fn list_entity_origins(
        &self,
        request: CoreEntityOriginPageRequest,
    ) -> Result<CoreCommandResponse<CoreEntityOriginPageResult>, CoreCommandError> {
        validate_entity_origin_page_request(&request)?;
        let profile_id = request.profile_id;
        let entity_id = request.entity_id;
        let offset = request.offset;
        let limit = request.limit;
        self.execute_unlocked_with_json(CoreRoute::EntityOrigins, &request, move |result| {
            validate_entity_origin_page_result(result, profile_id, entity_id, offset, limit)
        })
        .await
    }

    pub async fn decide_entity(
        &self,
        request: CoreEntityDecisionRequest,
    ) -> Result<CoreCommandResponse<CoreEntitySummary>, CoreCommandError> {
        validate_entity_decision_request(&request)?;
        let entity_id = request.entity_id;
        self.execute_unlocked_with_json(
            CoreRoute::DecideEntity,
            &request,
            move |entity: &CoreEntitySummary| {
                if entity.entity_id != entity_id {
                    return Err(CoreError::InvalidPhase3Response);
                }
                validate_entity_summary(entity)
            },
        )
        .await
    }

    pub async fn graph_snapshot(
        &self,
        request: CoreGraphSnapshotRequest,
    ) -> Result<CoreCommandResponse<CoreGraphSnapshot>, CoreCommandError> {
        validate_graph_snapshot_request(&request)?;
        let profile_id = request.profile_id;
        let max_nodes = usize::from(request.max_nodes);
        self.execute_unlocked_with_json(CoreRoute::GraphSnapshot, &request, move |snapshot| {
            validate_graph_snapshot(snapshot, profile_id, max_nodes)
        })
        .await
    }

    pub async fn local_ai_settings(
        &self,
    ) -> Result<CoreCommandResponse<CoreLocalAiSettings>, CoreCommandError> {
        self.execute_unlocked(CoreRoute::GetLocalAiSettings, validate_local_ai_settings)
            .await
    }

    pub async fn update_local_ai_settings(
        &self,
        request: CoreLocalAiSettingsUpdateRequest,
    ) -> Result<CoreCommandResponse<CoreLocalAiSettings>, CoreCommandError> {
        validate_local_ai_settings_update(&request)?;
        let expected_enabled = request.enabled;
        let expected_provider = request.provider;
        let expected_endpoint = request.endpoint.clone();
        let expected_model = request.selected_model.clone();
        let expected_revision = request.expected_revision;
        self.execute_unlocked_with_json(
            CoreRoute::UpdateLocalAiSettings,
            &request,
            move |settings| {
                validate_local_ai_settings(settings)?;
                if settings.enabled != expected_enabled
                    || settings.provider != expected_provider
                    || reqwest::Url::parse(&settings.endpoint).ok()
                        != reqwest::Url::parse(&expected_endpoint).ok()
                    || settings.selected_model != expected_model
                    || settings.revision < expected_revision
                    || settings.revision > expected_revision + 1
                {
                    return Err(CoreError::InvalidLocalAiResponse);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn discover_local_ai_models(
        &self,
        request: CoreLocalAiEndpointRequest,
    ) -> Result<CoreCommandResponse<CoreLocalAiModelDiscoveryResult>, CoreCommandError> {
        validate_local_ai_endpoint_request(&request)?;
        let provider = request.provider;
        self.execute_unlocked_with_json(CoreRoute::DiscoverLocalAiModels, &request, move |result| {
            validate_local_ai_models(result, provider)
        })
        .await
    }

    pub async fn test_local_ai_connection(
        &self,
        request: CoreLocalAiEndpointRequest,
    ) -> Result<CoreCommandResponse<CoreLocalAiConnectionResult>, CoreCommandError> {
        validate_local_ai_endpoint_request(&request)?;
        let selected_model = request.selected_model.clone();
        self.execute_unlocked_with_json(CoreRoute::TestLocalAiConnection, &request, move |result| {
            validate_local_ai_connection(result, selected_model.as_deref())
        })
        .await
    }

    pub async fn analyze_local_ai_workspace(
        &self,
        request: CoreLocalAiWorkspaceRequest,
    ) -> Result<CoreCommandResponse<CoreLocalAiWorkspaceResult>, CoreCommandError> {
        validate_local_ai_workspace_request(&request)?;
        let profile_id = request.profile_id;
        let task = request.task;
        let scopes = request.scopes.clone();
        let requested_execution = request.execution;
        let requested_model = request.model_id.clone();
        self.execute_unlocked_with_json(
            CoreRoute::AnalyzeLocalAiWorkspace,
            &request,
            move |result| {
                validate_local_ai_workspace_result(
                    result,
                    profile_id,
                    task,
                    &scopes,
                    requested_execution,
                    requested_model.as_deref(),
                )
            },
        )
        .await
    }

    pub async fn analyze_local_ai_corpus(
        &self,
        request: CoreLocalCorpusAiRequest,
    ) -> Result<CoreCommandResponse<CoreLocalCorpusAiResult>, CoreCommandError> {
        let binding = validate_local_corpus_ai_request(&request)?;
        self.execute_unlocked_with_json(CoreRoute::AnalyzeLocalAiCorpus, &request, move |result| {
            validate_local_corpus_ai_result(result, &binding)
        })
        .await
    }

    pub async fn search_public_discovery(
        &self,
        request: CorePublicDiscoverySearchRequest,
    ) -> Result<CoreCommandResponse<CorePublicDiscoverySearchResult>, CoreCommandError> {
        validate_public_discovery_request(&request)?;
        let provider = request.provider;
        let authorization_confirmed = request.authorized_self_audit;
        let max_results = request.max_results;
        self.execute_ready_with_json(CoreRoute::SearchPublicDiscovery, &request, move |result| {
            validate_public_discovery_result(result, provider, authorization_confirmed, max_results)
        })
        .await
    }

    pub async fn compile_investigation_plan(
        &self,
        request: CoreInvestigationPlanRequest,
    ) -> Result<CoreCommandResponse<CoreInvestigationPlanResult>, CoreCommandError> {
        let binding = validate_investigation_plan_request(&request)?;
        self.execute_ready_with_json(
            CoreRoute::CompileInvestigationPlan,
            &request,
            move |result| validate_investigation_plan_result(result, &binding),
        )
        .await
    }

    pub async fn search_hibp_account(
        &self,
        request: CoreHibpAccountRequest,
    ) -> Result<CoreCommandResponse<CoreHibpAccountResult>, CoreCommandError> {
        let binding = validate_hibp_account_request(&request)?;
        self.execute_ready_with_json(CoreRoute::SearchHibpAccount, &request, move |result| {
            validate_hibp_account_result(result, &binding)
        })
        .await
    }

    pub async fn search_hibp_domain(
        &self,
        request: CoreHibpDomainRequest,
    ) -> Result<CoreCommandResponse<CoreHibpDomainResult>, CoreCommandError> {
        let binding = validate_hibp_domain_request(&request)?;
        self.execute_ready_with_json(CoreRoute::SearchHibpDomain, &request, move |result| {
            validate_hibp_domain_result(result, &binding)
        })
        .await
    }

    pub async fn capture_public_discovery(
        &self,
        request: CorePublicDiscoveryCaptureRequest,
    ) -> Result<CoreCommandResponse<CorePublicDiscoveryCaptureResult>, CoreCommandError> {
        validate_public_discovery_capture_request(&request)?;
        let profile_id = request.profile_id;
        let provider = request.provider;
        let rank = request.rank;
        let source_id = request.source_id.clone();
        let url = request.url.clone();
        let captured_at_us = request.captured_at_us;
        self.execute_unlocked_with_json(
            CoreRoute::CapturePublicDiscovery,
            &request,
            move |result| {
                validate_public_discovery_capture_result(
                    result,
                    profile_id,
                    provider,
                    rank,
                    source_id.as_deref(),
                    &url,
                    captured_at_us,
                )
            },
        )
        .await
    }

    pub async fn query_provider_catalog(
        &self,
        request: CoreProviderCatalogRequest,
    ) -> Result<CoreCommandResponse<CoreProviderCatalogResult>, CoreCommandError> {
        let profile_id = request.profile_id;
        self.execute_unlocked_with_json(CoreRoute::QueryProviders, &request, move |result| {
            validate_query_provider_catalog(result, profile_id)
        })
        .await
    }

    pub async fn create_query_plan(
        &self,
        request: CoreQueryPlanRequest,
    ) -> Result<CoreCommandResponse<CoreQueryPlanResult>, CoreCommandError> {
        validate_query_plan_request(&request)?;
        let profile_id = request.profile_id;
        let policy_mode = request.policy_mode;
        let selected_provider_ids = request.provider_ids.clone();
        self.execute_unlocked_with_json(CoreRoute::CreateQueryPlan, &request, move |result| {
            validate_query_plan_result(result, profile_id, policy_mode, &selected_provider_ids)
        })
        .await
    }

    pub async fn execute_query_dry_run(
        &self,
        request: CoreQueryDryRunRequest,
    ) -> Result<CoreCommandResponse<CoreQueryPlanCell>, CoreCommandError> {
        validate_query_dry_run_request(&request)?;
        let check_id = request.check_id;
        let expected_revision = request.expected_revision;
        self.execute_unlocked_with_json(CoreRoute::ExecuteQueryDryRun, &request, move |cell| {
            validate_query_plan_cell(cell, false)?;
            if cell.check_id != check_id
                || cell.revision < expected_revision
                || cell.revision > expected_revision + 3
            {
                return Err(CoreError::InvalidQueryResponse);
            }
            Ok(())
        })
        .await
    }

    pub async fn list_phase5_findings(
        &self,
        request: CorePhase5FindingListRequest,
    ) -> Result<CoreCommandResponse<CorePhase5FindingListResult>, CoreCommandError> {
        validate_phase5_finding_list_request(&request)?;
        let profile_id = request.profile_id;
        let limit = usize::from(request.limit);
        self.execute_unlocked_with_json(CoreRoute::ListPhase5Findings, &request, move |result| {
            validate_phase5_finding_list(result, profile_id, limit)
        })
        .await
    }

    pub async fn get_phase5_finding(
        &self,
        request: CorePhase5FindingDetailRequest,
    ) -> Result<CoreCommandResponse<CorePhase5FindingDetailResult>, CoreCommandError> {
        validate_phase5_finding_detail_request(&request)?;
        let profile_id = request.profile_id;
        let finding_id = request.finding_id;
        self.execute_unlocked_with_json(CoreRoute::GetPhase5Finding, &request, move |result| {
            validate_phase5_finding_detail(result, profile_id, finding_id)
        })
        .await
    }

    pub async fn create_phase5_manual_finding(
        &self,
        request: CorePhase5ManualFindingCreateRequest,
    ) -> Result<CoreCommandResponse<CorePhase5FindingDetailResult>, CoreCommandError> {
        validate_phase5_manual_finding_request(&request)?;
        let profile_id = request.profile_id;
        let title = request.title.clone();
        let summary = request.summary.clone();
        let outcome = request.outcome;
        let severity = request.severity;
        let visibility = request.visibility;
        let provider_label = request.provider_label.clone();
        self.execute_unlocked_with_json(
            CoreRoute::CreatePhase5ManualFinding,
            &request,
            move |result| {
                validate_phase5_manual_finding_result(
                    result,
                    profile_id,
                    &title,
                    &summary,
                    outcome,
                    severity,
                    visibility,
                    &provider_label,
                )
            },
        )
        .await
    }

    pub async fn import_phase5_evidence(
        &self,
        request: CorePhase5ManualEvidenceImportRequest,
    ) -> Result<CoreCommandResponse<CorePhase5ManualEvidenceImportResult>, CoreCommandError> {
        validate_phase5_manual_import_request(&request)?;
        let profile_id = request.profile_id;
        let finding_id = request.finding_id;
        let kind = request.kind;
        self.execute_unlocked_with_json(CoreRoute::ImportPhase5Evidence, &request, move |result| {
            validate_phase5_manual_import_result(result, profile_id, finding_id, kind)
        })
        .await
    }

    pub async fn create_phase5_redacted_derivative(
        &self,
        request: CorePhase5RedactedDerivativeRequest,
    ) -> Result<CoreCommandResponse<CorePhase5RedactedDerivativeResult>, CoreCommandError> {
        validate_phase5_redacted_derivative_request(&request)?;
        let profile_id = request.profile_id;
        let original_artifact_id = request.original_artifact_id;
        let policy_version = request.redaction_policy_version.clone();
        let summary_code = request.redaction_summary_code.clone();
        self.execute_unlocked_with_json(
            CoreRoute::CreatePhase5RedactedDerivative,
            &request,
            move |result| {
                validate_phase5_redacted_derivative_result(
                    result,
                    profile_id,
                    original_artifact_id,
                    &policy_version,
                    &summary_code,
                )
            },
        )
        .await
    }

    pub async fn append_phase5_attribution_decision(
        &self,
        request: CorePhase5AttributionDecisionRequest,
    ) -> Result<CoreCommandResponse<CorePhase5AttributionDecisionResult>, CoreCommandError> {
        validate_phase5_attribution_decision_request(&request)?;
        let profile_id = request.profile_id;
        let finding_id = request.finding_id;
        let assessment_id = request.assessment_id;
        let state = request.state;
        let previous_decision_id = request.expected_previous_decision_id;
        let previous_revision = request.expected_previous_revision;
        self.execute_unlocked_with_json(
            CoreRoute::AppendPhase5AttributionDecision,
            &request,
            move |result| {
                validate_phase5_attribution_decision_result(
                    result,
                    profile_id,
                    finding_id,
                    assessment_id,
                    state,
                    previous_decision_id,
                    previous_revision,
                )
            },
        )
        .await
    }

    pub async fn list_phase6_audit_runs(
        &self,
        request: CorePhase6AuditRunListRequest,
    ) -> Result<CoreCommandResponse<CorePhase6AuditRunListResult>, CoreCommandError> {
        validate_phase6_audit_run_list_request(&request)?;
        let profile_id = request.profile_id;
        let limit = usize::from(request.limit);
        self.execute_unlocked_with_json(CoreRoute::ListPhase6AuditRuns, &request, move |result| {
            validate_phase6_audit_run_list(result, profile_id, limit)
        })
        .await
    }

    pub async fn create_phase6_local_checkpoint(
        &self,
        request: CorePhase6LocalCheckpointRequest,
    ) -> Result<CoreCommandResponse<CorePhase6LocalCheckpointResult>, CoreCommandError> {
        validate_phase6_local_checkpoint_request(&request)?;
        let profile_id = request.profile_id;
        let run_state = request.run_state;
        let provider_count = request.provider_coverage.len();
        self.execute_unlocked_with_json(
            CoreRoute::CreatePhase6LocalCheckpoint,
            &request,
            move |result| {
                validate_phase6_local_checkpoint_result(
                    result,
                    profile_id,
                    run_state,
                    provider_count,
                )
            },
        )
        .await
    }

    pub async fn compare_phase6_runs(
        &self,
        request: CorePhase6CompareRunsRequest,
    ) -> Result<CoreCommandResponse<CorePhase6ComparisonResult>, CoreCommandError> {
        validate_phase6_compare_runs_request(&request)?;
        let profile_id = request.profile_id;
        let baseline_run_id = request.baseline_run_id;
        let current_run_id = request.current_run_id;
        self.execute_unlocked_with_json(CoreRoute::ComparePhase6Runs, &request, move |result| {
            validate_phase6_comparison(result, profile_id, baseline_run_id, current_run_id)
        })
        .await
    }

    pub async fn list_phase6_remediation_cases(
        &self,
        request: CorePhase6RemediationListRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationListResult>, CoreCommandError> {
        validate_phase6_remediation_list_request(&request)?;
        let profile_id = request.profile_id;
        let limit = usize::from(request.limit);
        self.execute_unlocked_with_json(
            CoreRoute::ListPhase6RemediationCases,
            &request,
            move |result| validate_phase6_remediation_list(result, profile_id, limit),
        )
        .await
    }

    pub async fn get_phase6_remediation_case(
        &self,
        request: CorePhase6RemediationDetailRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_detail_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        self.execute_unlocked_with_json(
            CoreRoute::GetPhase6RemediationCase,
            &request,
            move |result| validate_phase6_remediation_detail(result, profile_id, case_id),
        )
        .await
    }

    pub async fn create_phase6_remediation_case(
        &self,
        request: CorePhase6RemediationCreateRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_create_request(&request)?;
        let profile_id = request.profile_id;
        let finding_ids = request.finding_ids.clone();
        let action = request.action;
        let deadline_at_us = request.deadline_at_us;
        let evidence_references = request.evidence_references.clone();
        let draft_text = request.draft_text.clone();
        self.execute_unlocked_with_json(
            CoreRoute::CreatePhase6RemediationCase,
            &request,
            move |result| {
                validate_phase6_remediation_create_result(
                    result,
                    profile_id,
                    &finding_ids,
                    action,
                    deadline_at_us,
                    &evidence_references,
                    draft_text.as_deref(),
                )
            },
        )
        .await
    }

    pub async fn update_phase6_remediation_draft(
        &self,
        request: CorePhase6RemediationDraftUpdateRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_draft_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let draft_text = request.draft_text.clone();
        self.execute_unlocked_with_json(
            CoreRoute::UpdatePhase6RemediationDraft,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::DraftUpdated,
                )?;
                if result.case.draft_text.as_deref() != Some(draft_text.as_str()) {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn require_phase6_remediation_approval(
        &self,
        request: CorePhase6RemediationRequireApprovalRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_mutation_request(
            request.profile_id,
            request.case_id,
            request.expected_revision,
        )?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        self.execute_unlocked_with_json(
            CoreRoute::RequirePhase6RemediationApproval,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::ApprovalRequired,
                )?;
                if result.case.action_disposition
                    != CorePhase6ActionDisposition::RequireExplicitApproval
                    || result.case.status != CorePhase6RemediationStatus::AwaitingExplicitApproval
                {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn transition_phase6_remediation_status(
        &self,
        request: CorePhase6RemediationStatusTransitionRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_status_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let target_status = request.target_status;
        let note = request.note.clone();
        self.execute_unlocked_with_json(
            CoreRoute::TransitionPhase6RemediationStatus,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::StatusChanged,
                )?;
                let last_event = result.case.history.last();
                if result.case.status != target_status
                    || last_event.and_then(|event| event.note.as_deref()) != note.as_deref()
                {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn set_phase6_remediation_deadline(
        &self,
        request: CorePhase6RemediationDeadlineUpdateRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_deadline_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let deadline_at_us = request.deadline_at_us;
        self.execute_unlocked_with_json(
            CoreRoute::SetPhase6RemediationDeadline,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::DeadlineChanged,
                )?;
                if result.case.deadline_at_us != deadline_at_us {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn link_phase6_remediation_evidence(
        &self,
        request: CorePhase6RemediationEvidenceLinkRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_evidence_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let evidence_references = request.evidence_references.clone();
        self.execute_unlocked_with_json(
            CoreRoute::LinkPhase6RemediationEvidence,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::EvidenceLinked,
                )?;
                let Some(last_event) = result.case.history.last() else {
                    return Err(CoreError::InvalidPhase6Response);
                };
                if !phase6_uuid_subset(&evidence_references, &result.case.evidence_references)
                    || last_event.evidence_references.is_empty()
                    || !phase6_uuid_subset(&last_event.evidence_references, &evidence_references)
                {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn record_phase6_provider_response(
        &self,
        request: CorePhase6RemediationProviderResponseRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_provider_response_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let provider_id = request.provider_id.clone();
        let response_code = request.response_code.clone();
        let summary = request.summary.clone();
        let evidence_references = request.evidence_references.clone();
        self.execute_unlocked_with_json(
            CoreRoute::RecordPhase6ProviderResponse,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::ProviderResponseRecorded,
                )?;
                let Some(response) = result.case.provider_responses.last() else {
                    return Err(CoreError::InvalidPhase6Response);
                };
                let Some(event) = result.case.history.last() else {
                    return Err(CoreError::InvalidPhase6Response);
                };
                if response.provider_id != provider_id
                    || response.response_code != response_code
                    || response.summary != summary
                    || !phase6_uuid_sets_equal(&response.evidence_references, &evidence_references)
                    || response.received_at_us != result.case.updated_at_us
                    || event.subject_id.as_deref() != Some(provider_id.as_str())
                    || !phase6_uuid_sets_equal(&event.evidence_references, &evidence_references)
                {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn record_phase6_reappearance(
        &self,
        request: CorePhase6RemediationReappearanceRequest,
    ) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
        validate_phase6_remediation_reappearance_request(&request)?;
        let profile_id = request.profile_id;
        let case_id = request.case_id;
        let expected_revision = request.expected_revision;
        let finding_id = request.finding_id;
        let evidence_references = request.evidence_references.clone();
        self.execute_unlocked_with_json(
            CoreRoute::RecordPhase6Reappearance,
            &request,
            move |result| {
                validate_phase6_mutation_result(
                    result,
                    profile_id,
                    case_id,
                    expected_revision,
                    CorePhase6RemediationEventType::ReappearanceRecorded,
                )?;
                let Some(event) = result.case.history.last() else {
                    return Err(CoreError::InvalidPhase6Response);
                };
                let finding_id_text = finding_id.to_string();
                if !result.case.finding_ids.contains(&finding_id)
                    || !phase6_uuid_subset(&evidence_references, &result.case.evidence_references)
                    || result.case.reappearance_count == 0
                    || result.case.last_reappearance_at_us != Some(result.case.updated_at_us)
                    || event.subject_id.as_deref() != Some(finding_id_text.as_str())
                    || !phase6_uuid_sets_equal(&event.evidence_references, &evidence_references)
                {
                    return Err(CoreError::InvalidPhase6Response);
                }
                Ok(())
            },
        )
        .await
    }

    pub async fn generate_local_report(
        &self,
        request: CoreLocalReportGenerateRequest,
    ) -> Result<CoreCommandResponse<CoreLocalReportGenerateResult>, CoreCommandError> {
        validate_local_report_request(&request)?;
        let profile_id = request.profile_id;
        let baseline_run_id = request.baseline_run_id;
        let current_run_id = request.current_run_id;
        let artifact_format = request.artifact_format;
        let mode = request.mode;
        let full_export_approval_id = request.full_export_approval_id;
        self.execute_unlocked_with_json(CoreRoute::GenerateLocalReport, &request, move |result| {
            validate_local_report_result(
                result,
                profile_id,
                baseline_run_id,
                current_run_id,
                artifact_format,
                mode,
                full_export_approval_id,
            )
        })
        .await
    }

    pub async fn identity_workspace(
        &self,
        request: CoreIdentityWorkspaceRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
        validate_identity_workspace_request(&request)?;
        let profile_id = request.profile_id;
        self.execute_unlocked_with_json(CoreRoute::GetIdentityWorkspace, &request, move |result| {
            validate_identity_workspace(result, profile_id)
        })
        .await
    }

    pub async fn update_identity_person(
        &self,
        request: CoreIdentityPersonUpdateRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
        validate_identity_person_update_request(&request)?;
        let profile_id = request.profile_id;
        let expected_profile_revision = request.expected_profile_revision;
        let expected_details_revision = request.expected_details_revision;
        let display_name = request.display_name.clone();
        let purpose = request.purpose.clone();
        let notes = request.notes.clone();
        let tags = request.tags.clone();
        self.execute_unlocked_with_json(CoreRoute::UpdateIdentityPerson, &request, move |result| {
            validate_identity_workspace(result, profile_id)?;
            if result.person.profile_revision != expected_profile_revision + 1
                || result.person.details_revision != expected_details_revision + 1
                || result.person.display_name != display_name
                || result.person.purpose != purpose
                || result.person.notes != notes
                || result.person.tags != tags
            {
                return Err(CoreError::InvalidIdentityResponse);
            }
            Ok(())
        })
        .await
    }

    pub async fn create_identity_source(
        &self,
        request: CoreIdentitySourceCreateRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
        validate_identity_source_request(&request)?;
        let profile_id = request.profile_id;
        let requested_url = request.url.clone();
        self.execute_unlocked_with_json(CoreRoute::CreateIdentitySource, &request, move |result| {
            validate_identity_workspace(result, profile_id)?;
            let requested = reqwest::Url::parse(&requested_url)
                .map_err(|_| CoreError::InvalidIdentityRequest)?;
            if !result.sources.iter().any(|source| {
                reqwest::Url::parse(&source.url).is_ok_and(|returned| returned == requested)
            }) {
                return Err(CoreError::InvalidIdentityResponse);
            }
            Ok(())
        })
        .await
    }

    pub async fn create_identity_audit(
        &self,
        request: CoreIdentityAuditCreateRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
        validate_identity_audit_create_request(&request)?;
        let profile_id = request.profile_id;
        let name = request.name.clone();
        let mode = request.mode;
        let provider_ids = request.provider_ids.clone();
        let max_depth = request.max_depth;
        let request_budget = request.request_budget;
        self.execute_unlocked_with_json(CoreRoute::CreateIdentityAudit, &request, move |result| {
            validate_identity_audit_detail(result, profile_id, None)?;
            if result.audit.name != name
                || result.audit.mode != mode
                || result.audit.provider_ids != provider_ids
                || result.audit.max_depth != max_depth
                || result.audit.request_budget != request_budget
            {
                return Err(CoreError::InvalidIdentityResponse);
            }
            Ok(())
        })
        .await
    }

    pub async fn get_identity_audit(
        &self,
        request: CoreIdentityAuditExecuteRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
        validate_identity_audit_execute_request(&request)?;
        let profile_id = request.profile_id;
        let audit_id = request.audit_id;
        self.execute_unlocked_with_json(CoreRoute::GetIdentityAudit, &request, move |result| {
            validate_identity_audit_detail(result, profile_id, Some(audit_id))
        })
        .await
    }

    pub async fn execute_identity_audit_batch(
        &self,
        request: CoreIdentityAuditExecuteRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
        validate_identity_audit_execute_request(&request)?;
        let profile_id = request.profile_id;
        let audit_id = request.audit_id;
        self.execute_unlocked_with_json(
            CoreRoute::ExecuteIdentityAuditBatch,
            &request,
            move |result| validate_identity_audit_detail(result, profile_id, Some(audit_id)),
        )
        .await
    }

    pub async fn control_identity_audit(
        &self,
        request: CoreIdentityAuditControlRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
        validate_identity_audit_control_request(&request)?;
        let profile_id = request.profile_id;
        let audit_id = request.audit_id;
        let expected_revision = request.expected_revision;
        self.execute_unlocked_with_json(CoreRoute::ControlIdentityAudit, &request, move |result| {
            validate_identity_audit_detail(result, profile_id, Some(audit_id))?;
            if result.audit.revision <= expected_revision {
                return Err(CoreError::InvalidIdentityResponse);
            }
            Ok(())
        })
        .await
    }

    pub async fn decide_identity_proposal(
        &self,
        request: CoreIdentityProposalDecisionRequest,
    ) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
        validate_identity_proposal_decision_request(&request)?;
        let profile_id = request.profile_id;
        let audit_id = request.audit_id;
        let proposal_id = request.proposal_id;
        let expected_revision = request.expected_revision;
        self.execute_unlocked_with_json(
            CoreRoute::DecideIdentityProposal,
            &request,
            move |result| {
                validate_identity_audit_detail(result, profile_id, Some(audit_id))?;
                let proposal = result
                    .proposals
                    .iter()
                    .find(|proposal| proposal.proposal_id == proposal_id)
                    .ok_or(CoreError::InvalidIdentityResponse)?;
                if proposal.revision != expected_revision + 1 {
                    return Err(CoreError::InvalidIdentityResponse);
                }
                Ok(())
            },
        )
        .await
    }

    async fn execute_ready_with_json<T, B, V>(
        &self,
        route: CoreRoute,
        body: &B,
        validate_response: V,
    ) -> Result<CoreCommandResponse<T>, CoreCommandError>
    where
        T: DeserializeOwned,
        B: Serialize,
        V: FnOnce(&T) -> Result<(), CoreError>,
    {
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        if !ready_route_metadata_is_valid(route) {
            return Err(
                CoreError::InternalState("generated ready route metadata is invalid")
                    .into_command_error(fallback_request_id),
            );
        }
        let (client, endpoint, credential) = {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready {
                return Err(
                    CoreError::NotReady(inner.state).into_command_error(fallback_request_id)
                );
            }
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };
        let (request_id, data) =
            request_route_with_json::<T, _>(&client, &endpoint, &credential, route, body)
                .await
                .map_err(|error| error.into_command_error(fallback_request_id))?;
        if let Err(error) = validate_response(&data) {
            self.mark_failed(&error);
            return Err(error.into_command_error(request_id));
        }
        let state = self.lock().state;
        if state != CoreLifecycleState::Ready {
            return Err(CoreError::NotReady(state).into_command_error(request_id));
        }
        Ok(CoreCommandResponse { request_id, data })
    }

    async fn execute_unlocked<T, V>(
        &self,
        route: CoreRoute,
        validate_response: V,
    ) -> Result<CoreCommandResponse<T>, CoreCommandError>
    where
        T: DeserializeOwned,
        V: FnOnce(&T) -> Result<(), CoreError>,
    {
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        if !unlocked_route_metadata_is_valid(route) {
            return Err(
                CoreError::InternalState("generated unlocked route metadata is invalid")
                    .into_command_error(fallback_request_id),
            );
        }
        let (client, endpoint, credential) = {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
                return Err(
                    CoreError::NotReady(inner.state).into_command_error(fallback_request_id)
                );
            }
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };
        let (request_id, data) = request_route::<T>(&client, &endpoint, &credential, route)
            .await
            .map_err(|error| error.into_command_error(fallback_request_id))?;
        if let Err(error) = validate_response(&data) {
            self.mark_failed(&error);
            return Err(error.into_command_error(request_id));
        }
        let inner = self.lock();
        if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
            return Err(CoreError::NotReady(inner.state).into_command_error(request_id));
        }
        Ok(CoreCommandResponse { request_id, data })
    }

    async fn execute_unlocked_with_json<T, B, V>(
        &self,
        route: CoreRoute,
        body: &B,
        validate_response: V,
    ) -> Result<CoreCommandResponse<T>, CoreCommandError>
    where
        T: DeserializeOwned,
        B: Serialize,
        V: FnOnce(&T) -> Result<(), CoreError>,
    {
        // Serializing vault requests closes the race in which a command passes
        // an unlocked check while a lock operation revokes the session. The
        // state is checked again after response validation for the same reason.
        let _request_guard = self.vault_request_gate.lock().await;
        let _active_operation = self.begin_active_operation();
        let fallback_request_id = Uuid::new_v4();
        if !unlocked_route_metadata_is_valid(route) {
            return Err(
                CoreError::InternalState("generated unlocked route metadata is invalid")
                    .into_command_error(fallback_request_id),
            );
        }
        let (client, endpoint, credential) = {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
                return Err(
                    CoreError::NotReady(inner.state).into_command_error(fallback_request_id)
                );
            }
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };
        let (request_id, data) =
            request_route_with_json::<T, _>(&client, &endpoint, &credential, route, body)
                .await
                .map_err(|error| error.into_command_error(fallback_request_id))?;
        if let Err(error) = validate_response(&data) {
            self.mark_failed(&error);
            return Err(error.into_command_error(request_id));
        }
        {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready || !inner.vault_unlocked {
                return Err(CoreError::NotReady(inner.state).into_command_error(request_id));
            }
        }
        Ok(CoreCommandResponse { request_id, data })
    }

    fn take_lease_operation(
        &self,
        next_state: CoreLifecycleState,
    ) -> Result<LeaseOperationRuntime, CoreError> {
        let mut inner = self.lock();
        if inner.state != CoreLifecycleState::Ready || inner.vault_unlocked {
            return Err(CoreError::NotReady(inner.state));
        }
        let broker = inner
            .key_lease_broker
            .take()
            .ok_or(CoreError::InternalState(
                "ready state has no key-lease broker",
            ))?;
        let handle = inner
            .key_lease_handle
            .take()
            .ok_or(CoreError::InternalState(
                "ready state has no key-lease handle",
            ))?;
        let runtime = LeaseOperationRuntime {
            client: inner
                .client
                .clone()
                .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
            endpoint: inner
                .endpoint
                .clone()
                .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
            credential: inner
                .credential
                .clone()
                .ok_or(CoreError::InternalState("ready state has no credential"))?,
            broker,
            handle,
        };
        inner.state = next_state;
        Ok(runtime)
    }

    fn finish_lease_operation(&self, expected: CoreLifecycleState) -> Result<(), CoreError> {
        let mut inner = self.lock();
        if inner.state != expected {
            return Err(CoreError::NotReady(inner.state));
        }
        inner.vault_unlocked = true;
        inner.state = CoreLifecycleState::Ready;
        Ok(())
    }

    fn state_is(&self, expected: CoreLifecycleState) -> bool {
        self.lock().state == expected
    }

    async fn execute<T>(&self, route: CoreRoute) -> Result<CoreCommandResponse<T>, CoreCommandError>
    where
        T: DeserializeOwned,
    {
        let fallback_request_id = Uuid::new_v4();
        let (client, endpoint, credential) = {
            let inner = self.lock();
            if inner.state != CoreLifecycleState::Ready {
                return Err(
                    CoreError::NotReady(inner.state).into_command_error(fallback_request_id)
                );
            }
            (
                inner
                    .client
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no HTTP client"))?,
                inner
                    .endpoint
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no endpoint"))?,
                inner
                    .credential
                    .clone()
                    .ok_or(CoreError::InternalState("ready state has no credential"))?,
            )
        };

        match request_route::<T>(&client, &endpoint, &credential, route).await {
            Ok((request_id, data)) => Ok(CoreCommandResponse { request_id, data }),
            Err(error) => {
                self.mark_failed(&error);
                Err(error.into_command_error(fallback_request_id))
            }
        }
    }

    pub async fn stop(&self) {
        let child = {
            let mut inner = self.lock();
            match inner.state {
                CoreLifecycleState::NotStarted | CoreLifecycleState::Stopped => return,
                _ => inner.state = CoreLifecycleState::Stopping,
            }
            inner.endpoint = None;
            inner.client = None;
            inner.credential = None;
            inner.key_lease_broker = None;
            inner.key_lease_handle = None;
            inner.vault_unlocked = false;
            inner.policy_restart_pending = false;
            inner.restart_scheduled = false;
            inner.child.take()
        };

        if let Some(child) = child {
            terminate_child(child).await;
        }

        let mut inner = self.lock();
        inner.state = CoreLifecycleState::Stopped;
    }

    pub async fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::Release);
        self.stop().await;
    }

    pub fn request_system_lock(&self) -> bool {
        let Some(plan) = self.begin_system_lock() else {
            return false;
        };
        let supervisor = self.clone();
        tauri::async_runtime::spawn(async move {
            if let Some(child) = plan.child {
                terminate_child(child).await;
            }
            while supervisor.active_operations.load(Ordering::Acquire) != 0 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            let should_restart = {
                let mut inner = supervisor.lock();
                if !inner.policy_restart_pending {
                    false
                } else {
                    inner.policy_restart_pending = false;
                    inner.state = CoreLifecycleState::Stopped;
                    !supervisor.shutting_down.load(Ordering::Acquire)
                }
            };
            if should_restart {
                let _ = supervisor.start().await;
            }
        });
        true
    }

    fn begin_system_lock(&self) -> Option<SystemLockPlan> {
        // Revoke every in-memory capability before waiting on child termination.
        // Durable core work is recovered later from its own leases; retaining an
        // HTTP client or credential during system lock would violate fail-closed.
        let mut inner = self.lock();
        let sensitive = matches!(
            inner.state,
            CoreLifecycleState::Creating | CoreLifecycleState::Unlocking
        ) || (inner.state == CoreLifecycleState::Ready && inner.vault_unlocked);
        if !sensitive || inner.policy_restart_pending {
            return None;
        }
        inner.state = CoreLifecycleState::Stopping;
        inner.endpoint = None;
        inner.client = None;
        inner.credential = None;
        inner.key_lease_broker = None;
        inner.key_lease_handle = None;
        inner.vault_unlocked = false;
        inner.policy_restart_pending = true;
        let mut child = inner.child.take();
        if let Some(process) = child.as_mut() {
            request_child_termination(process);
        }
        Some(SystemLockPlan { child })
    }

    fn begin_active_operation(&self) -> ActiveOperation {
        self.active_operations.fetch_add(1, Ordering::AcqRel);
        ActiveOperation {
            counter: Arc::clone(&self.active_operations),
        }
    }

    fn observe_child_exit(&self) -> Option<ChildExitPlan> {
        let mut inner = self.lock();
        let needs_termination = match inner.child.as_mut()?.try_wait() {
            Ok(Some(_status)) => false,
            Ok(None) => return None,
            Err(_) => true,
        };
        let mut child = inner.child.take();
        if needs_termination && let Some(process) = child.as_mut() {
            request_child_termination(process);
        }

        let expected = matches!(
            inner.state,
            CoreLifecycleState::Starting
                | CoreLifecycleState::Locking
                | CoreLifecycleState::Stopping
                | CoreLifecycleState::Stopped
        );
        inner.endpoint = None;
        inner.client = None;
        inner.credential = None;
        inner.key_lease_broker = None;
        inner.key_lease_handle = None;
        inner.vault_unlocked = false;
        if expected {
            inner.state = CoreLifecycleState::Stopped;
            inner.restart_scheduled = false;
        } else {
            inner.state = CoreLifecycleState::Failed;
            inner.last_error_code = Some("CORE_CHILD_EXITED");
            inner.restart_scheduled = true;
        }
        Some(ChildExitPlan {
            child_to_terminate: needs_termination.then_some(child).flatten(),
            restart: !expected,
        })
    }

    async fn recover_after_unexpected_exit(&self) {
        loop {
            while self.active_operations.load(Ordering::Acquire) != 0 {
                if self.shutting_down.load(Ordering::Acquire) {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            let Some(delay) = self.reserve_crash_restart() else {
                return;
            };
            tokio::time::sleep(delay).await;
            if self.shutting_down.load(Ordering::Acquire) || !self.restart_is_still_needed() {
                return;
            }
            if self.start().await.is_ok() {
                self.lock().restart_scheduled = false;
                return;
            }
        }
    }

    fn reserve_crash_restart(&self) -> Option<Duration> {
        let mut inner = self.lock();
        if inner.state != CoreLifecycleState::Failed || !inner.restart_scheduled {
            return None;
        }
        match inner.restart_budget.reserve(Instant::now()) {
            Some(delay) => Some(delay),
            None => {
                inner.restart_scheduled = false;
                inner.last_error_code = Some("CORE_RESTART_BUDGET_EXHAUSTED");
                None
            }
        }
    }

    fn restart_is_still_needed(&self) -> bool {
        let inner = self.lock();
        inner.state == CoreLifecycleState::Failed && inner.restart_scheduled
    }

    pub fn force_stop(&self) {
        self.shutting_down.store(true, Ordering::Release);
        let mut inner = self.lock();
        inner.endpoint = None;
        inner.client = None;
        inner.credential = None;
        inner.key_lease_broker = None;
        inner.key_lease_handle = None;
        inner.vault_unlocked = false;
        inner.policy_restart_pending = false;
        inner.restart_scheduled = false;
        // This path runs only once Tauri is already exiting. Detach instead of
        // abruptly signalling the one-file bootloader; the sidecar's parent
        // watcher observes this process exiting and performs socket cleanup.
        drop(inner.child.take());
        inner.state = CoreLifecycleState::Stopped;
    }

    fn mark_failed(&self, error: &CoreError) {
        let mut inner = self.lock();
        if inner.state == CoreLifecycleState::Stopping && inner.policy_restart_pending {
            return;
        }
        inner.endpoint = None;
        inner.client = None;
        inner.credential = None;
        inner.key_lease_broker = None;
        inner.key_lease_handle = None;
        inner.vault_unlocked = false;
        inner.last_error_code = Some(error.code());
        if let Some(mut child) = inner.child.take() {
            request_child_termination(&mut child);
        }
        inner.state = CoreLifecycleState::Failed;
    }

    fn lock(&self) -> MutexGuard<'_, SupervisorInner> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    #[cfg(test)]
    fn snapshot(&self) -> SupervisorSnapshot {
        let inner = self.lock();
        SupervisorSnapshot {
            state: inner.state,
            has_endpoint: inner.endpoint.is_some(),
            has_credential: inner.credential.is_some(),
            has_key_lease_broker: inner.key_lease_broker.is_some(),
            has_key_lease_handle: inner.key_lease_handle.is_some(),
        }
    }
}

#[derive(Default)]
struct SupervisorInner {
    state: CoreLifecycleState,
    child: Option<Child>,
    endpoint: Option<CoreEndpoint>,
    client: Option<Client>,
    credential: Option<Arc<SessionCredential>>,
    key_lease_broker: Option<KeyLeaseBroker>,
    key_lease_handle: Option<KeyLeaseHandle>,
    vault_unlocked: bool,
    policy_restart_pending: bool,
    restart_scheduled: bool,
    restart_budget: RestartBudget,
    last_error_code: Option<&'static str>,
}

struct ActiveOperation {
    counter: Arc<AtomicUsize>,
}

struct SystemLockPlan {
    child: Option<Child>,
}

struct ChildExitPlan {
    child_to_terminate: Option<Child>,
    restart: bool,
}

#[derive(Default)]
struct RestartBudget {
    attempts: VecDeque<Instant>,
}

impl RestartBudget {
    fn reserve(&mut self, now: Instant) -> Option<Duration> {
        while self
            .attempts
            .front()
            .is_some_and(|attempt| now.duration_since(*attempt) >= CRASH_RESTART_WINDOW)
        {
            self.attempts.pop_front();
        }
        let delay = CRASH_RESTART_BACKOFF.get(self.attempts.len()).copied()?;
        self.attempts.push_back(now);
        Some(delay)
    }
}

impl Drop for ActiveOperation {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::AcqRel);
    }
}

struct LeaseOperationRuntime {
    client: Client,
    endpoint: CoreEndpoint,
    credential: Arc<SessionCredential>,
    broker: KeyLeaseBroker,
    handle: KeyLeaseHandle,
}

impl Drop for SupervisorInner {
    fn drop(&mut self) {
        self.endpoint = None;
        self.client = None;
        self.credential = None;
        self.key_lease_broker = None;
        self.key_lease_handle = None;
        self.vault_unlocked = false;
        // `Child` is deliberately not kill-on-drop. An unplanned parent exit is
        // handled by the sidecar's bounded parent watcher so its UDS is removed.
        drop(self.child.take());
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) enum CoreLifecycleState {
    #[default]
    NotStarted,
    Starting,
    Ready,
    Creating,
    Unlocking,
    Locking,
    Stopping,
    Stopped,
    Failed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RuntimeMode {
    Development,
    Packaged,
}

fn validate_display_name(value: &str) -> Result<(), CoreError> {
    if value.is_empty()
        || value.chars().count() > 80
        || value.trim() != value
        || value.chars().any(char::is_control)
    {
        return Err(CoreError::InvalidDisplayName);
    }
    Ok(())
}

fn validate_profile_create_request(request: &CoreProfileCreateRequest) -> Result<(), CoreError> {
    validate_idempotency_key(&request.idempotency_key)?;
    if !is_safe_bounded_text(&request.display_label, 1, 80)
        || !is_safe_bounded_text(&request.purpose, 1, 240)
    {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_profile_delete_request(request: &CoreProfileDeleteRequest) -> Result<(), CoreError> {
    if request.expected_revision == 0 || !is_safe_bounded_text(&request.confirmation_label, 1, 80) {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn ready_route_metadata_is_valid(route: CoreRoute) -> bool {
    let capability = route.capability();
    if capability.required_lock_state != "ANY" {
        return false;
    }
    if capability.scope_class != "NONE"
        || capability.reveal_class != "NONE"
        || capability.authorization_class != "USER_GESTURE"
    {
        return false;
    }
    match route {
        CoreRoute::SearchPublicDiscovery => {
            capability.max_request_bytes == 8_192 && capability.max_response_bytes == 262_144
        }
        CoreRoute::CompileInvestigationPlan => {
            capability.max_request_bytes == 40_960 && capability.max_response_bytes == 262_144
        }
        CoreRoute::SearchHibpAccount | CoreRoute::SearchHibpDomain => {
            capability.max_request_bytes == 4_096
                && capability.max_response_bytes == MAX_HIBP_RESPONSE_BYTES
        }
        _ => false,
    }
}

fn unlocked_route_metadata_is_valid(route: CoreRoute) -> bool {
    let capability = route.capability();
    if capability.required_lock_state != "UNLOCKED" || capability.reveal_class != "NONE" {
        return false;
    }
    match route {
        CoreRoute::ListProfiles => {
            capability.scope_class == "VAULT" && capability.authorization_class == "SHELL_INTERNAL"
        }
        CoreRoute::CreateProfile => {
            capability.scope_class == "VAULT" && capability.authorization_class == "USER_GESTURE"
        }
        CoreRoute::IntakeFile => {
            capability.scope_class == "PROFILE"
                && capability.authorization_class == "USER_GESTURE_FILE_PICKER"
        }
        CoreRoute::IntakePaste
        | CoreRoute::ReviewEntities
        | CoreRoute::DecideEntity
        | CoreRoute::EntityOrigins
        | CoreRoute::GraphSnapshot => {
            capability.scope_class == "PROFILE" && capability.authorization_class == "USER_GESTURE"
        }
        CoreRoute::GetLocalAiSettings
        | CoreRoute::UpdateLocalAiSettings
        | CoreRoute::DiscoverLocalAiModels
        | CoreRoute::TestLocalAiConnection => {
            capability.scope_class == "VAULT" && capability.authorization_class == "USER_GESTURE"
        }
        CoreRoute::AnalyzeLocalAiWorkspace => {
            capability.scope_class == "PROFILE"
                && capability.authorization_class == "USER_GESTURE"
                && capability.max_request_bytes == 100_000
                && capability.max_response_bytes == 131_072
        }
        CoreRoute::AnalyzeLocalAiCorpus => {
            capability.scope_class == "PROFILE"
                && capability.authorization_class == "USER_GESTURE"
                && capability.max_request_bytes == 5_750_000
                && capability.max_response_bytes == 256_000
        }
        CoreRoute::CapturePublicDiscovery
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
        | CoreRoute::RecordPhase6Reappearance => {
            capability.scope_class == "PROFILE" && capability.authorization_class == "USER_GESTURE"
        }
        CoreRoute::GenerateLocalReport => {
            capability.scope_class == "PROFILE"
                && capability.authorization_class == "USER_GESTURE"
                && capability.max_request_bytes == 1_024
                && capability.max_response_bytes == MAX_LOCAL_REPORT_RESPONSE_BYTES
        }
        CoreRoute::GetIdentityWorkspace
        | CoreRoute::UpdateIdentityPerson
        | CoreRoute::CreateIdentitySource
        | CoreRoute::CreateIdentityAudit
        | CoreRoute::GetIdentityAudit
        | CoreRoute::ExecuteIdentityAuditBatch
        | CoreRoute::ControlIdentityAudit
        | CoreRoute::DecideIdentityProposal => {
            capability.scope_class == "PROFILE"
                && capability.authorization_class == "USER_GESTURE"
                && capability.max_request_bytes == 32_768
                && capability.max_response_bytes == MAX_RESPONSE_BYTES
        }
        _ => false,
    }
}

fn validate_identity_workspace_request(
    request: &CoreIdentityWorkspaceRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id) {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_person_update_request(
    request: &CoreIdentityPersonUpdateRequest,
) -> Result<(), CoreError> {
    validate_identity_workspace_request(&CoreIdentityWorkspaceRequest {
        profile_id: request.profile_id,
    })?;
    let mut tags = HashSet::with_capacity(request.tags.len());
    if request.expected_profile_revision == 0
        || request.expected_profile_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || request.expected_details_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_safe_bounded_text(&request.display_name, 1, 80)
        || !is_safe_multiline_text(&request.purpose, 1, 240)
        || !(request.notes.is_empty() || is_safe_multiline_text(&request.notes, 1, 20_000))
        || request.tags.len() > 32
        || request
            .tags
            .iter()
            .any(|tag| !is_safe_bounded_text(tag, 1, 48) || !tags.insert(tag.as_str()))
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_source_request(
    request: &CoreIdentitySourceCreateRequest,
) -> Result<(), CoreError> {
    validate_identity_workspace_request(&CoreIdentityWorkspaceRequest {
        profile_id: request.profile_id,
    })?;
    if !request.authorized_self_audit
        || !is_identity_url(&request.url)
        || request
            .title
            .as_deref()
            .is_some_and(|title| !is_safe_multiline_text(title, 1, 240))
        || !(request.notes.is_empty() || is_safe_multiline_text(&request.notes, 1, 4_000))
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_audit_create_request(
    request: &CoreIdentityAuditCreateRequest,
) -> Result<(), CoreError> {
    validate_identity_workspace_request(&CoreIdentityWorkspaceRequest {
        profile_id: request.profile_id,
    })?;
    let providers: HashSet<&str> = request.provider_ids.iter().map(String::as_str).collect();
    if !request.authorized_self_audit
        || !is_safe_bounded_text(&request.name, 1, 120)
        || request.provider_ids.is_empty()
        || request.provider_ids.len() > 8
        || providers.len() != request.provider_ids.len()
        || request
            .provider_ids
            .iter()
            .any(|provider| !is_identity_audit_provider(provider))
        || request.max_depth > 8
        || request.request_budget == 0
        || request.request_budget > 2_000
        || !(10..=86_400).contains(&request.time_budget_seconds)
        || request.cost_budget_micros > 1_000_000_000_000
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_audit_execute_request(
    request: &CoreIdentityAuditExecuteRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.audit_id)
        || !(1..=8).contains(&request.maximum_tasks)
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_audit_control_request(
    request: &CoreIdentityAuditControlRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.audit_id)
        || request.expected_revision == 0
        || request.expected_revision > MAX_SAFE_JAVASCRIPT_INTEGER
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_proposal_decision_request(
    request: &CoreIdentityProposalDecisionRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.audit_id)
        || !is_rfc4122_uuid(request.proposal_id)
        || request.expected_revision == 0
        || request.expected_revision > MAX_SAFE_JAVASCRIPT_INTEGER
    {
        return Err(CoreError::InvalidIdentityRequest);
    }
    Ok(())
}

fn validate_identity_workspace(
    result: &CoreIdentityWorkspace,
    profile_id: Uuid,
) -> Result<(), CoreError> {
    if result.person.profile_id != profile_id
        || !is_rfc4122_uuid(result.person.profile_id)
        || !is_safe_bounded_text(&result.person.display_name, 1, 80)
        || !is_safe_multiline_text(&result.person.purpose, 1, 240)
        || !is_bounded_event_label(&result.person.status, 32)
        || !(result.person.notes.is_empty()
            || is_safe_multiline_text(&result.person.notes, 1, 20_000))
        || result.person.tags.len() > 32
        || result.person.profile_revision == 0
        || result.person.profile_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || result.person.details_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || result.sources.len() > MAX_IDENTITY_SOURCES
        || result.audits.len() > MAX_IDENTITY_AUDITS
    {
        return Err(CoreError::InvalidIdentityResponse);
    }
    let mut tags = HashSet::with_capacity(result.person.tags.len());
    if result
        .person
        .tags
        .iter()
        .any(|tag| !is_safe_bounded_text(tag, 1, 48) || !tags.insert(tag.as_str()))
    {
        return Err(CoreError::InvalidIdentityResponse);
    }
    let mut source_ids = HashSet::with_capacity(result.sources.len());
    for source in &result.sources {
        if !source_ids.insert(source.source_id) || !validate_identity_source(source) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    let mut audit_ids = HashSet::with_capacity(result.audits.len());
    for audit in &result.audits {
        if !audit_ids.insert(audit.audit_id) || !validate_identity_audit_summary(audit) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    Ok(())
}

fn validate_identity_audit_detail(
    result: &CoreIdentityAuditDetail,
    profile_id: Uuid,
    audit_id: Option<Uuid>,
) -> Result<(), CoreError> {
    if result.profile_id != profile_id
        || !is_rfc4122_uuid(result.profile_id)
        || audit_id.is_some_and(|expected| result.audit.audit_id != expected)
        || !validate_identity_audit_summary(&result.audit)
        || result.tasks.len() > MAX_IDENTITY_TASKS
        || result.results.len() > MAX_IDENTITY_RESULTS
        || result.leads.len() > MAX_IDENTITY_LEADS
        || result.proposals.len() > MAX_IDENTITY_PROPOSALS
        || result.receipts.len() > MAX_IDENTITY_RECEIPTS
    {
        return Err(CoreError::InvalidIdentityResponse);
    }

    let mut task_ids = HashSet::with_capacity(result.tasks.len());
    for task in &result.tasks {
        if !task_ids.insert(task.task_id) || !validate_identity_task(task) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    let mut result_ids = HashSet::with_capacity(result.results.len());
    for discovery_result in &result.results {
        if !result_ids.insert(discovery_result.result_id)
            || !validate_identity_result(discovery_result)
        {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    let mut lead_ids = HashSet::with_capacity(result.leads.len());
    for lead in &result.leads {
        if !lead_ids.insert(lead.lead_id) || !validate_identity_lead(lead) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    let mut proposal_ids = HashSet::with_capacity(result.proposals.len());
    for proposal in &result.proposals {
        if !proposal_ids.insert(proposal.proposal_id) || !validate_identity_proposal(proposal) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    let mut receipt_ids = HashSet::with_capacity(result.receipts.len());
    for receipt in &result.receipts {
        if !receipt_ids.insert(receipt.receipt_id) || !validate_identity_receipt(receipt) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    if let Some(analysis) = &result.ai_analysis {
        let result_by_id: HashMap<Uuid, &CoreIdentityDiscoveryResult> = result
            .results
            .iter()
            .map(|item| (item.result_id, item))
            .collect();
        if !validate_identity_ai_analysis(analysis, &result_by_id) {
            return Err(CoreError::InvalidIdentityResponse);
        }
    }
    Ok(())
}

fn validate_identity_source(source: &CoreIdentitySource) -> bool {
    is_rfc4122_uuid(source.source_id)
        && source.parent_source_id.is_none_or(is_rfc4122_uuid)
        && is_identity_url(&source.url)
        && source
            .title
            .as_deref()
            .is_none_or(|title| title.is_empty() || is_safe_multiline_text(title, 1, 240))
        && (source.notes.is_empty() || is_safe_multiline_text(&source.notes, 1, 4_000))
        && is_bounded_event_label(&source.relationship_state, 32)
        && is_valid_timestamp_us(source.first_seen_at_us)
        && source.last_checked_at_us.is_none_or(is_valid_timestamp_us)
        && source
            .http_status
            .is_none_or(|status| (100..=599).contains(&status))
        && source.revision > 0
        && source.revision <= MAX_SAFE_JAVASCRIPT_INTEGER
}

fn validate_identity_audit_summary(audit: &CoreIdentityAuditSummary) -> bool {
    let providers: HashSet<&str> = audit.provider_ids.iter().map(String::as_str).collect();
    let mut states = HashSet::with_capacity(audit.task_states.len());
    let state_total = audit.task_states.iter().fold(0_u64, |total, state| {
        total.saturating_add(u64::from(state.count))
    });
    let terminal_total = audit
        .task_states
        .iter()
        .filter(|state| is_terminal_identity_task_state(state.state))
        .fold(0_u64, |total, state| {
            total.saturating_add(u64::from(state.count))
        });
    let expected_progress = if audit.total_tasks == 0 {
        1_000_000
    } else {
        audit
            .terminal_tasks
            .saturating_mul(1_000_000)
            .checked_div(audit.total_tasks)
            .unwrap_or_default()
    };
    is_rfc4122_uuid(audit.audit_id)
        && is_safe_bounded_text(&audit.name, 1, 120)
        && !audit.provider_ids.is_empty()
        && audit.provider_ids.len() <= 8
        && providers.len() == audit.provider_ids.len()
        && audit
            .provider_ids
            .iter()
            .all(|provider| is_identity_audit_provider(provider))
        && audit
            .selected_model
            .as_deref()
            .is_none_or(|model| is_safe_bounded_text(model, 1, 256))
        && audit.max_depth <= 8
        && (1..=2_000).contains(&audit.request_budget)
        && audit.terminal_tasks <= audit.total_tasks
        && audit.progress_micros == expected_progress
        && state_total == u64::from(audit.total_tasks)
        && terminal_total == u64::from(audit.terminal_tasks)
        && audit
            .task_states
            .iter()
            .all(|state| states.insert(state.state))
        && audit.progress_micros <= 1_000_000
        && audit
            .stop_reason
            .as_deref()
            .is_none_or(|reason| is_bounded_event_label(reason, 64))
        && audit.started_at_us.is_none_or(is_valid_timestamp_us)
        && audit.finished_at_us.is_none_or(is_valid_timestamp_us)
        && is_valid_timestamp_us(audit.created_at_us)
        && is_valid_timestamp_us(audit.updated_at_us)
        && audit.updated_at_us >= audit.created_at_us
        && audit.revision > 0
        && audit.revision <= MAX_SAFE_JAVASCRIPT_INTEGER
}

fn validate_identity_task(task: &CoreIdentityFrontierTask) -> bool {
    is_rfc4122_uuid(task.task_id)
        && task.lead_id.is_none_or(is_rfc4122_uuid)
        && task.parent_task_id.is_none_or(is_rfc4122_uuid)
        && is_identity_provider_label(&task.provider_id)
        && is_safe_multiline_text(&task.masked_payload, 1, 512)
        && task.priority <= 100
        && task.information_gain_micros <= 1_000_000
        && task.depth <= 8
        && task.retry_limit <= 10
        && task
            .stop_reason
            .as_deref()
            .is_none_or(|reason| is_bounded_event_label(reason, 96))
        && task.revision > 0
        && task.revision <= MAX_SAFE_JAVASCRIPT_INTEGER
}

fn validate_identity_result(result: &CoreIdentityDiscoveryResult) -> bool {
    is_rfc4122_uuid(result.result_id)
        && is_rfc4122_uuid(result.task_id)
        && is_identity_provider_label(&result.provider_id)
        && result.rank > 0
        && is_safe_bounded_text(&result.category, 1, 64)
        && is_identity_url(&result.url)
        && (result.title.is_empty() || is_safe_multiline_text(&result.title, 1, 512))
        && (result.snippet.is_empty() || is_safe_multiline_text(&result.snippet, 1, 4_000))
        && is_valid_timestamp_us(result.observed_at_us)
        && is_bounded_event_label(&result.review_state, 32)
}

fn validate_identity_lead(lead: &CoreIdentityDiscoveryLead) -> bool {
    is_rfc4122_uuid(lead.lead_id)
        && lead.parent_lead_id.is_none_or(is_rfc4122_uuid)
        && lead.source_id.is_none_or(is_rfc4122_uuid)
        && is_safe_bounded_text(&lead.lead_type, 1, 48)
        && is_safe_multiline_text(&lead.display_value, 1, 512)
        && lead.source_url.as_deref().is_none_or(is_identity_url)
        && is_identity_provider_label(&lead.provider_id)
        && lead.depth <= 8
        && lead.supporting_signals.len() <= 32
        && lead.contradictions.len() <= 32
        && lead
            .supporting_signals
            .iter()
            .chain(&lead.contradictions)
            .all(|signal| is_safe_multiline_text(signal, 1, 512))
        && lead.confidence_micros <= 1_000_000
        && is_bounded_event_label(&lead.ownership_state, 32)
        && is_bounded_event_label(&lead.temporal_state, 32)
        && is_bounded_event_label(&lead.review_state, 32)
        && is_bounded_event_label(&lead.expansion_state, 32)
}

fn validate_identity_proposal(proposal: &CoreIdentityKnowledgeProposal) -> bool {
    let spans_valid = match (proposal.source_span_start, proposal.source_span_end) {
        (None, None) => true,
        (Some(start), Some(end)) => start < end,
        _ => false,
    };
    is_rfc4122_uuid(proposal.proposal_id)
        && is_rfc4122_uuid(proposal.lead_id)
        && is_safe_bounded_text(&proposal.entity_type, 1, 48)
        && is_safe_multiline_text(&proposal.display_value, 1, 512)
        && is_identity_url(&proposal.source_url)
        && spans_valid
        && proposal.supporting_signals.len() <= 32
        && proposal.contradictions.len() <= 32
        && proposal
            .supporting_signals
            .iter()
            .chain(&proposal.contradictions)
            .all(|signal| is_safe_multiline_text(signal, 1, 512))
        && proposal.confidence_micros <= 1_000_000
        && is_bounded_event_label(&proposal.temporal_state, 32)
        && is_bounded_event_label(&proposal.review_state, 32)
        && proposal.recommended_actions.len() <= 16
        && proposal
            .recommended_actions
            .iter()
            .all(|action| is_bounded_event_label(action, 64))
        && proposal
            .model_provider
            .as_deref()
            .is_none_or(|provider| is_safe_bounded_text(provider, 1, 64))
        && proposal
            .model_id
            .as_deref()
            .is_none_or(|model| is_safe_bounded_text(model, 1, 256))
        && proposal.revision > 0
        && proposal.revision <= MAX_SAFE_JAVASCRIPT_INTEGER
}

fn validate_identity_receipt(receipt: &CoreIdentityToolReceipt) -> bool {
    is_rfc4122_uuid(receipt.receipt_id)
        && receipt.task_id.is_none_or(is_rfc4122_uuid)
        && is_bounded_event_label(&receipt.authorization_state, 32)
        && is_bounded_event_label(&receipt.execution_state, 32)
        && is_bounded_event_label(&receipt.result_code, 96)
        && receipt
            .model_provider
            .as_deref()
            .is_none_or(|provider| is_safe_bounded_text(provider, 1, 64))
        && receipt
            .model_id
            .as_deref()
            .is_none_or(|model| is_safe_bounded_text(model, 1, 256))
        && is_valid_timestamp_us(receipt.started_at_us)
        && is_valid_timestamp_us(receipt.finished_at_us)
        && receipt.finished_at_us >= receipt.started_at_us
}

fn validate_identity_ai_analysis(
    analysis: &CoreIdentityAiAnalysis,
    results: &HashMap<Uuid, &CoreIdentityDiscoveryResult>,
) -> bool {
    if !is_rfc4122_uuid(analysis.analysis_id)
        || !is_bounded_event_label(&analysis.result_code, 96)
        || analysis
            .provider
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        || analysis
            .model_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 256))
        || analysis
            .engine_version
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        || (analysis.title.is_empty() || !is_safe_multiline_text(&analysis.title, 1, 500))
        || (analysis.summary.is_empty() || !is_safe_multiline_text(&analysis.summary, 1, 4_000))
        || analysis.insights.len() > MAX_IDENTITY_AI_INSIGHTS
        || analysis.citations.len() > MAX_IDENTITY_AI_CITATIONS
        || analysis.limitations.len() > 32
        || !analysis
            .limitations
            .iter()
            .all(|value| is_safe_multiline_text(value, 1, 2_000))
        || !is_valid_timestamp_us(analysis.created_at_us)
    {
        return false;
    }
    let mut references = HashSet::with_capacity(analysis.citations.len());
    for citation in &analysis.citations {
        let expected_reference = format!("result:{}", citation.result_id);
        let Some(result) = results.get(&citation.result_id) else {
            return false;
        };
        if citation.reference_id != expected_reference
            || !references.insert(citation.reference_id.as_str())
            || citation.url != result.url
            || citation.title != result.title
        {
            return false;
        }
    }
    analysis.insights.iter().all(|insight| {
        is_safe_multiline_text(&insight.statement, 1, 2_000)
            && (insight.rationale.is_empty()
                || is_safe_multiline_text(&insight.rationale, 1, 2_000))
            && insight
                .confidence
                .as_deref()
                .is_none_or(|value| matches!(value, "HIGH" | "MEDIUM" | "LOW"))
            && insight.evidence_refs.len() <= 32
            && insight
                .evidence_refs
                .iter()
                .all(|reference| references.contains(reference.as_str()))
    })
}

fn is_identity_url(value: &str) -> bool {
    if !is_safe_bounded_text(value, 8, 2_048) {
        return false;
    }
    let Ok(url) = reqwest::Url::parse(value) else {
        return false;
    };
    matches!(url.scheme(), "http" | "https")
        && url.host_str().is_some()
        && url.username().is_empty()
        && url.password().is_none()
}

fn is_identity_audit_provider(value: &str) -> bool {
    matches!(
        value,
        "DUCKDUCKGO_HTML"
            | "GITHUB_USERS"
            | "GITLAB_USERS"
            | "NPM_REGISTRY"
            | "RDAP_DOMAIN"
            | "WAYBACK_CDX"
            | "CERTIFICATE_TRANSPARENCY"
            | "HAVE_I_BEEN_PWNED_V3"
            | "MANUAL_BROWSER_HANDOFFS"
    )
}

fn is_identity_provider_label(value: &str) -> bool {
    is_bounded_event_label(value, 64)
}

const fn is_terminal_identity_task_state(state: CoreIdentityTaskState) -> bool {
    matches!(
        state,
        CoreIdentityTaskState::SucceededEmpty
            | CoreIdentityTaskState::SucceededResults
            | CoreIdentityTaskState::Blocked
            | CoreIdentityTaskState::RateLimited
            | CoreIdentityTaskState::AuthRequired
            | CoreIdentityTaskState::FailedTerminal
            | CoreIdentityTaskState::Skipped
            | CoreIdentityTaskState::Cancelled
            | CoreIdentityTaskState::ReviewRequired
            | CoreIdentityTaskState::Reviewed
            | CoreIdentityTaskState::Saved
    )
}

fn validate_query_provider_catalog(
    result: &CoreProviderCatalogResult,
    profile_id: Uuid,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.providers.is_empty()
        || result.providers.len() > MAX_QUERY_PROVIDERS
        || result.external_provider_count != 0
    {
        return Err(CoreError::InvalidQueryResponse);
    }
    let mut provider_ids = HashSet::with_capacity(result.providers.len());
    for provider in &result.providers {
        if !provider_ids.insert(provider.provider_id.as_str())
            || !is_query_provider_id(&provider.provider_id)
            || !is_safe_bounded_text(&provider.display_name, 1, 96)
            || !is_safe_bounded_text(&provider.operator, 1, 128)
            || !matches!(provider.adapter_mode.as_str(), "DRY_RUN" | "MANUAL_LOCAL")
            || provider.access_basis != "LOCAL_ONLY"
            || !provider.processing_regions.is_empty()
            || provider.network_access
            || provider.sends_identifiers
            || !provider.enabled
            || !provider.retention_known
        {
            return Err(CoreError::InvalidQueryResponse);
        }
    }
    Ok(())
}

fn validate_query_plan_request(request: &CoreQueryPlanRequest) -> Result<(), CoreError> {
    let selected: HashSet<&str> = request.provider_ids.iter().map(String::as_str).collect();
    let allowed: HashSet<&str> = request
        .allowed_provider_ids
        .iter()
        .map(String::as_str)
        .collect();
    let regions: HashSet<&str> = request.allowed_regions.iter().map(String::as_str).collect();
    if !is_bounded_event_label(&request.purpose_code, 96)
        || request.purpose_code.len() < 3
        || request.provider_ids.is_empty()
        || request.provider_ids.len() > 2
        || selected.len() != request.provider_ids.len()
        || request
            .provider_ids
            .iter()
            .any(|provider| !is_query_provider_id(provider))
        || request.allowed_provider_ids.len() > 2
        || allowed.len() != request.allowed_provider_ids.len()
        || !allowed.is_subset(&selected)
        || (request.policy_mode == CoreQueryPolicyMode::Custom && allowed.is_empty())
        || request.allowed_regions.len() > 8
        || regions.len() != request.allowed_regions.len()
        || request.allowed_regions.iter().any(|region| {
            region.len() != 2 || !region.bytes().all(|byte| byte.is_ascii_uppercase())
        })
        || request.maximum_checks == 0
        || usize::from(request.maximum_checks) > MAX_QUERY_PLAN_CELLS
        || request.maximum_checks_per_provider == 0
        || request.maximum_checks_per_provider > 100
        || request.maximum_checks_per_provider > request.maximum_checks
    {
        return Err(CoreError::InvalidQueryRequest);
    }
    Ok(())
}

fn validate_query_dry_run_request(request: &CoreQueryDryRunRequest) -> Result<(), CoreError> {
    if request.expected_revision == 0 || request.expected_revision > MAX_SAFE_JAVASCRIPT_INTEGER {
        return Err(CoreError::InvalidQueryRequest);
    }
    Ok(())
}

fn validate_query_plan_result(
    result: &CoreQueryPlanResult,
    profile_id: Uuid,
    policy_mode: CoreQueryPolicyMode,
    selected_provider_ids: &[String],
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.policy_mode != policy_mode
        || result.cells.len() > MAX_QUERY_PLAN_CELLS
    {
        return Err(CoreError::InvalidQueryResponse);
    }
    let selected: HashSet<&str> = selected_provider_ids.iter().map(String::as_str).collect();
    let mut check_ids = HashSet::with_capacity(result.cells.len());
    let mut planned_count = 0_u16;
    let mut approval_required_count = 0_u16;
    let mut not_checked_count = 0_u16;
    let mut blocked_count = 0_u16;
    for cell in &result.cells {
        validate_query_plan_cell(cell, true)?;
        if !check_ids.insert(cell.check_id) || !selected.contains(cell.provider_id.as_str()) {
            return Err(CoreError::InvalidQueryResponse);
        }
        match cell.state {
            CoreQueryCheckState::Planned => planned_count += 1,
            CoreQueryCheckState::ApprovalRequired => approval_required_count += 1,
            CoreQueryCheckState::NotChecked => not_checked_count += 1,
            CoreQueryCheckState::Blocked => blocked_count += 1,
            _ => return Err(CoreError::InvalidQueryResponse),
        }
    }
    if result.planned_count != planned_count
        || result.approval_required_count != approval_required_count
        || result.not_checked_count != not_checked_count
        || result.blocked_count != blocked_count
        || usize::from(planned_count + approval_required_count + not_checked_count + blocked_count)
            != result.cells.len()
    {
        return Err(CoreError::InvalidQueryResponse);
    }
    Ok(())
}

fn validate_query_plan_cell(cell: &CoreQueryPlanCell, initial: bool) -> Result<(), CoreError> {
    let valid_state_outcome = match cell.state {
        CoreQueryCheckState::Planned
        | CoreQueryCheckState::ApprovalRequired
        | CoreQueryCheckState::NotChecked => cell.outcome == CoreQueryCoverageOutcome::NotChecked,
        CoreQueryCheckState::Blocked => cell.outcome == CoreQueryCoverageOutcome::AccessBlocked,
        CoreQueryCheckState::Dispatched => cell.outcome == CoreQueryCoverageOutcome::Dispatched,
        CoreQueryCheckState::Succeeded => cell.outcome == CoreQueryCoverageOutcome::Succeeded,
        CoreQueryCheckState::CheckFailed => cell.outcome == CoreQueryCoverageOutcome::CheckFailed,
    };
    if !valid_state_outcome
        || (initial
            && matches!(
                cell.state,
                CoreQueryCheckState::Dispatched
                    | CoreQueryCheckState::Succeeded
                    | CoreQueryCheckState::CheckFailed
            ))
        || cell.requires_approval != (cell.state == CoreQueryCheckState::ApprovalRequired)
        || !is_query_provider_id(&cell.provider_id)
        || !is_safe_bounded_text(&cell.masked_value, 1, 512)
        || !is_safe_bounded_text(&cell.entity_type, 1, 32)
        || cell.query_class != "EXACT"
        || !is_bounded_event_label(&cell.reason_code, 96)
        || cell.revision == 0
        || cell.revision > MAX_SAFE_JAVASCRIPT_INTEGER
    {
        return Err(CoreError::InvalidQueryResponse);
    }
    Ok(())
}

fn is_query_provider_id(value: &str) -> bool {
    (3..=64).contains(&value.len())
        && value.as_bytes()[0].is_ascii_lowercase()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
        })
}

fn validate_phase5_finding_list_request(
    request: &CorePhase5FindingListRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || request.limit == 0
        || usize::from(request.limit) > MAX_PHASE5_FINDINGS
    {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn validate_phase5_finding_detail_request(
    request: &CorePhase5FindingDetailRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id) || !is_rfc4122_uuid(request.finding_id) {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn validate_phase5_manual_finding_request(
    request: &CorePhase5ManualFindingCreateRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_safe_bounded_text(&request.title, 1, 256)
        || !is_safe_bounded_text(&request.summary, 1, 2_048)
        || !is_phase5_opaque_id(&request.provider_id)
        || !is_safe_bounded_text(&request.provider_label, 1, 128)
    {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn validate_phase5_finding_list(
    result: &CorePhase5FindingListResult,
    profile_id: Uuid,
    requested_limit: usize,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.findings.len() > MAX_PHASE5_FINDINGS
        || result.findings.len() > requested_limit
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    let mut finding_ids = HashSet::with_capacity(result.findings.len());
    for finding in &result.findings {
        validate_phase5_finding_summary(finding)?;
        if !finding_ids.insert(finding.finding_id) {
            return Err(CoreError::InvalidPhase5Response);
        }
    }
    Ok(())
}

fn validate_phase5_finding_summary(finding: &CorePhase5FindingSummary) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(finding.finding_id)
        || !is_safe_bounded_text(&finding.title, 1, 256)
        || !is_safe_bounded_text(&finding.summary, 1, 2_048)
        || !(-1_000..=1_000).contains(&finding.score)
        || !finding.human_review_required
        || !is_safe_bounded_text(&finding.provider_label, 1, 128)
        || finding.artifact_count > MAX_PHASE5_ARTIFACT_COUNT
        || finding.updated_at_us == 0
        || finding.updated_at_us > MAX_SAFE_JAVASCRIPT_INTEGER
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_finding_detail(
    result: &CorePhase5FindingDetailResult,
    profile_id: Uuid,
    finding_id: Uuid,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || !is_rfc4122_uuid(result.finding.finding_id)
        || !is_rfc4122_uuid(result.assessment.assessment_id)
        || !is_rfc4122_uuid(result.assessment.case_id)
        || result.profile_id != profile_id
        || result.finding.finding_id != finding_id
        || result.assessment.case_id != finding_id
        || result.artifacts.len() > MAX_PHASE5_ARTIFACTS
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    validate_phase5_finding_summary(&result.finding)?;
    validate_phase5_assessment(&result.assessment)?;
    if result.finding.score != result.assessment.score
        || result.finding.confidence_band != result.assessment.confidence_band
        || usize::from(result.finding.artifact_count) != result.artifacts.len()
    {
        return Err(CoreError::InvalidPhase5Response);
    }

    let mut artifact_ids = HashSet::with_capacity(result.artifacts.len());
    for artifact in &result.artifacts {
        validate_phase5_artifact(artifact)?;
        if !artifact_ids.insert(artifact.artifact_id) {
            return Err(CoreError::InvalidPhase5Response);
        }
    }
    for artifact_id in result
        .assessment
        .contributing_signals
        .iter()
        .flat_map(|item| item.evidence_artifact_ids.iter())
        .chain(
            result
                .assessment
                .contradictions
                .iter()
                .flat_map(|item| item.evidence_artifact_ids.iter()),
        )
    {
        if !artifact_ids.contains(artifact_id) {
            return Err(CoreError::InvalidPhase5Response);
        }
    }

    match (result.finding.attribution_state, &result.human_decision) {
        (None, None) => {}
        (Some(state), Some(decision))
            if is_rfc4122_uuid(decision.decision_id)
                && is_rfc4122_uuid(decision.assessment_id)
                && decision.supersedes_decision_id.is_none_or(is_rfc4122_uuid)
                && decision.state == state
                && decision.assessment_id == result.assessment.assessment_id
                && decision.actor_label == "Local user"
                && decision.decided_at_us > 0
                && decision.decided_at_us <= MAX_SAFE_JAVASCRIPT_INTEGER
                && decision.weight_profile_version == result.assessment.weight_profile_version
                && decision.revision > 0
                && decision.revision <= 2_147_483_647
                && ((decision.revision == 1 && decision.supersedes_decision_id.is_none())
                    || (decision.revision > 1 && decision.supersedes_decision_id.is_some())) => {}
        _ => return Err(CoreError::InvalidPhase5Response),
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_phase5_manual_finding_result(
    result: &CorePhase5FindingDetailResult,
    profile_id: Uuid,
    title: &str,
    summary: &str,
    outcome: CorePhase5CheckOutcome,
    severity: CorePhase5Severity,
    visibility: CorePhase5Visibility,
    provider_label: &str,
) -> Result<(), CoreError> {
    validate_phase5_finding_detail(result, profile_id, result.finding.finding_id)?;
    let finding = &result.finding;
    let assessment = &result.assessment;
    if finding.title != title
        || finding.summary != summary
        || finding.outcome != outcome
        || finding.severity != severity
        || finding.visibility != visibility
        || finding.provider_label != provider_label
        || finding.attribution_state.is_some()
        || finding.confidence_band != CorePhase5ConfidenceBand::Low
        || finding.score != 0
        || finding.artifact_count != 0
        || !result.artifacts.is_empty()
        || result.human_decision.is_some()
        || assessment.case_id != finding.finding_id
        || assessment.confidence_band != CorePhase5ConfidenceBand::Low
        || assessment.score != 0
        || !assessment.contributing_signals.is_empty()
        || !assessment.contradictions.is_empty()
        || assessment.missing_evidence.len() != ALL_PHASE5_POSITIVE_SIGNALS.len()
    {
        return Err(CoreError::InvalidPhase5Response);
    }

    let missing_signals: HashSet<_> = assessment
        .missing_evidence
        .iter()
        .map(|item| item.signal)
        .collect();
    let expected_missing: HashSet<_> = ALL_PHASE5_POSITIVE_SIGNALS.into_iter().collect();
    if missing_signals != expected_missing
        || assessment
            .recommended_next_evidence
            .iter()
            .any(|signal| !missing_signals.contains(signal))
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_assessment(
    assessment: &CorePhase5AttributionAssessment,
) -> Result<(), CoreError> {
    if !is_phase5_weight_profile_version(&assessment.weight_profile_version)
        || !(-1_000..=1_000).contains(&assessment.score)
        || !assessment.human_review_required
        || assessment.contributing_signals.len() > MAX_PHASE5_POSITIVE_SIGNALS
        || assessment.contradictions.len() > MAX_PHASE5_NEGATIVE_SIGNALS
        || assessment.missing_evidence.len() > MAX_PHASE5_POSITIVE_SIGNALS
        || assessment.recommended_next_evidence.len() > MAX_PHASE5_RECOMMENDED_SIGNALS
    {
        return Err(CoreError::InvalidPhase5Response);
    }

    let mut positive_signals = HashSet::with_capacity(assessment.contributing_signals.len());
    let mut positive_score = 0_i32;
    for contribution in &assessment.contributing_signals {
        if contribution.weight > 1_000
            || !positive_signals.insert(contribution.signal)
            || !phase5_evidence_ids_are_valid(&contribution.evidence_artifact_ids)
        {
            return Err(CoreError::InvalidPhase5Response);
        }
        positive_score += i32::from(contribution.weight);
    }

    let mut negative_signals = HashSet::with_capacity(assessment.contradictions.len());
    let mut negative_score = 0_i32;
    for contradiction in &assessment.contradictions {
        if contradiction.penalty > 1_000
            || !negative_signals.insert(contradiction.signal)
            || !phase5_evidence_ids_are_valid(&contradiction.evidence_artifact_ids)
        {
            return Err(CoreError::InvalidPhase5Response);
        }
        negative_score += i32::from(contradiction.penalty);
    }

    let mut missing_signals = HashSet::with_capacity(assessment.missing_evidence.len());
    for missing in &assessment.missing_evidence {
        if missing.potential_weight > 1_000
            || positive_signals.contains(&missing.signal)
            || !missing_signals.insert(missing.signal)
        {
            return Err(CoreError::InvalidPhase5Response);
        }
    }

    let mut recommended = HashSet::with_capacity(assessment.recommended_next_evidence.len());
    if assessment
        .recommended_next_evidence
        .iter()
        .any(|signal| !missing_signals.contains(signal) || !recommended.insert(*signal))
        || assessment.score != (positive_score - negative_score).clamp(-1_000, 1_000)
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn phase5_evidence_ids_are_valid(ids: &[Uuid]) -> bool {
    if ids.is_empty() || ids.len() > MAX_PHASE5_SIGNAL_EVIDENCE {
        return false;
    }
    let mut unique = HashSet::with_capacity(ids.len());
    ids.iter().all(|artifact_id| unique.insert(*artifact_id))
}

fn validate_phase5_artifact(artifact: &CorePhase5EvidenceArtifact) -> Result<(), CoreError> {
    let source_url_is_valid = artifact
        .source_url
        .as_deref()
        .is_none_or(is_safe_phase5_source_url);
    let viewport_is_valid = artifact.viewport.as_ref().is_none_or(|viewport| {
        (1..=16_384).contains(&viewport.width)
            && (1..=16_384).contains(&viewport.height)
            && (100_000..=8_000_000).contains(&viewport.device_scale_micros)
    });
    if !is_rfc4122_uuid(artifact.artifact_id)
        || !is_rfc4122_uuid(artifact.run_id)
        || decode_lower_hex_digest(&artifact.content_sha256).is_none()
        || artifact.captured_at_us == 0
        || artifact.captured_at_us > MAX_SAFE_JAVASCRIPT_INTEGER
        || !source_url_is_valid
        || artifact
            .http_status
            .is_some_and(|status| !(100..=599).contains(&status))
        || artifact.http_status.is_some() && artifact.source_url.is_none()
        || artifact.redirect_count > 10
        || artifact.redirect_count > 0 && artifact.source_url.is_none()
        || !is_phase5_opaque_id(&artifact.provider_id)
        || !viewport_is_valid
        || artifact.kind == CorePhase5ArtifactKind::Screenshot && artifact.viewport.is_none()
        || artifact.kind == CorePhase5ArtifactKind::UrlReference
            && (artifact.source_url.is_none() || artifact.viewport.is_some())
        || artifact.capture_method == super::contract::CorePhase5CaptureMethod::ManualLocalImport
            && (artifact.source_url.is_some()
                || artifact.http_status.is_some()
                || artifact.redirect_count > 0)
        || !artifact.encrypted_at_rest
        || artifact.derivative_count > 2_000
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_manual_import_request(
    request: &CorePhase5ManualEvidenceImportRequest,
) -> Result<(), CoreError> {
    validate_phase5_content_base64(request.content_base64.as_str())?;
    let viewport_is_valid = request
        .viewport
        .as_ref()
        .is_none_or(is_valid_phase5_viewport);
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.finding_id)
        || !viewport_is_valid
        || (request.kind == CorePhase5ManualArtifactKind::Screenshot) != request.viewport.is_some()
        || request.metadata.len() > MAX_PHASE5_METADATA_ENTRIES
    {
        return Err(CoreError::InvalidPhase5Request);
    }
    let mut keys = HashSet::with_capacity(request.metadata.len());
    let mut total_characters = 0_usize;
    for item in &request.metadata {
        if !is_phase5_metadata_key(&item.key)
            || !is_safe_bounded_text(&item.value, 1, 256)
            || !keys.insert(item.key.as_str())
        {
            return Err(CoreError::InvalidPhase5Request);
        }
        total_characters = total_characters
            .saturating_add(item.key.chars().count())
            .saturating_add(item.value.chars().count());
    }
    if total_characters > MAX_PHASE5_METADATA_TOTAL_CHARS {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn validate_phase5_manual_import_result(
    result: &CorePhase5ManualEvidenceImportResult,
    profile_id: Uuid,
    finding_id: Uuid,
    kind: CorePhase5ManualArtifactKind,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || !is_rfc4122_uuid(result.finding_id)
        || !is_rfc4122_uuid(result.artifact_id)
        || result.profile_id != profile_id
        || result.finding_id != finding_id
        || result.kind != kind
        || decode_lower_hex_digest(&result.content_sha256).is_none()
        || !is_valid_timestamp_us(result.captured_at_us)
        || result.capture_method != CorePhase5CaptureMethod::ManualLocalImport
        || !result.encrypted_at_rest
        || !result.local_only
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_redacted_derivative_request(
    request: &CorePhase5RedactedDerivativeRequest,
) -> Result<(), CoreError> {
    validate_phase5_content_base64(request.redacted_content_base64.as_str())?;
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.original_artifact_id)
        || !request.already_redacted
        || !is_phase5_weight_profile_version(&request.redaction_policy_version)
        || !is_bounded_event_label(&request.redaction_summary_code, 64)
    {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn validate_phase5_redacted_derivative_result(
    result: &CorePhase5RedactedDerivativeResult,
    profile_id: Uuid,
    original_artifact_id: Uuid,
    policy_version: &str,
    summary_code: &str,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || !is_rfc4122_uuid(result.original_artifact_id)
        || !is_rfc4122_uuid(result.derivative_id)
        || result.profile_id != profile_id
        || result.original_artifact_id != original_artifact_id
        || result.derivative_id == original_artifact_id
        || decode_lower_hex_digest(&result.content_sha256).is_none()
        || !is_valid_timestamp_us(result.created_at_us)
        || result.redaction_policy_version != policy_version
        || result.redaction_summary_code != summary_code
        || !result.encrypted_at_rest
        || !result.local_only
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_attribution_decision_request(
    request: &CorePhase5AttributionDecisionRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.finding_id)
        || !is_rfc4122_uuid(request.assessment_id)
        || request
            .expected_previous_decision_id
            .is_some_and(|value| !is_rfc4122_uuid(value))
        || request.expected_previous_revision > 2_147_483_647
        || (request.expected_previous_decision_id.is_none())
            != (request.expected_previous_revision == 0)
    {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_phase5_attribution_decision_result(
    result: &CorePhase5AttributionDecisionResult,
    profile_id: Uuid,
    finding_id: Uuid,
    assessment_id: Uuid,
    state: super::contract::CorePhase5AttributionState,
    expected_previous_decision_id: Option<Uuid>,
    expected_previous_revision: u32,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || !is_rfc4122_uuid(result.finding_id)
        || !is_rfc4122_uuid(result.assessment_id)
        || !is_rfc4122_uuid(result.decision_id)
        || result
            .supersedes_decision_id
            .is_some_and(|value| !is_rfc4122_uuid(value))
        || result.profile_id != profile_id
        || result.finding_id != finding_id
        || result.assessment_id != assessment_id
        || result.state != state
        || result.actor_label != "Local user"
        || !is_valid_timestamp_us(result.decided_at_us)
        || !is_phase5_weight_profile_version(&result.weight_profile_version)
        || result.supersedes_decision_id != expected_previous_decision_id
        || result.revision != expected_previous_revision.saturating_add(1)
        || result.revision > 2_147_483_647
        || result.decision_id == result.supersedes_decision_id.unwrap_or(Uuid::nil())
    {
        return Err(CoreError::InvalidPhase5Response);
    }
    Ok(())
}

fn validate_phase5_content_base64(value: &str) -> Result<(), CoreError> {
    let maximum_encoded = MAX_PHASE5_ARTIFACT_BYTES.div_ceil(3) * 4;
    if value.len() < 4 || value.len() > maximum_encoded {
        return Err(CoreError::InvalidPhase5Request);
    }
    let decoded = Zeroizing::new(
        STANDARD
            .decode(value.as_bytes())
            .map_err(|_| CoreError::InvalidPhase5Request)?,
    );
    if decoded.is_empty() || decoded.len() > MAX_PHASE5_ARTIFACT_BYTES {
        return Err(CoreError::InvalidPhase5Request);
    }
    let canonical = Zeroizing::new(STANDARD.encode(decoded.as_slice()));
    if canonical.as_str() != value {
        return Err(CoreError::InvalidPhase5Request);
    }
    Ok(())
}

fn is_valid_phase5_viewport(viewport: &CorePhase5EvidenceViewport) -> bool {
    (1..=16_384).contains(&viewport.width)
        && (1..=16_384).contains(&viewport.height)
        && (100_000..=8_000_000).contains(&viewport.device_scale_micros)
}

fn is_phase5_metadata_key(value: &str) -> bool {
    (1..=48).contains(&value.len())
        && value.as_bytes()[0].is_ascii_lowercase()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'.' | b'-')
        })
}

fn is_phase5_weight_profile_version(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value.as_bytes()[0].is_ascii_lowercase()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'.' | b'_' | b'-')
        })
}

fn is_phase5_opaque_id(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn is_safe_phase5_source_url(value: &str) -> bool {
    if !is_safe_bounded_text(value, 8, 2_048) {
        return false;
    }
    let Ok(parsed) = reqwest::Url::parse(value) else {
        return false;
    };
    if !matches!(parsed.scheme(), "http" | "https")
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some_and(|query| !query.is_empty())
        || parsed
            .fragment()
            .is_some_and(|fragment| !fragment.is_empty())
    {
        return false;
    }
    let Some(host) = parsed.host_str() else {
        return false;
    };
    let hostname = host
        .trim_matches(['[', ']'])
        .trim_end_matches('.')
        .to_ascii_lowercase();
    if matches!(hostname.as_str(), "localhost" | "localhost.localdomain")
        || hostname.ends_with(".localhost")
        || hostname.ends_with(".local")
        || hostname.ends_with(".internal")
        || hostname.ends_with(".lan")
        || hostname
            .replace('.', "")
            .bytes()
            .all(|byte| byte.is_ascii_digit())
        || hostname
            .split('.')
            .any(|label| label.starts_with("0x") || label.is_empty())
    {
        return false;
    }
    hostname.parse::<IpAddr>().map_or(true, is_public_phase5_ip)
}

fn is_public_phase5_ip(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => {
            let octets = address.octets();
            !address.is_private()
                && !address.is_loopback()
                && !address.is_link_local()
                && !address.is_broadcast()
                && !address.is_documentation()
                && !address.is_multicast()
                && !address.is_unspecified()
                && octets[0] != 0
                && !(octets[0] == 100 && (64..=127).contains(&octets[1]))
                && !(octets[0] == 192 && octets[1] == 0 && octets[2] == 0)
                && !(octets[0] == 198 && (18..=19).contains(&octets[1]))
                && octets[0] < 240
        }
        IpAddr::V6(address) => {
            let segments = address.segments();
            !address.is_loopback()
                && !address.is_unspecified()
                && !address.is_multicast()
                && segments[0] & 0xfe00 != 0xfc00
                && segments[0] & 0xffc0 != 0xfe80
                && !(segments[0] == 0x2001 && segments[1] == 0x0db8)
                && !(segments[..4] == [0x0064, 0, 0, 0])
                && !(segments[..6] == [0, 0, 0, 0, 0, 0xffff])
        }
    }
}

fn validate_phase6_audit_run_list_request(
    request: &CorePhase6AuditRunListRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !(2..=MAX_PHASE6_RUNS).contains(&usize::from(request.limit))
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_audit_run_list(
    result: &CorePhase6AuditRunListResult,
    profile_id: Uuid,
    requested_limit: usize,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.runs.len() > MAX_PHASE6_RUNS
        || result.runs.len() > requested_limit
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    let mut run_ids = HashSet::with_capacity(result.runs.len());
    for run in &result.runs {
        validate_phase6_audit_run_summary(run)?;
        if !run_ids.insert(run.run_id) {
            return Err(CoreError::InvalidPhase6Response);
        }
    }
    if result
        .runs
        .windows(2)
        .any(|pair| pair[1].sequence >= pair[0].sequence)
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_audit_run_summary(run: &CorePhase6AuditRunSummary) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(run.run_id)
        || run.sequence == 0
        || run.sequence > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_valid_timestamp_us(run.captured_at_us)
        || run.finding_count > 2_000
        || !(1..=256).contains(&run.provider_count)
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_local_checkpoint_request(
    request: &CorePhase6LocalCheckpointRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || request.provider_coverage.is_empty()
        || request.provider_coverage.len() > MAX_PHASE6_COVERAGE
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    let mut provider_ids = HashSet::with_capacity(request.provider_coverage.len());
    if request.provider_coverage.iter().any(|coverage| {
        !is_phase5_opaque_id(&coverage.provider_id)
            || !provider_ids.insert(coverage.provider_id.as_str())
    }) {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_local_checkpoint_result(
    result: &CorePhase6LocalCheckpointResult,
    profile_id: Uuid,
    run_state: CorePhase6SnapshotRunState,
    requested_provider_count: usize,
) -> Result<(), CoreError> {
    let summary = CorePhase6AuditRunSummary {
        run_id: result.run_id,
        sequence: result.sequence,
        captured_at_us: result.captured_at_us,
        run_state: result.run_state,
        finding_count: result.finding_count,
        provider_count: result.provider_count,
    };
    validate_phase6_audit_run_summary(&summary)?;
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.run_state != run_state
        || usize::from(result.provider_count) != requested_provider_count
        || !result.local_only
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_compare_runs_request(
    request: &CorePhase6CompareRunsRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.baseline_run_id)
        || !is_rfc4122_uuid(request.current_run_id)
        || request.baseline_run_id == request.current_run_id
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_comparison(
    result: &CorePhase6ComparisonResult,
    profile_id: Uuid,
    baseline_run_id: Uuid,
    current_run_id: Uuid,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.baseline_run_id != baseline_run_id
        || result.current_run_id != current_run_id
        || result.baseline_run_id == result.current_run_id
        || result.diffs.len() > MAX_PHASE6_DIFFS
        || result.unresolved_absences.len() > MAX_PHASE6_DIFFS
        || result.coverage.len() > MAX_PHASE6_COVERAGE
        || result.lifecycles.len() > MAX_PHASE6_LIFECYCLES
        || result.incomplete_reasons.len() > 6
        || result.incomplete_comparison != !result.incomplete_reasons.is_empty()
    {
        return Err(CoreError::InvalidPhase6Response);
    }

    let mut finding_providers = HashMap::with_capacity(
        result
            .diffs
            .len()
            .saturating_add(result.unresolved_absences.len()),
    );
    for diff in &result.diffs {
        validate_phase6_finding_diff(diff)?;
        if finding_providers
            .insert(diff.stable_id, diff.provider_id.as_str())
            .is_some()
        {
            return Err(CoreError::InvalidPhase6Response);
        }
    }
    for absence in &result.unresolved_absences {
        validate_phase6_unresolved_absence(absence)?;
        if finding_providers
            .insert(absence.stable_id, absence.provider_id.as_str())
            .is_some()
        {
            return Err(CoreError::InvalidPhase6Response);
        }
    }

    let mut coverage_providers = HashSet::with_capacity(result.coverage.len());
    for coverage in &result.coverage {
        validate_phase6_provider_coverage(coverage)?;
        if !coverage_providers.insert(coverage.provider_id.as_str()) {
            return Err(CoreError::InvalidPhase6Response);
        }
    }

    let mut lifecycle_ids = HashSet::with_capacity(result.lifecycles.len());
    for lifecycle in &result.lifecycles {
        validate_phase6_lifecycle(lifecycle)?;
        if !lifecycle_ids.insert(lifecycle.stable_id)
            || finding_providers.get(&lifecycle.stable_id).copied()
                != Some(lifecycle.provider_id.as_str())
            || lifecycle.events.last().map(|event| event.run_id) != Some(current_run_id)
        {
            return Err(CoreError::InvalidPhase6Response);
        }
    }
    if lifecycle_ids.len() != finding_providers.len()
        || finding_providers
            .keys()
            .any(|stable_id| !lifecycle_ids.contains(stable_id))
    {
        return Err(CoreError::InvalidPhase6Response);
    }

    let mut reasons = HashSet::with_capacity(result.incomplete_reasons.len());
    if result
        .incomplete_reasons
        .iter()
        .any(|reason| !reasons.insert(*reason))
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_finding_diff(diff: &CorePhase6FindingDiff) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(diff.stable_id) || !is_phase5_opaque_id(&diff.provider_id) {
        return Err(CoreError::InvalidPhase6Response);
    }
    let previous_is_valid = diff
        .previous_fingerprint
        .as_deref()
        .is_none_or(|value| decode_lower_hex_digest(value).is_some());
    let current_is_valid = diff
        .current_fingerprint
        .as_deref()
        .is_none_or(|value| decode_lower_hex_digest(value).is_some());
    let state_is_consistent = match diff.state {
        CorePhase6FindingDiffState::New => {
            diff.previous_fingerprint.is_none() && diff.current_fingerprint.is_some()
        }
        CorePhase6FindingDiffState::Removed => {
            diff.previous_fingerprint.is_some() && diff.current_fingerprint.is_none()
        }
        CorePhase6FindingDiffState::Changed => {
            diff.previous_fingerprint.is_some()
                && diff.current_fingerprint.is_some()
                && diff.previous_fingerprint != diff.current_fingerprint
        }
        CorePhase6FindingDiffState::Unchanged => {
            diff.previous_fingerprint.is_some()
                && diff.previous_fingerprint == diff.current_fingerprint
        }
        CorePhase6FindingDiffState::Reappeared => {
            diff.previous_fingerprint.is_some() && diff.current_fingerprint.is_some()
        }
    };
    if !previous_is_valid || !current_is_valid || !state_is_consistent {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_unresolved_absence(
    absence: &CorePhase6UnresolvedAbsence,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(absence.stable_id)
        || !is_phase5_opaque_id(&absence.provider_id)
        || decode_lower_hex_digest(&absence.previous_fingerprint).is_none()
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_provider_coverage(
    coverage: &CorePhase6ProviderCoverageComparison,
) -> Result<(), CoreError> {
    if !is_phase5_opaque_id(&coverage.provider_id) {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_lifecycle(lifecycle: &CorePhase6FindingLifecycle) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(lifecycle.stable_id)
        || !is_phase5_opaque_id(&lifecycle.provider_id)
        || lifecycle.events.is_empty()
        || lifecycle.events.len() > MAX_PHASE6_LIFECYCLE_EVENTS
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    let mut run_ids = HashSet::with_capacity(lifecycle.events.len());
    let mut previous_sequence = None;
    for event in &lifecycle.events {
        validate_phase6_lifecycle_event(event)?;
        if !run_ids.insert(event.run_id)
            || previous_sequence.is_some_and(|sequence| event.sequence <= sequence)
        {
            return Err(CoreError::InvalidPhase6Response);
        }
        previous_sequence = Some(event.sequence);
    }
    Ok(())
}

fn validate_phase6_lifecycle_event(event: &CorePhase6LifecycleEvent) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(event.run_id)
        || event.sequence == 0
        || event.sequence > MAX_SAFE_JAVASCRIPT_INTEGER
        || event.observed != event.content_fingerprint.is_some()
        || event
            .content_fingerprint
            .as_deref()
            .is_some_and(|value| decode_lower_hex_digest(value).is_none())
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_remediation_list_request(
    request: &CorePhase6RemediationListRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || request.limit == 0
        || usize::from(request.limit) > MAX_PHASE6_CASES
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_detail_request(
    request: &CorePhase6RemediationDetailRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id) || !is_rfc4122_uuid(request.case_id) {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_create_request(
    request: &CorePhase6RemediationCreateRequest,
) -> Result<(), CoreError> {
    let local_action = matches!(
        request.action,
        CorePhase6RemediationAction::Monitor | CorePhase6RemediationAction::PreserveEvidence
    );
    if !is_rfc4122_uuid(request.profile_id)
        || !phase6_unique_uuid_references(&request.finding_ids, 1, MAX_PHASE6_FINDING_LINKS)
        || request
            .deadline_at_us
            .is_some_and(|value| !is_valid_timestamp_us(value))
        || !phase6_unique_uuid_references(
            &request.evidence_references,
            0,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
        || request
            .draft_text
            .as_deref()
            .is_some_and(|value| !is_safe_multiline_text(value, 1, 10_000))
        || (local_action && request.draft_text.is_some())
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_mutation_request(
    profile_id: Uuid,
    case_id: Uuid,
    expected_revision: u16,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(profile_id)
        || !is_rfc4122_uuid(case_id)
        || expected_revision == 0
        || usize::from(expected_revision) >= MAX_PHASE6_HISTORY_ENTRIES
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_draft_request(
    request: &CorePhase6RemediationDraftUpdateRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if !is_safe_multiline_text(&request.draft_text, 1, 10_000) {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_status_request(
    request: &CorePhase6RemediationStatusTransitionRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if request
        .note
        .as_deref()
        .is_some_and(|value| !is_safe_multiline_text(value, 1, 1_000))
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_deadline_request(
    request: &CorePhase6RemediationDeadlineUpdateRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if request
        .deadline_at_us
        .is_some_and(|value| !is_valid_timestamp_us(value))
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_evidence_request(
    request: &CorePhase6RemediationEvidenceLinkRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if !phase6_unique_uuid_references(
        &request.evidence_references,
        1,
        MAX_PHASE6_EVIDENCE_REFERENCES,
    ) {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_provider_response_request(
    request: &CorePhase6RemediationProviderResponseRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if !is_phase5_opaque_id(&request.provider_id)
        || !is_phase6_code(&request.response_code)
        || !is_safe_bounded_text(&request.summary, 1, 2_048)
        || !phase6_unique_uuid_references(
            &request.evidence_references,
            0,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_reappearance_request(
    request: &CorePhase6RemediationReappearanceRequest,
) -> Result<(), CoreError> {
    validate_phase6_remediation_mutation_request(
        request.profile_id,
        request.case_id,
        request.expected_revision,
    )?;
    if !is_rfc4122_uuid(request.finding_id)
        || !phase6_unique_uuid_references(
            &request.evidence_references,
            1,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
    {
        return Err(CoreError::InvalidPhase6Request);
    }
    Ok(())
}

fn validate_phase6_remediation_list(
    result: &CorePhase6RemediationListResult,
    profile_id: Uuid,
    requested_limit: usize,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.cases.len() > MAX_PHASE6_CASES
        || result.cases.len() > requested_limit
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    let mut case_ids = HashSet::with_capacity(result.cases.len());
    for case in &result.cases {
        validate_phase6_remediation_summary(case)?;
        if !case_ids.insert(case.case_id) {
            return Err(CoreError::InvalidPhase6Response);
        }
    }
    if result
        .cases
        .windows(2)
        .any(|pair| pair[1].updated_at_us > pair[0].updated_at_us)
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_remediation_summary(
    case: &CorePhase6RemediationCaseSummary,
) -> Result<(), CoreError> {
    validate_phase6_remediation_summary_fields(
        case.case_id,
        &case.finding_ids,
        case.action,
        case.action_disposition,
        case.status,
        case.deadline_at_us,
        case.reappearance_count,
        case.revision,
        case.updated_at_us,
    )
}

#[allow(clippy::too_many_arguments)]
fn validate_phase6_remediation_summary_fields(
    case_id: Uuid,
    finding_ids: &[Uuid],
    action: CorePhase6RemediationAction,
    disposition: CorePhase6ActionDisposition,
    status: CorePhase6RemediationStatus,
    deadline_at_us: Option<u64>,
    _reappearance_count: u32,
    revision: u16,
    updated_at_us: u64,
) -> Result<(), CoreError> {
    let local_action = matches!(
        action,
        CorePhase6RemediationAction::Monitor | CorePhase6RemediationAction::PreserveEvidence
    );
    if !is_rfc4122_uuid(case_id)
        || !phase6_unique_uuid_references(finding_ids, 1, MAX_PHASE6_FINDING_LINKS)
        || local_action != (disposition == CorePhase6ActionDisposition::LocalOnly)
        || (status == CorePhase6RemediationStatus::AwaitingExplicitApproval
            && disposition != CorePhase6ActionDisposition::RequireExplicitApproval)
        || deadline_at_us.is_some_and(|value| !is_valid_timestamp_us(value))
        || revision == 0
        || usize::from(revision) > MAX_PHASE6_HISTORY_ENTRIES
        || !is_valid_timestamp_us(updated_at_us)
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_remediation_detail(
    result: &CorePhase6RemediationDetailResult,
    profile_id: Uuid,
    case_id: Uuid,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.case.case_id != case_id
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    validate_phase6_remediation_case(&result.case)
}

#[allow(clippy::too_many_arguments)]
fn validate_phase6_remediation_create_result(
    result: &CorePhase6RemediationDetailResult,
    profile_id: Uuid,
    finding_ids: &[Uuid],
    action: CorePhase6RemediationAction,
    deadline_at_us: Option<u64>,
    evidence_references: &[Uuid],
    draft_text: Option<&str>,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.case.revision != 1
        || result.case.action != action
        || result.case.deadline_at_us != deadline_at_us
        || result.case.draft_text.as_deref() != draft_text
        || !phase6_uuid_sets_equal(&result.case.finding_ids, finding_ids)
        || !phase6_uuid_sets_equal(&result.case.evidence_references, evidence_references)
        || result.case.history.first().map(|entry| entry.event_type)
            != Some(CorePhase6RemediationEventType::CaseCreated)
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    validate_phase6_remediation_case(&result.case)
}

fn validate_phase6_mutation_result(
    result: &CorePhase6RemediationDetailResult,
    profile_id: Uuid,
    case_id: Uuid,
    expected_revision: u16,
    expected_event_type: CorePhase6RemediationEventType,
) -> Result<(), CoreError> {
    validate_phase6_remediation_detail(result, profile_id, case_id)?;
    let expected_result_revision = expected_revision
        .checked_add(1)
        .ok_or(CoreError::InvalidPhase6Response)?;
    let Some(last_event) = result.case.history.last() else {
        return Err(CoreError::InvalidPhase6Response);
    };
    if result.case.revision != expected_result_revision
        || last_event.revision != result.case.revision
        || last_event.event_type != expected_event_type
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_remediation_case(case: &CorePhase6RemediationCase) -> Result<(), CoreError> {
    validate_phase6_remediation_summary_fields(
        case.case_id,
        &case.finding_ids,
        case.action,
        case.action_disposition,
        case.status,
        case.deadline_at_us,
        case.reappearance_count,
        case.revision,
        case.updated_at_us,
    )?;
    if !is_valid_timestamp_us(case.created_at_us)
        || case.created_at_us > case.updated_at_us
        || case
            .deadline_at_us
            .is_some_and(|deadline| deadline <= case.created_at_us)
        || (case.reappearance_count == 0) != case.last_reappearance_at_us.is_none()
        || case.last_reappearance_at_us.is_some_and(|timestamp| {
            !is_valid_timestamp_us(timestamp)
                || timestamp < case.created_at_us
                || timestamp > case.updated_at_us
        })
        || case
            .draft_text
            .as_deref()
            .is_some_and(|value| !is_safe_multiline_text(value, 1, 10_000))
        || !phase6_unique_uuid_references(
            &case.evidence_references,
            0,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
        || case.provider_responses.len() > MAX_PHASE6_PROVIDER_RESPONSES
        || case.history.is_empty()
        || case.history.len() > MAX_PHASE6_HISTORY_ENTRIES
        || case.history.len() != usize::from(case.revision)
    {
        return Err(CoreError::InvalidPhase6Response);
    }

    let linked_evidence: HashSet<Uuid> = case.evidence_references.iter().copied().collect();
    for response in &case.provider_responses {
        validate_phase6_provider_response(response, case.created_at_us, case.updated_at_us)?;
        if response
            .evidence_references
            .iter()
            .any(|reference| !linked_evidence.contains(reference))
        {
            return Err(CoreError::InvalidPhase6Response);
        }
    }

    let mut previous: Option<&CorePhase6RemediationHistoryEntry> = None;
    for (index, entry) in case.history.iter().enumerate() {
        validate_phase6_history_entry(entry)?;
        let expected_revision =
            u16::try_from(index + 1).map_err(|_| CoreError::InvalidPhase6Response)?;
        if entry.revision != expected_revision
            || entry
                .evidence_references
                .iter()
                .any(|reference| !linked_evidence.contains(reference))
            || previous.is_none()
                && (entry.previous_status.is_some()
                    || entry.event_type != CorePhase6RemediationEventType::CaseCreated)
            || previous.is_some_and(|prior| {
                entry.previous_status != Some(prior.current_status)
                    || entry.occurred_at_us <= prior.occurred_at_us
            })
        {
            return Err(CoreError::InvalidPhase6Response);
        }
        previous = Some(entry);
    }
    if previous.is_none_or(|entry| {
        entry.current_status != case.status || entry.occurred_at_us != case.updated_at_us
    }) {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_provider_response(
    response: &CorePhase6ProviderResponse,
    created_at_us: u64,
    updated_at_us: u64,
) -> Result<(), CoreError> {
    if !is_phase5_opaque_id(&response.provider_id)
        || !is_phase6_code(&response.response_code)
        || !is_safe_bounded_text(&response.summary, 1, 2_048)
        || !is_valid_timestamp_us(response.received_at_us)
        || response.received_at_us < created_at_us
        || response.received_at_us > updated_at_us
        || !phase6_unique_uuid_references(
            &response.evidence_references,
            0,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn validate_phase6_history_entry(
    entry: &CorePhase6RemediationHistoryEntry,
) -> Result<(), CoreError> {
    if entry.revision == 0
        || usize::from(entry.revision) > MAX_PHASE6_HISTORY_ENTRIES
        || entry.actor_label != "Local user"
        || !is_valid_timestamp_us(entry.occurred_at_us)
        || !is_phase6_code(&entry.detail_code)
        || entry
            .subject_id
            .as_deref()
            .is_some_and(|value| !is_phase5_opaque_id(value))
        || !phase6_unique_uuid_references(
            &entry.evidence_references,
            0,
            MAX_PHASE6_EVIDENCE_REFERENCES,
        )
        || entry
            .note
            .as_deref()
            .is_some_and(|value| !is_safe_multiline_text(value, 1, 1_000))
    {
        return Err(CoreError::InvalidPhase6Response);
    }
    Ok(())
}

fn phase6_unique_uuid_references(values: &[Uuid], minimum: usize, maximum: usize) -> bool {
    if values.len() < minimum || values.len() > maximum {
        return false;
    }
    let mut unique = HashSet::with_capacity(values.len());
    values
        .iter()
        .all(|value| is_rfc4122_uuid(*value) && unique.insert(*value))
}

fn phase6_uuid_subset(subset: &[Uuid], superset: &[Uuid]) -> bool {
    subset.iter().all(|value| superset.contains(value))
}

fn phase6_uuid_sets_equal(left: &[Uuid], right: &[Uuid]) -> bool {
    left.len() == right.len() && phase6_uuid_subset(left, right)
}

fn is_phase6_code(value: &str) -> bool {
    value.len() >= 2 && is_bounded_event_label(value, 64)
}

fn validate_local_report_request(
    request: &CoreLocalReportGenerateRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.baseline_run_id)
        || !is_rfc4122_uuid(request.current_run_id)
        || request.baseline_run_id == request.current_run_id
        || request
            .full_export_approval_id
            .is_some_and(|approval_id| !is_rfc4122_uuid(approval_id))
        || match request.mode {
            CoreReportExportMode::Redacted => request.full_export_approval_id.is_some(),
            CoreReportExportMode::FullExplicit => request.full_export_approval_id.is_none(),
        }
    {
        return Err(CoreError::InvalidLocalReportRequest);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_local_report_result(
    result: &CoreLocalReportGenerateResult,
    profile_id: Uuid,
    baseline_run_id: Uuid,
    current_run_id: Uuid,
    artifact_format: CoreReportArtifactFormat,
    mode: CoreReportExportMode,
    full_export_approval_id: Option<Uuid>,
) -> Result<(), CoreError> {
    if result.profile_id != profile_id
        || result.baseline_run_id != baseline_run_id
        || result.current_run_id != current_run_id
        || result.baseline_run_id == result.current_run_id
        || !result.local_only
        || result.artifact.schema != CoreLocalReportSchema::AriadneLocalReport
        || result.artifact.version != 1
        || result.artifact.mode != mode
        || result.manifest.schema != CoreLocalReportSchema::AriadneLocalReport
        || result.manifest.version != 1
        || result.manifest.mode != mode
        || result.manifest.full_export_approval_id != full_export_approval_id
        || !is_valid_timestamp_us(result.manifest.generated_at_us)
    {
        return Err(CoreError::InvalidLocalReportResponse);
    }

    let (expected_filename, expected_media_type) = report_artifact_identity(artifact_format);
    if result.artifact.filename != expected_filename
        || result.artifact.media_type != expected_media_type
    {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    validate_local_report_artifact(&result.artifact)?;

    if result.manifest.artifacts.len() != 2 {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    let mut filenames = HashSet::with_capacity(2);
    let mut selected_descriptor = None;
    for descriptor in &result.manifest.artifacts {
        validate_local_report_descriptor(descriptor)?;
        if !filenames.insert(descriptor.filename.as_str()) {
            return Err(CoreError::InvalidLocalReportResponse);
        }
        if descriptor.filename == expected_filename {
            selected_descriptor = Some(descriptor);
        }
    }
    if filenames != HashSet::from(["report.json", "report.md"]) {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    let Some(descriptor) = selected_descriptor else {
        return Err(CoreError::InvalidLocalReportResponse);
    };
    if descriptor.media_type != result.artifact.media_type
        || descriptor.byte_count != result.artifact.byte_count
        || descriptor.sha256 != result.artifact.sha256
    {
        return Err(CoreError::InvalidLocalReportResponse);
    }

    let response_bytes = serde_json::to_vec(result)
        .map_err(|_| CoreError::InvalidLocalReportResponse)?
        .len();
    if response_bytes > MAX_LOCAL_REPORT_RESPONSE_BYTES {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    Ok(())
}

fn validate_local_report_artifact(artifact: &CoreLocalReportArtifact) -> Result<(), CoreError> {
    let content = artifact.content.as_str().as_bytes();
    if content.is_empty()
        || content.len() > MAX_LOCAL_REPORT_RESPONSE_BYTES
        || artifact.byte_count != content.len()
        || artifact.byte_count > MAX_LOCAL_REPORT_ARTIFACT_BYTES
        || !report_filename_media_type_is_valid(&artifact.filename, &artifact.media_type)
    {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    let Some(expected_digest) = decode_lower_hex_digest(&artifact.sha256) else {
        return Err(CoreError::InvalidLocalReportResponse);
    };
    if Sha256::digest(content).as_slice() != expected_digest {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    Ok(())
}

fn validate_local_report_descriptor(
    descriptor: &CoreLocalReportArtifactDescriptor,
) -> Result<(), CoreError> {
    if !report_filename_media_type_is_valid(&descriptor.filename, &descriptor.media_type)
        || descriptor.byte_count == 0
        || descriptor.byte_count > MAX_LOCAL_REPORT_ARTIFACT_BYTES
        || decode_lower_hex_digest(&descriptor.sha256).is_none()
    {
        return Err(CoreError::InvalidLocalReportResponse);
    }
    Ok(())
}

const fn report_artifact_identity(
    format: CoreReportArtifactFormat,
) -> (&'static str, &'static str) {
    match format {
        CoreReportArtifactFormat::Json => ("report.json", "application/json"),
        CoreReportArtifactFormat::Markdown => ("report.md", "text/markdown; charset=utf-8"),
    }
}

fn report_filename_media_type_is_valid(filename: &str, media_type: &str) -> bool {
    matches!(
        (filename, media_type),
        ("report.json", "application/json") | ("report.md", "text/markdown; charset=utf-8")
    )
}

fn is_safe_multiline_text(value: &str, minimum: usize, maximum: usize) -> bool {
    let count = value.chars().count();
    count >= minimum
        && count <= maximum
        && value.trim() == value
        && !value
            .chars()
            .any(|character| character.is_control() && !matches!(character, '\n' | '\t'))
}

fn is_valid_timestamp_us(value: u64) -> bool {
    value > 0 && value <= MAX_SAFE_JAVASCRIPT_INTEGER
}

fn is_rfc4122_uuid(value: Uuid) -> bool {
    value.get_variant() == uuid::Variant::RFC4122
}

fn validate_local_ai_endpoint_request(
    request: &CoreLocalAiEndpointRequest,
) -> Result<(), CoreError> {
    if !is_local_ai_runtime_provider(request.provider)
        || !is_loopback_http_endpoint(&request.endpoint)
        || request
            .selected_model
            .as_deref()
            .is_some_and(|model| !is_local_model_id(model))
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    Ok(())
}

fn validate_local_ai_settings_update(
    request: &CoreLocalAiSettingsUpdateRequest,
) -> Result<(), CoreError> {
    if request.expected_revision == 0
        || request.expected_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_local_ai_runtime_provider(request.provider)
        || !is_loopback_http_endpoint(&request.endpoint)
        || request
            .selected_model
            .as_deref()
            .is_some_and(|model| !is_local_model_id(model))
        || (request.enabled && request.selected_model.is_none())
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    Ok(())
}

fn validate_local_ai_settings(settings: &CoreLocalAiSettings) -> Result<(), CoreError> {
    if settings.revision == 0
        || settings.revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_local_ai_runtime_provider(settings.provider)
        || !is_loopback_http_endpoint(&settings.endpoint)
        || settings
            .selected_model
            .as_deref()
            .is_some_and(|model| !is_local_model_id(model))
        || (settings.enabled && settings.selected_model.is_none())
    {
        return Err(CoreError::InvalidLocalAiResponse);
    }
    Ok(())
}

const fn is_local_ai_runtime_provider(provider: CoreLocalAiProvider) -> bool {
    matches!(
        provider,
        CoreLocalAiProvider::Ollama | CoreLocalAiProvider::OpenaiCompatible
    )
}

fn validate_local_ai_models(
    result: &CoreLocalAiModelDiscoveryResult,
    provider: CoreLocalAiProvider,
) -> Result<(), CoreError> {
    if result.models.len() > 512 {
        return Err(CoreError::InvalidLocalAiResponse);
    }
    let mut identifiers = HashSet::with_capacity(result.models.len());
    for model in &result.models {
        if model.provider != provider
            || !is_local_model_id(&model.model_id)
            || !identifiers.insert(model.model_id.as_str())
        {
            return Err(CoreError::InvalidLocalAiResponse);
        }
    }
    Ok(())
}

fn validate_local_ai_connection(
    result: &CoreLocalAiConnectionResult,
    selected_model: Option<&str>,
) -> Result<(), CoreError> {
    let valid = match result.status {
        CoreLocalAiConnectionStatus::Available => {
            result.reachable && result.selected_model_available != Some(false)
        }
        CoreLocalAiConnectionStatus::ModelUnavailable => {
            result.reachable && result.selected_model_available == Some(false)
        }
        CoreLocalAiConnectionStatus::Timeout
        | CoreLocalAiConnectionStatus::Unavailable
        | CoreLocalAiConnectionStatus::InvalidResponse => {
            !result.reachable
                && result.model_count == 0
                && result.selected_model_available.is_none()
        }
    };
    let selection_shape = if selected_model.is_some() && result.reachable {
        result.selected_model_available.is_some()
    } else if selected_model.is_none() {
        result.selected_model_available.is_none()
    } else {
        true
    };
    if result.model_count > 512 || !valid || !selection_shape {
        return Err(CoreError::InvalidLocalAiResponse);
    }
    Ok(())
}

fn validate_local_ai_workspace_request(
    request: &CoreLocalAiWorkspaceRequest,
) -> Result<(), CoreError> {
    let unique_scopes: HashSet<_> = request.scopes.iter().copied().collect();
    let question_valid = match request.task {
        CoreLocalAiWorkspaceTask::Question => request
            .question
            .as_deref()
            .is_some_and(|value| is_safe_workspace_text(value, 1, 2_000)),
        _ => request.question.is_none(),
    };
    let model_valid = match request.execution {
        CoreLocalAiWorkspaceExecution::LocalModel => {
            request.model_id.as_deref().is_some_and(is_local_model_id)
                && request.openai_api_key.is_none()
        }
        CoreLocalAiWorkspaceExecution::Deterministic => {
            request.model_id.is_none() && request.openai_api_key.is_none()
        }
        CoreLocalAiWorkspaceExecution::OpenaiResponses => {
            request.model_id.as_deref().is_some_and(is_local_model_id)
                && request
                    .openai_api_key
                    .as_deref()
                    .is_some_and(|value| is_openai_api_key(value.as_str()))
        }
    };
    let document_selected = unique_scopes.contains(&CoreLocalAiWorkspaceScope::Document);
    if !is_rfc4122_uuid(request.profile_id)
        || request.scopes.is_empty()
        || request.scopes.len() > 6
        || unique_scopes.len() != request.scopes.len()
        || !question_valid
        || !model_valid
        || document_selected != request.document.is_some()
        || request
            .document
            .as_ref()
            .is_some_and(|document| !is_valid_local_ai_workspace_document(document))
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    Ok(())
}

fn is_valid_local_ai_workspace_document(document: &CoreLocalAiWorkspaceDocument) -> bool {
    let content = document.content.as_bytes();
    let Some(expected_digest) = decode_lower_hex_digest(&document.content_sha256) else {
        return false;
    };
    if content.is_empty()
        || content.len() > MAX_LOCAL_AI_WORKSPACE_DOCUMENT_BYTES
        || document.content.trim().is_empty()
        || !is_safe_workspace_text(&document.content, 1, MAX_LOCAL_AI_WORKSPACE_DOCUMENT_BYTES)
        || !is_safe_bounded_text(&document.display_name, 1, 255)
        || Sha256::digest(content).as_slice() != expected_digest
    {
        return false;
    }
    match document.kind {
        CoreLocalAiWorkspaceDocumentKind::Paste => document
            .declared_media_type
            .as_deref()
            .is_none_or(|media_type| media_type == "text/plain"),
        CoreLocalAiWorkspaceDocumentKind::File => document
            .declared_media_type
            .as_deref()
            .is_some_and(|media_type| {
                is_supported_media_type(media_type)
                    && selected_file_name_matches_media(&document.display_name, media_type)
            }),
    }
}

fn validate_local_ai_workspace_result(
    result: &CoreLocalAiWorkspaceResult,
    profile_id: Uuid,
    task: CoreLocalAiWorkspaceTask,
    scopes: &[CoreLocalAiWorkspaceScope],
    requested_execution: CoreLocalAiWorkspaceExecution,
    requested_model: Option<&str>,
) -> Result<(), CoreError> {
    let identity_valid = match result.execution_mode {
        CoreLocalAiWorkspaceExecution::LocalModel => {
            requested_execution == CoreLocalAiWorkspaceExecution::LocalModel
                && result.fallback_reason.is_none()
                && matches!(
                    result.provider,
                    Some(CoreLocalAiProvider::Ollama | CoreLocalAiProvider::OpenaiCompatible)
                )
                && result.model_id.as_deref() == requested_model
        }
        CoreLocalAiWorkspaceExecution::Deterministic => {
            if requested_execution == CoreLocalAiWorkspaceExecution::OpenaiResponses {
                result.provider == Some(CoreLocalAiProvider::OpenaiResponses)
                    && result.model_id.as_deref() == requested_model
                    && result.fallback_reason.is_some()
            } else {
                result.provider.is_none()
                    && result.model_id.is_none()
                    && if requested_execution == CoreLocalAiWorkspaceExecution::LocalModel {
                        result.fallback_reason.is_some()
                    } else {
                        result.fallback_reason.is_none()
                    }
            }
        }
        CoreLocalAiWorkspaceExecution::OpenaiResponses => {
            requested_execution == CoreLocalAiWorkspaceExecution::OpenaiResponses
                && result.fallback_reason.is_none()
                && result.provider == Some(CoreLocalAiProvider::OpenaiResponses)
                && result.model_id.as_deref() == requested_model
        }
    };
    let network_shape_valid =
        if requested_execution == CoreLocalAiWorkspaceExecution::OpenaiResponses {
            !result.local_only && result.external_network_used
        } else {
            result.local_only && !result.external_network_used
        };
    if !is_rfc4122_uuid(result.profile_id)
        || result.profile_id != profile_id
        || result.task != task
        || result.selected_scopes != scopes
        || result.requested_execution != requested_execution
        || (requested_execution == CoreLocalAiWorkspaceExecution::Deterministic
            && result.execution_mode != CoreLocalAiWorkspaceExecution::Deterministic)
        || !identity_valid
        || result.engine_version != "1"
        || !is_safe_bounded_text(&result.title, 1, 120)
        || !is_safe_workspace_text(&result.summary, 1, 2_000)
        || result.sections.len() > 8
        || result.facts.len() > 20
        || result.connections.len() > 16
        || result.next_steps.len() > 16
        || result.sources.len() > 128
        || result.limitations.len() > 12
        || result
            .unanswered
            .as_deref()
            .is_some_and(|value| !is_safe_workspace_text(value, 1, 1_000))
        || decode_lower_hex_digest(&result.input_sha256).is_none()
        || result.restricted_values_redacted > 10_000
        || !network_shape_valid
        || result.raw_evidence_included
        || !result.review_only
        || !result.human_review_required
        || !workspace_counts_are_valid(&result.included_counts, &result.available_counts)
        || !workspace_sections_are_valid(&result.sections)
        || !workspace_facts_are_valid(&result.facts)
        || !workspace_connections_are_valid(&result.connections)
        || !workspace_next_steps_are_valid(&result.next_steps)
        || !workspace_sources_are_valid(result)
        || !workspace_text_list_is_valid(&result.limitations, 12, 600)
    {
        return Err(CoreError::InvalidLocalAiResponse);
    }
    Ok(())
}

fn workspace_counts_are_valid(
    included: &CoreLocalAiWorkspaceSourceCounts,
    available: &CoreLocalAiWorkspaceSourceCounts,
) -> bool {
    let included_values = [
        included.entities,
        included.graph_nodes,
        included.graph_edges,
        included.findings,
        included.remediation_cases,
        included.audit_runs,
        included.document_segments,
    ];
    let available_values = [
        available.entities,
        available.graph_nodes,
        available.graph_edges,
        available.findings,
        available.remediation_cases,
        available.audit_runs,
        available.document_segments,
    ];
    included_values
        .iter()
        .zip(available_values)
        .all(|(included_value, available_value)| {
            *included_value <= available_value && available_value <= 1_000_000
        })
}

fn workspace_sections_are_valid(sections: &[CoreLocalAiWorkspaceSection]) -> bool {
    let mut headings = HashSet::with_capacity(sections.len());
    sections.iter().all(|section| {
        let mut item_texts = HashSet::with_capacity(section.items.len());
        headings.insert(section.heading.as_str())
            && is_safe_bounded_text(&section.heading, 1, 96)
            && !section.items.is_empty()
            && section.items.len() <= 12
            && section.items.iter().all(|item| {
                item_texts.insert(item.text.as_str())
                    && is_safe_workspace_text(&item.text, 1, 600)
                    && workspace_refs_are_valid(&item.evidence_refs, 1, 8)
            })
    })
}

fn workspace_facts_are_valid(facts: &[CoreLocalAiWorkspaceFact]) -> bool {
    let mut statements = HashSet::with_capacity(facts.len());
    facts.iter().all(|fact| {
        statements.insert(fact.statement.as_str())
            && is_safe_workspace_text(&fact.statement, 1, 600)
            && workspace_refs_are_valid(&fact.evidence_refs, 1, 8)
    })
}

fn workspace_connections_are_valid(connections: &[CoreLocalAiWorkspaceConnection]) -> bool {
    let mut identities = HashSet::with_capacity(connections.len());
    connections.iter().all(|connection| {
        identities.insert((
            connection.from_ref.as_str(),
            connection.to_ref.as_str(),
            connection.relationship.as_str(),
        )) && connection.from_ref != connection.to_ref
            && is_workspace_ref(&connection.from_ref)
            && is_workspace_ref(&connection.to_ref)
            && is_safe_workspace_text(&connection.relationship, 1, 96)
            && workspace_refs_are_valid(&connection.supporting_refs, 1, 8)
            && workspace_refs_are_valid(&connection.contradiction_refs, 0, 8)
            && is_safe_workspace_text(&connection.rationale, 1, 600)
            && is_safe_workspace_text(&connection.verification_suggestion, 1, 600)
    })
}

fn workspace_next_steps_are_valid(steps: &[CoreLocalAiWorkspaceNextStep]) -> bool {
    let mut suggestions = HashSet::with_capacity(steps.len());
    steps.iter().all(|step| {
        (1..=5).contains(&step.priority)
            && suggestions.insert(step.suggestion.as_str())
            && is_safe_workspace_text(&step.suggestion, 1, 600)
            && is_safe_workspace_text(&step.rationale, 1, 600)
            && workspace_refs_are_valid(&step.supporting_refs, 1, 8)
    })
}

fn workspace_sources_are_valid(result: &CoreLocalAiWorkspaceResult) -> bool {
    let mut source_refs = HashSet::with_capacity(result.sources.len());
    if !result.sources.iter().all(|source| {
        source_refs.insert(source.reference.as_str()) && workspace_source_is_valid(source)
    }) {
        return false;
    }
    let mut cited_refs = HashSet::new();
    for section in &result.sections {
        for item in &section.items {
            cited_refs.extend(item.evidence_refs.iter().map(String::as_str));
        }
    }
    for fact in &result.facts {
        cited_refs.extend(fact.evidence_refs.iter().map(String::as_str));
    }
    for connection in &result.connections {
        cited_refs.insert(connection.from_ref.as_str());
        cited_refs.insert(connection.to_ref.as_str());
        cited_refs.extend(connection.supporting_refs.iter().map(String::as_str));
        cited_refs.extend(connection.contradiction_refs.iter().map(String::as_str));
    }
    for step in &result.next_steps {
        cited_refs.extend(step.supporting_refs.iter().map(String::as_str));
    }
    cited_refs == source_refs
}

fn workspace_source_is_valid(source: &CoreLocalAiWorkspaceSource) -> bool {
    let span_is_valid = match (source.source_span_start, source.source_span_end) {
        (None, None) => true,
        (Some(start), Some(end)) => start < end && end <= 1_000_000_000,
        _ => false,
    };
    let segment_fields = [
        source.segment_id.is_some(),
        source.segment_index.is_some(),
        source.segment_locator.is_some(),
    ];
    let segment_is_valid = segment_fields.iter().all(|present| *present)
        || segment_fields.iter().all(|present| !*present);
    let extractor_fields = [
        source.extraction_run_id.is_some(),
        source.extractor_kind.is_some(),
        source.extractor_name.is_some(),
        source.extractor_version.is_some(),
    ];
    let extractor_is_valid = extractor_fields.iter().all(|present| *present)
        || extractor_fields.iter().all(|present| !*present);
    let url_binding_is_valid = match (&source.source_url, &source.source_url_sha256) {
        (None, None) => true,
        (Some(url), Some(digest)) => {
            is_safe_workspace_source_url(url)
                && decode_lower_hex_digest(digest).is_some()
                && sha256_lower_hex(url.as_bytes()) == *digest
        }
        _ => false,
    };

    is_workspace_ref(&source.reference)
        && is_safe_bounded_text(&source.kind, 1, 64)
        && is_safe_bounded_text(&source.label, 1, 240)
        && is_safe_bounded_text(&source.locator, 1, 600)
        && url_binding_is_valid
        && source
            .content_sha256
            .as_deref()
            .is_none_or(|digest| decode_lower_hex_digest(digest).is_some())
        && source
            .provider_id
            .as_deref()
            .is_none_or(|provider| is_safe_bounded_text(provider, 1, 128))
        && source
            .source_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 160))
        && source
            .source_display_name
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 255))
        && source
            .artifact_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 160))
        && source
            .segment_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 160))
        && source.segment_index.is_none_or(|value| value <= 1_000_000)
        && source
            .segment_locator
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 600))
        && segment_is_valid
        && span_is_valid
        && (source.source_span_start.is_none() || source.segment_id.is_some())
        && source
            .extraction_run_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 160))
        && source
            .extractor_kind
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        && source
            .extractor_name
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 96))
        && source
            .extractor_version
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 48))
        && extractor_is_valid
        && (source.extraction_run_id.is_none() || source.segment_id.is_some())
        && source
            .run_id
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 160))
        && source
            .origin_kind
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        && source
            .origin_type
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        && source
            .observed_at_us
            .is_none_or(|value| value <= MAX_SAFE_JAVASCRIPT_INTEGER)
        && source
            .confidence_micros
            .is_none_or(|value| value <= 1_000_000)
        && source
            .disposition
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 32))
        && source
            .capture_method
            .as_deref()
            .is_none_or(|value| is_safe_bounded_text(value, 1, 64))
        && source
            .http_status
            .is_none_or(|value| (100..=599).contains(&value))
        && source.redirect_count.is_none_or(|value| value <= 20)
}

struct LocalCorpusDocumentBinding {
    document_id: String,
    display_name: String,
}

struct LocalCorpusRequestBinding {
    profile_id: Uuid,
    task: CoreLocalCorpusAiTask,
    requested_execution: CoreLocalCorpusAiExecution,
    requested_model: Option<String>,
    max_segments: u16,
    input_manifest_sha256: String,
    expected_corpus_id: String,
    documents: Vec<LocalCorpusDocumentBinding>,
}

fn validate_local_corpus_ai_request(
    request: &CoreLocalCorpusAiRequest,
) -> Result<LocalCorpusRequestBinding, CoreError> {
    let question_valid = match request.task {
        CoreLocalCorpusAiTask::Question => request
            .question
            .as_deref()
            .is_some_and(|value| is_safe_workspace_text(value, 1, 2_000) && value.len() <= 2_048),
        _ => request.question.is_none(),
    };
    let model_valid = match request.execution {
        CoreLocalCorpusAiExecution::LocalModel => {
            request.model_id.as_deref().is_some_and(is_local_model_id)
                && request.openai_api_key.is_none()
        }
        CoreLocalCorpusAiExecution::Deterministic => {
            request.model_id.is_none() && request.openai_api_key.is_none()
        }
        CoreLocalCorpusAiExecution::OpenaiResponses => {
            request.model_id.as_deref().is_some_and(is_local_model_id)
                && request
                    .openai_api_key
                    .as_deref()
                    .is_some_and(|value| is_openai_api_key(value.as_str()))
        }
    };
    if !is_rfc4122_uuid(request.profile_id)
        || request.documents.is_empty()
        || request.documents.len() > MAX_LOCAL_CORPUS_DOCUMENTS
        || !(1..=200).contains(&request.max_segments)
        || !question_valid
        || !model_valid
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }

    let mut total_bytes = 0_usize;
    for document in &request.documents {
        total_bytes = total_bytes
            .checked_add(document.expected_size_bytes)
            .ok_or(CoreError::InvalidLocalAiRequest)?;
        validate_local_corpus_document(document)?;
    }
    if total_bytes > MAX_LOCAL_CORPUS_TOTAL_BYTES {
        return Err(CoreError::InvalidLocalAiRequest);
    }

    Ok(LocalCorpusRequestBinding {
        profile_id: request.profile_id,
        task: request.task,
        requested_execution: request.execution,
        requested_model: request.model_id.clone(),
        max_segments: request.max_segments,
        input_manifest_sha256: local_corpus_manifest_sha256(&request.documents),
        expected_corpus_id: local_corpus_expected_id(&request.documents),
        documents: request
            .documents
            .iter()
            .enumerate()
            .map(|(index, document)| LocalCorpusDocumentBinding {
                document_id: format!(
                    "corpus-document:{:04}:{}",
                    index + 1,
                    document.expected_sha256
                ),
                display_name: document.display_name.clone(),
            })
            .collect(),
    })
}

fn validate_local_corpus_document(
    document: &CoreLocalCorpusDocumentRequest,
) -> Result<(), CoreError> {
    if !is_safe_local_corpus_document_name(&document.display_name)
        || !local_corpus_media_matches_name(&document.display_name, document.declared_media_type)
        || document.expected_size_bytes == 0
        || document.expected_size_bytes > MAX_LOCAL_CORPUS_DOCUMENT_BYTES
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    let expected_encoded_bytes = document.expected_size_bytes.div_ceil(3) * 4;
    if document.content_base64.len() != expected_encoded_bytes
        || document.content_base64.len() > MAX_LOCAL_CORPUS_DOCUMENT_BYTES.div_ceil(3) * 4
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    let decoded = Zeroizing::new(
        STANDARD
            .decode(document.content_base64.as_bytes())
            .map_err(|_| CoreError::InvalidLocalAiRequest)?,
    );
    let expected_digest = decode_lower_hex_digest(&document.expected_sha256)
        .ok_or(CoreError::InvalidLocalAiRequest)?;
    if decoded.len() != document.expected_size_bytes
        || Sha256::digest(decoded.as_slice()).as_slice() != expected_digest
        || STANDARD.encode(decoded.as_slice()) != document.content_base64.as_str()
        || std::str::from_utf8(decoded.as_slice()).is_err()
    {
        return Err(CoreError::InvalidLocalAiRequest);
    }
    Ok(())
}

fn is_safe_local_corpus_document_name(value: &str) -> bool {
    let count = value.chars().count();
    (1..=255).contains(&count)
        && value.trim() == value
        && !value.contains(['/', '\\'])
        && !value
            .chars()
            .any(|character| character.is_control() || is_unicode_format_character(character))
}

const fn is_unicode_format_character(character: char) -> bool {
    matches!(
        character,
        '\u{00ad}'
            | '\u{0600}'..='\u{0605}'
            | '\u{061c}'
            | '\u{06dd}'
            | '\u{070f}'
            | '\u{0890}'..='\u{0891}'
            | '\u{08e2}'
            | '\u{180e}'
            | '\u{200b}'..='\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2060}'..='\u{2064}'
            | '\u{2066}'..='\u{206f}'
            | '\u{feff}'
            | '\u{fff9}'..='\u{fffb}'
            | '\u{110bd}'
            | '\u{110cd}'
            | '\u{13430}'..='\u{1343f}'
            | '\u{1bca0}'..='\u{1bca3}'
            | '\u{1d173}'..='\u{1d17a}'
            | '\u{e0001}'
            | '\u{e0020}'..='\u{e007f}'
    )
}

fn local_corpus_media_matches_name(name: &str, media_type: CoreLocalCorpusMediaType) -> bool {
    let extension = name
        .rsplit_once('.')
        .map(|(_, extension)| extension.to_ascii_lowercase());
    matches!(
        (extension.as_deref(), media_type),
        (Some("txt"), CoreLocalCorpusMediaType::Text)
            | (
                Some("md"),
                CoreLocalCorpusMediaType::Markdown | CoreLocalCorpusMediaType::XMarkdown
            )
            | (Some("csv"), CoreLocalCorpusMediaType::Csv)
            | (Some("json"), CoreLocalCorpusMediaType::Json)
            | (
                Some("vcf"),
                CoreLocalCorpusMediaType::Vcard | CoreLocalCorpusMediaType::XVcard
            )
    )
}

fn local_corpus_manifest_sha256(documents: &[CoreLocalCorpusDocumentRequest]) -> String {
    let mut canonical = String::from("[");
    for (index, document) in documents.iter().enumerate() {
        if index > 0 {
            canonical.push(',');
        }
        canonical.push_str("{\"displayName\":");
        push_ascii_json_string(&mut canonical, &document.display_name);
        canonical.push_str(",\"mediaType\":");
        push_ascii_json_string(&mut canonical, document.declared_media_type.as_str());
        canonical.push_str(",\"sha256\":\"");
        canonical.push_str(&document.expected_sha256);
        canonical.push_str("\",\"sizeBytes\":");
        canonical.push_str(&document.expected_size_bytes.to_string());
        canonical.push('}');
    }
    canonical.push(']');
    sha256_lower_hex(canonical.as_bytes())
}

fn local_corpus_expected_id(documents: &[CoreLocalCorpusDocumentRequest]) -> String {
    let mut material = String::new();
    for (ordinal, document) in documents.iter().enumerate() {
        if ordinal > 0 {
            material.push('\n');
        }
        let (source_format, detected_media_type) = match document.declared_media_type {
            CoreLocalCorpusMediaType::Text => ("TEXT", "text/plain"),
            CoreLocalCorpusMediaType::Markdown | CoreLocalCorpusMediaType::XMarkdown => {
                ("MARKDOWN", "text/markdown")
            }
            CoreLocalCorpusMediaType::Csv => ("CSV", "text/csv"),
            CoreLocalCorpusMediaType::Json => ("JSON", "application/json"),
            CoreLocalCorpusMediaType::Vcard | CoreLocalCorpusMediaType::XVcard => {
                ("VCARD", "text/vcard")
            }
        };
        material.push_str(&ordinal.to_string());
        material.push('\0');
        material.push_str(&document.display_name);
        material.push('\0');
        material.push_str(source_format);
        material.push('\0');
        material.push_str(detected_media_type);
        material.push('\0');
        material.push_str(&document.expected_sha256);
    }
    format!("corpus:{}", sha256_lower_hex(material.as_bytes()))
}

fn push_ascii_json_string(output: &mut String, value: &str) {
    output.push('"');
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{0008}' => output.push_str("\\b"),
            '\u{000c}' => output.push_str("\\f"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character <= '\u{001f}' => {
                output.push_str(&format!("\\u{:04x}", u32::from(character)));
            }
            character if character.is_ascii() => output.push(character),
            character if u32::from(character) <= 0xffff => {
                output.push_str(&format!("\\u{:04x}", u32::from(character)));
            }
            character => {
                let scalar = u32::from(character) - 0x1_0000;
                let high = 0xd800 + (scalar >> 10);
                let low = 0xdc00 + (scalar & 0x3ff);
                output.push_str(&format!("\\u{high:04x}\\u{low:04x}"));
            }
        }
    }
    output.push('"');
}

fn sha256_lower_hex(value: &[u8]) -> String {
    Sha256::digest(value)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn validate_local_corpus_ai_result(
    result: &CoreLocalCorpusAiResult,
    binding: &LocalCorpusRequestBinding,
) -> Result<(), CoreError> {
    let identity_valid = match result.execution_mode {
        CoreLocalCorpusAiExecution::LocalModel => {
            binding.requested_execution == CoreLocalCorpusAiExecution::LocalModel
                && result.fallback_reason.is_none()
                && matches!(
                    result.provider,
                    Some(CoreLocalAiProvider::Ollama | CoreLocalAiProvider::OpenaiCompatible)
                )
                && result.model_id.as_deref() == binding.requested_model.as_deref()
        }
        CoreLocalCorpusAiExecution::Deterministic => {
            if binding.requested_execution == CoreLocalCorpusAiExecution::OpenaiResponses {
                result.provider == Some(CoreLocalAiProvider::OpenaiResponses)
                    && result.model_id.as_deref() == binding.requested_model.as_deref()
                    && result.fallback_reason.is_some()
            } else {
                result.provider.is_none()
                    && result.model_id.is_none()
                    && if binding.requested_execution == CoreLocalCorpusAiExecution::LocalModel {
                        result.fallback_reason.is_some()
                    } else {
                        result.fallback_reason.is_none()
                    }
            }
        }
        CoreLocalCorpusAiExecution::OpenaiResponses => {
            binding.requested_execution == CoreLocalCorpusAiExecution::OpenaiResponses
                && result.fallback_reason.is_none()
                && result.provider == Some(CoreLocalAiProvider::OpenaiResponses)
                && result.model_id.as_deref() == binding.requested_model.as_deref()
        }
    };
    let network_shape_valid =
        if binding.requested_execution == CoreLocalCorpusAiExecution::OpenaiResponses {
            !result.local_only && result.external_network_used
        } else {
            result.local_only && !result.external_network_used
        };
    let counts_valid = local_corpus_counts_are_valid(
        &result.included_counts,
        &result.available_counts,
        binding.documents.len(),
        binding.max_segments,
        result.projection_truncated,
    );
    if result.profile_id != binding.profile_id
        || result.task != binding.task
        || result.requested_execution != binding.requested_execution
        || (binding.requested_execution == CoreLocalCorpusAiExecution::Deterministic
            && result.execution_mode != CoreLocalCorpusAiExecution::Deterministic)
        || !identity_valid
        || result.input_manifest_sha256 != binding.input_manifest_sha256
        || result.corpus_id != binding.expected_corpus_id
        || !is_local_corpus_id(&result.corpus_id)
        || decode_lower_hex_digest(&result.input_sha256).is_none()
        || result.engine_version != "1"
        || !is_safe_bounded_text(&result.title, 1, 120)
        || !is_safe_workspace_text(&result.draft_summary, 1, 2_000)
        || result.narrative_label != "DRAFT_SUMMARY_NOT_A_FACT"
        || result.sections.len() > 8
        || result.facts.len() > 20
        || result.connections.len() > 16
        || result.next_steps.len() > 16
        || result.uncertainties.len() > 12
        || result.source_catalog.len() > MAX_LOCAL_CORPUS_SOURCE_CATALOG
        || result
            .unanswered
            .as_deref()
            .is_some_and(|value| !is_safe_workspace_text(value, 1, 1_000))
        || !counts_valid
        || result.restricted_values_redacted > 20_000
        || !network_shape_valid
        || result.raw_sources_retained
        || result.persisted
        || !result.review_only
        || !result.human_review_required
        || !local_corpus_output_is_grounded(result, &binding.documents)
    {
        return Err(CoreError::InvalidLocalAiResponse);
    }
    Ok(())
}

fn local_corpus_counts_are_valid(
    included: &CoreLocalCorpusAiCounts,
    available: &CoreLocalCorpusAiCounts,
    document_count: usize,
    max_segments: u16,
    projection_truncated: bool,
) -> bool {
    let included_values = [
        u32::from(included.documents),
        u32::from(included.segments),
        u32::from(included.entities),
        u32::from(included.shared_entities),
    ];
    let available_values = [
        u32::from(available.documents),
        u32::from(available.segments),
        u32::from(available.entities),
        u32::from(available.shared_entities),
    ];
    included.documents > 0
        && included.segments > 0
        && available.documents as usize == document_count
        && available.segments > 0
        && available.segments <= 5_000
        && available.entities <= 4_096
        && available.shared_entities <= 4_096
        && included.segments <= max_segments
        && included_values
            .iter()
            .zip(available_values)
            .all(|(included_value, available_value)| included_value <= &available_value)
        && (projection_truncated || included_values == available_values)
}

fn local_corpus_output_is_grounded(
    result: &CoreLocalCorpusAiResult,
    documents: &[LocalCorpusDocumentBinding],
) -> bool {
    let deterministic_only = result.execution_mode == CoreLocalCorpusAiExecution::Deterministic;
    if !result
        .sections
        .iter()
        .all(|section| local_corpus_section_is_valid(section, deterministic_only))
        || !result
            .facts
            .iter()
            .all(|fact| local_corpus_fact_is_valid(fact, deterministic_only))
        || !result
            .next_steps
            .iter()
            .all(|step| local_corpus_next_step_is_valid(step, deterministic_only))
        || !result
            .uncertainties
            .iter()
            .all(|note| local_corpus_review_note_is_valid(note, deterministic_only))
    {
        return false;
    }

    let mut catalog = HashMap::with_capacity(result.source_catalog.len());
    let mut pointers: HashMap<&str, (&str, &str, u32, &str)> = HashMap::new();
    for entry in &result.source_catalog {
        if catalog.insert(entry.reference_id.as_str(), entry).is_some()
            || !local_corpus_catalog_entry_is_valid(entry, documents, &mut pointers)
        {
            return false;
        }
    }

    let mut cited = HashSet::new();
    for section in &result.sections {
        for item in &section.items {
            cited.extend(item.evidence_refs.iter().map(String::as_str));
        }
    }
    for fact in &result.facts {
        cited.extend(fact.evidence_refs.iter().map(String::as_str));
    }
    for step in &result.next_steps {
        cited.extend(step.supporting_refs.iter().map(String::as_str));
    }
    for note in &result.uncertainties {
        cited.extend(note.evidence_refs.iter().map(String::as_str));
    }
    let mut connections = HashSet::with_capacity(result.connections.len());
    for connection in &result.connections {
        if !connections.insert((
            connection.from_ref.as_str(),
            connection.to_ref.as_str(),
            connection.relationship.as_str(),
        )) || !local_corpus_connection_is_valid(connection, deterministic_only, &catalog)
        {
            return false;
        }
        cited.insert(connection.from_ref.as_str());
        cited.insert(connection.to_ref.as_str());
        cited.extend(connection.shared_entity_refs.iter().map(String::as_str));
        cited.extend(connection.supporting_refs.iter().map(String::as_str));
        cited.extend(connection.contradiction_refs.iter().map(String::as_str));
    }

    cited.len() == catalog.len()
        && cited
            .iter()
            .all(|reference| catalog.contains_key(reference))
}

fn local_corpus_section_is_valid(
    section: &CoreLocalCorpusAiSection,
    deterministic_only: bool,
) -> bool {
    is_safe_bounded_text(&section.heading, 1, 96)
        && !section.items.is_empty()
        && section.items.len() <= 12
        && section
            .items
            .iter()
            .all(|note| local_corpus_review_note_is_valid(note, deterministic_only))
}

fn local_corpus_review_note_is_valid(
    note: &CoreLocalCorpusAiReviewNote,
    deterministic_only: bool,
) -> bool {
    is_safe_workspace_text(&note.text, 1, 600)
        && local_corpus_origin_is_valid(note.origin, deterministic_only)
        && local_corpus_refs_are_valid(&note.evidence_refs, 0, 8)
        && (!matches!(
            note.label,
            CoreLocalCorpusAiTextLabel::Organization | CoreLocalCorpusAiTextLabel::CitedSummary
        ) || !note.evidence_refs.is_empty())
}

fn local_corpus_fact_is_valid(fact: &CoreLocalCorpusAiFact, deterministic_only: bool) -> bool {
    is_safe_workspace_text(&fact.statement, 1, 600)
        && local_corpus_refs_are_valid(&fact.evidence_refs, 1, 8)
        && local_corpus_origin_is_valid(fact.origin, deterministic_only)
}

fn local_corpus_next_step_is_valid(
    step: &CoreLocalCorpusAiNextStep,
    deterministic_only: bool,
) -> bool {
    (1..=5).contains(&step.priority)
        && is_safe_workspace_text(&step.suggestion, 1, 600)
        && is_safe_workspace_text(&step.rationale, 1, 600)
        && local_corpus_refs_are_valid(&step.supporting_refs, 1, 8)
        && local_corpus_origin_is_valid(step.origin, deterministic_only)
}

fn local_corpus_connection_is_valid(
    connection: &CoreLocalCorpusAiConnection,
    deterministic_only: bool,
    catalog: &HashMap<&str, &CoreLocalCorpusAiSourceCatalogEntry>,
) -> bool {
    if connection.from_ref == connection.to_ref
        || !is_local_corpus_segment_id(&connection.from_ref)
        || !is_local_corpus_segment_id(&connection.to_ref)
        || !local_corpus_refs_are_valid(&connection.shared_entity_refs, 1, 4)
        || !connection
            .shared_entity_refs
            .iter()
            .all(|reference| is_local_corpus_entity_id(reference))
        || !is_safe_workspace_text(&connection.relationship, 1, 96)
        || !local_corpus_refs_are_valid(&connection.supporting_refs, 3, 8)
        || !local_corpus_refs_are_valid(&connection.contradiction_refs, 0, 8)
        || !local_corpus_origin_is_valid(connection.origin, deterministic_only)
        || !is_safe_workspace_text(&connection.rationale, 1, 600)
        || !is_safe_workspace_text(&connection.verification_suggestion, 1, 600)
    {
        return false;
    }
    let support = connection
        .supporting_refs
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    if ![connection.from_ref.as_str(), connection.to_ref.as_str()]
        .into_iter()
        .chain(connection.shared_entity_refs.iter().map(String::as_str))
        .all(|reference| support.contains(reference))
    {
        return false;
    }
    let Some(from) = catalog.get(connection.from_ref.as_str()) else {
        return false;
    };
    let Some(to) = catalog.get(connection.to_ref.as_str()) else {
        return false;
    };
    if from.reference_kind != CoreLocalCorpusAiReferenceKind::Segment
        || to.reference_kind != CoreLocalCorpusAiReferenceKind::Segment
        || from.sources[0].document_id == to.sources[0].document_id
    {
        return false;
    }
    connection.shared_entity_refs.iter().all(|reference| {
        catalog.get(reference.as_str()).is_some_and(|entry| {
            entry.reference_kind == CoreLocalCorpusAiReferenceKind::Entity
                && entry
                    .sources
                    .iter()
                    .any(|source| source.segment_id == connection.from_ref)
                && entry
                    .sources
                    .iter()
                    .any(|source| source.segment_id == connection.to_ref)
        })
    })
}

fn local_corpus_catalog_entry_is_valid<'a>(
    entry: &'a CoreLocalCorpusAiSourceCatalogEntry,
    documents: &[LocalCorpusDocumentBinding],
    pointers: &mut HashMap<&'a str, (&'a str, &'a str, u32, &'a str)>,
) -> bool {
    let reference_shape = match entry.reference_kind {
        CoreLocalCorpusAiReferenceKind::Segment => is_local_corpus_segment_id(&entry.reference_id),
        CoreLocalCorpusAiReferenceKind::Entity => is_local_corpus_entity_id(&entry.reference_id),
    };
    if !reference_shape || entry.sources.is_empty() || entry.sources.len() > 32 {
        return false;
    }
    let mut source_ids = HashSet::with_capacity(entry.sources.len());
    for source in &entry.sources {
        let Some(document) = documents
            .iter()
            .find(|document| document.document_id == source.document_id)
        else {
            return false;
        };
        if document.display_name != source.document_name
            || !source_ids.insert(source.segment_id.as_str())
            || !local_corpus_source_pointer_is_valid(source)
        {
            return false;
        }
        let binding = (
            source.document_id.as_str(),
            source.document_name.as_str(),
            source.segment_index,
            source.locator.as_str(),
        );
        if pointers
            .insert(source.segment_id.as_str(), binding)
            .is_some_and(|existing| existing != binding)
        {
            return false;
        }
    }
    entry.reference_kind != CoreLocalCorpusAiReferenceKind::Segment
        || (entry.sources.len() == 1 && entry.sources[0].segment_id == entry.reference_id)
}

fn local_corpus_source_pointer_is_valid(source: &CoreLocalCorpusAiSourcePointer) -> bool {
    is_local_corpus_document_id(&source.document_id)
        && is_local_corpus_segment_id(&source.segment_id)
        && source.segment_index <= 99_999
        && source
            .segment_id
            .strip_prefix(&source.document_id)
            .is_some_and(|suffix| suffix == format!(":segment:{}", source.segment_index))
        && is_safe_workspace_text(&source.document_name, 1, 255)
        && is_safe_workspace_text(&source.locator, 1, 4_096)
}

fn local_corpus_refs_are_valid(values: &[String], minimum: usize, maximum: usize) -> bool {
    let mut unique = HashSet::with_capacity(values.len());
    values.len() >= minimum
        && values.len() <= maximum
        && values.iter().all(|value| {
            unique.insert(value.as_str())
                && (is_local_corpus_segment_id(value) || is_local_corpus_entity_id(value))
        })
}

const fn local_corpus_origin_is_valid(
    origin: CoreLocalCorpusAiContentOrigin,
    deterministic_only: bool,
) -> bool {
    !deterministic_only || matches!(origin, CoreLocalCorpusAiContentOrigin::Deterministic)
}

fn is_local_corpus_id(value: &str) -> bool {
    value.strip_prefix("corpus:").is_some_and(is_lower_sha256)
}

fn is_local_corpus_document_id(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("corpus-document:") else {
        return false;
    };
    let Some((ordinal, sha256)) = rest.split_once(':') else {
        return false;
    };
    ordinal.len() == 4
        && ordinal.bytes().all(|byte| byte.is_ascii_digit())
        && ordinal != "0000"
        && is_lower_sha256(sha256)
}

fn is_local_corpus_segment_id(value: &str) -> bool {
    let Some((document_id, index)) = value.rsplit_once(":segment:") else {
        return false;
    };
    is_local_corpus_document_id(document_id)
        && !index.is_empty()
        && index.len() <= 5
        && index.bytes().all(|byte| byte.is_ascii_digit())
        && index
            .parse::<u32>()
            .is_ok_and(|parsed| parsed <= 99_999 && index == parsed.to_string())
}

fn is_local_corpus_entity_id(value: &str) -> bool {
    value
        .strip_prefix("corpus-entity:")
        .is_some_and(is_lower_sha256)
}

fn is_lower_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn is_openai_api_key(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 512
        && value.trim() == value
        && value
            .chars()
            .all(|character| u32::from(character) > 32 && character != '\u{007f}')
}

fn is_safe_workspace_source_url(value: &str) -> bool {
    if !is_safe_bounded_text(value, 1, 2_048) {
        return false;
    }
    reqwest::Url::parse(value).is_ok_and(|url| {
        matches!(url.scheme(), "http" | "https")
            && url.host_str().is_some()
            && url.username().is_empty()
            && url.password().is_none()
    })
}

fn validate_public_discovery_capture_request(
    request: &CorePublicDiscoveryCaptureRequest,
) -> Result<(), CoreError> {
    let query_is_canonical = request
        .query
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        == request.query;
    let title_is_canonical = request
        .title
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        == request.title;
    let snippet_is_canonical = request
        .snippet
        .as_deref()
        .is_none_or(|value| value.split_whitespace().collect::<Vec<_>>().join(" ") == value);
    let source_id_is_canonical = request
        .source_id
        .as_deref()
        .is_none_or(|value| value.split_whitespace().collect::<Vec<_>>().join(" ") == value);
    if !is_rfc4122_uuid(request.profile_id)
        || !request.authorized_self_audit
        || !(1..=MAX_PUBLIC_DISCOVERY_RESULTS).contains(&usize::from(request.rank))
        || !is_safe_bounded_text(&request.query, 1, 1_024)
        || request.query.len() > 1_024
        || !query_is_canonical
        || !is_safe_bounded_text(&request.title, 1, 240)
        || !title_is_canonical
        || !is_safe_public_discovery_url(&request.url)
        || request
            .snippet
            .as_deref()
            .is_some_and(|value| !is_safe_bounded_text(value, 1, 600))
        || !snippet_is_canonical
        || request
            .source_id
            .as_deref()
            .is_some_and(|value| !is_safe_bounded_text(value, 1, 160))
        || !source_id_is_canonical
        || !is_valid_timestamp_us(request.captured_at_us)
    {
        return Err(CoreError::InvalidPublicDiscoveryRequest);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_public_discovery_capture_result(
    result: &CorePublicDiscoveryCaptureResult,
    profile_id: Uuid,
    provider: CorePublicDiscoveryProvider,
    rank: u8,
    source_id: Option<&str>,
    url: &str,
    captured_at_us: u64,
) -> Result<(), CoreError> {
    let query_reference_is_valid = result
        .query_reference
        .strip_prefix("mq_")
        .and_then(decode_lower_hex_digest)
        .is_some();
    if !is_rfc4122_uuid(result.profile_id)
        || !is_rfc4122_uuid(result.finding_id)
        || !is_rfc4122_uuid(result.artifact_id)
        || result.profile_id == result.finding_id
        || result.profile_id == result.artifact_id
        || result.finding_id == result.artifact_id
        || result.profile_id != profile_id
        || result.provider != provider
        || result.rank != rank
        || result.source_id.as_deref() != source_id
        || result.url != url
        || !is_safe_public_discovery_url(&result.url)
        || result.url_sha256 != sha256_lower_hex(url.as_bytes())
        || !query_reference_is_valid
        || result.captured_at_us != captured_at_us
        || !is_valid_timestamp_us(result.captured_at_us)
        || result.evidence_kind != CorePhase5ArtifactKind::UrlReference
        || !result.encrypted_at_rest
        || !result.local_only
    {
        return Err(CoreError::InvalidPublicDiscoveryResponse);
    }
    Ok(())
}

fn validate_public_discovery_request(
    request: &CorePublicDiscoverySearchRequest,
) -> Result<(), CoreError> {
    if !(1..=MAX_PUBLIC_DISCOVERY_RESULTS).contains(&usize::from(request.max_results))
        || !is_safe_bounded_text(&request.query, 1, 1_024)
        || request.query.len() > 1_024
        || request
            .query
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            != request.query
    {
        return Err(CoreError::InvalidPublicDiscoveryRequest);
    }
    Ok(())
}

fn validate_public_discovery_result(
    result: &CorePublicDiscoverySearchResult,
    provider: CorePublicDiscoveryProvider,
    authorization_confirmed: bool,
    max_results: u8,
) -> Result<(), CoreError> {
    let reason_matches_state = matches!(
        (result.state, result.reason),
        (
            CorePublicDiscoveryState::NotChecked,
            CorePublicDiscoveryReason::SelfAuditAuthorizationRequired
        ) | (
            CorePublicDiscoveryState::Succeeded,
            CorePublicDiscoveryReason::Complete
                | CorePublicDiscoveryReason::NoResults
                | CorePublicDiscoveryReason::PartialResults
        ) | (
            CorePublicDiscoveryState::RateLimited,
            CorePublicDiscoveryReason::UpstreamRateLimited
        ) | (
            CorePublicDiscoveryState::AccessBlocked,
            CorePublicDiscoveryReason::RestrictedValue
                | CorePublicDiscoveryReason::CaptchaOrChallenge
                | CorePublicDiscoveryReason::UpstreamAccessBlocked
                | CorePublicDiscoveryReason::RedirectRefused
        ) | (
            CorePublicDiscoveryState::Failed,
            CorePublicDiscoveryReason::Timeout
                | CorePublicDiscoveryReason::ResponseLimit
                | CorePublicDiscoveryReason::NetworkUnavailable
                | CorePublicDiscoveryReason::UpstreamUnavailable
                | CorePublicDiscoveryReason::UpstreamRejected
                | CorePublicDiscoveryReason::InvalidResponse
        )
    );
    let external_request_state_is_valid = match (result.state, result.reason) {
        (CorePublicDiscoveryState::NotChecked, _) => !result.external_request_made,
        (CorePublicDiscoveryState::AccessBlocked, CorePublicDiscoveryReason::RestrictedValue) => {
            !result.external_request_made
        }
        _ => result.external_request_made,
    };
    let result_count = result.results.len();
    if result.provider != provider
        || result.authorization_confirmed != authorization_confirmed
        || !result.human_review_required
        || !reason_matches_state
        || !external_request_state_is_valid
        || result.external_request_made && !result.authorization_confirmed
        || result_count > usize::from(max_results)
        || result_count > MAX_PUBLIC_DISCOVERY_RESULTS
        || result
            .total_estimate
            .is_some_and(|value| value > 1_000_000_000)
        || result
            .rate_limit_remaining
            .is_some_and(|value| value > 1_000_000_000)
        || result.truncated && result.state != CorePublicDiscoveryState::Succeeded
        || result.state != CorePublicDiscoveryState::Succeeded && result_count != 0
        || result.reason == CorePublicDiscoveryReason::NoResults && result_count != 0
        || matches!(
            result.reason,
            CorePublicDiscoveryReason::Complete | CorePublicDiscoveryReason::PartialResults
        ) && result_count == 0
    {
        return Err(CoreError::InvalidPublicDiscoveryResponse);
    }

    let mut urls = HashSet::with_capacity(result_count);
    for (index, item) in result.results.iter().enumerate() {
        if item.provider != provider
            || usize::from(item.rank) != index + 1
            || !is_safe_bounded_text(&item.title, 1, 240)
            || !is_safe_public_discovery_url(&item.url)
            || !urls.insert(item.url.as_str())
            || item
                .snippet
                .as_deref()
                .is_some_and(|value| !is_safe_bounded_text(value, 1, 600))
            || item
                .source_id
                .as_deref()
                .is_some_and(|value| !is_safe_bounded_text(value, 1, 160))
        {
            return Err(CoreError::InvalidPublicDiscoveryResponse);
        }
    }
    Ok(())
}

struct HibpAccountBinding {
    email: Zeroizing<String>,
    mode: CoreHibpAccountMode,
    authorized_self_audit: bool,
    authorized_direct_identifier_transmission: bool,
}

struct HibpDomainBinding {
    domain: Zeroizing<String>,
    authorized_self_audit: bool,
}

struct InvestigationPlanBinding {
    plan_id: String,
    steps: Vec<CoreInvestigationPlanStep>,
    notices: Vec<CoreInvestigationNotice>,
    authorization_confirmed: bool,
}

struct InvestigationStepTemplate<'a> {
    provider: CoreInvestigationProvider,
    operation: CoreInvestigationOperation,
    execution_route: &'a str,
    transmission: CoreInvestigationTransmission,
    prerequisites: &'a [CoreInvestigationPrerequisite],
}

fn validate_hibp_account_request(
    request: &CoreHibpAccountRequest,
) -> Result<HibpAccountBinding, CoreError> {
    if !is_canonical_hibp_email(request.email.as_str())
        || !is_valid_hibp_api_key(request.api_key.as_str())
    {
        return Err(CoreError::InvalidHibpRequest);
    }
    Ok(HibpAccountBinding {
        email: Zeroizing::new(request.email.as_str().to_owned()),
        mode: request.mode,
        authorized_self_audit: request.authorized_self_audit,
        authorized_direct_identifier_transmission: request
            .authorized_direct_identifier_transmission,
    })
}

fn validate_hibp_domain_request(
    request: &CoreHibpDomainRequest,
) -> Result<HibpDomainBinding, CoreError> {
    if !is_canonical_hibp_domain(request.domain.as_str())
        || !is_valid_hibp_api_key(request.api_key.as_str())
    {
        return Err(CoreError::InvalidHibpRequest);
    }
    Ok(HibpDomainBinding {
        domain: Zeroizing::new(request.domain.as_str().to_owned()),
        authorized_self_audit: request.authorized_self_audit,
    })
}

fn validate_hibp_account_result(
    result: &CoreHibpAccountResult,
    binding: &HibpAccountBinding,
) -> Result<(), CoreError> {
    validate_hibp_provider_fields(
        result.provider,
        &result.provider_home_url,
        &result.api_documentation_url,
        &result.attribution,
        &result.license,
    )?;
    let should_dispatch = binding.authorized_self_audit
        && (binding.mode == CoreHibpAccountMode::KAnonymity
            || binding.authorized_direct_identifier_transmission);
    if result.mode != binding.mode
        || result.authorization_confirmed != binding.authorized_self_audit
        || result.external_request_made != should_dispatch
        || result.requests.len() != usize::from(should_dispatch)
        || !result.human_review_required
        || result.direct_transmission_authorized
            != (should_dispatch
                && binding.mode == CoreHibpAccountMode::Direct
                && binding.authorized_direct_identifier_transmission)
        || result.breaches.len() > MAX_HIBP_BREACHES
        || !hibp_state_reason_is_valid(result.state, result.reason)
        || result.reason == CoreHibpReason::PartialResults
        || !hibp_retry_state_is_valid(
            result.state,
            result.retry_after_seconds,
            result.requests.last(),
        )
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    if !binding.authorized_self_audit {
        if result.state != CoreHibpState::NotChecked
            || result.reason != CoreHibpReason::SelfAuditAuthorizationRequired
        {
            return Err(CoreError::InvalidHibpResponse);
        }
    } else if binding.mode == CoreHibpAccountMode::Direct
        && !binding.authorized_direct_identifier_transmission
    {
        if result.state != CoreHibpState::NotChecked
            || result.reason != CoreHibpReason::DirectTransmissionAuthorizationRequired
        {
            return Err(CoreError::InvalidHibpResponse);
        }
    } else if result.state == CoreHibpState::NotChecked {
        return Err(CoreError::InvalidHibpResponse);
    }

    if should_dispatch {
        let (operation, disclosure, request_url) = match binding.mode {
            CoreHibpAccountMode::KAnonymity => (
                CoreHibpOperation::EmailKAnonymity,
                CoreHibpIdentifierDisclosure::PartialSha1Prefix,
                format!(
                    "https://haveibeenpwned.com/api/v3/breachedaccount/range/{}",
                    hibp_sha1_prefix(binding.email.as_bytes())
                ),
            ),
            CoreHibpAccountMode::Direct => (
                CoreHibpOperation::EmailDirect,
                CoreHibpIdentifierDisclosure::DirectEmail,
                format!(
                    "https://haveibeenpwned.com/api/v3/breachedAccount/{}?truncateResponse=true&IncludeUnverified=false",
                    percent_encode_path_segment(binding.email.as_bytes())
                ),
            ),
        };
        validate_hibp_request_metadata(
            &result.requests[0],
            1,
            operation,
            disclosure,
            &request_url,
        )?;
    }
    validate_hibp_reason_http_binding(result.reason, result.requests.last())?;
    validate_hibp_breaches(&result.breaches)?;
    let has_breaches = !result.breaches.is_empty();
    if result.state != CoreHibpState::Succeeded && has_breaches
        || result.reason == CoreHibpReason::Complete && !has_breaches
        || result.reason == CoreHibpReason::NoResults && has_breaches
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    Ok(())
}

fn validate_hibp_domain_result(
    result: &CoreHibpDomainResult,
    binding: &HibpDomainBinding,
) -> Result<(), CoreError> {
    validate_hibp_provider_fields(
        result.provider,
        &result.provider_home_url,
        &result.api_documentation_url,
        &result.attribution,
        &result.license,
    )?;
    let expected_request_count = if binding.authorized_self_audit {
        result.requests.len()
    } else {
        0
    };
    if result.authorization_confirmed != binding.authorized_self_audit
        || result.external_request_made != binding.authorized_self_audit
        || result.requests.len() != expected_request_count
        || result.requests.len() > 2
        || binding.authorized_self_audit && result.requests.is_empty()
        || !result.human_review_required
        || result.accounts.len() > MAX_HIBP_DOMAIN_ACCOUNTS
        || result.provider_verified_domain != (result.requests.len() == 2)
        || !hibp_state_reason_is_valid(result.state, result.reason)
        || !hibp_retry_state_is_valid(
            result.state,
            result.retry_after_seconds,
            result.requests.last(),
        )
        || result.state == CoreHibpState::Succeeded && !result.provider_verified_domain
        || result.state != CoreHibpState::Succeeded && !result.accounts.is_empty()
        || result.truncated && result.state != CoreHibpState::Succeeded
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    if !binding.authorized_self_audit {
        if result.state != CoreHibpState::NotChecked
            || result.reason != CoreHibpReason::SelfAuditAuthorizationRequired
            || result.provider_verified_domain
            || result.truncated
        {
            return Err(CoreError::InvalidHibpResponse);
        }
    } else {
        if result.state == CoreHibpState::NotChecked {
            return Err(CoreError::InvalidHibpResponse);
        }
        validate_hibp_request_metadata(
            &result.requests[0],
            1,
            CoreHibpOperation::VerifySubscribedDomain,
            CoreHibpIdentifierDisclosure::None,
            "https://haveibeenpwned.com/api/v3/subscribedDomains",
        )?;
        if result.requests.len() == 2 {
            let request_url = format!(
                "https://haveibeenpwned.com/api/v3/breachedDomain/{}",
                percent_encode_path_segment(binding.domain.as_bytes())
            );
            validate_hibp_request_metadata(
                &result.requests[1],
                2,
                CoreHibpOperation::DomainEnumeration,
                CoreHibpIdentifierDisclosure::DirectDomain,
                &request_url,
            )?;
        }
    }
    if result.reason == CoreHibpReason::DomainNotProviderVerified
        && (result.requests.len() != 1
            || result.requests[0].http_status != Some(200)
            || result.provider_verified_domain)
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    validate_hibp_reason_http_binding(result.reason, result.requests.last())?;

    let mut previous_alias: Option<String> = None;
    let mut aliases = HashSet::with_capacity(result.accounts.len());
    for account in &result.accounts {
        if !is_safe_bounded_text(&account.alias, 1, 160)
            || account.alias.contains('@')
            || !aliases.insert(account.alias.to_lowercase())
            || previous_alias
                .as_ref()
                .is_some_and(|previous| previous >= &account.alias.to_lowercase())
        {
            return Err(CoreError::InvalidHibpResponse);
        }
        previous_alias = Some(account.alias.to_lowercase());
        validate_hibp_breaches(&account.breaches)?;
    }
    let has_accounts = !result.accounts.is_empty();
    if matches!(
        result.reason,
        CoreHibpReason::Complete | CoreHibpReason::PartialResults
    ) && !has_accounts
        || result.reason == CoreHibpReason::NoResults && has_accounts
        || result.reason == CoreHibpReason::PartialResults && !result.truncated
        || result.truncated && result.reason != CoreHibpReason::PartialResults
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    Ok(())
}

fn validate_hibp_provider_fields(
    provider: CoreHibpProvider,
    provider_home_url: &str,
    api_documentation_url: &str,
    attribution: &str,
    license: &str,
) -> Result<(), CoreError> {
    if provider != CoreHibpProvider::HaveIBeenPwnedV3
        || provider_home_url != "https://haveibeenpwned.com/"
        || api_documentation_url != "https://haveibeenpwned.com/API/v3"
        || attribution != "Have I Been Pwned"
        || license != "CC BY 4.0"
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    Ok(())
}

fn validate_hibp_request_metadata(
    metadata: &CoreHibpRequestMetadata,
    sequence: u8,
    operation: CoreHibpOperation,
    disclosure: CoreHibpIdentifierDisclosure,
    request_url: &str,
) -> Result<(), CoreError> {
    if metadata.sequence != sequence
        || metadata.operation != operation
        || metadata.method != "GET"
        || metadata.request_url != request_url
        || metadata.endpoint_host != "haveibeenpwned.com"
        || metadata.identifier_disclosure != disclosure
        || metadata.request_sha256 != sha256_lower_hex(format!("GET\n{request_url}").as_bytes())
        || metadata
            .http_status
            .is_some_and(|status| !(100..=599).contains(&status))
        || metadata.response_bytes > MAX_HIBP_RESPONSE_BYTES
        || metadata.http_status.is_none() && metadata.response_bytes != 0
        || !is_bounded_rfc3339(&metadata.observed_at)
        || metadata
            .retry_after_seconds
            .is_some_and(|seconds| seconds > MAX_HIBP_RETRY_AFTER_SECONDS)
        || metadata.retry_after_seconds.is_some() && metadata.http_status != Some(429)
        || !metadata.api_key_sent
        || metadata.redirects_followed
    {
        return Err(CoreError::InvalidHibpResponse);
    }
    Ok(())
}

fn validate_hibp_breaches(breaches: &[CoreHibpBreachReference]) -> Result<(), CoreError> {
    if breaches.len() > MAX_HIBP_BREACHES {
        return Err(CoreError::InvalidHibpResponse);
    }
    let mut previous_name: Option<String> = None;
    for breach in breaches {
        let folded = breach.name.to_lowercase();
        let expected_source = format!(
            "https://haveibeenpwned.com/api/v3/breach/{}",
            percent_encode_path_segment(breach.name.as_bytes())
        );
        if !is_safe_bounded_text(&breach.name, 1, 160)
            || breach.source_url != expected_source
            || previous_name
                .as_ref()
                .is_some_and(|previous| previous >= &folded)
        {
            return Err(CoreError::InvalidHibpResponse);
        }
        previous_name = Some(folded);
    }
    Ok(())
}

fn hibp_state_reason_is_valid(state: CoreHibpState, reason: CoreHibpReason) -> bool {
    matches!(
        (state, reason),
        (
            CoreHibpState::NotChecked,
            CoreHibpReason::SelfAuditAuthorizationRequired
                | CoreHibpReason::DirectTransmissionAuthorizationRequired
        ) | (
            CoreHibpState::Succeeded,
            CoreHibpReason::Complete | CoreHibpReason::NoResults | CoreHibpReason::PartialResults
        ) | (
            CoreHibpState::RateLimited,
            CoreHibpReason::UpstreamRateLimited
        ) | (
            CoreHibpState::AccessBlocked,
            CoreHibpReason::DomainNotProviderVerified
                | CoreHibpReason::InvalidApiKey
                | CoreHibpReason::RedirectRefused
                | CoreHibpReason::UpstreamAccessBlocked
        ) | (
            CoreHibpState::Failed,
            CoreHibpReason::Timeout
                | CoreHibpReason::ResponseLimit
                | CoreHibpReason::NetworkUnavailable
                | CoreHibpReason::UpstreamUnavailable
                | CoreHibpReason::UpstreamRejected
                | CoreHibpReason::InvalidResponse
        )
    )
}

fn hibp_retry_state_is_valid(
    state: CoreHibpState,
    retry_after_seconds: Option<u32>,
    last_request: Option<&CoreHibpRequestMetadata>,
) -> bool {
    if retry_after_seconds.is_some_and(|seconds| seconds > MAX_HIBP_RETRY_AFTER_SECONDS) {
        return false;
    }
    if state != CoreHibpState::RateLimited && retry_after_seconds.is_some() {
        return false;
    }
    retry_after_seconds == last_request.and_then(|request| request.retry_after_seconds)
}

fn validate_hibp_reason_http_binding(
    reason: CoreHibpReason,
    last_request: Option<&CoreHibpRequestMetadata>,
) -> Result<(), CoreError> {
    let status = last_request.and_then(|request| request.http_status);
    let valid = match reason {
        CoreHibpReason::InvalidApiKey => status == Some(401),
        CoreHibpReason::UpstreamRateLimited => status == Some(429),
        CoreHibpReason::RedirectRefused => status.is_some_and(|value| (300..400).contains(&value)),
        CoreHibpReason::UpstreamAccessBlocked => matches!(status, Some(403 | 451)),
        CoreHibpReason::UpstreamUnavailable => status.is_some_and(|value| value >= 500),
        CoreHibpReason::Timeout
        | CoreHibpReason::ResponseLimit
        | CoreHibpReason::NetworkUnavailable => status.is_none(),
        CoreHibpReason::SelfAuditAuthorizationRequired
        | CoreHibpReason::DirectTransmissionAuthorizationRequired => last_request.is_none(),
        _ => true,
    };
    if !valid {
        return Err(CoreError::InvalidHibpResponse);
    }
    Ok(())
}

fn validate_investigation_plan_request(
    request: &CoreInvestigationPlanRequest,
) -> Result<InvestigationPlanBinding, CoreError> {
    if !(1..=MAX_INVESTIGATION_IDENTIFIERS).contains(&request.identifiers.len())
        || request.enabled_providers.is_empty()
        || request.enabled_providers.len() > 3
    {
        return Err(CoreError::InvalidInvestigationPlanRequest);
    }
    let providers: HashSet<_> = request.enabled_providers.iter().copied().collect();
    if providers.len() != request.enabled_providers.len() {
        return Err(CoreError::InvalidInvestigationPlanRequest);
    }
    let mut references = HashSet::with_capacity(request.identifiers.len());
    let mut identities = HashSet::with_capacity(request.identifiers.len());
    let mut identifier_hashes = Vec::with_capacity(request.identifiers.len());
    for identifier in &request.identifiers {
        if !is_investigation_identifier_ref(&identifier.identifier_ref)
            || !is_canonical_investigation_value(identifier.kind, identifier.value.as_str())
            || !references.insert(identifier.identifier_ref.as_str())
            || !identities.insert((identifier.kind, identifier.value.as_str()))
        {
            return Err(CoreError::InvalidInvestigationPlanRequest);
        }
        identifier_hashes.push(sha256_lower_hex(identifier.value.as_bytes()));
    }

    let plan_id = deterministic_investigation_plan_id(request, &identifier_hashes);
    if !request.authorized_self_audit {
        return Ok(InvestigationPlanBinding {
            plan_id,
            steps: Vec::new(),
            notices: vec![CoreInvestigationNotice::SelfAuditAuthorizationRequired],
            authorization_confirmed: false,
        });
    }

    let mut steps = Vec::new();
    let mut notices = Vec::new();
    for (identifier, identifier_sha256) in request.identifiers.iter().zip(identifier_hashes.iter())
    {
        if providers.contains(&CoreInvestigationProvider::DuckduckgoHtml) {
            push_investigation_step(
                &mut steps,
                identifier,
                identifier_sha256,
                InvestigationStepTemplate {
                    provider: CoreInvestigationProvider::DuckduckgoHtml,
                    operation: CoreInvestigationOperation::PublicWebSearch,
                    execution_route: "/v1/discovery/public/search",
                    transmission: CoreInvestigationTransmission::DirectPublicQuery,
                    prerequisites: &[CoreInvestigationPrerequisite::ExplicitSelfAuditAuthorization],
                },
            );
        }
        if identifier.kind == CoreInvestigationIdentifierKind::Username
            && providers.contains(&CoreInvestigationProvider::GithubUsers)
        {
            push_investigation_step(
                &mut steps,
                identifier,
                identifier_sha256,
                InvestigationStepTemplate {
                    provider: CoreInvestigationProvider::GithubUsers,
                    operation: CoreInvestigationOperation::GithubUserSearch,
                    execution_route: "/v1/discovery/public/search",
                    transmission: CoreInvestigationTransmission::DirectPublicQuery,
                    prerequisites: &[CoreInvestigationPrerequisite::ExplicitSelfAuditAuthorization],
                },
            );
        }
        if !providers.contains(&CoreInvestigationProvider::HaveIBeenPwnedV3)
            || !matches!(
                identifier.kind,
                CoreInvestigationIdentifierKind::Email | CoreInvestigationIdentifierKind::Domain
            )
        {
            continue;
        }
        if !request.hibp_api_key_available {
            push_investigation_notice(&mut notices, CoreInvestigationNotice::HibpApiKeyRequired);
            continue;
        }
        if identifier.kind == CoreInvestigationIdentifierKind::Domain {
            push_investigation_step(
                &mut steps,
                identifier,
                identifier_sha256,
                InvestigationStepTemplate {
                    provider: CoreInvestigationProvider::HaveIBeenPwnedV3,
                    operation: CoreInvestigationOperation::HibpVerifiedDomainEnumeration,
                    execution_route: "/v1/discovery/hibp/domain",
                    transmission: CoreInvestigationTransmission::ProviderVerifiedDomain,
                    prerequisites: &[
                        CoreInvestigationPrerequisite::ExplicitSelfAuditAuthorization,
                        CoreInvestigationPrerequisite::HibpApiKey,
                        CoreInvestigationPrerequisite::ProviderVerifiedDomain,
                    ],
                },
            );
        } else if request.hibp_k_anonymity_available {
            push_investigation_step(
                &mut steps,
                identifier,
                identifier_sha256,
                InvestigationStepTemplate {
                    provider: CoreInvestigationProvider::HaveIBeenPwnedV3,
                    operation: CoreInvestigationOperation::HibpEmailKAnonymity,
                    execution_route: "/v1/discovery/hibp/account",
                    transmission: CoreInvestigationTransmission::PartialSha1Prefix,
                    prerequisites: &[
                        CoreInvestigationPrerequisite::ExplicitSelfAuditAuthorization,
                        CoreInvestigationPrerequisite::HibpApiKey,
                        CoreInvestigationPrerequisite::HibpKAnonymitySubscription,
                    ],
                },
            );
        } else if request.authorized_direct_email_transmission {
            push_investigation_step(
                &mut steps,
                identifier,
                identifier_sha256,
                InvestigationStepTemplate {
                    provider: CoreInvestigationProvider::HaveIBeenPwnedV3,
                    operation: CoreInvestigationOperation::HibpEmailDirect,
                    execution_route: "/v1/discovery/hibp/account",
                    transmission: CoreInvestigationTransmission::DirectEmail,
                    prerequisites: &[
                        CoreInvestigationPrerequisite::ExplicitSelfAuditAuthorization,
                        CoreInvestigationPrerequisite::HibpApiKey,
                        CoreInvestigationPrerequisite::DirectIdentifierTransmissionAuthorization,
                    ],
                },
            );
        } else {
            push_investigation_notice(
                &mut notices,
                CoreInvestigationNotice::HibpEmailModeNotAuthorized,
            );
        }
    }
    if steps.len() > MAX_INVESTIGATION_STEPS {
        return Err(CoreError::InvalidInvestigationPlanRequest);
    }
    Ok(InvestigationPlanBinding {
        plan_id,
        steps,
        notices,
        authorization_confirmed: true,
    })
}

fn validate_investigation_plan_result(
    result: &CoreInvestigationPlanResult,
    binding: &InvestigationPlanBinding,
) -> Result<(), CoreError> {
    if result.plan_id != binding.plan_id
        || result.steps != binding.steps
        || result.notices != binding.notices
        || result.authorization_confirmed != binding.authorization_confirmed
        || !result.deterministic
        || result.executed
        || result.steps.len() > MAX_INVESTIGATION_STEPS
        || result.notices.len() > 3
    {
        return Err(CoreError::InvalidInvestigationPlanResponse);
    }
    Ok(())
}

fn push_investigation_step(
    steps: &mut Vec<CoreInvestigationPlanStep>,
    identifier: &super::contract::CoreInvestigationIdentifierInput,
    identifier_sha256: &str,
    template: InvestigationStepTemplate<'_>,
) {
    let sequence = u8::try_from(steps.len() + 1).expect("investigation step bound fits in u8");
    steps.push(CoreInvestigationPlanStep {
        step_id: format!("step-{sequence:03}"),
        identifier_ref: identifier.identifier_ref.clone(),
        identifier_kind: identifier.kind,
        identifier_sha256: identifier_sha256.to_owned(),
        provider: template.provider,
        operation: template.operation,
        execution_route: template.execution_route.to_owned(),
        transmission: template.transmission,
        prerequisites: template.prerequisites.to_vec(),
        sequence,
        executes_during_compilation: false,
        human_review_required: true,
    });
}

fn push_investigation_notice(
    notices: &mut Vec<CoreInvestigationNotice>,
    notice: CoreInvestigationNotice,
) {
    if !notices.contains(&notice) {
        notices.push(notice);
    }
}

fn deterministic_investigation_plan_id(
    request: &CoreInvestigationPlanRequest,
    identifier_hashes: &[String],
) -> String {
    let identifiers = request
        .identifiers
        .iter()
        .zip(identifier_hashes)
        .map(|(identifier, digest)| {
            format!(
                "{{\"kind\":{},\"ref\":{},\"sha256\":{}}}",
                serde_json::to_string(investigation_kind_wire(identifier.kind))
                    .expect("static investigation kind is JSON-safe"),
                serde_json::to_string(&identifier.identifier_ref)
                    .expect("validated investigation reference is JSON-safe"),
                serde_json::to_string(digest).expect("SHA-256 is JSON-safe")
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let mut providers = request
        .enabled_providers
        .iter()
        .map(|provider| investigation_provider_wire(*provider))
        .collect::<Vec<_>>();
    providers.sort_unstable();
    let providers = providers
        .iter()
        .map(|provider| serde_json::to_string(provider).expect("static provider is JSON-safe"))
        .collect::<Vec<_>>()
        .join(",");
    let canonical = format!(
        "{{\"authorized\":{},\"directEmail\":{},\"hibpKAnon\":{},\"hibpKey\":{},\"identifiers\":[{}],\"providers\":[{}]}}",
        request.authorized_self_audit,
        request.authorized_direct_email_transmission,
        request.hibp_k_anonymity_available,
        request.hibp_api_key_available,
        identifiers,
        providers,
    );
    format!("plan-{}", &sha256_lower_hex(canonical.as_bytes())[..24])
}

const fn investigation_kind_wire(kind: CoreInvestigationIdentifierKind) -> &'static str {
    match kind {
        CoreInvestigationIdentifierKind::Email => "EMAIL",
        CoreInvestigationIdentifierKind::Username => "USERNAME",
        CoreInvestigationIdentifierKind::Domain => "DOMAIN",
        CoreInvestigationIdentifierKind::Name => "NAME",
        CoreInvestigationIdentifierKind::Url => "URL",
    }
}

const fn investigation_provider_wire(provider: CoreInvestigationProvider) -> &'static str {
    match provider {
        CoreInvestigationProvider::DuckduckgoHtml => "DUCKDUCKGO_HTML",
        CoreInvestigationProvider::GithubUsers => "GITHUB_USERS",
        CoreInvestigationProvider::HaveIBeenPwnedV3 => "HAVE_I_BEEN_PWNED_V3",
    }
}

fn is_investigation_identifier_ref(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value.is_ascii()
        && value
            .bytes()
            .next()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn is_canonical_investigation_value(kind: CoreInvestigationIdentifierKind, value: &str) -> bool {
    if value.is_empty()
        || value.len() > 1_024
        || value.chars().any(char::is_control)
        || value.trim() != value
    {
        return false;
    }
    match kind {
        CoreInvestigationIdentifierKind::Email => is_canonical_hibp_email(value),
        CoreInvestigationIdentifierKind::Domain => is_canonical_hibp_domain(value),
        CoreInvestigationIdentifierKind::Username => {
            value.chars().count() <= 128 && !value.chars().any(char::is_whitespace)
        }
        CoreInvestigationIdentifierKind::Name => {
            value.chars().count() <= 256
                && value.split_whitespace().collect::<Vec<_>>().join(" ") == value
        }
        CoreInvestigationIdentifierKind::Url => {
            if !is_safe_public_discovery_url(value) {
                return false;
            }
            reqwest::Url::parse(value).is_ok_and(|parsed| parsed.as_str() == value)
        }
    }
}

fn is_valid_hibp_api_key(value: &str) -> bool {
    value.len() == 32 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn is_canonical_hibp_email(value: &str) -> bool {
    if !(3..=254).contains(&value.len())
        || !value.is_ascii()
        || value != value.to_ascii_lowercase()
        || value
            .chars()
            .any(|character| character.is_whitespace() || character.is_control())
    {
        return false;
    }
    let mut parts = value.split('@');
    let Some(local) = parts.next() else {
        return false;
    };
    let Some(domain) = parts.next() else {
        return false;
    };
    parts.next().is_none()
        && !local.is_empty()
        && local.len() <= 64
        && !local.starts_with('.')
        && !local.ends_with('.')
        && !local.contains("..")
        && is_canonical_hibp_domain(domain)
}

fn is_canonical_hibp_domain(value: &str) -> bool {
    if !(3..=253).contains(&value.len())
        || !value.is_ascii()
        || value != value.to_ascii_lowercase()
        || value.starts_with('.')
        || value.ends_with('.')
    {
        return false;
    }
    let labels = value.split('.').collect::<Vec<_>>();
    labels.len() >= 2
        && labels.iter().all(|label| {
            (1..=63).contains(&label.len())
                && label
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
                && label
                    .bytes()
                    .next()
                    .is_some_and(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
                && label
                    .bytes()
                    .last()
                    .is_some_and(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        })
}

fn is_bounded_rfc3339(value: &str) -> bool {
    if !(20..=35).contains(&value.len()) || !value.is_ascii() {
        return false;
    }
    let bytes = value.as_bytes();
    if bytes.get(4) != Some(&b'-')
        || bytes.get(7) != Some(&b'-')
        || bytes.get(10) != Some(&b'T')
        || bytes.get(13) != Some(&b':')
        || bytes.get(16) != Some(&b':')
        || !bytes[..4].iter().all(u8::is_ascii_digit)
        || !bytes[5..7].iter().all(u8::is_ascii_digit)
        || !bytes[8..10].iter().all(u8::is_ascii_digit)
        || !bytes[11..13].iter().all(u8::is_ascii_digit)
        || !bytes[14..16].iter().all(u8::is_ascii_digit)
        || !bytes[17..19].iter().all(u8::is_ascii_digit)
    {
        return false;
    }
    value.ends_with('Z')
        || value
            .get(19..)
            .is_some_and(|suffix| suffix.contains('+') || suffix.contains('-'))
}

fn percent_encode_path_segment(value: &[u8]) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(*byte));
        } else {
            encoded.push('%');
            encoded.push(char::from(b"0123456789ABCDEF"[usize::from(byte >> 4)]));
            encoded.push(char::from(b"0123456789ABCDEF"[usize::from(byte & 0x0f)]));
        }
    }
    encoded
}

fn hibp_sha1_prefix(value: &[u8]) -> String {
    let mut message = Zeroizing::new(value.to_vec());
    let bit_length = u64::try_from(message.len()).unwrap_or(u64::MAX) * 8;
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_length.to_be_bytes());

    let mut state = [
        0x6745_2301_u32,
        0xefcd_ab89,
        0x98ba_dcfe,
        0x1032_5476,
        0xc3d2_e1f0,
    ];
    for chunk in message.chunks_exact(64) {
        let mut words = [0_u32; 80];
        for (index, bytes) in chunk.chunks_exact(4).enumerate() {
            words[index] = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        }
        for index in 16..80 {
            words[index] =
                (words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16])
                    .rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = state;
        for (index, word) in words.iter().enumerate() {
            let (function, constant) = match index {
                0..=19 => ((b & c) | ((!b) & d), 0x5a82_7999),
                20..=39 => (b ^ c ^ d, 0x6ed9_eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1b_bcdc),
                _ => (b ^ c ^ d, 0xca62_c1d6),
            };
            let temporary = a
                .rotate_left(5)
                .wrapping_add(function)
                .wrapping_add(e)
                .wrapping_add(constant)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temporary;
        }
        state[0] = state[0].wrapping_add(a);
        state[1] = state[1].wrapping_add(b);
        state[2] = state[2].wrapping_add(c);
        state[3] = state[3].wrapping_add(d);
        state[4] = state[4].wrapping_add(e);
    }
    format!("{:08X}", state[0])[..6].to_owned()
}

fn is_safe_public_discovery_url(value: &str) -> bool {
    if !is_safe_bounded_text(value, 8, 2_048) || value.chars().any(char::is_whitespace) {
        return false;
    }
    let Ok(parsed) = reqwest::Url::parse(value) else {
        return false;
    };
    if !matches!(parsed.scheme(), "http" | "https")
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.fragment().is_some()
    {
        return false;
    }
    let Some(host) = parsed.host_str() else {
        return false;
    };
    let hostname = host
        .trim_matches(['[', ']'])
        .trim_end_matches('.')
        .to_ascii_lowercase();
    if matches!(hostname.as_str(), "localhost" | "localhost.localdomain")
        || hostname.ends_with(".localhost")
        || hostname.ends_with(".local")
        || hostname.ends_with(".internal")
        || hostname.ends_with(".lan")
        || hostname
            .split('.')
            .any(|label| label.is_empty() || label.starts_with("0x"))
    {
        return false;
    }
    hostname
        .parse::<IpAddr>()
        .map_or_else(|_| hostname.contains('.'), is_public_phase5_ip)
}

fn workspace_text_list_is_valid(values: &[String], maximum: usize, text_maximum: usize) -> bool {
    if values.len() > maximum {
        return false;
    }
    let mut unique = HashSet::with_capacity(values.len());
    values.iter().all(|value| {
        unique.insert(value.as_str()) && is_safe_workspace_text(value, 1, text_maximum)
    })
}

fn workspace_refs_are_valid(values: &[String], minimum: usize, maximum: usize) -> bool {
    if values.len() < minimum || values.len() > maximum {
        return false;
    }
    let mut unique = HashSet::with_capacity(values.len());
    values
        .iter()
        .all(|value| unique.insert(value.as_str()) && is_workspace_ref(value))
}

fn is_workspace_ref(value: &str) -> bool {
    is_safe_bounded_text(value, 1, 160) && !value.chars().any(char::is_whitespace)
}

fn is_safe_workspace_text(value: &str, minimum: usize, maximum: usize) -> bool {
    let count = value.chars().count();
    count >= minimum
        && count <= maximum
        && value.trim() == value
        && !value
            .chars()
            .any(|character| character.is_control() && !matches!(character, '\n' | '\r' | '\t'))
}

fn is_loopback_http_endpoint(value: &str) -> bool {
    if value.is_empty()
        || value.len() > 256
        || value.trim() != value
        || value.chars().any(char::is_control)
    {
        return false;
    }
    let Ok(endpoint) = reqwest::Url::parse(value) else {
        return false;
    };
    if endpoint.scheme() != "http"
        || !endpoint.username().is_empty()
        || endpoint.password().is_some()
        || endpoint.path() != "/"
        || endpoint.query().is_some()
        || endpoint.fragment().is_some()
    {
        return false;
    }
    endpoint.host_str().is_some_and(|host| {
        host.eq_ignore_ascii_case("localhost")
            || host
                .parse::<IpAddr>()
                .is_ok_and(|address| address.is_loopback())
    })
}

fn is_local_model_id(value: &str) -> bool {
    is_safe_bounded_text(value, 1, 256)
}

fn validate_paste_intake_request(request: &CorePasteIntakeRequest) -> Result<(), CoreError> {
    validate_idempotency_key(&request.idempotency_key)?;
    let character_count = request.content.chars().count();
    if !request.consent_confirmed
        || !is_safe_bounded_text(&request.display_name, 1, 128)
        || character_count == 0
        || character_count > MAX_PASTED_TEXT_CHARACTERS
    {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_file_intake_request(request: &CoreFileIntakeRequest) -> Result<(), CoreError> {
    validate_idempotency_key(&request.idempotency_key)?;
    if !request.consent_confirmed
        || !is_safe_bounded_text(&request.display_name, 1, 255)
        || request.display_name.chars().any(is_bidi_control)
        || !is_supported_media_type(&request.declared_media_type)
        || !selected_file_name_matches_media(&request.display_name, &request.declared_media_type)
        || request.expected_size_bytes == 0
        || request.expected_size_bytes > MAX_PHASE3_FILE_BYTES
    {
        return Err(CoreError::InvalidPhase3Request);
    }

    let expected_encoded_bytes = request.expected_size_bytes.div_ceil(3) * 4;
    if request.content_base64.len() != expected_encoded_bytes
        || request.content_base64.len() > MAX_PHASE3_FILE_BASE64_BYTES
    {
        return Err(CoreError::InvalidPhase3File);
    }
    let decoded = Zeroizing::new(
        STANDARD
            .decode(request.content_base64.as_bytes())
            .map_err(|_| CoreError::InvalidPhase3File)?,
    );
    if decoded.len() != request.expected_size_bytes {
        return Err(CoreError::InvalidPhase3File);
    }
    let expected_digest =
        decode_lower_hex_digest(&request.expected_sha256).ok_or(CoreError::InvalidPhase3File)?;
    let actual_digest = Sha256::digest(decoded.as_slice());
    if actual_digest[..] != expected_digest {
        return Err(CoreError::InvalidPhase3File);
    }
    Ok(())
}

fn validate_entity_review_request(request: &CoreEntityReviewRequest) -> Result<(), CoreError> {
    if request.limit == 0 || usize::from(request.limit) > MAX_REVIEW_ENTITIES {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_entity_origin_page_request(
    request: &CoreEntityOriginPageRequest,
) -> Result<(), CoreError> {
    if !is_rfc4122_uuid(request.profile_id)
        || !is_rfc4122_uuid(request.entity_id)
        || request.offset > MAX_ENTITY_ORIGIN_OFFSET
        || request.limit == 0
        || usize::from(request.limit) > MAX_ENTITY_ORIGIN_PAGE_SIZE
        || usize::from(request.limit) > MAX_ENTITY_ORIGINS
    {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_entity_decision_request(request: &CoreEntityDecisionRequest) -> Result<(), CoreError> {
    validate_idempotency_key(&request.idempotency_key)?;
    if request.expected_revision == 0
        || request.expected_revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || request
            .reason
            .as_deref()
            .is_some_and(|reason| !is_safe_bounded_text(reason, 1, 240))
    {
        return Err(CoreError::InvalidPhase3Request);
    }
    let review_matches = match request.decision_type {
        CoreEntityDecisionType::Confirm => request.review_state == CoreReviewState::Confirmed,
        CoreEntityDecisionType::Reject => request.review_state == CoreReviewState::FalsePositive,
        CoreEntityDecisionType::Exclude => request.review_state == CoreReviewState::Excluded,
        CoreEntityDecisionType::Classify => matches!(
            request.review_state,
            CoreReviewState::Probable | CoreReviewState::Possible
        ),
        CoreEntityDecisionType::PolicyChange => true,
    };
    let restricted_policy_is_safe = request.sensitivity != CoreSensitivity::HighlySensitive
        || (request.search_policy != CoreSearchPolicy::Allow
            && request.transmission_policy != CoreTransmissionPolicy::PolicyControlled);
    let excluded_policy_is_safe = !matches!(
        request.review_state,
        CoreReviewState::FalsePositive | CoreReviewState::Excluded
    ) || (request.search_policy == CoreSearchPolicy::Deny
        && request.transmission_policy == CoreTransmissionPolicy::Never);
    if !review_matches || !restricted_policy_is_safe || !excluded_policy_is_safe {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_graph_snapshot_request(request: &CoreGraphSnapshotRequest) -> Result<(), CoreError> {
    if request.max_nodes == 0 || usize::from(request.max_nodes) > MAX_GRAPH_NODES {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn validate_profile_summary(profile: &CoreProfileSummary) -> Result<(), CoreError> {
    if profile.revision == 0
        || profile.revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_safe_bounded_text(&profile.display_label, 1, 80)
        || !is_safe_bounded_text(&profile.purpose, 1, 240)
        || !matches!(
            profile.status.as_str(),
            "DRAFT" | "ACTIVE" | "ARCHIVED" | "PURGE_PENDING"
        )
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    Ok(())
}

fn validate_profile_list_result(result: &CoreProfileListResult) -> Result<(), CoreError> {
    if result.profiles.len() > MAX_PROFILES {
        return Err(CoreError::InvalidPhase3Response);
    }
    let mut profile_ids = HashSet::with_capacity(result.profiles.len());
    for profile in &result.profiles {
        validate_profile_summary(profile)?;
        if !profile_ids.insert(profile.profile_id) {
            return Err(CoreError::InvalidPhase3Response);
        }
    }
    Ok(())
}

fn validate_profile_delete_result(
    result: &CoreProfileDeleteResult,
    profile_id: Uuid,
) -> Result<(), CoreError> {
    if result.profile_id != profile_id || result.deleted_rows == 0 {
        return Err(CoreError::InvalidPhase3Response);
    }
    Ok(())
}

fn validate_intake_receipt(
    receipt: &CoreIntakeReceipt,
    profile_id: Uuid,
    source_kind: &str,
) -> Result<(), CoreError> {
    let counts = [
        receipt.segment_count,
        receipt.candidate_count,
        receipt.duplicate_count,
        receipt.quarantine_count,
    ];
    let enrichment_attempted = !matches!(
        receipt.local_ai_status,
        CoreLocalAiIntakeStatus::NotRequested | CoreLocalAiIntakeStatus::Disabled
    );
    let enrichment_identity_present = receipt.local_ai_provider.is_some()
        && receipt.local_ai_model.is_some()
        && receipt.local_ai_engine_version.is_some();
    let suggestion_count_valid = receipt.local_ai_suggestion_count <= 64
        && (receipt.local_ai_status == CoreLocalAiIntakeStatus::Succeeded
            || receipt.local_ai_suggestion_count == 0);
    if receipt.profile_id != profile_id
        || receipt.source_kind != source_kind
        || receipt.revision == 0
        || receipt.revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || !is_bounded_event_label(&receipt.state, 32)
        || counts.into_iter().any(|count| count > 1_000_000)
        || enrichment_attempted != enrichment_identity_present
        || receipt.local_ai_provider == Some(CoreLocalAiProvider::OpenaiResponses)
        || !suggestion_count_valid
        || receipt
            .local_ai_model
            .as_ref()
            .is_some_and(|model| !is_safe_bounded_text(model, 1, 256))
        || receipt
            .local_ai_engine_version
            .as_ref()
            .is_some_and(|version| !is_safe_bounded_text(version, 1, 48))
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    Ok(())
}

fn validate_entity_review_result(
    result: &CoreEntityReviewResult,
    profile_id: Uuid,
    limit: usize,
) -> Result<(), CoreError> {
    if result.profile_id != profile_id
        || result.entities.len() > limit
        || result.entities.len() > MAX_REVIEW_ENTITIES
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    let mut identifiers = HashSet::with_capacity(result.entities.len());
    for entity in &result.entities {
        if !identifiers.insert(entity.entity_id) {
            return Err(CoreError::InvalidPhase3Response);
        }
        validate_entity_summary(entity)?;
    }
    Ok(())
}

fn validate_entity_origin_page_result(
    result: &CoreEntityOriginPageResult,
    profile_id: Uuid,
    entity_id: Uuid,
    offset: u32,
    limit: u8,
) -> Result<(), CoreError> {
    let next_offset = u64::from(result.offset)
        .checked_add(result.origins.len() as u64)
        .ok_or(CoreError::InvalidPhase3Response)?;
    if result.profile_id != profile_id
        || result.entity_id != entity_id
        || result.offset != offset
        || result.limit != limit
        || result.offset > MAX_ENTITY_ORIGIN_OFFSET
        || result.limit == 0
        || usize::from(result.limit) > MAX_ENTITY_ORIGIN_PAGE_SIZE
        || result.origins.len() > usize::from(result.limit)
        || result.origins.len() > MAX_ENTITY_ORIGIN_PAGE_SIZE
        || result.total > MAX_SAFE_JAVASCRIPT_INTEGER
        || (u64::from(result.offset) < result.total && result.origins.is_empty())
        || (!result.origins.is_empty() && next_offset > result.total)
        || result.has_more != (next_offset < result.total)
    {
        return Err(CoreError::InvalidPhase3Response);
    }

    let mut origin_keys = HashSet::with_capacity(result.origins.len());
    for origin in &result.origins {
        let key = (
            origin.source_id,
            origin.segment_id,
            origin.source_span_start,
            origin.source_span_end,
            origin.extraction_run_id,
            origin.origin_kind.as_str(),
        );
        if !origin_keys.insert(key) {
            return Err(CoreError::InvalidPhase3Response);
        }
        validate_entity_origin(origin)?;
    }
    if result.origins.windows(2).any(|pair| {
        pair[0].confidence_micros < pair[1].confidence_micros
            || (pair[0].confidence_micros == pair[1].confidence_micros
                && pair[0].observed_at_us > pair[1].observed_at_us)
    }) {
        return Err(CoreError::InvalidPhase3Response);
    }
    Ok(())
}

fn validate_entity_summary(entity: &CoreEntitySummary) -> Result<(), CoreError> {
    if entity.revision == 0
        || entity.revision > MAX_SAFE_JAVASCRIPT_INTEGER
        || entity.confidence_micros > 1_000_000
        || !is_bounded_event_label(&entity.entity_type, 64)
        || !is_safe_bounded_text(&entity.display_value, 1, 512)
        || !is_safe_bounded_text(&entity.provenance_label, 1, 160)
        || entity.origins.is_empty()
        || entity.origins.len() > MAX_ENTITY_ORIGINS
        || entity.origins_truncated && entity.origins.len() != MAX_ENTITY_ORIGINS
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    let mut origin_keys = HashSet::with_capacity(entity.origins.len());
    for origin in &entity.origins {
        let key = (
            origin.source_id,
            origin.segment_id,
            origin.source_span_start,
            origin.source_span_end,
            origin.extraction_run_id,
            origin.origin_kind.as_str(),
        );
        if !origin_keys.insert(key) {
            return Err(CoreError::InvalidPhase3Response);
        }
        validate_entity_origin(origin)?;
    }
    Ok(())
}

fn validate_entity_origin(origin: &CoreEntityOrigin) -> Result<(), CoreError> {
    let span_is_valid = match (origin.source_span_start, origin.source_span_end) {
        (None, None) => true,
        (Some(start), Some(end)) => start < end && end <= 1_048_576,
        _ => false,
    };
    let extractor_fields = [
        origin.extraction_run_id.is_some(),
        origin.extractor_kind.is_some(),
        origin.extractor_name.is_some(),
        origin.extractor_version.is_some(),
    ];
    let extractor_is_valid = extractor_fields.iter().all(|present| *present)
        || extractor_fields.iter().all(|present| !*present);
    if !is_rfc4122_uuid(origin.source_id)
        || !is_rfc4122_uuid(origin.segment_id)
        || origin
            .extraction_run_id
            .is_some_and(|identifier| !is_rfc4122_uuid(identifier))
        || !is_safe_bounded_text(&origin.source_display_name, 1, 255)
        || decode_lower_hex_digest(&origin.source_sha256).is_none()
        || origin.segment_index > 1_000_000
        || !is_safe_bounded_text(&origin.segment_locator, 1, 16_384)
        || !span_is_valid
        || !extractor_is_valid
        || origin
            .extractor_kind
            .as_deref()
            .is_some_and(|value| !is_safe_bounded_text(value, 1, 24))
        || origin
            .extractor_name
            .as_deref()
            .is_some_and(|value| !is_safe_bounded_text(value, 1, 96))
        || origin
            .extractor_version
            .as_deref()
            .is_some_and(|value| !is_safe_bounded_text(value, 1, 48))
        || !is_safe_bounded_text(&origin.origin_kind, 1, 24)
        || origin.observed_at_us == 0
        || origin.observed_at_us > MAX_SAFE_JAVASCRIPT_INTEGER
        || origin.confidence_micros > 1_000_000
        || !is_safe_bounded_text(&origin.explanation, 1, 2_048)
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    Ok(())
}

fn validate_graph_snapshot(
    snapshot: &CoreGraphSnapshot,
    profile_id: Uuid,
    max_nodes: usize,
) -> Result<(), CoreError> {
    if snapshot.profile_id != profile_id
        || snapshot.nodes.len() > max_nodes
        || snapshot.nodes.len() > MAX_GRAPH_NODES
        || snapshot.edges.len() > MAX_GRAPH_EDGES
        || snapshot
            .edges
            .iter()
            .try_fold(0_usize, |total, edge| {
                total.checked_add(edge.evidence.len())
            })
            .is_none_or(|count| count > MAX_GRAPH_EVIDENCE)
    {
        return Err(CoreError::InvalidPhase3Response);
    }
    let mut node_ids = HashSet::with_capacity(snapshot.nodes.len());
    for node in &snapshot.nodes {
        if !node_ids.insert(node.node_id)
            || !is_bounded_event_label(&node.node_type, 64)
            || !is_safe_bounded_text(&node.display_label, 1, 512)
        {
            return Err(CoreError::InvalidPhase3Response);
        }
    }
    let mut edge_ids = HashSet::with_capacity(snapshot.edges.len());
    for edge in &snapshot.edges {
        let included_support = edge
            .evidence
            .iter()
            .filter(|evidence| evidence.disposition == CoreGraphEvidenceDisposition::Supports)
            .count();
        let included_contradictions = edge.evidence.len() - included_support;
        let total_evidence = u64::from(edge.support_count) + u64::from(edge.contradiction_count);
        if !edge_ids.insert(edge.edge_id)
            || !node_ids.contains(&edge.from_node_id)
            || !node_ids.contains(&edge.to_node_id)
            || edge.from_node_id == edge.to_node_id
            || edge.confidence_micros > 1_000_000
            || !is_bounded_event_label(&edge.edge_type, 64)
            || !is_bounded_event_label(&edge.origin_type, 64)
            || !is_safe_bounded_text(&edge.explanation, 1, 2_048)
            || total_evidence == 0
            || edge.evidence.is_empty()
            || edge.evidence.len() > MAX_GRAPH_EDGE_EVIDENCE
            || usize::try_from(edge.support_count)
                .ok()
                .is_none_or(|count| count < included_support)
            || usize::try_from(edge.contradiction_count)
                .ok()
                .is_none_or(|count| count < included_contradictions)
            || edge.evidence_truncated != (total_evidence > edge.evidence.len() as u64)
        {
            return Err(CoreError::InvalidPhase3Response);
        }
        for evidence in &edge.evidence {
            let valid_span = match (evidence.source_span_start, evidence.source_span_end) {
                (None, None) => true,
                (Some(start), Some(end)) => end > start,
                _ => false,
            };
            if !valid_span
                || evidence.confidence_micros > 1_000_000
                || evidence.observed_at_us == 0
                || evidence.observed_at_us > MAX_SAFE_JAVASCRIPT_INTEGER
                || !is_bounded_event_label(&evidence.origin_type, 64)
                || !is_safe_bounded_text(&evidence.explanation, 1, 160)
            {
                return Err(CoreError::InvalidPhase3Response);
            }
        }
    }
    Ok(())
}

fn validate_idempotency_key(value: &str) -> Result<(), CoreError> {
    if !is_safe_bounded_text(value, 16, 256)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return Err(CoreError::InvalidPhase3Request);
    }
    Ok(())
}

fn is_safe_bounded_text(value: &str, minimum: usize, maximum: usize) -> bool {
    let length = value.chars().count();
    length >= minimum
        && length <= maximum
        && value.trim() == value
        && !value.chars().any(char::is_control)
}

const fn is_bidi_control(character: char) -> bool {
    matches!(
        character,
        '\u{061c}'
            | '\u{200e}'
            | '\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2066}'..='\u{2069}'
    )
}

fn is_supported_media_type(value: &str) -> bool {
    if value.len() > 64 || !value.is_ascii() {
        return false;
    }
    let mut components = value
        .split(';')
        .map(|component| component.trim().to_ascii_lowercase());
    let Some(media_type) = components.next() else {
        return false;
    };
    if !matches!(
        media_type.as_str(),
        "text/plain"
            | "text/markdown"
            | "text/x-markdown"
            | "text/csv"
            | "application/json"
            | "text/vcard"
            | "text/x-vcard"
    ) {
        return false;
    }
    components.all(|parameter| {
        let Some((name, value)) = parameter.split_once('=') else {
            return false;
        };
        name.trim() == "charset" && matches!(value.trim().trim_matches('"'), "utf-8" | "utf8")
    })
}

fn selected_file_name_matches_media(display_name: &str, declared_media_type: &str) -> bool {
    if matches!(display_name, "." | "..")
        || display_name.contains(['/', '\\'])
        || display_name.starts_with('.')
    {
        return false;
    }
    let Some((_, extension)) = display_name.rsplit_once('.') else {
        return false;
    };
    let media_type = declared_media_type
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    match extension.to_ascii_lowercase().as_str() {
        "txt" => media_type == "text/plain",
        "md" => matches!(media_type.as_str(), "text/markdown" | "text/x-markdown"),
        "csv" => media_type == "text/csv",
        "json" => media_type == "application/json",
        "vcf" => matches!(media_type.as_str(), "text/vcard" | "text/x-vcard"),
        _ => false,
    }
}

fn decode_lower_hex_digest(value: &str) -> Option<[u8; 32]> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return None;
    }
    let mut decoded = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        decoded[index] = (hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?;
    }
    Some(decoded)
}

const fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn validate_unlocked_response(
    response: &CoreVaultLifecycleResult,
    expected_vault_id: Uuid,
) -> Result<(), CoreError> {
    if response.vault_id != expected_vault_id
        || response.lock_state != SessionLockState::Unlocked
        || response.vault_state != VaultState::Unlocked
    {
        return Err(CoreError::InvalidVaultResponse);
    }
    Ok(())
}

fn validate_event_replay(response: &EventReplayResult) -> Result<(), CoreError> {
    if response.events.len() > 32 || (response.events.is_empty() && response.has_more) {
        return Err(CoreError::InvalidEventResponse);
    }
    if let Some(last) = response.events.last()
        && response.next_cursor != Some(last.event_id)
    {
        return Err(CoreError::InvalidEventResponse);
    }
    let mut identifiers = HashSet::with_capacity(response.events.len());
    for event in &response.events {
        if event.sequence == 0
            || !identifiers.insert(event.event_id)
            || !is_bounded_event_label(&event.event_type, 96)
            || event
                .resource_type
                .as_deref()
                .is_some_and(|value| !is_bounded_event_label(value, 64))
            || event.resource_revision == Some(0)
        {
            return Err(CoreError::InvalidEventResponse);
        }
    }
    for pair in response.events.windows(2) {
        if pair[0].sequence.checked_add(1) != Some(pair[1].sequence) {
            return Err(CoreError::InvalidEventResponse);
        }
    }
    Ok(())
}

fn is_bounded_event_label(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value.as_bytes()[0].is_ascii_uppercase()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
}

impl RuntimeMode {
    const fn current() -> Self {
        if cfg!(debug_assertions) {
            Self::Development
        } else {
            Self::Packaged
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum CoreEndpoint {
    Loopback {
        port: u16,
    },
    #[cfg(unix)]
    UnixSocket {
        path: PathBuf,
    },
}

impl CoreEndpoint {
    fn from_readiness(readiness: ReadinessMessage, mode: RuntimeMode) -> Result<Self, CoreError> {
        if readiness.status != "ready" {
            return Err(CoreError::InvalidReadiness("sidecar did not report ready"));
        }
        if readiness.contract_version != CONTRACT_VERSION {
            return Err(CoreError::ContractVersionMismatch {
                expected: CONTRACT_VERSION,
                actual: readiness.contract_version,
            });
        }

        match (mode, readiness.transport) {
            (RuntimeMode::Development, ReadinessTransport::Tcp) => {
                if readiness.host.as_deref() != Some("127.0.0.1") {
                    return Err(CoreError::InvalidReadiness(
                        "development TCP must bind to 127.0.0.1",
                    ));
                }
                if readiness.socket_path.is_some() {
                    return Err(CoreError::InvalidReadiness(
                        "development TCP readiness included a socket path",
                    ));
                }
                let port =
                    readiness
                        .port
                        .filter(|port| *port != 0)
                        .ok_or(CoreError::InvalidReadiness(
                            "development TCP readiness omitted a valid port",
                        ))?;
                Ok(Self::Loopback { port })
            }
            (RuntimeMode::Packaged, ReadinessTransport::Tcp) => {
                Err(CoreError::PackagedTcpForbidden)
            }
            #[cfg(unix)]
            (RuntimeMode::Packaged, ReadinessTransport::Uds) => {
                if readiness.host.is_some() || readiness.port.is_some() {
                    return Err(CoreError::InvalidReadiness(
                        "packaged UDS readiness included TCP fields",
                    ));
                }
                let path = PathBuf::from(readiness.socket_path.ok_or(
                    CoreError::InvalidReadiness("packaged UDS readiness omitted socket_path"),
                )?);
                validate_private_unix_socket(&path)?;
                Ok(Self::UnixSocket { path })
            }
            (RuntimeMode::Development, ReadinessTransport::Uds) => Err(
                CoreError::InvalidReadiness("development sidecar must use loopback TCP"),
            ),
            #[cfg(not(unix))]
            (RuntimeMode::Packaged, ReadinessTransport::Uds) => {
                Err(CoreError::PackagedSidecarUnavailable)
            }
        }
    }

    fn build_client(&self) -> Result<Client, CoreError> {
        let builder = Client::builder()
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .redirect(Policy::none())
            .no_proxy();

        #[cfg(unix)]
        let builder = match self {
            Self::Loopback { .. } => builder,
            Self::UnixSocket { path } => builder.unix_socket(path.as_path()),
        };

        builder.build().map_err(CoreError::HttpClient)
    }

    fn url(&self, route: CoreRoute) -> String {
        match self {
            Self::Loopback { port } => format!("http://127.0.0.1:{port}{}", route.path()),
            #[cfg(unix)]
            Self::UnixSocket { .. } => format!("http://ariadne.local{}", route.path()),
        }
    }

    fn host_header(&self) -> String {
        match self {
            Self::Loopback { port } => format!("127.0.0.1:{port}"),
            #[cfg(unix)]
            Self::UnixSocket { .. } => "ariadne.local".to_owned(),
        }
    }

    const fn origin(&self) -> &'static str {
        match self {
            Self::Loopback { .. } => "http://127.0.0.1:1420",
            #[cfg(unix)]
            Self::UnixSocket { .. } => "tauri://localhost",
        }
    }
}

async fn request_route<T>(
    client: &Client,
    endpoint: &CoreEndpoint,
    credential: &SessionCredential,
    route: CoreRoute,
) -> Result<(Uuid, T), CoreError>
where
    T: DeserializeOwned,
{
    request_route_inner(client, endpoint, credential, route, None).await
}

async fn request_route_with_json<T, B>(
    client: &Client,
    endpoint: &CoreEndpoint,
    credential: &SessionCredential,
    route: CoreRoute,
    value: &B,
) -> Result<(Uuid, T), CoreError>
where
    T: DeserializeOwned,
    B: Serialize,
{
    let encoded = serde_json::to_vec(value).map_err(CoreError::RequestJson)?;
    let maximum = route.capability().max_request_bytes;
    if maximum == 0 || encoded.len() > maximum {
        return Err(CoreError::RequestTooLarge);
    }
    request_route_inner(client, endpoint, credential, route, Some(encoded)).await
}

async fn request_route_inner<T>(
    client: &Client,
    endpoint: &CoreEndpoint,
    credential: &SessionCredential,
    route: CoreRoute,
    request_body: Option<Vec<u8>>,
) -> Result<(Uuid, T), CoreError>
where
    T: DeserializeOwned,
{
    // Capability metadata is the single authority for method, path, size, and
    // authorization class. Even internal callers cannot widen these per request.
    let request_id = Uuid::new_v4();
    let capability = route.capability();
    let response_limit = capability.max_response_bytes.min(MAX_RESPONSE_BYTES);
    let method = Method::from_bytes(capability.method.as_bytes())
        .map_err(|_| CoreError::InternalState("generated route method is invalid"))?;
    let mut headers = HeaderMap::new();
    headers.insert(
        SESSION_HEADER,
        HeaderValue::from_str(credential.expose())
            .map_err(|_| CoreError::InternalState("generated credential is not a valid header"))?,
    );
    headers.insert(CONTRACT_HEADER, HeaderValue::from_static("1"));
    headers.insert(
        REQUEST_ID_HEADER,
        HeaderValue::from_str(&request_id.to_string())
            .map_err(|_| CoreError::InternalState("generated request ID is not a valid header"))?,
    );
    headers.insert(ORIGIN, HeaderValue::from_static(endpoint.origin()));
    headers.insert(
        HOST,
        HeaderValue::from_str(&endpoint.host_header())
            .map_err(|_| CoreError::InternalState("validated endpoint produced an invalid Host"))?,
    );
    headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
    if request_body.is_some() {
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    }

    let request_timeout = if route == CoreRoute::AnalyzeLocalAiCorpus {
        LOCAL_AI_CORPUS_REQUEST_TIMEOUT
    } else if route == CoreRoute::AnalyzeLocalAiWorkspace {
        LOCAL_AI_WORKSPACE_REQUEST_TIMEOUT
    } else if matches!(
        route,
        CoreRoute::SearchPublicDiscovery | CoreRoute::CapturePublicDiscovery
    ) {
        PUBLIC_DISCOVERY_REQUEST_TIMEOUT
    } else if matches!(
        route,
        CoreRoute::SearchHibpAccount | CoreRoute::SearchHibpDomain
    ) {
        HIBP_REQUEST_TIMEOUT
    } else if route == CoreRoute::ListPhase5Findings {
        PHASE5_LIST_REQUEST_TIMEOUT
    } else if matches!(
        route,
        CoreRoute::GetIdentityWorkspace
            | CoreRoute::UpdateIdentityPerson
            | CoreRoute::CreateIdentitySource
            | CoreRoute::CreateIdentityAudit
            | CoreRoute::GetIdentityAudit
            | CoreRoute::ExecuteIdentityAuditBatch
            | CoreRoute::ControlIdentityAudit
            | CoreRoute::DecideIdentityProposal
    ) {
        IDENTITY_REQUEST_TIMEOUT
    } else if capability.authorization_class == "USER_GESTURE_KEYCHAIN" {
        KEYCHAIN_REQUEST_TIMEOUT
    } else {
        REQUEST_TIMEOUT
    };
    let mut request = client
        .request(method, endpoint.url(route))
        .headers(headers)
        .timeout(request_timeout);
    if let Some(body) = request_body {
        request = request.body(body);
    }
    let mut response = request.send().await.map_err(CoreError::HttpRequest)?;

    let status = response.status();
    if let Some(length) = response.content_length()
        && length > response_limit as u64
    {
        return Err(CoreError::ResponseTooLarge);
    }

    let is_json = response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.starts_with("application/json"));

    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(CoreError::HttpRequest)? {
        if body.len().saturating_add(chunk.len()) > response_limit {
            return Err(CoreError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }

    if !status.is_success() {
        return Err(CoreError::HttpStatus(status));
    }
    if !is_json {
        return Err(CoreError::InvalidContentType);
    }

    let payload = serde_json::from_slice(&body).map_err(|_| CoreError::InvalidResponseJson)?;
    Ok((request_id, payload))
}

async fn read_bounded_line<R>(reader: &mut R, maximum: usize) -> Result<Vec<u8>, CoreError>
where
    R: AsyncRead + Unpin,
{
    let mut line = Vec::with_capacity(maximum.min(512));
    let mut byte = [0_u8; 1];

    loop {
        let read = reader
            .read(&mut byte)
            .await
            .map_err(CoreError::ReadinessRead)?;
        if read == 0 {
            return Err(CoreError::ReadinessEof);
        }
        if byte[0] == b'\n' {
            return Ok(line);
        }
        if line.len() + 1 >= maximum {
            return Err(CoreError::ReadinessTooLarge);
        }
        line.push(byte[0]);
    }
}

async fn drain_stream<R>(mut stream: R)
where
    R: AsyncRead + Unpin,
{
    let mut buffer = [0_u8; 4096];
    loop {
        match stream.read(&mut buffer).await {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
    }
}

async fn terminate_child(mut child: Child) {
    child.stdin.take();
    request_child_termination(&mut child);

    if timeout(SHUTDOWN_GRACE, child.wait()).await.is_err() {
        let _ = child.kill().await;
        let _ = child.wait().await;
    }
}

fn request_child_termination(child: &mut Child) {
    #[cfg(unix)]
    if let Some(pid) = child.id() {
        // SAFETY: `pid` is the identifier returned for this direct child. SIGTERM asks
        // the sidecar to close its listener and remove its private runtime directory.
        unsafe {
            libc::kill(pid as libc::pid_t, libc::SIGTERM);
        }
    }

    #[cfg(not(unix))]
    {
        let _ = child.start_kill();
    }
}

#[cfg(unix)]
fn validate_private_unix_socket(path: &Path) -> Result<(), CoreError> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt};

    if !path.is_absolute() {
        return Err(CoreError::InvalidUds("socket path must be absolute"));
    }

    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| CoreError::InvalidUds("socket path is unavailable"))?;
    if !metadata.file_type().is_socket() {
        return Err(CoreError::InvalidUds("socket path is not a Unix socket"));
    }
    if metadata.permissions().mode() & 0o777 != 0o600 {
        return Err(CoreError::InvalidUds("socket mode must be 0600"));
    }
    // SAFETY: geteuid has no preconditions and does not mutate memory.
    if metadata.uid() != unsafe { libc::geteuid() } {
        return Err(CoreError::InvalidUds("socket is owned by another user"));
    }

    let parent = path
        .parent()
        .ok_or(CoreError::InvalidUds("socket has no parent directory"))?;
    let parent_metadata = std::fs::symlink_metadata(parent)
        .map_err(|_| CoreError::InvalidUds("socket parent is unavailable"))?;
    if !parent_metadata.file_type().is_dir()
        || parent_metadata.permissions().mode() & 0o777 != 0o700
    {
        return Err(CoreError::InvalidUds(
            "socket parent directory mode must be 0700",
        ));
    }
    if parent_metadata.uid() != unsafe { libc::geteuid() } {
        return Err(CoreError::InvalidUds(
            "socket parent directory is owned by another user",
        ));
    }

    Ok(())
}

#[derive(Debug)]
struct DevelopmentSpawnSpec {
    program: OsString,
    args: Vec<OsString>,
    current_dir: PathBuf,
    explicit_environment: Vec<(OsString, OsString)>,
}

impl DevelopmentSpawnSpec {
    fn from_manifest_dir() -> Result<Self, CoreError> {
        let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .map_err(CoreError::RepositoryRoot)?;

        Ok(Self {
            program: OsString::from("uv"),
            args: [
                "run",
                "--project",
                "services/core",
                "ariadne-core",
                "serve",
                "--bootstrap-stdin",
            ]
            .into_iter()
            .map(OsString::from)
            .collect(),
            current_dir: repo_root,
            explicit_environment: Vec::new(),
        })
    }

    fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command
            .args(&self.args)
            .current_dir(&self.current_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env_remove("ARIADNE_SESSION_TOKEN")
            .env_remove("ARIADNE_BOOTSTRAP");
        for (name, value) in &self.explicit_environment {
            command.env(name, value);
        }
        command
    }

    #[cfg(test)]
    fn contains_value(&self, needle: &str) -> bool {
        self.program == std::ffi::OsStr::new(needle)
            || self
                .args
                .iter()
                .any(|value| value == std::ffi::OsStr::new(needle))
            || self.explicit_environment.iter().any(|(name, value)| {
                name == std::ffi::OsStr::new(needle) || value == std::ffi::OsStr::new(needle)
            })
    }
}

#[derive(Debug)]
struct PackagedSpawnSpec {
    program: PathBuf,
    args: Vec<OsString>,
    current_dir: PathBuf,
}

impl PackagedSpawnSpec {
    fn from_current_executable() -> Result<Self, CoreError> {
        let executable =
            std::env::current_exe().map_err(|_| CoreError::PackagedSidecarUnavailable)?;
        Self::from_executable_path(&executable)
    }

    fn from_executable_path(executable: &Path) -> Result<Self, CoreError> {
        if !executable.is_absolute() {
            return Err(CoreError::InvalidPackagedSidecar(
                "application executable path is not absolute",
            ));
        }
        let current_dir = executable
            .parent()
            .ok_or(CoreError::InvalidPackagedSidecar(
                "application executable has no parent directory",
            ))?;
        let program = current_dir.join(PACKAGED_SIDECAR_FILENAME);
        validate_packaged_sidecar(&program)?;

        Ok(Self {
            program,
            args: ["serve", "--bootstrap-stdin", "--transport", "uds"]
                .into_iter()
                .map(OsString::from)
                .collect(),
            current_dir: current_dir.to_path_buf(),
        })
    }

    fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command
            .args(&self.args)
            .current_dir(&self.current_dir)
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        command
    }

    #[cfg(test)]
    fn contains_value(&self, needle: &str) -> bool {
        self.program == Path::new(needle)
            || self
                .args
                .iter()
                .any(|value| value == std::ffi::OsStr::new(needle))
    }
}

#[cfg(unix)]
fn validate_packaged_sidecar(path: &Path) -> Result<(), CoreError> {
    use std::os::unix::fs::PermissionsExt;

    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(CoreError::InvalidPackagedSidecar("sidecar is missing"));
        }
        Err(_) => {
            return Err(CoreError::InvalidPackagedSidecar(
                "sidecar metadata is unavailable",
            ));
        }
    };

    if metadata.file_type().is_symlink() {
        return Err(CoreError::InvalidPackagedSidecar(
            "sidecar must not be a symbolic link",
        ));
    }
    if !metadata.file_type().is_file() {
        return Err(CoreError::InvalidPackagedSidecar(
            "sidecar is not a regular file",
        ));
    }

    let mode = metadata.permissions().mode();
    if mode & 0o022 != 0 {
        return Err(CoreError::InvalidPackagedSidecar(
            "sidecar is writable by group or others",
        ));
    }
    if mode & 0o111 == 0 {
        return Err(CoreError::InvalidPackagedSidecar(
            "sidecar is not executable",
        ));
    }

    Ok(())
}

#[cfg(not(unix))]
fn validate_packaged_sidecar(_path: &Path) -> Result<(), CoreError> {
    Err(CoreError::PackagedSidecarUnavailable)
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum CoreError {
    #[error("the local core lifecycle is in an invalid state: {0:?}")]
    InvalidLifecycleState(CoreLifecycleState),
    #[error("the local core is not ready ({0:?})")]
    NotReady(CoreLifecycleState),
    #[error("the local core startup was cancelled")]
    StartupCancelled,
    #[error("packaged core sidecar is unavailable; TCP fallback is forbidden")]
    PackagedSidecarUnavailable,
    #[error("packaged core sidecar failed validation: {0}")]
    InvalidPackagedSidecar(&'static str),
    #[error("packaged TCP transport is forbidden")]
    PackagedTcpForbidden,
    #[error("failed to locate the repository root for development")]
    RepositoryRoot(#[source] std::io::Error),
    #[error("failed to spawn the local core")]
    Spawn(#[source] std::io::Error),
    #[error("the core child process is missing its {0} pipe")]
    MissingChildPipe(&'static str),
    #[error("failed to generate the local core credential")]
    Random(getrandom::Error),
    #[error("failed to write the private bootstrap message")]
    BootstrapWrite(#[source] std::io::Error),
    #[error("the local key-lease startup failed")]
    KeyLease(#[from] KeyLeaseError),
    #[error("the local key-lease startup worker failed")]
    KeyLeaseWorker,
    #[error(transparent)]
    VaultManifest(#[from] VaultManifestError),
    #[error("the vault display name is invalid")]
    InvalidDisplayName,
    #[error("the Phase 3 command input is invalid")]
    InvalidPhase3Request,
    #[error("the selected file failed local integrity validation")]
    InvalidPhase3File,
    #[error("the local core returned an invalid Phase 3 response")]
    InvalidPhase3Response,
    #[error("the local AI command input is invalid")]
    InvalidLocalAiRequest,
    #[error("the local core returned an invalid local AI response")]
    InvalidLocalAiResponse,
    #[error("the public-discovery command input is invalid")]
    InvalidPublicDiscoveryRequest,
    #[error("the local core returned an invalid public-discovery response")]
    InvalidPublicDiscoveryResponse,
    #[error("the HIBP self-audit command input is invalid")]
    InvalidHibpRequest,
    #[error("the local core returned an invalid HIBP self-audit response")]
    InvalidHibpResponse,
    #[error("the investigation-plan command input is invalid")]
    InvalidInvestigationPlanRequest,
    #[error("the local core returned an invalid investigation plan")]
    InvalidInvestigationPlanResponse,
    #[error("the query-policy command input is invalid")]
    InvalidQueryRequest,
    #[error("the local core returned an invalid query-policy response")]
    InvalidQueryResponse,
    #[error("the Phase 5 finding command input is invalid")]
    InvalidPhase5Request,
    #[error("the local core returned an invalid Phase 5 finding response")]
    InvalidPhase5Response,
    #[error("the Phase 6 command input is invalid")]
    InvalidPhase6Request,
    #[error("the local core returned an invalid Phase 6 response")]
    InvalidPhase6Response,
    #[error("the local report command input is invalid")]
    InvalidLocalReportRequest,
    #[error("the local core returned an invalid local report response")]
    InvalidLocalReportResponse,
    #[error("the identity-discovery command input is invalid")]
    InvalidIdentityRequest,
    #[error("the local core returned an invalid identity-discovery response")]
    InvalidIdentityResponse,
    #[error("timed out waiting for local core readiness")]
    ReadinessTimeout,
    #[error("the local core exited before reporting readiness")]
    ReadinessEof,
    #[error("failed to read local core readiness")]
    ReadinessRead(#[source] std::io::Error),
    #[error("local core readiness exceeded its byte limit")]
    ReadinessTooLarge,
    #[error("invalid local core readiness: {0}")]
    InvalidReadiness(&'static str),
    #[error("local core contract mismatch (expected {expected}, received {actual})")]
    ContractVersionMismatch { expected: u16, actual: u16 },
    #[error("invalid packaged Unix socket: {0}")]
    InvalidUds(&'static str),
    #[error("failed to construct the private local HTTP client")]
    HttpClient(#[source] reqwest::Error),
    #[error("the local core request failed")]
    HttpRequest(#[source] reqwest::Error),
    #[error("the local core request JSON is invalid")]
    RequestJson(#[source] serde_json::Error),
    #[error("the local core request exceeded its route bound")]
    RequestTooLarge,
    #[error("the local core returned HTTP {0}")]
    HttpStatus(StatusCode),
    #[error("the local core returned a non-JSON response")]
    InvalidContentType,
    #[error("the local core returned invalid JSON")]
    InvalidResponseJson,
    #[error("the local core response exceeded its byte limit")]
    ResponseTooLarge,
    #[error("the local core returned an invalid vault lifecycle state")]
    InvalidVaultResponse,
    #[error("the local core returned an invalid event replay window")]
    InvalidEventResponse,
    #[error("local core internal state is inconsistent: {0}")]
    InternalState(&'static str),
    #[error(transparent)]
    Contract(#[from] ContractError),
}

impl CoreError {
    fn code(&self) -> &'static str {
        match self {
            Self::InvalidLifecycleState(_) | Self::NotReady(_) => "CORE_NOT_READY",
            Self::StartupCancelled => "CORE_STARTUP_CANCELLED",
            Self::PackagedSidecarUnavailable
            | Self::InvalidPackagedSidecar(_)
            | Self::PackagedTcpForbidden => "CORE_RELEASE_TRANSPORT_UNAVAILABLE",
            Self::RepositoryRoot(_) | Self::Spawn(_) | Self::MissingChildPipe(_) => {
                "CORE_SPAWN_FAILED"
            }
            Self::Random(_) | Self::BootstrapWrite(_) | Self::Contract(_) => {
                "CORE_BOOTSTRAP_FAILED"
            }
            Self::KeyLease(_) | Self::KeyLeaseWorker => "CORE_KEY_LEASE_FAILED",
            Self::VaultManifest(_) | Self::InvalidDisplayName => "VAULT_CONTEXT_INVALID",
            Self::InvalidPhase3Request
            | Self::InvalidLocalAiRequest
            | Self::InvalidPublicDiscoveryRequest
            | Self::InvalidHibpRequest
            | Self::InvalidInvestigationPlanRequest
            | Self::InvalidQueryRequest
            | Self::InvalidPhase5Request
            | Self::InvalidPhase6Request
            | Self::InvalidLocalReportRequest
            | Self::InvalidIdentityRequest => "CORE_INPUT_INVALID",
            Self::InvalidPhase3File => "CORE_FILE_INPUT_INVALID",
            Self::ReadinessTimeout
            | Self::ReadinessEof
            | Self::ReadinessRead(_)
            | Self::ReadinessTooLarge
            | Self::InvalidReadiness(_)
            | Self::ContractVersionMismatch { .. }
            | Self::InvalidUds(_) => "CORE_READINESS_FAILED",
            Self::HttpClient(_)
            | Self::HttpRequest(_)
            | Self::RequestJson(_)
            | Self::RequestTooLarge
            | Self::HttpStatus(_)
            | Self::InvalidContentType
            | Self::InvalidResponseJson
            | Self::ResponseTooLarge
            | Self::InvalidVaultResponse
            | Self::InvalidEventResponse
            | Self::InvalidPhase3Response
            | Self::InvalidLocalAiResponse
            | Self::InvalidPublicDiscoveryResponse
            | Self::InvalidHibpResponse
            | Self::InvalidInvestigationPlanResponse
            | Self::InvalidQueryResponse
            | Self::InvalidPhase5Response
            | Self::InvalidPhase6Response
            | Self::InvalidLocalReportResponse
            | Self::InvalidIdentityResponse => "CORE_REQUEST_FAILED",
            Self::InternalState(_) => "CORE_INTERNAL_STATE",
        }
    }

    fn into_command_error(self, request_id: Uuid) -> CoreCommandError {
        CoreCommandError {
            code: self.code(),
            message: self.to_string(),
            request_id,
        }
    }
}

impl From<CoreError> for CoreCommandError {
    fn from(error: CoreError) -> Self {
        error.into_command_error(Uuid::new_v4())
    }
}

#[cfg(test)]
#[derive(Debug, Eq, PartialEq)]
struct SupervisorSnapshot {
    state: CoreLifecycleState,
    has_endpoint: bool,
    has_credential: bool,
    has_key_lease_broker: bool,
    has_key_lease_handle: bool,
}

#[cfg(test)]
mod tests {
    use std::{
        ffi::OsStr,
        fs,
        os::unix::{
            fs::{PermissionsExt, symlink},
            net::UnixListener,
        },
    };

    use serde_json::json;
    use tokio::io::AsyncWriteExt;

    use super::*;

    const TEST_TOKEN: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

    async fn wait_for_locked_session(supervisor: &CoreSupervisor) {
        timeout(Duration::from_secs(30), async {
            loop {
                if let Ok(session) = supervisor.session().await
                    && session.data.lock_state == SessionLockState::Locked
                    && session.data.vault_state == VaultState::Locked
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .unwrap();
    }

    fn synthetic_file_request(content: &[u8]) -> CoreFileIntakeRequest {
        let digest = Sha256::digest(content);
        let expected_sha256 = digest.iter().map(|byte| format!("{byte:02x}")).collect();
        CoreFileIntakeRequest {
            profile_id: Uuid::new_v4(),
            idempotency_key: "synthetic_file_request_0001".to_owned(),
            display_name: "synthetic-profile.json".to_owned(),
            declared_media_type: "application/json".to_owned(),
            expected_size_bytes: content.len(),
            expected_sha256,
            content_base64: Zeroizing::new(STANDARD.encode(content)),
            consent_confirmed: true,
            retain_raw_source: false,
            semantic_enrichment_enabled: true,
        }
    }

    #[test]
    fn selected_file_bytes_require_canonical_base64_size_and_digest() {
        let content = br#"{"name":"Synthetic Person"}"#;
        let valid = synthetic_file_request(content);
        validate_file_intake_request(&valid).unwrap();
        assert_eq!(format!("{valid:?}"), "CoreFileIntakeRequest([REDACTED])");

        let mut malformed = synthetic_file_request(content);
        malformed.content_base64 = Zeroizing::new("!".repeat(malformed.content_base64.len()));
        assert!(matches!(
            validate_file_intake_request(&malformed),
            Err(CoreError::InvalidPhase3File)
        ));

        let mut wrong_size = synthetic_file_request(content);
        wrong_size.expected_size_bytes += 1;
        assert!(matches!(
            validate_file_intake_request(&wrong_size),
            Err(CoreError::InvalidPhase3File)
        ));

        let mut wrong_digest = synthetic_file_request(content);
        wrong_digest.expected_sha256 = "0".repeat(64);
        assert!(matches!(
            validate_file_intake_request(&wrong_digest),
            Err(CoreError::InvalidPhase3File)
        ));
    }

    #[test]
    fn phase3_request_validation_fails_closed() {
        let invalid_key = CoreProfileCreateRequest {
            idempotency_key: "contains whitespace".to_owned(),
            display_label: "Synthetic profile".to_owned(),
            purpose: "Local synthetic test".to_owned(),
        };
        assert!(matches!(
            validate_profile_create_request(&invalid_key),
            Err(CoreError::InvalidPhase3Request)
        ));

        let unsafe_policy = CoreEntityDecisionRequest {
            profile_id: Uuid::new_v4(),
            entity_id: Uuid::new_v4(),
            idempotency_key: "synthetic_decision_0001".to_owned(),
            expected_revision: 1,
            decision_type: CoreEntityDecisionType::Confirm,
            review_state: CoreReviewState::Confirmed,
            sensitivity: CoreSensitivity::HighlySensitive,
            temporal_state: super::super::contract::CoreTemporalState::Unknown,
            search_policy: CoreSearchPolicy::Allow,
            transmission_policy: CoreTransmissionPolicy::PolicyControlled,
            reason: None,
        };
        assert!(matches!(
            validate_entity_decision_request(&unsafe_policy),
            Err(CoreError::InvalidPhase3Request)
        ));
    }

    #[test]
    fn entity_origin_page_is_strictly_scoped_bounded_and_consistent() {
        assert!(unlocked_route_metadata_is_valid(CoreRoute::EntityOrigins));
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000101").unwrap();
        let entity_id = Uuid::parse_str("00000000-0000-4000-8000-000000000102").unwrap();
        let request: CoreEntityOriginPageRequest = serde_json::from_value(json!({
            "profileId": profile_id,
            "entityId": entity_id
        }))
        .unwrap();
        assert_eq!(request.offset, 0);
        assert_eq!(request.limit, 12);
        validate_entity_origin_page_request(&request).unwrap();
        assert!(
            serde_json::from_value::<CoreEntityOriginPageRequest>(json!({
                "profileId": "00000000-0000-4000-8000-00000000010A",
                "entityId": entity_id
            }))
            .is_err()
        );

        let origin = json!({
            "sourceId": "00000000-0000-4000-8000-000000000103",
            "sourceDisplayName": "Synthetic source",
            "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "segmentId": "00000000-0000-4000-8000-000000000104",
            "segmentIndex": 0,
            "segmentLocator": "{\"kind\":\"synthetic\",\"line\":1}",
            "sourceSpanStart": 0,
            "sourceSpanEnd": 12,
            "extractionRunId": null,
            "extractorKind": null,
            "extractorName": null,
            "extractorVersion": null,
            "originKind": "USER_INPUT",
            "observedAtUs": 1_700_000_000_000_000_u64,
            "confidenceMicros": 900_000,
            "explanation": "Synthetic exact origin"
        });
        let value = json!({
            "profileId": profile_id,
            "entityId": entity_id,
            "offset": 0,
            "limit": 12,
            "origins": [origin],
            "total": 2,
            "hasMore": true
        });
        let valid: CoreEntityOriginPageResult = serde_json::from_value(value.clone()).unwrap();
        validate_entity_origin_page_result(&valid, profile_id, entity_id, 0, 12).unwrap();

        let mut wrong_scope = value.clone();
        wrong_scope["profileId"] = json!("00000000-0000-4000-8000-000000000105");
        let wrong_scope: CoreEntityOriginPageResult = serde_json::from_value(wrong_scope).unwrap();
        assert!(matches!(
            validate_entity_origin_page_result(&wrong_scope, profile_id, entity_id, 0, 12),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut inconsistent = value;
        inconsistent["hasMore"] = json!(false);
        let inconsistent: CoreEntityOriginPageResult =
            serde_json::from_value(inconsistent).unwrap();
        assert!(matches!(
            validate_entity_origin_page_result(&inconsistent, profile_id, entity_id, 0, 12),
            Err(CoreError::InvalidPhase3Response)
        ));

        let past_end: CoreEntityOriginPageResult = serde_json::from_value(json!({
            "profileId": profile_id,
            "entityId": entity_id,
            "offset": 10,
            "limit": 12,
            "origins": [],
            "total": 2,
            "hasMore": false
        }))
        .unwrap();
        validate_entity_origin_page_result(&past_end, profile_id, entity_id, 10, 12).unwrap();

        let oversized_request = CoreEntityOriginPageRequest {
            profile_id,
            entity_id,
            offset: 0,
            limit: 13,
        };
        assert!(matches!(
            validate_entity_origin_page_request(&oversized_request),
            Err(CoreError::InvalidPhase3Request)
        ));
    }

    #[test]
    fn local_ai_validation_allows_only_loopback_and_explicit_models() {
        for endpoint in [
            "https://127.0.0.1:11434",
            "http://192.0.2.10:11434",
            "http://example.invalid:11434",
            "http://127.0.0.1:11434/api",
            "http://user:secret@127.0.0.1:11434",
            "http://0.0.0.0:11434",
        ] {
            let request = CoreLocalAiEndpointRequest {
                provider: CoreLocalAiProvider::Ollama,
                endpoint: endpoint.to_owned(),
                selected_model: None,
            };
            assert!(matches!(
                validate_local_ai_endpoint_request(&request),
                Err(CoreError::InvalidLocalAiRequest)
            ));
        }

        let disabled = CoreLocalAiSettingsUpdateRequest {
            enabled: false,
            provider: CoreLocalAiProvider::OpenaiCompatible,
            endpoint: "http://127.0.0.1:1234".to_owned(),
            selected_model: None,
            expected_revision: 1,
        };
        validate_local_ai_settings_update(&disabled).unwrap();

        let mut enabled_without_model = disabled;
        enabled_without_model.enabled = true;
        assert!(matches!(
            validate_local_ai_settings_update(&enabled_without_model),
            Err(CoreError::InvalidLocalAiRequest)
        ));

        enabled_without_model.selected_model = Some("qwen-local:7b".to_owned());
        validate_local_ai_settings_update(&enabled_without_model).unwrap();
    }

    #[test]
    fn local_ai_workspace_response_requires_exact_source_catalog() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let reference = "finding:00000000-0000-4000-8000-000000000002";
        let counts = json!({
            "entities": 0,
            "graphNodes": 0,
            "graphEdges": 0,
            "findings": 1,
            "remediationCases": 0,
            "auditRuns": 0,
            "documentSegments": 0
        });
        let source = json!({
            "ref": reference,
            "kind": "FINDING",
            "label": "Synthetic finding",
            "locator": format!("{reference} · provider provider-synthetic-local"),
            "sourceUrl": "https://synthetic-source.example.invalid/profile",
            "contentSha256": null,
            "providerId": "provider-synthetic-local",
            "sourceId": null,
            "sourceDisplayName": null,
            "artifactId": null,
            "segmentId": null,
            "segmentIndex": null,
            "segmentLocator": null,
            "sourceSpanStart": null,
            "sourceSpanEnd": null,
            "extractionRunId": null,
            "extractorKind": null,
            "extractorName": null,
            "extractorVersion": null,
            "runId": null,
            "originKind": null,
            "originType": null,
            "observedAtUs": null,
            "confidenceMicros": null,
            "disposition": null,
            "sourceUrlSha256": "837691979e1bc09c25b49590223c7f7134f035dc3b31ee2f8bc9385bba971856",
            "captureMethod": null,
            "httpStatus": null,
            "redirectCount": null
        });
        let value = json!({
            "profileId": profile_id,
            "task": "SUMMARY",
            "selectedScopes": ["FINDINGS"],
            "requestedExecution": "DETERMINISTIC",
            "executionMode": "DETERMINISTIC",
            "fallbackReason": null,
            "provider": null,
            "modelId": null,
            "engineVersion": "1",
            "title": "Synthetic summary",
            "summary": "One synthetic finding is available for review.",
            "sections": [{
                "heading": "Synthetic evidence",
                "items": [{
                    "text": "The selected finding is available for human review.",
                    "evidenceRefs": [reference]
                }]
            }],
            "facts": [{
                "statement": "The selected finding is stored.",
                "evidenceRefs": [reference],
                "confidence": "HIGH"
            }],
            "connections": [],
            "nextSteps": [],
            "sources": [source],
            "unanswered": null,
            "limitations": ["Human review remains required."],
            "includedCounts": counts,
            "availableCounts": counts,
            "projectionTruncated": false,
            "inputSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "restrictedValuesRedacted": 0,
            "localOnly": true,
            "externalNetworkUsed": false,
            "rawEvidenceIncluded": false,
            "reviewOnly": true,
            "humanReviewRequired": true
        });
        let valid: CoreLocalAiWorkspaceResult = serde_json::from_value(value.clone()).unwrap();
        validate_local_ai_workspace_result(
            &valid,
            profile_id,
            CoreLocalAiWorkspaceTask::Summary,
            &[CoreLocalAiWorkspaceScope::Findings],
            CoreLocalAiWorkspaceExecution::Deterministic,
            None,
        )
        .unwrap();

        let mut section_only = value.clone();
        section_only["facts"] = json!([]);
        let section_only: CoreLocalAiWorkspaceResult =
            serde_json::from_value(section_only).unwrap();
        validate_local_ai_workspace_result(
            &section_only,
            profile_id,
            CoreLocalAiWorkspaceTask::Summary,
            &[CoreLocalAiWorkspaceScope::Findings],
            CoreLocalAiWorkspaceExecution::Deterministic,
            None,
        )
        .unwrap();

        let mut exact_segment = value.clone();
        exact_segment["sources"][0]["kind"] = json!("ENTITY_ORIGIN");
        exact_segment["sources"][0]["contentSha256"] = json!("a".repeat(64));
        exact_segment["sources"][0]["sourceId"] = json!("00000000-0000-4000-8000-000000000021");
        exact_segment["sources"][0]["sourceDisplayName"] = json!("Synthetic source");
        exact_segment["sources"][0]["segmentId"] = json!("00000000-0000-4000-8000-000000000022");
        exact_segment["sources"][0]["segmentIndex"] = json!(0);
        exact_segment["sources"][0]["segmentLocator"] = json!("line 1");
        exact_segment["sources"][0]["sourceSpanStart"] = json!(0);
        exact_segment["sources"][0]["sourceSpanEnd"] = json!(12);
        exact_segment["sources"][0]["extractionRunId"] =
            json!("00000000-0000-4000-8000-000000000023");
        exact_segment["sources"][0]["extractorKind"] = json!("DETERMINISTIC");
        exact_segment["sources"][0]["extractorName"] = json!("synthetic-parser");
        exact_segment["sources"][0]["extractorVersion"] = json!("1");
        exact_segment["sources"][0]["originKind"] = json!("USER_INPUT");
        exact_segment["sources"][0]["observedAtUs"] = json!(1_700_000_000_000_000_u64);
        exact_segment["sources"][0]["confidenceMicros"] = json!(900_000);
        let exact_segment: CoreLocalAiWorkspaceResult =
            serde_json::from_value(exact_segment).unwrap();
        validate_local_ai_workspace_result(
            &exact_segment,
            profile_id,
            CoreLocalAiWorkspaceTask::Summary,
            &[CoreLocalAiWorkspaceScope::Findings],
            CoreLocalAiWorkspaceExecution::Deterministic,
            None,
        )
        .unwrap();

        let mut uncited = value.clone();
        uncited["sources"] = json!([]);
        let uncited: CoreLocalAiWorkspaceResult = serde_json::from_value(uncited).unwrap();
        assert!(matches!(
            validate_local_ai_workspace_result(
                &uncited,
                profile_id,
                CoreLocalAiWorkspaceTask::Summary,
                &[CoreLocalAiWorkspaceScope::Findings],
                CoreLocalAiWorkspaceExecution::Deterministic,
                None,
            ),
            Err(CoreError::InvalidLocalAiResponse)
        ));

        let mut invalid_url_binding = value.clone();
        invalid_url_binding["sources"][0]["sourceUrlSha256"] = json!("b".repeat(64));
        let invalid_url_binding: CoreLocalAiWorkspaceResult =
            serde_json::from_value(invalid_url_binding).unwrap();
        assert!(matches!(
            validate_local_ai_workspace_result(
                &invalid_url_binding,
                profile_id,
                CoreLocalAiWorkspaceTask::Summary,
                &[CoreLocalAiWorkspaceScope::Findings],
                CoreLocalAiWorkspaceExecution::Deterministic,
                None,
            ),
            Err(CoreError::InvalidLocalAiResponse)
        ));

        let mut incomplete_segment = value.clone();
        incomplete_segment["sources"][0]["segmentId"] = json!("segment:synthetic-1");
        let incomplete_segment: CoreLocalAiWorkspaceResult =
            serde_json::from_value(incomplete_segment).unwrap();
        assert!(matches!(
            validate_local_ai_workspace_result(
                &incomplete_segment,
                profile_id,
                CoreLocalAiWorkspaceTask::Summary,
                &[CoreLocalAiWorkspaceScope::Findings],
                CoreLocalAiWorkspaceExecution::Deterministic,
                None,
            ),
            Err(CoreError::InvalidLocalAiResponse)
        ));

        let mut missing_nullable = value;
        missing_nullable["sources"][0]
            .as_object_mut()
            .unwrap()
            .remove("sourceId");
        assert!(serde_json::from_value::<CoreLocalAiWorkspaceResult>(missing_nullable).is_err());
    }

    fn synthetic_local_corpus_request() -> CoreLocalCorpusAiRequest {
        let documents = [
            ("synthetic-a.txt", b"Synthetic alpha record.".as_slice()),
            ("synthetic-b.txt", b"Synthetic beta record.".as_slice()),
        ]
        .into_iter()
        .map(|(display_name, content)| CoreLocalCorpusDocumentRequest {
            display_name: display_name.to_owned(),
            declared_media_type: CoreLocalCorpusMediaType::Text,
            content_base64: Zeroizing::new(STANDARD.encode(content)),
            expected_size_bytes: content.len(),
            expected_sha256: sha256_lower_hex(content),
        })
        .collect();
        CoreLocalCorpusAiRequest {
            documents,
            semantic_enrichment_enabled: true,
            profile_id: Uuid::parse_str("00000000-0000-4000-8000-000000000011").unwrap(),
            task: CoreLocalCorpusAiTask::Connections,
            question: None,
            execution: CoreLocalCorpusAiExecution::Deterministic,
            model_id: None,
            openai_api_key: None,
            max_segments: 2,
        }
    }

    #[test]
    fn local_corpus_request_requires_canonical_bound_file_bytes() {
        let request = synthetic_local_corpus_request();
        let binding = validate_local_corpus_ai_request(&request).unwrap();
        assert_eq!(binding.input_manifest_sha256.len(), 64);
        assert_eq!(
            format!("{request:?}"),
            "CoreLocalCorpusAiRequest([REDACTED])"
        );

        let unicode_content = b"synthetic content";
        let unicode = CoreLocalCorpusAiRequest {
            documents: vec![CoreLocalCorpusDocumentRequest {
                display_name: "synthetic-😀.txt".to_owned(),
                declared_media_type: CoreLocalCorpusMediaType::Text,
                content_base64: Zeroizing::new(STANDARD.encode(unicode_content)),
                expected_size_bytes: unicode_content.len(),
                expected_sha256: sha256_lower_hex(unicode_content),
            }],
            semantic_enrichment_enabled: false,
            profile_id: Uuid::parse_str("00000000-0000-4000-8000-000000000012").unwrap(),
            task: CoreLocalCorpusAiTask::Summary,
            question: None,
            execution: CoreLocalCorpusAiExecution::Deterministic,
            model_id: None,
            openai_api_key: None,
            max_segments: 1,
        };
        assert_eq!(
            validate_local_corpus_ai_request(&unicode)
                .unwrap()
                .input_manifest_sha256,
            "f284d67633ea22efebdaf2865ed574fd65ce478cab41d7a2e2ae57f6fdcd50d8"
        );

        let mut altered = synthetic_local_corpus_request();
        altered.documents[0].expected_sha256 = "0".repeat(64);
        assert!(matches!(
            validate_local_corpus_ai_request(&altered),
            Err(CoreError::InvalidLocalAiRequest)
        ));

        let mut non_canonical = synthetic_local_corpus_request();
        non_canonical.documents[0].content_base64.push('=');
        assert!(matches!(
            validate_local_corpus_ai_request(&non_canonical),
            Err(CoreError::InvalidLocalAiRequest)
        ));
    }

    #[test]
    fn local_corpus_response_requires_exact_cross_document_sources() {
        let request = synthetic_local_corpus_request();
        let binding = validate_local_corpus_ai_request(&request).unwrap();
        let manifest = binding.input_manifest_sha256.clone();
        let corpus_id = binding.expected_corpus_id.clone();
        assert_eq!(
            corpus_id,
            "corpus:2a785114ac306a04bd9faf0a850bd02c130e15a515948280691ffbe56e0644a9"
        );
        let first_document = format!(
            "corpus-document:0001:{}",
            request.documents[0].expected_sha256
        );
        let second_document = format!(
            "corpus-document:0002:{}",
            request.documents[1].expected_sha256
        );
        let first_segment = format!("{first_document}:segment:0");
        let second_segment = format!("{second_document}:segment:0");
        let entity = format!("corpus-entity:{}", "c".repeat(64));
        let counts = json!({
            "documents": 2,
            "segments": 2,
            "entities": 1,
            "sharedEntities": 1
        });
        let value = json!({
            "profileId": request.profile_id,
            "corpusId": corpus_id,
            "inputManifestSha256": manifest,
            "inputSha256": "b".repeat(64),
            "task": "CONNECTIONS",
            "requestedExecution": "DETERMINISTIC",
            "executionMode": "DETERMINISTIC",
            "fallbackReason": null,
            "provider": null,
            "modelId": null,
            "engineVersion": "1",
            "title": "Synthetic cited connections",
            "draftSummary": "Draft synthesis for human review.",
            "narrativeLabel": "DRAFT_SUMMARY_NOT_A_FACT",
            "sections": [{
                "heading": "Synthetic coverage",
                "items": [{
                    "text": "Two synthetic records were compared.",
                    "label": "CITED_SUMMARY",
                    "origin": "DETERMINISTIC",
                    "evidenceRefs": [first_segment]
                }]
            }],
            "facts": [{
                "statement": "The first synthetic record is present.",
                "evidenceRefs": [first_segment],
                "confidence": "HIGH",
                "origin": "DETERMINISTIC"
            }],
            "connections": [{
                "fromRef": first_segment,
                "toRef": second_segment,
                "sharedEntityRefs": [entity],
                "relationship": "Shared synthetic entity",
                "supportingRefs": [first_segment, second_segment, entity],
                "contradictionRefs": [],
                "confidence": "MEDIUM",
                "origin": "DETERMINISTIC",
                "rationale": "The cited entity has origins in both documents.",
                "verificationSuggestion": "Review both cited source segments."
            }],
            "nextSteps": [{
                "priority": 1,
                "suggestion": "Review the source pair.",
                "rationale": "Human confirmation is still required.",
                "supportingRefs": [entity],
                "origin": "DETERMINISTIC"
            }],
            "unanswered": null,
            "uncertainties": [{
                "text": "This is a synthetic inference.",
                "label": "LIMITATION",
                "origin": "DETERMINISTIC",
                "evidenceRefs": []
            }],
            "sourceCatalog": [{
                "referenceId": first_segment,
                "referenceKind": "SEGMENT",
                "sources": [{
                    "documentId": first_document,
                    "documentName": "synthetic-a.txt",
                    "segmentId": first_segment,
                    "segmentIndex": 0,
                    "locator": "line 1"
                }]
            }, {
                "referenceId": second_segment,
                "referenceKind": "SEGMENT",
                "sources": [{
                    "documentId": second_document,
                    "documentName": "synthetic-b.txt",
                    "segmentId": second_segment,
                    "segmentIndex": 0,
                    "locator": "line 1"
                }]
            }, {
                "referenceId": entity,
                "referenceKind": "ENTITY",
                "sources": [{
                    "documentId": first_document,
                    "documentName": "synthetic-a.txt",
                    "segmentId": first_segment,
                    "segmentIndex": 0,
                    "locator": "line 1"
                }, {
                    "documentId": second_document,
                    "documentName": "synthetic-b.txt",
                    "segmentId": second_segment,
                    "segmentIndex": 0,
                    "locator": "line 1"
                }]
            }],
            "includedCounts": counts,
            "availableCounts": counts,
            "projectionTruncated": false,
            "restrictedValuesRedacted": 0,
            "localOnly": true,
            "externalNetworkUsed": false,
            "rawSourcesRetained": false,
            "persisted": false,
            "reviewOnly": true,
            "humanReviewRequired": true
        });
        let valid: CoreLocalCorpusAiResult = serde_json::from_value(value.clone()).unwrap();
        validate_local_corpus_ai_result(&valid, &binding).unwrap();

        let mut unbound = value;
        unbound["sourceCatalog"][2]["sources"] =
            json!([unbound["sourceCatalog"][2]["sources"][0].clone()]);
        let unbound: CoreLocalCorpusAiResult = serde_json::from_value(unbound).unwrap();
        assert!(matches!(
            validate_local_corpus_ai_result(&unbound, &binding),
            Err(CoreError::InvalidLocalAiResponse)
        ));
    }

    #[test]
    fn public_discovery_requires_bound_exact_sources_and_response_binding() {
        let mut request = CorePublicDiscoverySearchRequest {
            provider: CorePublicDiscoveryProvider::DuckduckgoHtml,
            query: "synthetic profile".to_owned(),
            authorized_self_audit: true,
            max_results: 3,
        };
        validate_public_discovery_request(&request).unwrap();

        let response_value = json!({
            "provider": "DUCKDUCKGO_HTML",
            "state": "SUCCEEDED",
            "reason": "COMPLETE",
            "results": [{
                "provider": "DUCKDUCKGO_HTML",
                "rank": 1,
                "title": "Synthetic public result",
                "url": "https://synthetic-source.example/profile?ref=source-7",
                "snippet": "Reserved synthetic evidence for local review.",
                "sourceId": "SYN-007"
            }],
            "totalEstimate": 1,
            "rateLimitRemaining": null,
            "truncated": false,
            "externalRequestMade": true,
            "authorizationConfirmed": true,
            "humanReviewRequired": true
        });
        let response: CorePublicDiscoverySearchResult =
            serde_json::from_value(response_value.clone()).unwrap();
        validate_public_discovery_result(
            &response,
            request.provider,
            request.authorized_self_audit,
            request.max_results,
        )
        .unwrap();

        let mut unsafe_source = response_value;
        unsafe_source["results"][0]["url"] = json!("http://127.0.0.1/private?ref=source-7");
        let unsafe_source: CorePublicDiscoverySearchResult =
            serde_json::from_value(unsafe_source).unwrap();
        assert!(matches!(
            validate_public_discovery_result(
                &unsafe_source,
                request.provider,
                request.authorized_self_audit,
                request.max_results,
            ),
            Err(CoreError::InvalidPublicDiscoveryResponse)
        ));

        request.query = "synthetic  profile".to_owned();
        assert!(matches!(
            validate_public_discovery_request(&request),
            Err(CoreError::InvalidPublicDiscoveryRequest)
        ));
    }

    #[test]
    fn hibp_account_validation_binds_k_anonymity_request_and_exact_sources() {
        let request: CoreHibpAccountRequest = serde_json::from_value(json!({
            "email": "synthetic.user@example.invalid",
            "apiKey": "0123456789abcdef0123456789abcdef",
            "mode": "K_ANONYMITY",
            "authorizedSelfAudit": true,
            "authorizedDirectIdentifierTransmission": false
        }))
        .unwrap();
        let binding = validate_hibp_account_request(&request).unwrap();
        assert_eq!(hibp_sha1_prefix(binding.email.as_bytes()), "EBA136");
        let url = "https://haveibeenpwned.com/api/v3/breachedaccount/range/EBA136";
        let response_value = json!({
            "provider": "HAVE_I_BEEN_PWNED_V3",
            "providerHomeUrl": "https://haveibeenpwned.com/",
            "apiDocumentationUrl": "https://haveibeenpwned.com/API/v3",
            "attribution": "Have I Been Pwned",
            "license": "CC BY 4.0",
            "state": "SUCCEEDED",
            "reason": "COMPLETE",
            "requests": [{
                "sequence": 1,
                "operation": "EMAIL_K_ANONYMITY",
                "method": "GET",
                "requestUrl": url,
                "endpointHost": "haveibeenpwned.com",
                "identifierDisclosure": "PARTIAL_SHA1_PREFIX",
                "requestSha256": sha256_lower_hex(format!("GET\n{url}").as_bytes()),
                "httpStatus": 200,
                "responseBytes": 96,
                "observedAt": "2026-07-14T12:00:00+00:00",
                "retryAfterSeconds": null,
                "apiKeySent": true,
                "redirectsFollowed": false
            }],
            "retryAfterSeconds": null,
            "externalRequestMade": true,
            "authorizationConfirmed": true,
            "humanReviewRequired": true,
            "mode": "K_ANONYMITY",
            "breaches": [{
                "name": "SyntheticBreach",
                "sourceUrl": "https://haveibeenpwned.com/api/v3/breach/SyntheticBreach"
            }],
            "directTransmissionAuthorized": false
        });
        let response: CoreHibpAccountResult =
            serde_json::from_value(response_value.clone()).unwrap();
        validate_hibp_account_result(&response, &binding).unwrap();

        let mut unbound = response_value;
        unbound["breaches"][0]["sourceUrl"] =
            json!("https://haveibeenpwned.com/api/v3/breach/OtherBreach");
        let unbound: CoreHibpAccountResult = serde_json::from_value(unbound).unwrap();
        assert!(matches!(
            validate_hibp_account_result(&unbound, &binding),
            Err(CoreError::InvalidHibpResponse)
        ));
    }

    #[test]
    fn hibp_domain_validation_requires_provider_verification_and_partial_metadata() {
        let request: CoreHibpDomainRequest = serde_json::from_value(json!({
            "domain": "example.invalid",
            "apiKey": "0123456789abcdef0123456789abcdef",
            "authorizedSelfAudit": true
        }))
        .unwrap();
        let binding = validate_hibp_domain_request(&request).unwrap();
        let verification_url = "https://haveibeenpwned.com/api/v3/subscribedDomains";
        let enumeration_url = "https://haveibeenpwned.com/api/v3/breachedDomain/example.invalid";
        let response_value = json!({
            "provider": "HAVE_I_BEEN_PWNED_V3",
            "providerHomeUrl": "https://haveibeenpwned.com/",
            "apiDocumentationUrl": "https://haveibeenpwned.com/API/v3",
            "attribution": "Have I Been Pwned",
            "license": "CC BY 4.0",
            "state": "SUCCEEDED",
            "reason": "PARTIAL_RESULTS",
            "requests": [{
                "sequence": 1,
                "operation": "VERIFY_SUBSCRIBED_DOMAIN",
                "method": "GET",
                "requestUrl": verification_url,
                "endpointHost": "haveibeenpwned.com",
                "identifierDisclosure": "NONE",
                "requestSha256": sha256_lower_hex(format!("GET\n{verification_url}").as_bytes()),
                "httpStatus": 200,
                "responseBytes": 80,
                "observedAt": "2026-07-14T12:00:00Z",
                "retryAfterSeconds": null,
                "apiKeySent": true,
                "redirectsFollowed": false
            }, {
                "sequence": 2,
                "operation": "DOMAIN_ENUMERATION",
                "method": "GET",
                "requestUrl": enumeration_url,
                "endpointHost": "haveibeenpwned.com",
                "identifierDisclosure": "DIRECT_DOMAIN",
                "requestSha256": sha256_lower_hex(format!("GET\n{enumeration_url}").as_bytes()),
                "httpStatus": 200,
                "responseBytes": 128,
                "observedAt": "2026-07-14T12:00:01Z",
                "retryAfterSeconds": null,
                "apiKeySent": true,
                "redirectsFollowed": false
            }],
            "retryAfterSeconds": null,
            "externalRequestMade": true,
            "authorizationConfirmed": true,
            "humanReviewRequired": true,
            "accounts": [{
                "alias": "synthetic-alias",
                "breaches": [{
                    "name": "SyntheticBreach",
                    "sourceUrl": "https://haveibeenpwned.com/api/v3/breach/SyntheticBreach"
                }]
            }],
            "providerVerifiedDomain": true,
            "truncated": true
        });
        let response: CoreHibpDomainResult =
            serde_json::from_value(response_value.clone()).unwrap();
        validate_hibp_domain_result(&response, &binding).unwrap();

        let mut unverified = response_value;
        unverified["providerVerifiedDomain"] = json!(false);
        let unverified: CoreHibpDomainResult = serde_json::from_value(unverified).unwrap();
        assert!(matches!(
            validate_hibp_domain_result(&unverified, &binding),
            Err(CoreError::InvalidHibpResponse)
        ));
    }

    #[test]
    fn investigation_plan_validation_is_deterministic_and_source_bound() {
        assert!(ready_route_metadata_is_valid(
            CoreRoute::CompileInvestigationPlan
        ));
        assert!(ready_route_metadata_is_valid(CoreRoute::SearchHibpAccount));
        assert!(ready_route_metadata_is_valid(CoreRoute::SearchHibpDomain));
        let request: CoreInvestigationPlanRequest = serde_json::from_value(json!({
            "identifiers": [{
                "identifierRef": "synthetic-email",
                "kind": "EMAIL",
                "value": "synthetic.user@example.invalid"
            }, {
                "identifierRef": "synthetic-user",
                "kind": "USERNAME",
                "value": "synthetic-user"
            }],
            "enabledProviders": [
                "DUCKDUCKGO_HTML",
                "GITHUB_USERS",
                "HAVE_I_BEEN_PWNED_V3"
            ],
            "authorizedSelfAudit": true,
            "hibpApiKeyAvailable": true,
            "hibpKAnonymityAvailable": true,
            "authorizedDirectEmailTransmission": false
        }))
        .unwrap();
        let binding = validate_investigation_plan_request(&request).unwrap();
        assert_eq!(binding.plan_id, "plan-a43d07855470c7e65cf91655");
        assert_eq!(binding.steps.len(), 4);
        let mut response = CoreInvestigationPlanResult {
            plan_id: binding.plan_id.clone(),
            steps: binding.steps.clone(),
            notices: binding.notices.clone(),
            authorization_confirmed: true,
            deterministic: true,
            executed: false,
        };
        validate_investigation_plan_result(&response, &binding).unwrap();
        response.steps[0].identifier_sha256 = "f".repeat(64);
        assert!(matches!(
            validate_investigation_plan_result(&response, &binding),
            Err(CoreError::InvalidInvestigationPlanResponse)
        ));
    }

    #[test]
    fn public_discovery_capture_requires_atomic_exact_source_binding() {
        assert!(unlocked_route_metadata_is_valid(
            CoreRoute::CapturePublicDiscovery
        ));
        let profile_id = Uuid::new_v4();
        let finding_id = Uuid::new_v4();
        let artifact_id = Uuid::new_v4();
        let url = "https://synthetic-source.example/profile?ref=capture-9037";
        let mut request = CorePublicDiscoveryCaptureRequest {
            profile_id,
            provider: CorePublicDiscoveryProvider::GithubUsers,
            query: "SYNTHETIC CAPTURE QUERY 9037".to_owned(),
            rank: 2,
            title: "Synthetic capture fixture 9037".to_owned(),
            url: url.to_owned(),
            snippet: Some("Synthetic provider excerpt for review.".to_owned()),
            source_id: Some("synthetic-capture-9037".to_owned()),
            captured_at_us: 1_765_000_000_000_000,
            authorized_self_audit: true,
        };
        validate_public_discovery_capture_request(&request).unwrap();

        let response_value = json!({
            "profileId": profile_id,
            "findingId": finding_id,
            "artifactId": artifact_id,
            "provider": "GITHUB_USERS",
            "rank": 2,
            "sourceId": "synthetic-capture-9037",
            "url": url,
            "urlSha256": sha256_lower_hex(url.as_bytes()),
            "queryReference": format!("mq_{}", "a".repeat(64)),
            "capturedAtUs": 1_765_000_000_000_000_u64,
            "evidenceKind": "URL_REFERENCE",
            "encryptedAtRest": true,
            "localOnly": true,
            "deduplicated": false
        });
        let response: CorePublicDiscoveryCaptureResult =
            serde_json::from_value(response_value.clone()).unwrap();
        validate_public_discovery_capture_result(
            &response,
            profile_id,
            request.provider,
            request.rank,
            request.source_id.as_deref(),
            &request.url,
            request.captured_at_us,
        )
        .unwrap();

        let mut unbound = response_value;
        unbound["urlSha256"] = json!("b".repeat(64));
        let unbound: CorePublicDiscoveryCaptureResult = serde_json::from_value(unbound).unwrap();
        assert!(matches!(
            validate_public_discovery_capture_result(
                &unbound,
                profile_id,
                request.provider,
                request.rank,
                request.source_id.as_deref(),
                &request.url,
                request.captured_at_us,
            ),
            Err(CoreError::InvalidPublicDiscoveryResponse)
        ));

        request.authorized_self_audit = false;
        assert!(matches!(
            validate_public_discovery_capture_request(&request),
            Err(CoreError::InvalidPublicDiscoveryRequest)
        ));
    }

    #[test]
    fn query_policy_validation_rejects_network_providers_and_implicit_custom_scope() {
        let profile_id = Uuid::new_v4();
        let mut catalog = CoreProviderCatalogResult {
            profile_id,
            providers: vec![super::super::contract::CoreQueryProviderSummary {
                provider_id: "local-dry-run".to_owned(),
                display_name: "Local dry-run evaluator".to_owned(),
                operator: "Codename Ariadne on this Mac".to_owned(),
                adapter_mode: "DRY_RUN".to_owned(),
                access_basis: "LOCAL_ONLY".to_owned(),
                processing_regions: Vec::new(),
                network_access: false,
                sends_identifiers: false,
                enabled: true,
                retention_known: true,
            }],
            external_provider_count: 0,
        };
        validate_query_provider_catalog(&catalog, profile_id).unwrap();
        catalog.providers[0].network_access = true;
        assert!(matches!(
            validate_query_provider_catalog(&catalog, profile_id),
            Err(CoreError::InvalidQueryResponse)
        ));

        let implicit_custom = CoreQueryPlanRequest {
            profile_id,
            purpose_code: "AUTHORIZED_LOCAL_REVIEW".to_owned(),
            provider_ids: vec!["local-dry-run".to_owned()],
            policy_mode: CoreQueryPolicyMode::Custom,
            allowed_provider_ids: Vec::new(),
            allowed_regions: Vec::new(),
            maximum_checks: 12,
            maximum_checks_per_provider: 6,
        };
        assert!(matches!(
            validate_query_plan_request(&implicit_custom),
            Err(CoreError::InvalidQueryRequest)
        ));
    }

    fn synthetic_phase5_detail_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "finding": {
                "findingId": "00000000-0000-4000-8000-000000000002",
                "title": "Synthetic public profile",
                "summary": "Synthetic evidence requires local review.",
                "outcome": "FOUND",
                "severity": "MEDIUM",
                "visibility": "PUBLIC_PSEUDONYMOUS",
                "attributionState": null,
                "confidenceBand": "MEDIUM",
                "score": 180,
                "humanReviewRequired": true,
                "providerLabel": "Synthetic provider",
                "artifactCount": 1,
                "updatedAtUs": 1_700_000_000_000_000_u64
            },
            "assessment": {
                "assessmentId": "00000000-0000-4000-8000-000000000005",
                "caseId": "00000000-0000-4000-8000-000000000002",
                "weightProfileVersion": "ariadne-core-attribution-v1",
                "score": 180,
                "confidenceBand": "MEDIUM",
                "contributingSignals": [{
                    "signal": "EXACT_EMAIL",
                    "weight": 180,
                    "evidenceArtifactIds": ["00000000-0000-4000-8000-000000000003"]
                }],
                "contradictions": [],
                "missingEvidence": [{
                    "signal": "SAME_PHOTOGRAPH",
                    "potentialWeight": 120
                }],
                "recommendedNextEvidence": ["SAME_PHOTOGRAPH"],
                "humanReviewRequired": true
            },
            "artifacts": [{
                "artifactId": "00000000-0000-4000-8000-000000000003",
                "kind": "SCREENSHOT",
                "contentSha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "capturedAtUs": 1_700_000_000_000_000_u64,
                "sourceUrl": "https://phase5.example.invalid/profile",
                "httpStatus": 200,
                "redirectCount": 0,
                "providerId": "synthetic-provider",
                "runId": "00000000-0000-4000-8000-000000000004",
                "viewport": {
                    "width": 1440,
                    "height": 900,
                    "deviceScaleMicros": 2_000_000
                },
                "captureMethod": "BROWSER_CAPTURE",
                "encryptedAtRest": true,
                "integrityStatus": "VERIFIED",
                "derivativeCount": 1
            }],
            "humanDecision": null
        })
    }

    #[test]
    fn phase5_finding_validation_binds_profiles_evidence_scores_and_decisions() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let finding_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let valid: CorePhase5FindingDetailResult =
            serde_json::from_value(synthetic_phase5_detail_json()).unwrap();
        validate_phase5_finding_detail(&valid, profile_id, finding_id).unwrap();

        assert!(matches!(
            validate_phase5_finding_detail(&valid, Uuid::new_v4(), finding_id),
            Err(CoreError::InvalidPhase5Response)
        ));

        let mut inconsistent_score = synthetic_phase5_detail_json();
        inconsistent_score["assessment"]["score"] = json!(181);
        let inconsistent_score = serde_json::from_value(inconsistent_score).unwrap();
        assert!(matches!(
            validate_phase5_finding_detail(&inconsistent_score, profile_id, finding_id),
            Err(CoreError::InvalidPhase5Response)
        ));

        let mut unavailable_reference = synthetic_phase5_detail_json();
        unavailable_reference["assessment"]["contributingSignals"][0]["evidenceArtifactIds"][0] =
            json!("00000000-0000-4000-8000-000000000099");
        let unavailable_reference = serde_json::from_value(unavailable_reference).unwrap();
        assert!(matches!(
            validate_phase5_finding_detail(&unavailable_reference, profile_id, finding_id),
            Err(CoreError::InvalidPhase5Response)
        ));

        let mut automatic_decision = synthetic_phase5_detail_json();
        automatic_decision["finding"]["attributionState"] = json!("PROBABLE");
        automatic_decision["humanDecision"] = json!({
            "decisionId": "00000000-0000-4000-8000-000000000006",
            "assessmentId": "00000000-0000-4000-8000-000000000005",
            "state": "POSSIBLE",
            "actorLabel": "Local user",
            "decidedAtUs": 1_700_000_000_000_001_u64,
            "weightProfileVersion": "ariadne-core-attribution-v1",
            "supersedesDecisionId": null,
            "revision": 1
        });
        let automatic_decision = serde_json::from_value(automatic_decision).unwrap();
        assert!(matches!(
            validate_phase5_finding_detail(&automatic_decision, profile_id, finding_id),
            Err(CoreError::InvalidPhase5Response)
        ));
    }

    #[test]
    fn phase5_finding_validation_rejects_unsafe_artifacts_and_unbounded_lists() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let finding_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();

        let mut unsafe_url = synthetic_phase5_detail_json();
        unsafe_url["artifacts"][0]["sourceUrl"] =
            json!("https://phase5.example.invalid/profile?token=synthetic-secret");
        let unsafe_url = serde_json::from_value(unsafe_url).unwrap();
        assert!(matches!(
            validate_phase5_finding_detail(&unsafe_url, profile_id, finding_id),
            Err(CoreError::InvalidPhase5Response)
        ));

        let detail_json = synthetic_phase5_detail_json();
        let list: CorePhase5FindingListResult = serde_json::from_value(json!({
            "profileId": detail_json["profileId"],
            "findings": [detail_json["finding"], detail_json["finding"]],
            "hasMore": false
        }))
        .unwrap();
        assert!(matches!(
            validate_phase5_finding_list(&list, profile_id, 100),
            Err(CoreError::InvalidPhase5Response)
        ));

        assert!(matches!(
            validate_phase5_finding_list_request(&CorePhase5FindingListRequest {
                profile_id,
                limit: 101,
            }),
            Err(CoreError::InvalidPhase5Request)
        ));
    }

    fn synthetic_phase5_manual_finding_json() -> serde_json::Value {
        let missing_signals = [
            "EXACT_EMAIL",
            "RECOVERY_RELATIONSHIP",
            "EXACT_LEGAL_NAME",
            "SAME_UNCOMMON_USERNAME",
            "SAME_PHOTOGRAPH",
            "SAME_ORGANISATION",
            "SAME_EDUCATION",
            "SAME_LOCATION",
            "SAME_PROJECT",
            "SAME_LINKED_DOMAIN",
            "SAME_WRITING_PROFILE_LINKS",
            "CHRONOLOGICAL_COMPATIBILITY",
            "USER_CONFIRMATION",
            "IMMUTABLE_PLATFORM_ID_CONTINUITY",
        ]
        .into_iter()
        .map(|signal| json!({"signal": signal, "potentialWeight": 1}))
        .collect::<Vec<_>>();
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "finding": {
                "findingId": "00000000-0000-4000-8000-000000000002",
                "title": "Synthetic manual finding",
                "summary": "Synthetic local observation requiring review.",
                "outcome": "MANUAL_REVIEW_REQUIRED",
                "severity": "LOW",
                "visibility": "UNKNOWN",
                "attributionState": null,
                "confidenceBand": "LOW",
                "score": 0,
                "humanReviewRequired": true,
                "providerLabel": "Synthetic provider",
                "artifactCount": 0,
                "updatedAtUs": 1_700_000_000_000_000_u64
            },
            "assessment": {
                "assessmentId": "00000000-0000-4000-8000-000000000003",
                "caseId": "00000000-0000-4000-8000-000000000002",
                "weightProfileVersion": "ariadne-core-attribution-v1",
                "score": 0,
                "confidenceBand": "LOW",
                "contributingSignals": [],
                "contradictions": [],
                "missingEvidence": missing_signals,
                "recommendedNextEvidence": [
                    "EXACT_EMAIL",
                    "RECOVERY_RELATIONSHIP",
                    "EXACT_LEGAL_NAME",
                    "SAME_UNCOMMON_USERNAME",
                    "SAME_PHOTOGRAPH"
                ],
                "humanReviewRequired": true
            },
            "artifacts": [],
            "humanDecision": null
        })
    }

    #[test]
    fn phase5_manual_finding_validation_binds_neutral_assessment_and_request_fields() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let mut request = CorePhase5ManualFindingCreateRequest {
            profile_id,
            title: "Synthetic manual finding".to_owned(),
            summary: "Synthetic local observation requiring review.".to_owned(),
            outcome: CorePhase5CheckOutcome::ManualReviewRequired,
            severity: CorePhase5Severity::Low,
            visibility: CorePhase5Visibility::Unknown,
            provider_id: "synthetic-provider".to_owned(),
            provider_label: "Synthetic provider".to_owned(),
        };
        validate_phase5_manual_finding_request(&request).unwrap();
        request.title = " surrounding whitespace ".to_owned();
        assert!(matches!(
            validate_phase5_manual_finding_request(&request),
            Err(CoreError::InvalidPhase5Request)
        ));
        request.title = "Synthetic manual finding".to_owned();
        request.provider_id = "synthetic/provider".to_owned();
        assert!(matches!(
            validate_phase5_manual_finding_request(&request),
            Err(CoreError::InvalidPhase5Request)
        ));

        let result: CorePhase5FindingDetailResult =
            serde_json::from_value(synthetic_phase5_manual_finding_json()).unwrap();
        validate_phase5_manual_finding_result(
            &result,
            profile_id,
            "Synthetic manual finding",
            "Synthetic local observation requiring review.",
            CorePhase5CheckOutcome::ManualReviewRequired,
            CorePhase5Severity::Low,
            CorePhase5Visibility::Unknown,
            "Synthetic provider",
        )
        .unwrap();

        let mut incomplete_missing = synthetic_phase5_manual_finding_json();
        incomplete_missing["assessment"]["missingEvidence"]
            .as_array_mut()
            .unwrap()
            .pop();
        let incomplete_missing = serde_json::from_value(incomplete_missing).unwrap();
        assert!(matches!(
            validate_phase5_manual_finding_result(
                &incomplete_missing,
                profile_id,
                "Synthetic manual finding",
                "Synthetic local observation requiring review.",
                CorePhase5CheckOutcome::ManualReviewRequired,
                CorePhase5Severity::Low,
                CorePhase5Visibility::Unknown,
                "Synthetic provider",
            ),
            Err(CoreError::InvalidPhase5Response)
        ));

        let mut nonneutral = synthetic_phase5_manual_finding_json();
        nonneutral["finding"]["score"] = json!(1);
        nonneutral["assessment"]["score"] = json!(1);
        let nonneutral = serde_json::from_value(nonneutral).unwrap();
        assert!(matches!(
            validate_phase5_manual_finding_result(
                &nonneutral,
                profile_id,
                "Synthetic manual finding",
                "Synthetic local observation requiring review.",
                CorePhase5CheckOutcome::ManualReviewRequired,
                CorePhase5Severity::Low,
                CorePhase5Visibility::Unknown,
                "Synthetic provider",
            ),
            Err(CoreError::InvalidPhase5Response)
        ));

        assert!(matches!(
            validate_phase5_manual_finding_result(
                &result,
                profile_id,
                "Different title",
                "Synthetic local observation requiring review.",
                CorePhase5CheckOutcome::ManualReviewRequired,
                CorePhase5Severity::Low,
                CorePhase5Visibility::Unknown,
                "Synthetic provider",
            ),
            Err(CoreError::InvalidPhase5Response)
        ));
    }

    #[test]
    fn phase5_write_validation_binds_content_and_append_only_decisions() {
        let import: CorePhase5ManualEvidenceImportRequest = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "findingId": "00000000-0000-4000-8000-000000000002",
            "kind": "SCREENSHOT",
            "contentBase64": STANDARD.encode(b"synthetic evidence"),
            "viewport": {
                "width": 1440,
                "height": 900,
                "deviceScaleMicros": 2_000_000
            },
            "metadata": [{"key": "capture.source", "value": "Synthetic local import"}]
        }))
        .unwrap();
        validate_phase5_manual_import_request(&import).unwrap();

        let mut malformed = serde_json::to_value(&import).unwrap();
        malformed["contentBase64"] = json!("not-canonical");
        let malformed = serde_json::from_value(malformed).unwrap();
        assert!(matches!(
            validate_phase5_manual_import_request(&malformed),
            Err(CoreError::InvalidPhase5Request)
        ));

        let decision: CorePhase5AttributionDecisionRequest = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "findingId": "00000000-0000-4000-8000-000000000002",
            "assessmentId": "00000000-0000-4000-8000-000000000003",
            "state": "PROBABLE",
            "expectedPreviousDecisionId": null,
            "expectedPreviousRevision": 0
        }))
        .unwrap();
        validate_phase5_attribution_decision_request(&decision).unwrap();
        let result: CorePhase5AttributionDecisionResult = serde_json::from_value(json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "findingId": "00000000-0000-4000-8000-000000000002",
            "assessmentId": "00000000-0000-4000-8000-000000000003",
            "decisionId": "00000000-0000-4000-8000-000000000004",
            "state": "PROBABLE",
            "actorLabel": "Local user",
            "decidedAtUs": 1_700_000_000_000_000_u64,
            "weightProfileVersion": "ariadne-core-attribution-v1",
            "supersedesDecisionId": null,
            "revision": 1
        }))
        .unwrap();
        validate_phase5_attribution_decision_result(
            &result,
            decision.profile_id,
            decision.finding_id,
            decision.assessment_id,
            decision.state,
            None,
            0,
        )
        .unwrap();
        assert!(matches!(
            validate_phase5_attribution_decision_result(
                &result,
                decision.profile_id,
                decision.finding_id,
                decision.assessment_id,
                decision.state,
                Some(Uuid::new_v4()),
                1,
            ),
            Err(CoreError::InvalidPhase5Response)
        ));
    }

    fn synthetic_phase6_local_checkpoint_request_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "runState": "PARTIAL",
            "providerCoverage": [
                {"providerId": "synthetic-provider", "state": "COMPLETE"},
                {"providerId": "synthetic-provider-2", "state": "CHECK_FAILED"}
            ]
        })
    }

    fn synthetic_phase6_local_checkpoint_result_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "runId": "00000000-0000-4000-8000-000000000002",
            "sequence": 2,
            "capturedAtUs": 1_700_000_000_000_000_u64,
            "runState": "PARTIAL",
            "findingCount": 1,
            "providerCount": 2,
            "localOnly": true
        })
    }

    #[test]
    fn phase6_local_checkpoint_validation_binds_profile_coverage_and_result() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let request: CorePhase6LocalCheckpointRequest =
            serde_json::from_value(synthetic_phase6_local_checkpoint_request_json()).unwrap();
        validate_phase6_local_checkpoint_request(&request).unwrap();

        let result: CorePhase6LocalCheckpointResult =
            serde_json::from_value(synthetic_phase6_local_checkpoint_result_json()).unwrap();
        validate_phase6_local_checkpoint_result(
            &result,
            profile_id,
            CorePhase6SnapshotRunState::Partial,
            2,
        )
        .unwrap();

        let mut duplicate_coverage = synthetic_phase6_local_checkpoint_request_json();
        duplicate_coverage["providerCoverage"][1]["providerId"] = json!("synthetic-provider");
        let duplicate_coverage = serde_json::from_value(duplicate_coverage).unwrap();
        assert!(matches!(
            validate_phase6_local_checkpoint_request(&duplicate_coverage),
            Err(CoreError::InvalidPhase6Request)
        ));

        let mut mismatched_state = synthetic_phase6_local_checkpoint_result_json();
        mismatched_state["runState"] = json!("COMPLETED");
        let mismatched_state = serde_json::from_value(mismatched_state).unwrap();
        assert!(matches!(
            validate_phase6_local_checkpoint_result(
                &mismatched_state,
                profile_id,
                CorePhase6SnapshotRunState::Partial,
                2,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));

        let mut mismatched_coverage = synthetic_phase6_local_checkpoint_result_json();
        mismatched_coverage["providerCount"] = json!(1);
        let mismatched_coverage = serde_json::from_value(mismatched_coverage).unwrap();
        assert!(matches!(
            validate_phase6_local_checkpoint_result(
                &mismatched_coverage,
                profile_id,
                CorePhase6SnapshotRunState::Partial,
                2,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));

        let mut nonlocal_result = synthetic_phase6_local_checkpoint_result_json();
        nonlocal_result["localOnly"] = json!(false);
        let nonlocal_result = serde_json::from_value(nonlocal_result).unwrap();
        assert!(matches!(
            validate_phase6_local_checkpoint_result(
                &nonlocal_result,
                profile_id,
                CorePhase6SnapshotRunState::Partial,
                2,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));
    }

    fn synthetic_phase6_comparison_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "baselineRunId": "00000000-0000-4000-8000-000000000002",
            "currentRunId": "00000000-0000-4000-8000-000000000003",
            "diffs": [{
                "stableId": "00000000-0000-4000-8000-000000000004",
                "providerId": "synthetic-provider",
                "state": "NEW",
                "previousFingerprint": null,
                "currentFingerprint": "0".repeat(64)
            }],
            "unresolvedAbsences": [],
            "coverage": [{
                "providerId": "synthetic-provider",
                "baselineState": "COMPLETE",
                "currentState": "COMPLETE"
            }],
            "lifecycles": [{
                "stableId": "00000000-0000-4000-8000-000000000004",
                "providerId": "synthetic-provider",
                "events": [{
                    "runId": "00000000-0000-4000-8000-000000000003",
                    "sequence": 2,
                    "runState": "COMPLETED",
                    "providerCoverage": "COMPLETE",
                    "observed": true,
                    "contentFingerprint": "0".repeat(64)
                }]
            }],
            "incompleteComparison": false,
            "incompleteReasons": []
        })
    }

    #[test]
    fn phase6_comparison_validation_binds_runs_lifecycles_and_fingerprints() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let baseline_run_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let current_run_id = Uuid::parse_str("00000000-0000-4000-8000-000000000003").unwrap();
        let comparison: CorePhase6ComparisonResult =
            serde_json::from_value(synthetic_phase6_comparison_json()).unwrap();
        validate_phase6_comparison(&comparison, profile_id, baseline_run_id, current_run_id)
            .unwrap();

        let mut missing_lifecycle = synthetic_phase6_comparison_json();
        missing_lifecycle["lifecycles"] = json!([]);
        let missing_lifecycle = serde_json::from_value(missing_lifecycle).unwrap();
        assert!(matches!(
            validate_phase6_comparison(
                &missing_lifecycle,
                profile_id,
                baseline_run_id,
                current_run_id,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));

        let mut mismatched_provider = synthetic_phase6_comparison_json();
        mismatched_provider["lifecycles"][0]["providerId"] = json!("other-provider");
        let mismatched_provider = serde_json::from_value(mismatched_provider).unwrap();
        assert!(matches!(
            validate_phase6_comparison(
                &mismatched_provider,
                profile_id,
                baseline_run_id,
                current_run_id,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));
    }

    fn synthetic_phase6_remediation_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "case": {
                "caseId": "00000000-0000-4000-8000-000000000002",
                "findingIds": ["00000000-0000-4000-8000-000000000003"],
                "action": "MONITOR",
                "actionDisposition": "LOCAL_ONLY",
                "status": "OPEN",
                "deadlineAtUs": null,
                "reappearanceCount": 0,
                "revision": 1,
                "updatedAtUs": 1_700_000_000_000_000_u64,
                "draftText": null,
                "evidenceReferences": ["00000000-0000-4000-8000-000000000004"],
                "providerResponses": [],
                "lastReappearanceAtUs": null,
                "createdAtUs": 1_700_000_000_000_000_u64,
                "history": [{
                    "revision": 1,
                    "eventType": "CASE_CREATED",
                    "actorLabel": "Local user",
                    "occurredAtUs": 1_700_000_000_000_000_u64,
                    "previousStatus": null,
                    "currentStatus": "OPEN",
                    "detailCode": "CASE_CREATED",
                    "subjectId": null,
                    "evidenceReferences": ["00000000-0000-4000-8000-000000000004"],
                    "note": "Synthetic local case"
                }]
            }
        })
    }

    #[test]
    fn phase6_remediation_validation_binds_history_and_nested_evidence() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let case_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let detail: CorePhase6RemediationDetailResult =
            serde_json::from_value(synthetic_phase6_remediation_json()).unwrap();
        validate_phase6_remediation_detail(&detail, profile_id, case_id).unwrap();

        let mut broken_history = synthetic_phase6_remediation_json();
        broken_history["case"]["history"][0]["previousStatus"] = json!("OPEN");
        let broken_history = serde_json::from_value(broken_history).unwrap();
        assert!(matches!(
            validate_phase6_remediation_detail(&broken_history, profile_id, case_id),
            Err(CoreError::InvalidPhase6Response)
        ));

        let mut unlinked_evidence = synthetic_phase6_remediation_json();
        unlinked_evidence["case"]["history"][0]["evidenceReferences"][0] =
            json!("00000000-0000-4000-8000-000000000099");
        let unlinked_evidence = serde_json::from_value(unlinked_evidence).unwrap();
        assert!(matches!(
            validate_phase6_remediation_detail(&unlinked_evidence, profile_id, case_id),
            Err(CoreError::InvalidPhase6Response)
        ));
    }

    #[test]
    fn phase6_mutation_request_validation_enforces_bounds_and_cross_fields() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let case_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let finding_id = Uuid::parse_str("00000000-0000-4000-8000-000000000003").unwrap();
        let evidence_id = Uuid::parse_str("00000000-0000-4000-8000-000000000004").unwrap();

        let mut create = CorePhase6RemediationCreateRequest {
            profile_id,
            finding_ids: vec![finding_id],
            action: CorePhase6RemediationAction::RequestCorrection,
            deadline_at_us: None,
            evidence_references: vec![evidence_id],
            draft_text: Some("Synthetic correction draft".to_owned()),
        };
        validate_phase6_remediation_create_request(&create).unwrap();
        create.action = CorePhase6RemediationAction::Monitor;
        assert!(matches!(
            validate_phase6_remediation_create_request(&create),
            Err(CoreError::InvalidPhase6Request)
        ));
        create.action = CorePhase6RemediationAction::RequestCorrection;
        create.finding_ids.push(finding_id);
        assert!(matches!(
            validate_phase6_remediation_create_request(&create),
            Err(CoreError::InvalidPhase6Request)
        ));

        let mut draft = CorePhase6RemediationDraftUpdateRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            draft_text: "Synthetic revised draft".to_owned(),
        };
        validate_phase6_remediation_draft_request(&draft).unwrap();
        draft.expected_revision = 256;
        assert!(matches!(
            validate_phase6_remediation_draft_request(&draft),
            Err(CoreError::InvalidPhase6Request)
        ));
        draft.expected_revision = 1;
        draft.draft_text = " surrounding whitespace ".to_owned();
        assert!(matches!(
            validate_phase6_remediation_draft_request(&draft),
            Err(CoreError::InvalidPhase6Request)
        ));

        let mut status = CorePhase6RemediationStatusTransitionRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            target_status: CorePhase6RemediationStatus::InProgress,
            note: Some("Synthetic status note".to_owned()),
        };
        validate_phase6_remediation_status_request(&status).unwrap();
        status.note = Some("Synthetic\0note".to_owned());
        assert!(matches!(
            validate_phase6_remediation_status_request(&status),
            Err(CoreError::InvalidPhase6Request)
        ));

        let mut deadline = CorePhase6RemediationDeadlineUpdateRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            deadline_at_us: None,
        };
        validate_phase6_remediation_deadline_request(&deadline).unwrap();
        deadline.deadline_at_us = Some(0);
        assert!(matches!(
            validate_phase6_remediation_deadline_request(&deadline),
            Err(CoreError::InvalidPhase6Request)
        ));

        let evidence = CorePhase6RemediationEvidenceLinkRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            evidence_references: vec![evidence_id],
        };
        validate_phase6_remediation_evidence_request(&evidence).unwrap();

        let mut provider = CorePhase6RemediationProviderResponseRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            provider_id: "synthetic-provider".to_owned(),
            response_code: "REQUEST_RECEIVED".to_owned(),
            summary: "Synthetic provider summary".to_owned(),
            evidence_references: vec![evidence_id],
        };
        validate_phase6_remediation_provider_response_request(&provider).unwrap();
        provider.provider_id = "invalid provider".to_owned();
        assert!(matches!(
            validate_phase6_remediation_provider_response_request(&provider),
            Err(CoreError::InvalidPhase6Request)
        ));
        provider.provider_id = "synthetic-provider".to_owned();
        provider.response_code = "lowercase".to_owned();
        assert!(matches!(
            validate_phase6_remediation_provider_response_request(&provider),
            Err(CoreError::InvalidPhase6Request)
        ));

        let reappearance = CorePhase6RemediationReappearanceRequest {
            profile_id,
            case_id,
            expected_revision: 1,
            finding_id,
            evidence_references: vec![evidence_id],
        };
        validate_phase6_remediation_reappearance_request(&reappearance).unwrap();
    }

    #[test]
    fn phase6_mutation_response_validation_binds_revision_event_and_creation() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let case_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let finding_id = Uuid::parse_str("00000000-0000-4000-8000-000000000003").unwrap();
        let evidence_id = Uuid::parse_str("00000000-0000-4000-8000-000000000004").unwrap();

        let created: CorePhase6RemediationDetailResult =
            serde_json::from_value(synthetic_phase6_remediation_json()).unwrap();
        validate_phase6_remediation_create_result(
            &created,
            profile_id,
            &[finding_id],
            CorePhase6RemediationAction::Monitor,
            None,
            &[evidence_id],
            None,
        )
        .unwrap();
        assert!(matches!(
            validate_phase6_remediation_create_result(
                &created,
                profile_id,
                &[finding_id],
                CorePhase6RemediationAction::PreserveEvidence,
                None,
                &[evidence_id],
                None,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));

        let mut mutation_json = synthetic_phase6_remediation_json();
        mutation_json["case"]["action"] = json!("REQUEST_CORRECTION");
        mutation_json["case"]["actionDisposition"] = json!("DRAFT");
        mutation_json["case"]["draftText"] = json!("Synthetic revised draft");
        mutation_json["case"]["revision"] = json!(2);
        mutation_json["case"]["updatedAtUs"] = json!(1_700_000_000_000_001_u64);
        mutation_json["case"]["history"]
            .as_array_mut()
            .unwrap()
            .push(json!({
                "revision": 2,
                "eventType": "DRAFT_UPDATED",
                "actorLabel": "Local user",
                "occurredAtUs": 1_700_000_000_000_001_u64,
                "previousStatus": "OPEN",
                "currentStatus": "OPEN",
                "detailCode": "DRAFT_UPDATED",
                "subjectId": null,
                "evidenceReferences": [],
                "note": null
            }));
        let mutation: CorePhase6RemediationDetailResult =
            serde_json::from_value(mutation_json).unwrap();
        validate_phase6_mutation_result(
            &mutation,
            profile_id,
            case_id,
            1,
            CorePhase6RemediationEventType::DraftUpdated,
        )
        .unwrap();
        assert!(matches!(
            validate_phase6_mutation_result(
                &mutation,
                profile_id,
                case_id,
                1,
                CorePhase6RemediationEventType::StatusChanged,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));
        assert!(matches!(
            validate_phase6_mutation_result(
                &mutation,
                profile_id,
                case_id,
                2,
                CorePhase6RemediationEventType::DraftUpdated,
            ),
            Err(CoreError::InvalidPhase6Response)
        ));
    }

    fn sha256_hex(content: &[u8]) -> String {
        Sha256::digest(content)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    fn synthetic_local_report_result_json() -> serde_json::Value {
        let json_content = r#"{"schema":"ariadne.local-report","version":1}"#;
        let markdown_content = "# Synthetic local report\n";
        json!({
            "profileId": "00000000-0000-4000-8000-000000000001",
            "baselineRunId": "00000000-0000-4000-8000-000000000002",
            "currentRunId": "00000000-0000-4000-8000-000000000003",
            "localOnly": true,
            "artifact": {
                "filename": "report.json",
                "mediaType": "application/json",
                "byteCount": json_content.len(),
                "sha256": sha256_hex(json_content.as_bytes()),
                "schema": "ariadne.local-report",
                "version": 1,
                "mode": "FULL_EXPLICIT",
                "content": json_content
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
                    "byteCount": json_content.len(),
                    "sha256": sha256_hex(json_content.as_bytes())
                }, {
                    "filename": "report.md",
                    "mediaType": "text/markdown; charset=utf-8",
                    "byteCount": markdown_content.len(),
                    "sha256": sha256_hex(markdown_content.as_bytes())
                }]
            }
        })
    }

    #[test]
    fn local_report_validation_binds_request_artifact_manifest_hash_and_bounds() {
        let profile_id = Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap();
        let baseline_run_id = Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap();
        let current_run_id = Uuid::parse_str("00000000-0000-4000-8000-000000000003").unwrap();
        let approval_id = Uuid::parse_str("00000000-0000-4000-8000-000000000004").unwrap();

        let mut request = CoreLocalReportGenerateRequest {
            profile_id,
            baseline_run_id,
            current_run_id,
            artifact_format: CoreReportArtifactFormat::Json,
            mode: CoreReportExportMode::FullExplicit,
            full_export_approval_id: Some(approval_id),
        };
        validate_local_report_request(&request).unwrap();
        request.full_export_approval_id = None;
        assert!(matches!(
            validate_local_report_request(&request),
            Err(CoreError::InvalidLocalReportRequest)
        ));
        request.mode = CoreReportExportMode::Redacted;
        validate_local_report_request(&request).unwrap();
        request.full_export_approval_id = Some(approval_id);
        assert!(matches!(
            validate_local_report_request(&request),
            Err(CoreError::InvalidLocalReportRequest)
        ));
        request.full_export_approval_id = None;
        request.current_run_id = baseline_run_id;
        assert!(matches!(
            validate_local_report_request(&request),
            Err(CoreError::InvalidLocalReportRequest)
        ));

        let result: CoreLocalReportGenerateResult =
            serde_json::from_value(synthetic_local_report_result_json()).unwrap();
        validate_local_report_result(
            &result,
            profile_id,
            baseline_run_id,
            current_run_id,
            CoreReportArtifactFormat::Json,
            CoreReportExportMode::FullExplicit,
            Some(approval_id),
        )
        .unwrap();

        let mut wrong_hash = synthetic_local_report_result_json();
        wrong_hash["artifact"]["sha256"] = json!("0".repeat(64));
        let wrong_hash = serde_json::from_value(wrong_hash).unwrap();
        assert!(matches!(
            validate_local_report_result(
                &wrong_hash,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Json,
                CoreReportExportMode::FullExplicit,
                Some(approval_id),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));

        let mut descriptor_mismatch = synthetic_local_report_result_json();
        descriptor_mismatch["manifest"]["artifacts"][0]["byteCount"] = json!(1);
        let descriptor_mismatch = serde_json::from_value(descriptor_mismatch).unwrap();
        assert!(matches!(
            validate_local_report_result(
                &descriptor_mismatch,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Json,
                CoreReportExportMode::FullExplicit,
                Some(approval_id),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));

        let mut duplicate_artifact = synthetic_local_report_result_json();
        duplicate_artifact["manifest"]["artifacts"][1]["filename"] = json!("report.json");
        duplicate_artifact["manifest"]["artifacts"][1]["mediaType"] = json!("application/json");
        let duplicate_artifact = serde_json::from_value(duplicate_artifact).unwrap();
        assert!(matches!(
            validate_local_report_result(
                &duplicate_artifact,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Json,
                CoreReportExportMode::FullExplicit,
                Some(approval_id),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));

        assert!(matches!(
            validate_local_report_result(
                &result,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Markdown,
                CoreReportExportMode::FullExplicit,
                Some(approval_id),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));
        assert!(matches!(
            validate_local_report_result(
                &result,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Json,
                CoreReportExportMode::FullExplicit,
                Some(Uuid::new_v4()),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));

        let oversized_content =
            format!("\"{}\"", "x".repeat(MAX_LOCAL_REPORT_RESPONSE_BYTES - 102));
        let oversized_digest = sha256_hex(oversized_content.as_bytes());
        let mut oversized = synthetic_local_report_result_json();
        oversized["artifact"]["content"] = json!(oversized_content);
        oversized["artifact"]["byteCount"] = json!(MAX_LOCAL_REPORT_RESPONSE_BYTES - 100);
        oversized["artifact"]["sha256"] = json!(oversized_digest);
        oversized["manifest"]["artifacts"][0]["byteCount"] =
            json!(MAX_LOCAL_REPORT_RESPONSE_BYTES - 100);
        oversized["manifest"]["artifacts"][0]["sha256"] = json!(oversized_digest);
        let oversized: CoreLocalReportGenerateResult = serde_json::from_value(oversized).unwrap();
        assert!(serde_json::to_vec(&oversized).unwrap().len() > MAX_LOCAL_REPORT_RESPONSE_BYTES);
        assert!(matches!(
            validate_local_report_result(
                &oversized,
                profile_id,
                baseline_run_id,
                current_run_id,
                CoreReportArtifactFormat::Json,
                CoreReportExportMode::FullExplicit,
                Some(approval_id),
            ),
            Err(CoreError::InvalidLocalReportResponse)
        ));
    }

    fn synthetic_graph_snapshot_json() -> serde_json::Value {
        json!({
            "profileId": "00000000-0000-0000-0000-000000000001",
            "nodes": [
                {
                    "nodeId": "00000000-0000-0000-0000-000000000002",
                    "nodeType": "IDENTITY",
                    "displayLabel": "Synthetic identity",
                    "sensitivity": "SENSITIVE",
                    "entityId": null
                },
                {
                    "nodeId": "00000000-0000-0000-0000-000000000005",
                    "nodeType": "IDENTITY",
                    "displayLabel": "Synthetic linked identity",
                    "sensitivity": "SENSITIVE",
                    "entityId": null
                }
            ],
            "edges": [{
                "edgeId": "00000000-0000-0000-0000-000000000003",
                "fromNodeId": "00000000-0000-0000-0000-000000000002",
                "toNodeId": "00000000-0000-0000-0000-000000000005",
                "edgeType": "RELATED_TO",
                "confidenceMicros": 900_000,
                "originType": "DETERMINISTIC",
                "explanation": "Synthetic relationship",
                "supportCount": 1,
                "contradictionCount": 0,
                "evidence": [{
                    "sourceId": "00000000-0000-0000-0000-000000000004",
                    "segmentOrdinal": 0,
                    "sourceSpanStart": 4,
                    "sourceSpanEnd": 16,
                    "disposition": "SUPPORTS",
                    "confidenceMicros": 900_000,
                    "visibility": "PRIVATE_ONLY",
                    "observedAtUs": 1_700_000_000_000_000_u64,
                    "originType": "DETERMINISTIC",
                    "explanation": "Synthetic supporting observation"
                }],
                "evidenceTruncated": false
            }],
            "truncated": false
        })
    }

    #[test]
    fn graph_evidence_validation_enforces_bounds_and_truncation_contract() {
        let profile_id = Uuid::from_u128(1);
        let valid: CoreGraphSnapshot =
            serde_json::from_value(synthetic_graph_snapshot_json()).unwrap();
        validate_graph_snapshot(&valid, profile_id, 200).unwrap();

        let mut inconsistent_count = synthetic_graph_snapshot_json();
        inconsistent_count["edges"][0]["supportCount"] = json!(2);
        let inconsistent_count: CoreGraphSnapshot =
            serde_json::from_value(inconsistent_count).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&inconsistent_count, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut unsafe_timestamp = synthetic_graph_snapshot_json();
        unsafe_timestamp["edges"][0]["evidence"][0]["observedAtUs"] =
            json!(MAX_SAFE_JAVASCRIPT_INTEGER + 1);
        let unsafe_timestamp: CoreGraphSnapshot = serde_json::from_value(unsafe_timestamp).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&unsafe_timestamp, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut oversized_explanation = synthetic_graph_snapshot_json();
        oversized_explanation["edges"][0]["evidence"][0]["explanation"] = json!("x".repeat(161));
        let oversized_explanation: CoreGraphSnapshot =
            serde_json::from_value(oversized_explanation).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&oversized_explanation, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut invalid_span = synthetic_graph_snapshot_json();
        invalid_span["edges"][0]["evidence"][0]["sourceSpanEnd"] = json!(4);
        let invalid_span: CoreGraphSnapshot = serde_json::from_value(invalid_span).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&invalid_span, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut half_present_span = synthetic_graph_snapshot_json();
        half_present_span["edges"][0]["evidence"][0]["sourceSpanEnd"] = serde_json::Value::Null;
        let half_present_span: CoreGraphSnapshot =
            serde_json::from_value(half_present_span).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&half_present_span, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut empty_evidence = synthetic_graph_snapshot_json();
        empty_evidence["edges"][0]["supportCount"] = json!(0);
        empty_evidence["edges"][0]["evidence"] = json!([]);
        let empty_evidence: CoreGraphSnapshot = serde_json::from_value(empty_evidence).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&empty_evidence, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut self_edge = synthetic_graph_snapshot_json();
        self_edge["edges"][0]["toNodeId"] = self_edge["edges"][0]["fromNodeId"].clone();
        let self_edge: CoreGraphSnapshot = serde_json::from_value(self_edge).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&self_edge, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));

        let mut too_many_edges = synthetic_graph_snapshot_json();
        let edge_template = too_many_edges["edges"][0].clone();
        let edges = too_many_edges["edges"].as_array_mut().unwrap();
        edges.clear();
        for index in 0..=MAX_GRAPH_EDGES {
            let mut edge = edge_template.clone();
            edge["edgeId"] = json!(Uuid::from_u128(100 + index as u128).to_string());
            edges.push(edge);
        }
        let too_many_edges: CoreGraphSnapshot = serde_json::from_value(too_many_edges).unwrap();
        assert!(matches!(
            validate_graph_snapshot(&too_many_edges, profile_id, 200),
            Err(CoreError::InvalidPhase3Response)
        ));
    }

    #[tokio::test]
    async fn phase3_commands_require_an_unlocked_supervisor() {
        let supervisor = CoreSupervisor::new();
        let list_error = supervisor.list_profiles().await.unwrap_err();
        assert_eq!(list_error.code, "CORE_NOT_READY");
        let error = supervisor
            .create_profile(CoreProfileCreateRequest {
                idempotency_key: "synthetic_profile_0001".to_owned(),
                display_label: "Synthetic profile".to_owned(),
                purpose: "Local synthetic test".to_owned(),
            })
            .await
            .unwrap_err();
        assert_eq!(error.code, "CORE_NOT_READY");
        let origin_error = supervisor
            .list_entity_origins(CoreEntityOriginPageRequest {
                profile_id: Uuid::new_v4(),
                entity_id: Uuid::new_v4(),
                offset: 0,
                limit: 12,
            })
            .await
            .unwrap_err();
        assert_eq!(origin_error.code, "CORE_NOT_READY");
    }

    struct PackagedTestTree {
        root: PathBuf,
        executable: PathBuf,
        sidecar: PathBuf,
    }

    impl PackagedTestTree {
        fn new() -> Self {
            let nonce = Uuid::new_v4().simple().to_string();
            let root = PathBuf::from(format!("/tmp/ariadne-sidecar-{}", &nonce[..8]));
            fs::create_dir(&root).unwrap();
            fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
            let executable = root.join("Codename Ariadne");
            fs::write(&executable, b"application").unwrap();
            fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
            let sidecar = root.join(PACKAGED_SIDECAR_FILENAME);
            Self {
                root,
                executable,
                sidecar,
            }
        }

        fn write_sidecar(&self, mode: u32) {
            fs::write(&self.sidecar, b"sidecar").unwrap();
            fs::set_permissions(&self.sidecar, fs::Permissions::from_mode(mode)).unwrap();
        }
    }

    impl Drop for PackagedTestTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn readiness(value: serde_json::Value) -> ReadinessMessage {
        serde_json::from_value(value).unwrap()
    }

    #[test]
    fn development_spawn_is_exact_and_contains_no_session_secret() {
        let spec = DevelopmentSpawnSpec::from_manifest_dir().unwrap();
        let args: Vec<_> = spec
            .args
            .iter()
            .map(|value| value.to_string_lossy().into_owned())
            .collect();

        assert_eq!(spec.program, OsStr::new("uv"));
        assert_eq!(
            args,
            [
                "run",
                "--project",
                "services/core",
                "ariadne-core",
                "serve",
                "--bootstrap-stdin",
            ]
        );
        assert!(!spec.contains_value(TEST_TOKEN));
        assert!(spec.explicit_environment.is_empty());
    }

    #[test]
    fn packaged_spawn_is_exact_and_contains_no_session_secret() {
        let tree = PackagedTestTree::new();
        tree.write_sidecar(0o700);
        let spec = PackagedSpawnSpec::from_executable_path(&tree.executable).unwrap();
        let args: Vec<_> = spec
            .args
            .iter()
            .map(|value| value.to_string_lossy().into_owned())
            .collect();
        let command = spec.command();

        assert_eq!(spec.program, tree.sidecar);
        assert_eq!(spec.current_dir, tree.root);
        assert_eq!(args, ["serve", "--bootstrap-stdin", "--transport", "uds"]);
        assert!(!spec.contains_value(TEST_TOKEN));
        assert!(command.as_std().get_envs().next().is_none());
        assert_eq!(command.as_std().get_program(), tree.sidecar.as_os_str());
    }

    #[tokio::test]
    async fn packaged_command_clears_inherited_environment() {
        assert!(std::env::var_os("PATH").is_some());
        let tree = PackagedTestTree::new();
        let probe = PackagedSpawnSpec {
            program: PathBuf::from("/usr/bin/env"),
            args: Vec::new(),
            current_dir: tree.root.clone(),
        };
        let output = probe.command().output().await.unwrap();

        assert!(output.status.success());
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }

    #[test]
    fn packaged_sidecar_path_rejects_missing_and_alternate_names() {
        let tree = PackagedTestTree::new();
        fs::write(
            tree.root.join("ariadne-core-aarch64-apple-darwin"),
            b"alternate",
        )
        .unwrap();

        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar("sidecar is missing"))
        ));
    }

    #[test]
    fn packaged_sidecar_path_rejects_symlink_and_non_regular_file() {
        let tree = PackagedTestTree::new();
        let target = tree.root.join("sidecar-target");
        fs::write(&target, b"target").unwrap();
        fs::set_permissions(&target, fs::Permissions::from_mode(0o700)).unwrap();
        symlink(&target, &tree.sidecar).unwrap();

        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar(
                "sidecar must not be a symbolic link"
            ))
        ));

        fs::remove_file(&tree.sidecar).unwrap();
        fs::create_dir(&tree.sidecar).unwrap();
        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar(
                "sidecar is not a regular file"
            ))
        ));
    }

    #[test]
    fn packaged_sidecar_path_rejects_unsafe_permissions() {
        let tree = PackagedTestTree::new();
        tree.write_sidecar(0o720);
        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar(
                "sidecar is writable by group or others"
            ))
        ));

        fs::set_permissions(&tree.sidecar, fs::Permissions::from_mode(0o702)).unwrap();
        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar(
                "sidecar is writable by group or others"
            ))
        ));

        fs::set_permissions(&tree.sidecar, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(matches!(
            PackagedSpawnSpec::from_executable_path(&tree.executable),
            Err(CoreError::InvalidPackagedSidecar(
                "sidecar is not executable"
            ))
        ));
    }

    #[test]
    fn development_endpoint_accepts_only_exact_loopback() {
        let valid = readiness(json!({
          "status": "ready",
          "transport": "tcp",
          "host": "127.0.0.1",
          "port": 43119,
          "contract_version": 1
        }));
        assert_eq!(
            CoreEndpoint::from_readiness(valid, RuntimeMode::Development).unwrap(),
            CoreEndpoint::Loopback { port: 43119 }
        );

        for host in ["0.0.0.0", "::1", "localhost", "192.168.1.2"] {
            let invalid = readiness(json!({
              "status": "ready",
              "transport": "tcp",
              "host": host,
              "port": 43119,
              "contract_version": 1
            }));
            assert!(CoreEndpoint::from_readiness(invalid, RuntimeMode::Development).is_err());
        }
    }

    #[test]
    fn packaged_tcp_is_always_rejected() {
        let readiness = readiness(json!({
          "status": "ready",
          "transport": "tcp",
          "host": "127.0.0.1",
          "port": 43119,
          "contract_version": 1
        }));
        assert!(matches!(
            CoreEndpoint::from_readiness(readiness, RuntimeMode::Packaged),
            Err(CoreError::PackagedTcpForbidden)
        ));
    }

    #[test]
    fn packaged_uds_requires_socket_0600_inside_directory_0700() {
        let nonce = Uuid::new_v4().simple().to_string();
        let root = PathBuf::from(format!("/tmp/ariadne-uds-{}", &nonce[..8]));
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let socket_path = root.join("core.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();
        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600)).unwrap();

        let valid = readiness(json!({
          "status": "ready",
          "transport": "uds",
          "socket_path": socket_path,
          "contract_version": 1
        }));
        assert!(matches!(
            CoreEndpoint::from_readiness(valid, RuntimeMode::Packaged),
            Ok(CoreEndpoint::UnixSocket { .. })
        ));

        fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o666)).unwrap();
        let invalid = readiness(json!({
          "status": "ready",
          "transport": "uds",
          "socket_path": socket_path,
          "contract_version": 1
        }));
        assert!(CoreEndpoint::from_readiness(invalid, RuntimeMode::Packaged).is_err());

        drop(listener);
        fs::remove_file(&socket_path).unwrap();
        fs::remove_dir(&root).unwrap();
    }

    #[tokio::test]
    async fn bounded_readiness_rejects_oversized_output() {
        let (mut writer, mut reader) = tokio::io::duplex(MAX_READINESS_BYTES * 2);
        let write_task = tokio::spawn(async move {
            writer
                .write_all(&vec![b'x'; MAX_READINESS_BYTES + 1])
                .await
                .unwrap();
            writer.write_all(b"\n").await.unwrap();
        });

        assert!(matches!(
            read_bounded_line(&mut reader, MAX_READINESS_BYTES).await,
            Err(CoreError::ReadinessTooLarge)
        ));
        write_task.abort();
    }

    #[tokio::test]
    async fn supervisor_starts_fail_closed_and_without_endpoint_state() {
        let supervisor = CoreSupervisor::new();
        assert_eq!(
            supervisor.snapshot(),
            SupervisorSnapshot {
                state: CoreLifecycleState::NotStarted,
                has_endpoint: false,
                has_credential: false,
                has_key_lease_broker: false,
                has_key_lease_handle: false,
            }
        );

        let error = supervisor.session().await.unwrap_err();
        assert_eq!(error.code, "CORE_NOT_READY");
        assert_eq!(supervisor.snapshot().state, CoreLifecycleState::NotStarted);
    }

    #[test]
    fn system_lock_synchronously_revokes_state_and_coalesces_duplicates() {
        let supervisor = CoreSupervisor::new();
        {
            let mut inner = supervisor.lock();
            inner.state = CoreLifecycleState::Ready;
            inner.vault_unlocked = true;
        }

        let plan = supervisor.begin_system_lock().unwrap();
        assert!(plan.child.is_none());
        {
            let inner = supervisor.lock();
            assert_eq!(inner.state, CoreLifecycleState::Stopping);
            assert!(!inner.vault_unlocked);
            assert!(inner.endpoint.is_none());
            assert!(inner.credential.is_none());
            assert!(inner.key_lease_broker.is_none());
            assert!(inner.key_lease_handle.is_none());
            assert!(inner.policy_restart_pending);
        }
        assert!(supervisor.begin_system_lock().is_none());
        assert!(
            supervisor
                .finish_lease_operation(CoreLifecycleState::Unlocking)
                .is_err()
        );
        assert!(!supervisor.lock().vault_unlocked);
    }

    #[test]
    fn crash_restart_budget_allows_only_three_attempts_per_window() {
        let now = Instant::now();
        let mut budget = RestartBudget::default();
        assert_eq!(budget.reserve(now), Some(CRASH_RESTART_BACKOFF[0]));
        assert_eq!(
            budget.reserve(now + Duration::from_secs(1)),
            Some(CRASH_RESTART_BACKOFF[1])
        );
        assert_eq!(
            budget.reserve(now + Duration::from_secs(2)),
            Some(CRASH_RESTART_BACKOFF[2])
        );
        assert_eq!(budget.reserve(now + Duration::from_secs(3)), None);
        assert_eq!(
            budget.reserve(now + CRASH_RESTART_WINDOW),
            Some(CRASH_RESTART_BACKOFF[2])
        );
    }

    #[tokio::test]
    async fn unexpected_ready_child_exit_revokes_state_and_schedules_restart() {
        let supervisor = CoreSupervisor::new();
        let child = Command::new("/usr/bin/true").spawn().unwrap();
        {
            let mut inner = supervisor.lock();
            inner.state = CoreLifecycleState::Ready;
            inner.vault_unlocked = true;
            inner.child = Some(child);
        }
        tokio::time::sleep(Duration::from_millis(25)).await;

        let exit = supervisor.observe_child_exit().unwrap();
        assert!(exit.restart);
        assert!(exit.child_to_terminate.is_none());
        let inner = supervisor.lock();
        assert_eq!(inner.state, CoreLifecycleState::Failed);
        assert!(!inner.vault_unlocked);
        assert!(inner.credential.is_none());
        assert!(inner.key_lease_handle.is_none());
        assert!(inner.restart_scheduled);
        assert_eq!(inner.last_error_code, Some("CORE_CHILD_EXITED"));
    }

    #[tokio::test]
    async fn child_exit_during_startup_revokes_state_without_restart() {
        let supervisor = CoreSupervisor::new();
        let child = Command::new("/usr/bin/true").spawn().unwrap();
        {
            let mut inner = supervisor.lock();
            inner.state = CoreLifecycleState::Starting;
            inner.credential = Some(Arc::new(SessionCredential::generate().unwrap()));
            inner.child = Some(child);
        }
        tokio::time::sleep(Duration::from_millis(25)).await;

        let exit = supervisor.observe_child_exit().unwrap();
        assert!(!exit.restart);
        assert!(exit.child_to_terminate.is_none());
        let inner = supervisor.lock();
        assert_eq!(inner.state, CoreLifecycleState::Stopped);
        assert!(inner.credential.is_none());
        assert!(inner.endpoint.is_none());
        assert!(inner.key_lease_broker.is_none());
        assert!(inner.key_lease_handle.is_none());
        assert!(!inner.restart_scheduled);
    }

    #[tokio::test]
    async fn readiness_failure_terminates_owned_child_and_revokes_startup_state() {
        let supervisor = CoreSupervisor::new();
        let child = Command::new("/bin/sleep").arg("30").spawn().unwrap();
        let pid = child.id().unwrap();
        {
            let mut inner = supervisor.lock();
            inner.state = CoreLifecycleState::Starting;
            inner.credential = Some(Arc::new(SessionCredential::generate().unwrap()));
            inner.child = Some(child);
        }

        supervisor.mark_failed(&CoreError::InvalidReadiness(
            "synthetic readiness rejection",
        ));
        let snapshot = supervisor.snapshot();
        assert_eq!(snapshot.state, CoreLifecycleState::Failed);
        assert!(!snapshot.has_endpoint);
        assert!(!snapshot.has_credential);
        assert!(!snapshot.has_key_lease_broker);
        assert!(!snapshot.has_key_lease_handle);
        assert_eq!(
            supervisor.lock().last_error_code,
            Some("CORE_READINESS_FAILED")
        );

        timeout(Duration::from_secs(2), async {
            loop {
                // SAFETY: signal 0 only checks the direct child PID captured above.
                if unsafe { libc::kill(pid as libc::pid_t, 0) } != 0 {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
    }

    #[tokio::test]
    #[allow(clippy::await_holding_lock)]
    async fn development_supervisor_completes_authenticated_typed_handshake() {
        let _fd_guard = super::super::key_lease::FD_TEST_LOCK.lock().unwrap();
        let supervisor = CoreSupervisor::new();
        supervisor.start().await.unwrap();
        assert_eq!(
            supervisor.snapshot(),
            SupervisorSnapshot {
                state: CoreLifecycleState::Ready,
                has_endpoint: true,
                has_credential: true,
                has_key_lease_broker: true,
                has_key_lease_handle: true,
            }
        );

        let capabilities = supervisor.capabilities().await.unwrap();
        assert_eq!(capabilities.data.versions.contract, CONTRACT_VERSION);
        assert!(matches!(
            capabilities.data.transport,
            super::super::contract::CoreTransport::DevLoopback
        ));

        let session = supervisor.session().await.unwrap();
        assert!(session.data.authenticated_transport);
        assert!(matches!(
            session.data.lock_state,
            super::super::contract::SessionLockState::Locked
        ));

        supervisor.stop().await;
        assert_eq!(
            supervisor.snapshot(),
            SupervisorSnapshot {
                state: CoreLifecycleState::Stopped,
                has_endpoint: false,
                has_credential: false,
                has_key_lease_broker: false,
                has_key_lease_handle: false,
            }
        );
    }

    #[tokio::test]
    #[allow(clippy::await_holding_lock)]
    async fn unexpected_ready_sidecar_exit_restarts_once_into_locked_state() {
        let _fd_guard = super::super::key_lease::FD_TEST_LOCK.lock().unwrap();
        let supervisor = CoreSupervisor::new();
        supervisor.start().await.unwrap();
        supervisor.spawn_crash_monitor();
        let pid = supervisor.lock().child.as_ref().unwrap().id().unwrap();
        // SAFETY: pid is the live direct child owned by this supervisor test.
        assert_eq!(unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) }, 0);

        timeout(Duration::from_secs(30), async {
            loop {
                let restarted = {
                    let inner = supervisor.lock();
                    inner.state == CoreLifecycleState::Ready
                        && inner.restart_budget.attempts.len() == 1
                };
                if restarted {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .unwrap();
        let session = supervisor.session().await.unwrap();
        assert_eq!(session.data.lock_state, SessionLockState::Locked);
        assert!(matches!(
            session.data.vault_state,
            VaultState::NoVault | VaultState::Locked
        ));
        supervisor.shutdown().await;
    }

    #[tokio::test]
    #[allow(clippy::await_holding_lock)]
    async fn development_create_lock_unlock_uses_real_cross_language_lease() {
        let _fd_guard = super::super::key_lease::FD_TEST_LOCK.lock().unwrap();
        let home = PathBuf::from(format!(
            "/tmp/ariadne-lifecycle-{}",
            Uuid::new_v4().simple()
        ));
        fs::create_dir(&home).unwrap();
        fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).unwrap();
        let supervisor = CoreSupervisor::with_test_home(home.clone());
        let custody = KeyCustody::memory_for_test();

        supervisor.start().await.unwrap();
        let created = supervisor
            .create_vault("Synthetic cross-language vault".to_owned(), custody.clone())
            .await
            .unwrap();
        assert_eq!(created.data.lock_state, SessionLockState::Unlocked);
        assert_eq!(created.data.vault_state, VaultState::Unlocked);
        assert!(supervisor.vault_root.join("vault.json").is_file());
        assert!(supervisor.vault_root.join("vault.db").is_file());
        let replay = supervisor.replay_events(None).await.unwrap().unwrap();
        assert_eq!(
            replay.disposition,
            super::super::contract::EventReplayDisposition::Ok
        );
        assert!(replay.events.is_empty());
        assert!(replay.next_cursor.is_none());

        let locked = supervisor.lock_current_vault().await.unwrap();
        assert_eq!(locked.data.vault_id, created.data.vault_id);
        assert_eq!(locked.data.lock_state, SessionLockState::Locked);
        assert!(supervisor.snapshot().has_key_lease_broker);

        let (blocking_custody, entered, release) = custody.blocking_get_for_test();
        let unlock_supervisor = supervisor.clone();
        let blocked_unlock = tokio::spawn(async move {
            unlock_supervisor
                .unlock_current_vault(blocking_custody)
                .await
        });
        tokio::task::spawn_blocking(move || entered.wait())
            .await
            .unwrap();
        assert!(supervisor.request_system_lock());
        tokio::task::spawn_blocking(move || release.wait())
            .await
            .unwrap();
        assert!(blocked_unlock.await.unwrap().is_err());
        wait_for_locked_session(&supervisor).await;

        let unlocked = supervisor
            .unlock_current_vault(custody.clone())
            .await
            .unwrap();
        assert_eq!(unlocked.data.vault_id, created.data.vault_id);
        assert_eq!(unlocked.data.lock_state, SessionLockState::Unlocked);
        assert!(supervisor.request_system_lock());
        wait_for_locked_session(&supervisor).await;
        assert!(!supervisor.vault_is_unlocked());
        supervisor.stop().await;
        fs::remove_dir_all(home).unwrap();
    }

    #[tokio::test]
    #[allow(clippy::await_holding_lock)]
    async fn development_phase3_bridge_is_profile_scoped_and_typed() {
        let _fd_guard = super::super::key_lease::FD_TEST_LOCK.lock().unwrap();
        let home = PathBuf::from(format!("/tmp/ariadne-phase3-{}", Uuid::new_v4().simple()));
        fs::create_dir(&home).unwrap();
        fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).unwrap();
        let supervisor = CoreSupervisor::with_test_home(home.clone());
        let custody = KeyCustody::memory_for_test();

        supervisor.start().await.unwrap();
        supervisor
            .create_vault("Synthetic Phase 3 vault".to_owned(), custody)
            .await
            .unwrap();
        let profile = supervisor
            .create_profile(CoreProfileCreateRequest {
                idempotency_key: "synthetic_profile_bridge_0001".to_owned(),
                display_label: "Synthetic profile".to_owned(),
                purpose: "Local bridge verification".to_owned(),
            })
            .await
            .unwrap()
            .data;
        let profiles = supervisor.list_profiles().await.unwrap().data;
        assert_eq!(profiles.profiles.len(), 1);
        assert_eq!(profiles.profiles[0].profile_id, profile.profile_id);
        assert!(!profiles.has_more);

        let paste = supervisor
            .intake_paste(CorePasteIntakeRequest {
                profile_id: profile.profile_id,
                idempotency_key: "synthetic_paste_bridge_0001".to_owned(),
                display_name: "Synthetic pasted note".to_owned(),
                content: Zeroizing::new(
                    "Morgan Vale uses @synthetic_orbit and morgan.vale@example.invalid.".to_owned(),
                ),
                consent_confirmed: true,
                retain_raw_source: false,
                semantic_enrichment_enabled: false,
            })
            .await
            .unwrap()
            .data;
        assert_eq!(paste.profile_id, profile.profile_id);
        assert_eq!(paste.source_kind, "PASTE");

        let file_content = br#"{"username":"synthetic_orbit"}"#;
        let mut file_request = synthetic_file_request(file_content);
        file_request.profile_id = profile.profile_id;
        file_request.idempotency_key = "synthetic_file_bridge_0001".to_owned();
        let file = supervisor.intake_file(file_request).await.unwrap().data;
        assert_eq!(file.profile_id, profile.profile_id);
        assert_eq!(file.source_kind, "FILE");

        let review = supervisor
            .review_entities(CoreEntityReviewRequest {
                profile_id: profile.profile_id,
                source_id: Some(paste.source_id),
                limit: 100,
            })
            .await
            .unwrap()
            .data;
        assert_eq!(review.profile_id, profile.profile_id);
        let entity = review.entities.first().unwrap();
        let origin_page = supervisor
            .list_entity_origins(CoreEntityOriginPageRequest {
                profile_id: profile.profile_id,
                entity_id: entity.entity_id,
                offset: 0,
                limit: 12,
            })
            .await
            .unwrap()
            .data;
        assert_eq!(origin_page.profile_id, profile.profile_id);
        assert_eq!(origin_page.entity_id, entity.entity_id);
        assert!(!origin_page.origins.is_empty());
        assert!(origin_page.total >= origin_page.origins.len() as u64);
        let decided = supervisor
            .decide_entity(CoreEntityDecisionRequest {
                profile_id: profile.profile_id,
                entity_id: entity.entity_id,
                idempotency_key: "synthetic_decision_bridge_0001".to_owned(),
                expected_revision: entity.revision,
                decision_type: CoreEntityDecisionType::Confirm,
                review_state: CoreReviewState::Confirmed,
                sensitivity: entity.sensitivity,
                temporal_state: entity.temporal_state,
                search_policy: entity.search_policy,
                transmission_policy: entity.transmission_policy,
                reason: Some(Zeroizing::new("Synthetic confirmation".to_owned())),
            })
            .await
            .unwrap()
            .data;
        assert_eq!(decided.entity_id, entity.entity_id);
        assert_eq!(decided.review_state, CoreReviewState::Confirmed);

        let graph = supervisor
            .graph_snapshot(CoreGraphSnapshotRequest {
                profile_id: profile.profile_id,
                max_nodes: 200,
                include_sensitive: true,
            })
            .await
            .unwrap()
            .data;
        assert_eq!(graph.profile_id, profile.profile_id);
        assert!(!graph.nodes.is_empty());

        let findings = supervisor
            .list_phase5_findings(CorePhase5FindingListRequest {
                profile_id: profile.profile_id,
                limit: 100,
            })
            .await
            .unwrap()
            .data;
        assert_eq!(findings.profile_id, profile.profile_id);
        assert!(findings.findings.is_empty());
        assert!(!findings.has_more);

        supervisor.lock_current_vault().await.unwrap();
        supervisor.stop().await;
        fs::remove_dir_all(home).unwrap();
    }
}
