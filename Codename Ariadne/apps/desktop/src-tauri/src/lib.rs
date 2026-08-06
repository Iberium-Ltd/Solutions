//! Tauri composition root and the renderer's native command allowlist.
//!
//! Commands delegate to `CoreSupervisor`; they do not expose an arbitrary HTTP,
//! filesystem, or process bridge. Vault lifecycle and key custody remain native.

mod core;
mod external_urls;
mod platform;
mod security;

use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

use core::{
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
    CoreLocalAiUnloadResult, CoreLocalAiWorkspaceRequest, CoreLocalAiWorkspaceResult,
    CoreLocalCorpusAiRequest, CoreLocalCorpusAiResult, CoreLocalReportGenerateRequest,
    CoreLocalReportGenerateResult, CorePasteIntakeRequest, CorePhase5AttributionDecisionRequest,
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
    CoreQueryPlanCell, CoreQueryPlanRequest, CoreQueryPlanResult, CoreSession, CoreSupervisor,
    CoreVaultLifecycleResult, spawn_event_relay,
};
use security::KeyCustody;
use tauri::Manager;

#[tauri::command]
fn open_external_url(url: String) -> Result<(), &'static str> {
    external_urls::open_external_url(&url).map_err(|_| "EXTERNAL_URL_REFUSED")
}

#[tauri::command]
async fn core_capabilities(
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreCapabilities>, CoreCommandError> {
    supervisor.capabilities().await
}

#[tauri::command]
async fn core_session(
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreSession>, CoreCommandError> {
    supervisor.session().await
}

#[tauri::command]
async fn core_create_vault(
    display_name: String,
    supervisor: tauri::State<'_, CoreSupervisor>,
    key_custody: tauri::State<'_, KeyCustody>,
) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
    supervisor
        .create_vault(display_name, key_custody.inner().clone())
        .await
}

#[tauri::command]
async fn core_unlock_current_vault(
    supervisor: tauri::State<'_, CoreSupervisor>,
    key_custody: tauri::State<'_, KeyCustody>,
) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
    supervisor
        .unlock_current_vault(key_custody.inner().clone())
        .await
}

