//! Supervised sidecar boundary, typed wire contract, key lease, and lock lifecycle.

mod auto_lock;
mod contract;
mod event_relay;
#[cfg(unix)]
pub(crate) mod key_lease;
mod supervisor;
mod vault_manifest;

pub use auto_lock::{AppActivity, spawn_auto_lock};
pub use contract::{
    CoreCapabilities, CoreCommandError, CoreCommandResponse, CoreEntityDecisionRequest,
    CoreEntityOriginPageRequest, CoreEntityOriginPageResult, CoreEntityReviewRequest,
    CoreEntityReviewResult, CoreEntitySummary, CoreFileIntakeRequest, CoreGraphSnapshot,
    CoreGraphSnapshotRequest, CoreHibpAccountRequest, CoreHibpAccountResult, CoreHibpDomainRequest,
    CoreHibpDomainResult, CoreIdentityAuditControlRequest, CoreIdentityAuditCreateRequest,
    CoreIdentityAuditDetail, CoreIdentityAuditExecuteRequest, CoreIdentityPersonUpdateRequest,
    CoreIdentityProposalDecisionRequest, CoreIdentitySourceCreateRequest, CoreIdentityWorkspace,
    CoreIdentityWorkspaceRequest, CoreIntakeReceipt, CoreInvestigationPlanRequest,
    CoreInvestigationPlanResult, CoreLocalAiConnectionResult, CoreLocalAiEndpointRequest,
    CoreLocalAiModelDiscoveryResult, CoreLocalAiSettings, CoreLocalAiSettingsUpdateRequest,
    CoreLocalAiWorkspaceRequest, CoreLocalAiWorkspaceResult, CoreLocalCorpusAiRequest,
    CoreLocalCorpusAiResult, CoreLocalReportGenerateRequest, CoreLocalReportGenerateResult,
    CorePasteIntakeRequest, CorePhase5AttributionDecisionRequest,
    CorePhase5AttributionDecisionResult, CorePhase5FindingDetailRequest,
    CorePhase5FindingDetailResult, CorePhase5FindingListRequest, CorePhase5FindingListResult,
    CorePhase5ManualEvidenceImportRequest, CorePhase5ManualEvidenceImportResult,
    CorePhase5ManualFindingCreateRequest, CorePhase5RedactedDerivativeRequest,
    CorePhase5RedactedDerivativeResult, CorePhase6AuditRunListRequest,
    CorePhase6AuditRunListResult, CorePhase6CompareRunsRequest, CorePhase6ComparisonResult,
    CorePhase6LocalCheckpointRequest, CorePhase6LocalCheckpointResult,
    CorePhase6RemediationCreateRequest, CorePhase6RemediationDeadlineUpdateRequest,
    CorePhase6RemediationDetailRequest, CorePhase6RemediationDetailResult,
    CorePhase6RemediationDraftUpdateRequest, CorePhase6RemediationEvidenceLinkRequest,
    CorePhase6RemediationListRequest, CorePhase6RemediationListResult,
    CorePhase6RemediationProviderResponseRequest, CorePhase6RemediationReappearanceRequest,
    CorePhase6RemediationRequireApprovalRequest, CorePhase6RemediationStatusTransitionRequest,
    CoreProfileCreateRequest, CoreProfileDeleteRequest, CoreProfileDeleteResult,
    CoreProfileListResult, CoreProfileSummary, CoreProviderCatalogRequest,
    CoreProviderCatalogResult, CorePublicDiscoveryCaptureRequest, CorePublicDiscoveryCaptureResult,
    CorePublicDiscoverySearchRequest, CorePublicDiscoverySearchResult, CoreQueryDryRunRequest,
    CoreQueryPlanCell, CoreQueryPlanRequest, CoreQueryPlanResult, CoreSession,
    CoreVaultLifecycleResult,
};
pub(crate) use event_relay::spawn_event_relay;
pub use supervisor::CoreSupervisor;