#[tauri::command]
async fn core_lock_current_vault(
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreVaultLifecycleResult>, CoreCommandError> {
    supervisor.lock_current_vault().await
}

#[tauri::command]
async fn core_create_profile(
    request: CoreProfileCreateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreProfileSummary>, CoreCommandError> {
    supervisor.create_profile(request).await
}

#[tauri::command]
async fn core_list_profiles(
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreProfileListResult>, CoreCommandError> {
    supervisor.list_profiles().await
}

#[tauri::command]
async fn core_delete_profile(
    request: CoreProfileDeleteRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreProfileDeleteResult>, CoreCommandError> {
    supervisor.delete_profile(request).await
}

#[tauri::command]
async fn core_intake_paste(
    request: CorePasteIntakeRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIntakeReceipt>, CoreCommandError> {
    supervisor.intake_paste(request).await
}

#[tauri::command]
async fn core_intake_file(
    request: CoreFileIntakeRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIntakeReceipt>, CoreCommandError> {
    supervisor.intake_file(request).await
}

#[tauri::command]
async fn core_review_entities(
    request: CoreEntityReviewRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreEntityReviewResult>, CoreCommandError> {
    supervisor.review_entities(request).await
}

#[tauri::command]
async fn core_decide_entity(
    request: CoreEntityDecisionRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreEntitySummary>, CoreCommandError> {
    supervisor.decide_entity(request).await
}

#[tauri::command]
async fn core_list_entity_origins(
    request: CoreEntityOriginPageRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreEntityOriginPageResult>, CoreCommandError> {
    supervisor.list_entity_origins(request).await
}

#[tauri::command]
async fn core_graph_snapshot(
    request: CoreGraphSnapshotRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreGraphSnapshot>, CoreCommandError> {
    supervisor.graph_snapshot(request).await
}

#[tauri::command]
async fn core_get_local_ai_settings(
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiSettings>, CoreCommandError> {
    supervisor.local_ai_settings().await
}

#[tauri::command]
async fn core_update_local_ai_settings(
    request: CoreLocalAiSettingsUpdateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiSettings>, CoreCommandError> {
    supervisor.update_local_ai_settings(request).await
}

#[tauri::command]
async fn core_discover_local_ai_models(
    request: CoreLocalAiEndpointRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiModelDiscoveryResult>, CoreCommandError> {
    supervisor.discover_local_ai_models(request).await
}

#[tauri::command]
async fn core_test_local_ai_connection(
    request: CoreLocalAiEndpointRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiConnectionResult>, CoreCommandError> {
    supervisor.test_local_ai_connection(request).await
}

#[tauri::command]
async fn core_unload_local_ai_model(
    request: CoreLocalAiEndpointRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiUnloadResult>, CoreCommandError> {
    supervisor.unload_local_ai_model(request).await
}

#[tauri::command]
async fn core_analyze_local_ai_workspace(
    request: CoreLocalAiWorkspaceRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalAiWorkspaceResult>, CoreCommandError> {
    supervisor.analyze_local_ai_workspace(request).await
}

#[tauri::command]
async fn core_analyze_local_ai_corpus(
    request: CoreLocalCorpusAiRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalCorpusAiResult>, CoreCommandError> {
    supervisor.analyze_local_ai_corpus(request).await
}

#[tauri::command]
async fn core_search_public_discovery(
    request: CorePublicDiscoverySearchRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePublicDiscoverySearchResult>, CoreCommandError> {
    supervisor.search_public_discovery(request).await
}

#[tauri::command]
async fn core_compile_investigation_plan(
    request: CoreInvestigationPlanRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreInvestigationPlanResult>, CoreCommandError> {
    supervisor.compile_investigation_plan(request).await
}

#[tauri::command]
async fn core_search_hibp_account(
    request: CoreHibpAccountRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreHibpAccountResult>, CoreCommandError> {
    supervisor.search_hibp_account(request).await
}

#[tauri::command]
async fn core_search_hibp_domain(
    request: CoreHibpDomainRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreHibpDomainResult>, CoreCommandError> {
    supervisor.search_hibp_domain(request).await
}

#[tauri::command]
async fn core_capture_public_discovery(
    request: CorePublicDiscoveryCaptureRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePublicDiscoveryCaptureResult>, CoreCommandError> {
    supervisor.capture_public_discovery(request).await
}

#[tauri::command]
async fn core_query_providers(
    request: CoreProviderCatalogRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreProviderCatalogResult>, CoreCommandError> {
    supervisor.query_provider_catalog(request).await
}

#[tauri::command]
async fn core_create_query_plan(
    request: CoreQueryPlanRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreQueryPlanResult>, CoreCommandError> {
    supervisor.create_query_plan(request).await
}

#[tauri::command]
async fn core_execute_query_dry_run(
    request: CoreQueryDryRunRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreQueryPlanCell>, CoreCommandError> {
    supervisor.execute_query_dry_run(request).await
}

#[tauri::command]
async fn core_list_phase5_findings(
    request: CorePhase5FindingListRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5FindingListResult>, CoreCommandError> {
    supervisor.list_phase5_findings(request).await
}

#[tauri::command]
async fn core_get_phase5_finding(
    request: CorePhase5FindingDetailRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5FindingDetailResult>, CoreCommandError> {
    supervisor.get_phase5_finding(request).await
}

#[tauri::command]
async fn core_create_phase5_manual_finding(
    request: CorePhase5ManualFindingCreateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5FindingDetailResult>, CoreCommandError> {
    supervisor.create_phase5_manual_finding(request).await
}

#[tauri::command]
async fn core_import_phase5_evidence(
    request: CorePhase5ManualEvidenceImportRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5ManualEvidenceImportResult>, CoreCommandError> {
    supervisor.import_phase5_evidence(request).await
}

#[tauri::command]
async fn core_create_phase5_redacted_derivative(
    request: CorePhase5RedactedDerivativeRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5RedactedDerivativeResult>, CoreCommandError> {
    supervisor.create_phase5_redacted_derivative(request).await
}

#[tauri::command]
async fn core_append_phase5_attribution_decision(
    request: CorePhase5AttributionDecisionRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase5AttributionDecisionResult>, CoreCommandError> {
    supervisor.append_phase5_attribution_decision(request).await
}

#[tauri::command]
async fn core_list_phase6_audit_runs(
    request: CorePhase6AuditRunListRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6AuditRunListResult>, CoreCommandError> {
    supervisor.list_phase6_audit_runs(request).await
}

#[tauri::command]
async fn core_create_phase6_local_checkpoint(
    request: CorePhase6LocalCheckpointRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6LocalCheckpointResult>, CoreCommandError> {
    supervisor.create_phase6_local_checkpoint(request).await
}

#[tauri::command]
async fn core_compare_phase6_runs(
    request: CorePhase6CompareRunsRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6ComparisonResult>, CoreCommandError> {
    supervisor.compare_phase6_runs(request).await
}

#[tauri::command]
async fn core_list_phase6_remediation_cases(
    request: CorePhase6RemediationListRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationListResult>, CoreCommandError> {
    supervisor.list_phase6_remediation_cases(request).await
}

#[tauri::command]
async fn core_get_phase6_remediation_case(
    request: CorePhase6RemediationDetailRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.get_phase6_remediation_case(request).await
}

#[tauri::command]
async fn core_create_phase6_remediation_case(
    request: CorePhase6RemediationCreateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.create_phase6_remediation_case(request).await
}

#[tauri::command]
async fn core_update_phase6_remediation_draft(
    request: CorePhase6RemediationDraftUpdateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.update_phase6_remediation_draft(request).await
}

#[tauri::command]
async fn core_require_phase6_remediation_approval(
    request: CorePhase6RemediationRequireApprovalRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor
        .require_phase6_remediation_approval(request)
        .await
}

#[tauri::command]
async fn core_transition_phase6_remediation_status(
    request: CorePhase6RemediationStatusTransitionRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor
        .transition_phase6_remediation_status(request)
        .await
}

#[tauri::command]
async fn core_set_phase6_remediation_deadline(
    request: CorePhase6RemediationDeadlineUpdateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.set_phase6_remediation_deadline(request).await
}

#[tauri::command]
async fn core_link_phase6_remediation_evidence(
    request: CorePhase6RemediationEvidenceLinkRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.link_phase6_remediation_evidence(request).await
}

#[tauri::command]
async fn core_record_phase6_provider_response(
    request: CorePhase6RemediationProviderResponseRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.record_phase6_provider_response(request).await
}

#[tauri::command]
async fn core_record_phase6_reappearance(
    request: CorePhase6RemediationReappearanceRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CorePhase6RemediationDetailResult>, CoreCommandError> {
    supervisor.record_phase6_reappearance(request).await
}

#[tauri::command]
async fn core_generate_local_report(
    request: CoreLocalReportGenerateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreLocalReportGenerateResult>, CoreCommandError> {
    supervisor.generate_local_report(request).await
}

#[tauri::command]
async fn core_identity_workspace(
    request: CoreIdentityWorkspaceRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
    supervisor.identity_workspace(request).await
}

#[tauri::command]
async fn core_update_identity_person(
    request: CoreIdentityPersonUpdateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
    supervisor.update_identity_person(request).await
}

#[tauri::command]
async fn core_create_identity_source(
    request: CoreIdentitySourceCreateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityWorkspace>, CoreCommandError> {
    supervisor.create_identity_source(request).await
}

#[tauri::command]
async fn core_create_identity_audit(
    request: CoreIdentityAuditCreateRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
    supervisor.create_identity_audit(request).await
}

#[tauri::command]
async fn core_get_identity_audit(
    request: CoreIdentityAuditExecuteRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
    supervisor.get_identity_audit(request).await
}

#[tauri::command]
async fn core_execute_identity_audit_batch(
    request: CoreIdentityAuditExecuteRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
    supervisor.execute_identity_audit_batch(request).await
}

#[tauri::command]
async fn core_control_identity_audit(
    request: CoreIdentityAuditControlRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
    supervisor.control_identity_audit(request).await
}

#[tauri::command]
async fn core_decide_identity_proposal(
    request: CoreIdentityProposalDecisionRequest,
    supervisor: tauri::State<'_, CoreSupervisor>,
) -> Result<CoreCommandResponse<CoreIdentityAuditDetail>, CoreCommandError> {
    supervisor.decide_identity_proposal(request).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // State is constructed once here so every command shares one supervised core.
    let application = tauri::Builder::default()
        .setup(move |app| {
            let vault_root = app.path().app_data_dir()?.join("vault");
            let supervisor = CoreSupervisor::with_vault_root(vault_root);
            let key_custody = KeyCustody::platform();
            app.manage(supervisor.clone());
            app.manage(key_custody);
            supervisor.spawn_crash_monitor();
            spawn_event_relay(app.handle().clone(), supervisor.clone());
            tauri::async_runtime::spawn(async move {
                if let Err(error) = supervisor.start().await {
                    // The error variants contain no bootstrap token, response body, or private data.
                    eprintln!("Ariadne Core unavailable: {error}");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_external_url,
            core_capabilities,
            core_session,
            core_create_vault,
            core_unlock_current_vault,
            core_lock_current_vault,
            core_list_profiles,
            core_create_profile,
            core_delete_profile,
            core_intake_paste,
            core_intake_file,
            core_review_entities,
            core_decide_entity,
            core_list_entity_origins,
            core_graph_snapshot,
            core_get_local_ai_settings,
            core_update_local_ai_settings,
            core_discover_local_ai_models,
            core_test_local_ai_connection,
            core_unload_local_ai_model,
            core_analyze_local_ai_workspace,
            core_analyze_local_ai_corpus,
            core_search_public_discovery,
            core_compile_investigation_plan,
            core_search_hibp_account,
            core_search_hibp_domain,
            core_capture_public_discovery,
            core_query_providers,
            core_create_query_plan,
            core_execute_query_dry_run,
            core_list_phase5_findings,
            core_get_phase5_finding,
            core_create_phase5_manual_finding,
            core_import_phase5_evidence,
            core_create_phase5_redacted_derivative,
            core_append_phase5_attribution_decision,
            core_list_phase6_audit_runs,
            core_create_phase6_local_checkpoint,
            core_compare_phase6_runs,
            core_list_phase6_remediation_cases,
            core_get_phase6_remediation_case,
            core_create_phase6_remediation_case,
            core_update_phase6_remediation_draft,
            core_require_phase6_remediation_approval,
            core_transition_phase6_remediation_status,
            core_set_phase6_remediation_deadline,
            core_link_phase6_remediation_evidence,
            core_record_phase6_provider_response,
            core_record_phase6_reappearance,
            core_generate_local_report,
            core_identity_workspace,
            core_update_identity_person,
            core_create_identity_source,
            core_create_identity_audit,
            core_get_identity_audit,
            core_execute_identity_audit_batch,
            core_control_identity_audit,
            core_decide_identity_proposal
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    let exit_started = Arc::new(AtomicBool::new(false));
    application.run(move |app_handle, event| match event {
        tauri::RunEvent::ExitRequested { code, api, .. } => {
            if !exit_started.swap(true, Ordering::AcqRel) {
                api.prevent_exit();
                let supervisor = app_handle.state::<CoreSupervisor>().inner().clone();
                let app_handle = app_handle.clone();
                let exit_code = code.unwrap_or_default();
                tauri::async_runtime::spawn(async move {
                    supervisor.shutdown().await;
                    app_handle.exit(exit_code);
                });
            }
        }
        tauri::RunEvent::Exit => {
            app_handle.state::<CoreSupervisor>().force_stop();
        }
        _ => {}
    });
}
