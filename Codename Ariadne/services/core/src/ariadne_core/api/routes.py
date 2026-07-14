"""Truthful authenticated routes for the bounded Phase 2 local foundation."""

from __future__ import annotations

import hmac
from typing import Any, NoReturn
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request

from ariadne_core.api.hibp_schemas import (
    HibpAccountRequest,
    HibpAccountResult,
    HibpDomainRequest,
    HibpDomainResult,
)
from ariadne_core.api.intake_schemas import (
    EntityDecisionRequest,
    EntityOriginPageRequest,
    EntityOriginPageResult,
    EntityReviewRequest,
    EntityReviewResult,
    EntitySummary,
    FileIntakeRequest,
    GraphSnapshot,
    GraphSnapshotRequest,
    IntakeReceipt,
    PasteIntakeRequest,
    ProfileCreateRequest,
    ProfileListResult,
    ProfileSummary,
)
from ariadne_core.api.investigation_plan_schemas import (
    InvestigationPlanCompileRequest,
    InvestigationPlanResult,
)
from ariadne_core.api.local_ai_workspace_schemas import (
    LocalAIWorkspaceRequest,
    LocalAIWorkspaceResult,
)
from ariadne_core.api.local_corpus_ai_schemas import (
    LocalCorpusAIRequest,
    LocalCorpusAIResult,
)
from ariadne_core.api.local_corpus_schemas import (
    MAX_LOCAL_CORPUS_API_REQUEST_BYTES,
    MAX_LOCAL_CORPUS_API_RESPONSE_BYTES,
)
from ariadne_core.api.phase5_schemas import (
    Phase5AttributionDecisionRequest,
    Phase5AttributionDecisionResult,
    Phase5FindingDetailRequest,
    Phase5FindingDetailResult,
    Phase5FindingListRequest,
    Phase5FindingListResult,
    Phase5ManualEvidenceImportRequest,
    Phase5ManualEvidenceImportResult,
    Phase5ManualFindingCreateRequest,
    Phase5RedactedDerivativeRequest,
    Phase5RedactedDerivativeResult,
)
from ariadne_core.api.phase6_schemas import (
    Phase6AuditRunListRequest,
    Phase6AuditRunListResult,
    Phase6CompareRunsRequest,
    Phase6ComparisonResult,
    Phase6LocalCheckpointRequest,
    Phase6LocalCheckpointResult,
    Phase6RemediationCreateRequest,
    Phase6RemediationDeadlineUpdateRequest,
    Phase6RemediationDetailRequest,
    Phase6RemediationDetailResult,
    Phase6RemediationDraftUpdateRequest,
    Phase6RemediationEvidenceLinkRequest,
    Phase6RemediationListRequest,
    Phase6RemediationListResult,
    Phase6RemediationProviderResponseRequest,
    Phase6RemediationReappearanceRequest,
    Phase6RemediationRequireApprovalRequest,
    Phase6RemediationStatusTransitionRequest,
)
from ariadne_core.api.public_discovery_capture_schemas import (
    PublicDiscoveryCaptureRequest,
    PublicDiscoveryCaptureResult,
)
from ariadne_core.api.public_discovery_schemas import (
    PublicDiscoverySearchRequest,
    PublicDiscoverySearchResult,
)
from ariadne_core.api.query_schemas import (
    ProviderCatalogRequest,
    ProviderCatalogResult,
    QueryDryRunRequest,
    QueryPlanCell,
    QueryPlanRequest,
    QueryPlanResult,
)
from ariadne_core.api.reporting_schemas import (
    MAX_REPORT_API_REQUEST_BYTES,
    MAX_REPORT_API_RESPONSE_BYTES,
    ReportGenerateRequest,
    ReportGenerateResult,
)
from ariadne_core.api.schemas import (
    ApiError,
    CapabilityVersions,
    CipherCapability,
    CompatibilityState,
    EventReplayDisposition,
    EventReplayRequest,
    EventReplayResult,
    FeatureCapability,
    FeatureKey,
    FeatureStatus,
    LocalAIConnectionResult,
    LocalAIEndpointRequest,
    LocalAIModelDiscoveryResult,
    LocalAISettings,
    LocalAISettingsUpdateRequest,
    LockState,
    SafeCoreEvent,
    SessionState,
    SystemCapabilities,
    VaultCreateRequest,
    VaultLifecycleResult,
    VaultState,
    VaultUnlockRequest,
)
from ariadne_core.application.hibp import HibpService
from ariadne_core.application.investigation_planning import InvestigationPlanCompiler
from ariadne_core.application.local_ai_settings import (
    LocalAISettingsConflict,
    LocalAISettingsService,
    LocalAISettingsUnavailable,
)
from ariadne_core.application.local_ai_workspace import (
    LocalAIWorkspaceConflict,
    LocalAIWorkspaceCoordinator,
    LocalAIWorkspaceNotFound,
    LocalAIWorkspaceUnavailable,
)
from ariadne_core.application.local_corpus_ai import (
    LocalCorpusAIConflict,
    LocalCorpusAICoordinator,
    LocalCorpusAINotFound,
    LocalCorpusAIUnavailable,
)
from ariadne_core.application.phase3 import (
    Phase3Conflict,
    Phase3Coordinator,
    Phase3InvalidRequest,
    Phase3NotFound,
    Phase3Unavailable,
    translate_phase3_exception,
)
from ariadne_core.application.phase5 import (
    Phase5Conflict,
    Phase5Coordinator,
    Phase5NotFound,
    Phase5Unavailable,
)
from ariadne_core.application.phase6 import (
    Phase6Conflict,
    Phase6Coordinator,
    Phase6NotFound,
    Phase6Unavailable,
)
from ariadne_core.application.public_discovery import PublicDiscoveryService
from ariadne_core.application.public_discovery_capture import (
    PublicDiscoveryCaptureConflict,
    PublicDiscoveryCaptureCoordinator,
    PublicDiscoveryCaptureNotFound,
    PublicDiscoveryCaptureUnavailable,
)
from ariadne_core.application.query_vertical import (
    QueryVerticalConflict,
    QueryVerticalCoordinator,
    QueryVerticalNotFound,
    QueryVerticalUnavailable,
)
from ariadne_core.application.reporting_projection import (
    ReportingConflict,
    ReportingNotFound,
    ReportingProjectionCoordinator,
    ReportingUnavailable,
)
from ariadne_core.application.vault import VaultLifecycleError, VaultManager, VaultManifest
from ariadne_core.domain.query_policy import Sensitivity
from ariadne_core.infrastructure.db.repositories import EventReplayRepository
from ariadne_core.local_ai import LocalAIError, LocalAIErrorCode
from ariadne_core.security.key_lease import KeyLeaseClient, LeaseOperation

router = APIRouter(prefix="/v1")

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ApiError, "description": "Safe local API error"}
    for status in (400, 401, 403, 404, 409, 413, 431, 500, 503)
}

COMMON_CAPABILITY = {
    "maxRequestBytes": 0,
    "maxResponseBytes": 65536,
    "requiredLockState": "ANY",
    "scopeClass": "NONE",
    "revealClass": "NONE",
    "authorizationClass": "LAUNCH_SESSION",
}

PROFILE_CREATE_BODY_BYTES = 1024
PASTE_INTAKE_BODY_BYTES = 1_052_672
FILE_INTAKE_BODY_BYTES = 1_402_880
PROFILE_QUERY_BODY_BYTES = 512
ENTITY_DECISION_BODY_BYTES = 2048
LARGE_PHASE3_RESPONSE_BYTES = 1_048_576
LOCAL_AI_REQUEST_BYTES = 1024
LOCAL_AI_MODELS_RESPONSE_BYTES = 262_144
LOCAL_AI_WORKSPACE_REQUEST_BYTES = 100_000
LOCAL_AI_WORKSPACE_RESPONSE_BYTES = 131_072
QUERY_PLAN_REQUEST_BYTES = 2048
QUERY_PLAN_RESPONSE_BYTES = 262_144
PUBLIC_DISCOVERY_REQUEST_BYTES = 8_192
PUBLIC_DISCOVERY_RESPONSE_BYTES = 262_144
PUBLIC_DISCOVERY_CAPTURE_REQUEST_BYTES = 8_192
PUBLIC_DISCOVERY_CAPTURE_RESPONSE_BYTES = 4_096
HIBP_REQUEST_BYTES = 4_096
HIBP_RESPONSE_BYTES = 1_048_576
INVESTIGATION_PLAN_REQUEST_BYTES = 40_960
INVESTIGATION_PLAN_RESPONSE_BYTES = 262_144
PHASE5_REQUEST_BYTES = 512
PHASE5_RESPONSE_BYTES = 1_048_576
PHASE5_MANUAL_FINDING_REQUEST_BYTES = 4_096
PHASE5_EVIDENCE_WRITE_REQUEST_BYTES = 14_000_000
PHASE5_WRITE_RESPONSE_BYTES = 4_096
PHASE6_REQUEST_BYTES = 512
PHASE6_RESPONSE_BYTES = 1_048_576
PHASE6_LOCAL_CHECKPOINT_REQUEST_BYTES = 50_000
PHASE6_LOCAL_CHECKPOINT_RESPONSE_BYTES = 4_096
PHASE6_CREATE_REQUEST_BYTES = 50_000
PHASE6_DRAFT_REQUEST_BYTES = 50_000
PHASE6_STATUS_REQUEST_BYTES = 6_144
PHASE6_EVIDENCE_REQUEST_BYTES = 4_096
PHASE6_PROVIDER_RESPONSE_REQUEST_BYTES = 12_288


def _vault_components(request: Request) -> tuple[VaultManager, KeyLeaseClient]:
    runtime = request.app.state.runtime
    manager = runtime.vault_manager
    lease_client = runtime.key_lease_client
    if manager is None or lease_client is None or runtime.cipher_runtime is None:
        raise HTTPException(status_code=503)
    return manager, lease_client


def _operation_failure() -> HTTPException:
    return HTTPException(status_code=409)


def _phase3_coordinator(request: Request) -> Phase3Coordinator:
    coordinator = request.app.state.phase3_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_phase3(error: Exception) -> NoReturn:
    if isinstance(error, Phase3Unavailable):
        raise HTTPException(status_code=409) from None
    translated = translate_phase3_exception(error)
    if isinstance(translated, Phase3NotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(translated, Phase3InvalidRequest):
        raise HTTPException(status_code=400) from None
    if isinstance(translated, Phase3Conflict):
        raise HTTPException(status_code=409) from None
    raise HTTPException(status_code=409) from None


def _local_ai_service(request: Request) -> LocalAISettingsService:
    service = request.app.state.local_ai_settings_service
    if service is None:
        raise HTTPException(status_code=503)
    return service


def _raise_local_ai(error: Exception) -> NoReturn:
    if isinstance(error, LocalAISettingsUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, LocalAISettingsConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, LocalAIError):
        status = 400 if error.code is LocalAIErrorCode.INVALID_CONFIGURATION else 503
        raise HTTPException(status_code=status) from None
    raise HTTPException(status_code=503) from None


def _local_ai_workspace(request: Request) -> LocalAIWorkspaceCoordinator:
    coordinator = request.app.state.local_ai_workspace_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_local_ai_workspace(error: Exception) -> NoReturn:
    if isinstance(error, LocalAIWorkspaceUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, LocalAIWorkspaceNotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, LocalAIWorkspaceConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _local_corpus_ai(request: Request) -> LocalCorpusAICoordinator:
    coordinator = request.app.state.local_corpus_ai_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_local_corpus_ai(error: Exception) -> NoReturn:
    if isinstance(error, LocalCorpusAIUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, LocalCorpusAINotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, LocalCorpusAIConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _query_vertical(request: Request) -> QueryVerticalCoordinator:
    coordinator = request.app.state.query_vertical_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_query_vertical(error: Exception) -> NoReturn:
    if isinstance(error, QueryVerticalUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, QueryVerticalNotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, QueryVerticalConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, (ValueError, RuntimeError)):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _public_discovery(request: Request) -> PublicDiscoveryService:
    service = request.app.state.public_discovery_service
    if not isinstance(service, PublicDiscoveryService):
        raise HTTPException(status_code=503)
    return service


def _hibp(request: Request) -> HibpService:
    service = request.app.state.hibp_service
    if not isinstance(service, HibpService):
        raise HTTPException(status_code=503)
    return service


def _investigation_plan_compiler(request: Request) -> InvestigationPlanCompiler:
    compiler = request.app.state.investigation_plan_compiler
    if not isinstance(compiler, InvestigationPlanCompiler):
        raise HTTPException(status_code=503)
    return compiler


def _public_discovery_capture(request: Request) -> PublicDiscoveryCaptureCoordinator:
    coordinator = request.app.state.public_discovery_capture_coordinator
    if not isinstance(coordinator, PublicDiscoveryCaptureCoordinator):
        raise HTTPException(status_code=503)
    return coordinator


def _raise_public_discovery_capture(error: Exception) -> NoReturn:
    if isinstance(error, PublicDiscoveryCaptureUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, PublicDiscoveryCaptureNotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, PublicDiscoveryCaptureConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _phase5_coordinator(request: Request) -> Phase5Coordinator:
    coordinator = request.app.state.phase5_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_phase5(error: Exception) -> NoReturn:
    if isinstance(error, Phase5Unavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, Phase5NotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, Phase5Conflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _phase6_coordinator(request: Request) -> Phase6Coordinator:
    coordinator = request.app.state.phase6_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_phase6(error: Exception) -> NoReturn:
    if isinstance(error, Phase6Unavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, Phase6NotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, Phase6Conflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


def _reporting_coordinator(request: Request) -> ReportingProjectionCoordinator:
    coordinator = request.app.state.reporting_coordinator
    if coordinator is None:
        raise HTTPException(status_code=503)
    return coordinator


def _raise_reporting(error: Exception) -> NoReturn:
    if isinstance(error, ReportingUnavailable):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ReportingNotFound):
        raise HTTPException(status_code=404) from None
    if isinstance(error, ReportingConflict):
        raise HTTPException(status_code=409) from None
    if isinstance(error, ValueError):
        raise HTTPException(status_code=400) from None
    raise HTTPException(status_code=503) from None


@router.get(
    "/system/capabilities",
    response_model=SystemCapabilities,
    responses=ERROR_RESPONSES,
    operation_id="getSystemCapabilities",
    openapi_extra={
        "x-ariadne-capability": {
            **COMMON_CAPABILITY,
            "routeId": "system.capabilities.read",
        }
    },
)
async def get_system_capabilities(request: Request) -> SystemCapabilities:
    runtime = request.app.state.runtime
    cipher = runtime.cipher_runtime
    vault_foundation_available = (
        cipher is not None
        and runtime.vault_manager is not None
        and runtime.key_lease_client is not None
    )
    available_features = {
        FeatureKey.AUTHENTICATED_LOCAL_API,
        FeatureKey.PUBLIC_DISCOVERY,
        *(
            {
                FeatureKey.DATABASE,
                FeatureKey.MIGRATIONS,
                FeatureKey.ENCRYPTION,
                FeatureKey.KEY_LEASE,
                FeatureKey.VAULT_LIFECYCLE,
                FeatureKey.EVENTS,
                FeatureKey.IMPORT_EXPORT,
                FeatureKey.INTAKE,
                FeatureKey.IDENTITY_COMPILER,
                FeatureKey.ENTITY_REVIEW,
                FeatureKey.IDENTITY_GRAPH,
                FeatureKey.LOCAL_AI,
                FeatureKey.QUERY_POLICY,
                FeatureKey.EVIDENCE,
                FeatureKey.ATTRIBUTION,
                FeatureKey.AUDIT_COMPARISON,
                FeatureKey.REMEDIATION,
            }
            if vault_foundation_available
            else set()
        ),
    }
    return SystemCapabilities(
        versions=CapabilityVersions(
            contract=1,
            schema="ariadne-v1",
            events=1,
            core="0.1.0",
        ),
        transport=runtime.transport,
        cipher=CipherCapability(
            required="SQLCIPHER",
            available=cipher is not None,
            sqlite_version=None if cipher is None else cipher.sqlite_version,
            cipher_version=None if cipher is None else cipher.cipher_version,
        ),
        features=tuple(
            FeatureCapability(
                key=key,
                status=(
                    FeatureStatus.AVAILABLE
                    if key in available_features
                    else FeatureStatus.NOT_IMPLEMENTED
                ),
            )
            for key in FeatureKey
        ),
    )


@router.post(
    "/phase5/findings/manual",
    response_model=Phase5FindingDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="createPhase5ManualFinding",
    summary="Create a manual local finding",
    description=(
        "Atomically create a local finding and neutral attribution assessment without network use."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.findings.manual.create",
            "maxRequestBytes": PHASE5_MANUAL_FINDING_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_phase5_manual_finding(
    body: Phase5ManualFindingCreateRequest,
    request: Request,
) -> Phase5FindingDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).create_manual_finding,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase5/findings/list",
    response_model=Phase5FindingListResult,
    responses=ERROR_RESPONSES,
    operation_id="listPhase5Findings",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.findings.list",
            "maxRequestBytes": PHASE5_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def list_phase5_findings(
    body: Phase5FindingListRequest,
    request: Request,
) -> Phase5FindingListResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).list_findings,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase5/findings/detail",
    response_model=Phase5FindingDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="getPhase5Finding",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.findings.detail",
            "maxRequestBytes": PHASE5_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def get_phase5_finding(
    body: Phase5FindingDetailRequest,
    request: Request,
) -> Phase5FindingDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).finding_detail,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase5/evidence/manual-import",
    response_model=Phase5ManualEvidenceImportResult,
    responses=ERROR_RESPONSES,
    operation_id="importPhase5ManualEvidence",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.evidence.manual_import",
            "maxRequestBytes": PHASE5_EVIDENCE_WRITE_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_WRITE_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def import_phase5_manual_evidence(
    body: Phase5ManualEvidenceImportRequest,
    request: Request,
) -> Phase5ManualEvidenceImportResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).manual_evidence_import,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase5/evidence/redacted-derivative",
    response_model=Phase5RedactedDerivativeResult,
    responses=ERROR_RESPONSES,
    operation_id="createPhase5RedactedDerivative",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.evidence.redacted_derivative.create",
            "maxRequestBytes": PHASE5_EVIDENCE_WRITE_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_WRITE_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_phase5_redacted_derivative(
    body: Phase5RedactedDerivativeRequest,
    request: Request,
) -> Phase5RedactedDerivativeResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).create_redacted_derivative,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase5/attribution/decision",
    response_model=Phase5AttributionDecisionResult,
    responses=ERROR_RESPONSES,
    operation_id="appendPhase5AttributionDecision",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase5.attribution.decision.append",
            "maxRequestBytes": PHASE5_REQUEST_BYTES,
            "maxResponseBytes": PHASE5_WRITE_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def append_phase5_attribution_decision(
    body: Phase5AttributionDecisionRequest,
    request: Request,
) -> Phase5AttributionDecisionResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase5_coordinator(request).append_attribution_decision,
            body,
        )
    except Exception as error:
        _raise_phase5(error)


@router.post(
    "/phase6/audits/local-checkpoint",
    response_model=Phase6LocalCheckpointResult,
    responses=ERROR_RESPONSES,
    operation_id="createPhase6LocalCheckpoint",
    summary="Create a local checkpoint",
    description=(
        "Materialize current persisted Phase 5 state without running providers or using a network."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.audits.local_checkpoint.create",
            "maxRequestBytes": PHASE6_LOCAL_CHECKPOINT_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_LOCAL_CHECKPOINT_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_phase6_local_checkpoint(
    body: Phase6LocalCheckpointRequest,
    request: Request,
) -> Phase6LocalCheckpointResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).create_local_checkpoint,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/audits/list",
    response_model=Phase6AuditRunListResult,
    responses=ERROR_RESPONSES,
    operation_id="listPhase6AuditRuns",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.audits.list",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def list_phase6_audit_runs(
    body: Phase6AuditRunListRequest,
    request: Request,
) -> Phase6AuditRunListResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).list_audit_runs,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/audits/compare",
    response_model=Phase6ComparisonResult,
    responses=ERROR_RESPONSES,
    operation_id="comparePhase6AuditRuns",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.audits.compare",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def compare_phase6_audit_runs(
    body: Phase6CompareRunsRequest,
    request: Request,
) -> Phase6ComparisonResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).compare_runs,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/list",
    response_model=Phase6RemediationListResult,
    responses=ERROR_RESPONSES,
    operation_id="listPhase6RemediationCases",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.list",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def list_phase6_remediation_cases(
    body: Phase6RemediationListRequest,
    request: Request,
) -> Phase6RemediationListResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).list_remediation_cases,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/detail",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="getPhase6RemediationCase",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.detail",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def get_phase6_remediation_case(
    body: Phase6RemediationDetailRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).remediation_detail,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/create",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="createPhase6RemediationCase",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.create",
            "maxRequestBytes": PHASE6_CREATE_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_phase6_remediation_case(
    body: Phase6RemediationCreateRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).create_remediation_case,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/draft",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="updatePhase6RemediationDraft",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.draft.update",
            "maxRequestBytes": PHASE6_DRAFT_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def update_phase6_remediation_draft(
    body: Phase6RemediationDraftUpdateRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).update_remediation_draft,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/require-approval",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="requirePhase6RemediationApproval",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.approval.require",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def require_phase6_remediation_approval(
    body: Phase6RemediationRequireApprovalRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).require_remediation_approval,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/status",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="transitionPhase6RemediationStatus",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.status.transition",
            "maxRequestBytes": PHASE6_STATUS_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def transition_phase6_remediation_status(
    body: Phase6RemediationStatusTransitionRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).transition_remediation_status,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/deadline",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="updatePhase6RemediationDeadline",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.deadline.update",
            "maxRequestBytes": PHASE6_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def update_phase6_remediation_deadline(
    body: Phase6RemediationDeadlineUpdateRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).update_remediation_deadline,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/evidence",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="linkPhase6RemediationEvidence",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.evidence.link",
            "maxRequestBytes": PHASE6_EVIDENCE_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def link_phase6_remediation_evidence(
    body: Phase6RemediationEvidenceLinkRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).link_remediation_evidence,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/provider-response",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="recordPhase6RemediationProviderResponse",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.provider_response.record",
            "maxRequestBytes": PHASE6_PROVIDER_RESPONSE_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def record_phase6_remediation_provider_response(
    body: Phase6RemediationProviderResponseRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).record_remediation_provider_response,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/phase6/remediation/reappearance",
    response_model=Phase6RemediationDetailResult,
    responses=ERROR_RESPONSES,
    operation_id="recordPhase6RemediationReappearance",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "phase6.remediation.reappearance.record",
            "maxRequestBytes": PHASE6_EVIDENCE_REQUEST_BYTES,
            "maxResponseBytes": PHASE6_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def record_phase6_remediation_reappearance(
    body: Phase6RemediationReappearanceRequest,
    request: Request,
) -> Phase6RemediationDetailResult:
    try:
        return await anyio.to_thread.run_sync(
            _phase6_coordinator(request).record_remediation_reappearance,
            body,
        )
    except Exception as error:
        _raise_phase6(error)


@router.post(
    "/reports/generate",
    response_model=ReportGenerateResult,
    responses=ERROR_RESPONSES,
    operation_id="generateLocalReport",
    summary="Generate one local report artifact",
    description=(
        "Project persisted profile data into one bounded in-memory JSON or Markdown artifact "
        "without filesystem, network, or outbound actions."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "reports.generate",
            "maxRequestBytes": MAX_REPORT_API_REQUEST_BYTES,
            "maxResponseBytes": MAX_REPORT_API_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def generate_local_report(
    body: ReportGenerateRequest,
    request: Request,
) -> ReportGenerateResult:
    try:
        return await anyio.to_thread.run_sync(
            _reporting_coordinator(request).generate,
            body,
        )
    except Exception as error:
        _raise_reporting(error)


@router.post(
    "/query/providers",
    response_model=ProviderCatalogResult,
    responses=ERROR_RESPONSES,
    operation_id="getQueryProviderCatalog",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "query.providers.read",
            "maxRequestBytes": PROFILE_QUERY_BODY_BYTES,
            "maxResponseBytes": 16384,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def get_query_provider_catalog(
    body: ProviderCatalogRequest,
    request: Request,
) -> ProviderCatalogResult:
    try:
        return await anyio.to_thread.run_sync(
            _query_vertical(request).catalog,
            body.profile_id,
        )
    except Exception as error:
        _raise_query_vertical(error)


@router.post(
    "/query/plans",
    response_model=QueryPlanResult,
    responses=ERROR_RESPONSES,
    operation_id="createQueryPlan",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "query.plans.create",
            "maxRequestBytes": QUERY_PLAN_REQUEST_BYTES,
            "maxResponseBytes": QUERY_PLAN_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_query_plan(body: QueryPlanRequest, request: Request) -> QueryPlanResult:
    try:
        return await anyio.to_thread.run_sync(_query_vertical(request).create_plan, body)
    except Exception as error:
        _raise_query_vertical(error)


@router.post(
    "/query/dry-run",
    response_model=QueryPlanCell,
    responses=ERROR_RESPONSES,
    operation_id="executeQueryDryRun",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "query.dry_run.execute",
            "maxRequestBytes": 1024,
            "maxResponseBytes": 4096,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def execute_query_dry_run(
    body: QueryDryRunRequest,
    request: Request,
) -> QueryPlanCell:
    try:
        return await anyio.to_thread.run_sync(
            _query_vertical(request).execute_dry_run,
            body,
        )
    except Exception as error:
        _raise_query_vertical(error)


@router.post(
    "/discovery/investigation/plan",
    response_model=InvestigationPlanResult,
    responses=ERROR_RESPONSES,
    operation_id="compileInvestigationPlan",
    summary="Compile an authorised multi-provider investigation plan without execution",
    description=(
        "Deterministically select compatible DuckDuckGo, GitHub, and HIBP steps for "
        "approved identifiers. Compilation performs no network request and returns no raw "
        "identifier values or credentials."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "discovery.investigation.plan",
            "maxRequestBytes": INVESTIGATION_PLAN_REQUEST_BYTES,
            "maxResponseBytes": INVESTIGATION_PLAN_RESPONSE_BYTES,
            "requiredLockState": "ANY",
            "scopeClass": "NONE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def compile_investigation_plan(
    body: InvestigationPlanCompileRequest,
    request: Request,
) -> InvestigationPlanResult:
    try:
        result = _investigation_plan_compiler(request).compile(body.to_domain())
        return InvestigationPlanResult.from_domain(result)
    except ValueError:
        raise HTTPException(status_code=400) from None


@router.post(
    "/discovery/hibp/account",
    response_model=HibpAccountResult,
    responses=ERROR_RESPONSES,
    operation_id="searchHibpAccount",
    summary="Check one authorised email address with HIBP v3",
    description=(
        "Use HIBP's six-character SHA-1 k-anonymity range by default. Direct email "
        "transmission requires a valid API key plus a separate explicit authorization. "
        "The API key is ephemeral and is never persisted, returned, or logged."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "discovery.hibp.account",
            "maxRequestBytes": HIBP_REQUEST_BYTES,
            "maxResponseBytes": HIBP_RESPONSE_BYTES,
            "requiredLockState": "ANY",
            "scopeClass": "NONE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def search_hibp_account(
    body: HibpAccountRequest,
    request: Request,
) -> HibpAccountResult:
    try:
        result = await anyio.to_thread.run_sync(
            _hibp(request).search_account,
            body.to_domain(),
        )
        return HibpAccountResult.from_domain(result)
    except ValueError:
        raise HTTPException(status_code=400) from None


@router.post(
    "/discovery/hibp/domain",
    response_model=HibpDomainResult,
    responses=ERROR_RESPONSES,
    operation_id="searchHibpDomain",
    summary="Enumerate an HIBP domain only after provider verification",
    description=(
        "First confirms the domain is present in HIBP's subscribedDomains response for the "
        "supplied key. breachedDomain is never called unless that provider-side verification "
        "succeeds. No passwords or credential material are stored or returned."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "discovery.hibp.domain",
            "maxRequestBytes": HIBP_REQUEST_BYTES,
            "maxResponseBytes": HIBP_RESPONSE_BYTES,
            "requiredLockState": "ANY",
            "scopeClass": "NONE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def search_hibp_domain(
    body: HibpDomainRequest,
    request: Request,
) -> HibpDomainResult:
    try:
        result = await anyio.to_thread.run_sync(
            _hibp(request).search_domain,
            body.to_domain(),
        )
        return HibpDomainResult.from_domain(result)
    except ValueError:
        raise HTTPException(status_code=400) from None


@router.post(
    "/discovery/public/search",
    response_model=PublicDiscoverySearchResult,
    responses=ERROR_RESPONSES,
    operation_id="searchPublicDiscovery",
    summary="Search one public provider for an authorised self-audit",
    description=(
        "Send one bounded ad-hoc query to the explicitly selected public provider after an "
        "authorised-self-audit preflight. Raw input is treated as sensitive by the server, "
        "is not persisted by this operation, and is never written to request logs."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "discovery.public.search",
            "maxRequestBytes": PUBLIC_DISCOVERY_REQUEST_BYTES,
            "maxResponseBytes": PUBLIC_DISCOVERY_RESPONSE_BYTES,
            "requiredLockState": "ANY",
            "scopeClass": "NONE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def search_public_discovery(
    body: PublicDiscoverySearchRequest,
    request: Request,
) -> PublicDiscoverySearchResult:
    try:
        domain_request = body.to_domain(sensitivity=Sensitivity.SENSITIVE)
        result = await anyio.to_thread.run_sync(
            _public_discovery(request).search,
            domain_request,
        )
        return PublicDiscoverySearchResult.from_domain(result)
    except ValueError:
        raise HTTPException(status_code=400) from None


@router.post(
    "/discovery/public/capture",
    response_model=PublicDiscoveryCaptureResult,
    responses=ERROR_RESPONSES,
    operation_id="capturePublicDiscoveryResult",
    summary="Retain one reviewed public result with its exact source",
    description=(
        "Atomically create an encrypted Phase 5 finding and structured URL-reference "
        "evidence. The exact normalized result URL is retained; the raw search query is "
        "replaced with a purpose-keyed, non-reversible reference before persistence."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "discovery.public.capture",
            "maxRequestBytes": PUBLIC_DISCOVERY_CAPTURE_REQUEST_BYTES,
            "maxResponseBytes": PUBLIC_DISCOVERY_CAPTURE_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def capture_public_discovery_result(
    body: PublicDiscoveryCaptureRequest,
    request: Request,
) -> PublicDiscoveryCaptureResult:
    try:
        return await anyio.to_thread.run_sync(
            _public_discovery_capture(request).capture,
            body,
        )
    except Exception as error:
        _raise_public_discovery_capture(error)


@router.get(
    "/session",
    response_model=SessionState,
    responses=ERROR_RESPONSES,
    operation_id="getSession",
    openapi_extra={
        "x-ariadne-capability": {
            **COMMON_CAPABILITY,
            "routeId": "session.read",
        }
    },
)
async def get_session(request: Request) -> SessionState:
    runtime = request.app.state.runtime
    manager = runtime.vault_manager
    if manager is None or not manager.has_manifest:
        lock_state = LockState.LOCKED
        vault_state = VaultState.NO_VAULT
    elif manager.is_unlocked:
        lock_state = LockState.UNLOCKED
        vault_state = VaultState.UNLOCKED
    else:
        lock_state = LockState.LOCKED
        vault_state = VaultState.LOCKED
    return SessionState(
        lock_state=lock_state,
        vault_state=vault_state,
        compatibility=CompatibilityState.COMPATIBLE,
        authenticated_transport=True,
        session_expires_at=runtime.session.expires_at,
        active_reveal_capabilities=0,
    )


@router.get(
    "/local-ai/settings",
    response_model=LocalAISettings,
    responses=ERROR_RESPONSES,
    operation_id="getLocalAISettings",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.settings.read",
            "maxRequestBytes": 0,
            "maxResponseBytes": 2048,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def get_local_ai_settings(request: Request) -> LocalAISettings:
    try:
        return await anyio.to_thread.run_sync(_local_ai_service(request).get)
    except Exception as error:
        _raise_local_ai(error)


@router.post(
    "/local-ai/workspace/analyze",
    response_model=LocalAIWorkspaceResult,
    responses=ERROR_RESPONSES,
    operation_id="analyzeLocalAIWorkspace",
    summary="Analyze selected local workspace data",
    description=(
        "Create a bounded, review-only summary, organization, or grounded answer from selected "
        "profile records and optional in-memory document text. Models use either the explicit "
        "persisted loopback configuration or one ephemeral OpenAI Responses API credential; "
        "evidence content bytes are never loaded."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.workspace.analyze",
            "maxRequestBytes": LOCAL_AI_WORKSPACE_REQUEST_BYTES,
            "maxResponseBytes": LOCAL_AI_WORKSPACE_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def analyze_local_ai_workspace(
    body: LocalAIWorkspaceRequest,
    request: Request,
) -> LocalAIWorkspaceResult:
    try:
        return await anyio.to_thread.run_sync(
            _local_ai_workspace(request).analyze,
            body,
        )
    except Exception as error:
        _raise_local_ai_workspace(error)


@router.post(
    "/local-ai/corpus/analyze",
    response_model=LocalCorpusAIResult,
    responses=ERROR_RESPONSES,
    operation_id="analyzeLocalAICorpus",
    summary="Analyze a local multi-document corpus",
    description=(
        "Safely parse up to twenty hash-bound local documents and return ephemeral, review-only "
        "summaries, organization, grounded answers, cross-document connection candidates, or "
        "evidence-gap suggestions using deterministic, loopback, or explicitly credentialed "
        "OpenAI Responses execution. Every factual claim, connection, and suggestion resolves to "
        "document and segment provenance. Optional model execution uses only the exact enabled "
        "persisted loopback model; no corpus content is persisted by this operation."
    ),
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.corpus.analyze",
            "maxRequestBytes": MAX_LOCAL_CORPUS_API_REQUEST_BYTES,
            "maxResponseBytes": MAX_LOCAL_CORPUS_API_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def analyze_local_ai_corpus(
    body: LocalCorpusAIRequest,
    request: Request,
) -> LocalCorpusAIResult:
    try:
        result = await anyio.to_thread.run_sync(
            _local_corpus_ai(request).analyze,
            body,
        )
    except Exception as error:
        _raise_local_corpus_ai(error)
    encoded_bytes = len(result.model_dump_json(by_alias=True).encode("utf-8"))
    if encoded_bytes > MAX_LOCAL_CORPUS_API_RESPONSE_BYTES:
        raise HTTPException(status_code=503)
    return result


@router.post(
    "/local-ai/settings",
    response_model=LocalAISettings,
    responses=ERROR_RESPONSES,
    operation_id="updateLocalAISettings",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.settings.update",
            "maxRequestBytes": LOCAL_AI_REQUEST_BYTES,
            "maxResponseBytes": 2048,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def update_local_ai_settings(
    body: LocalAISettingsUpdateRequest,
    request: Request,
) -> LocalAISettings:
    try:
        return await anyio.to_thread.run_sync(_local_ai_service(request).update, body)
    except Exception as error:
        _raise_local_ai(error)


@router.post(
    "/local-ai/models",
    response_model=LocalAIModelDiscoveryResult,
    responses=ERROR_RESPONSES,
    operation_id="discoverLocalAIModels",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.models.discover",
            "maxRequestBytes": LOCAL_AI_REQUEST_BYTES,
            "maxResponseBytes": LOCAL_AI_MODELS_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def discover_local_ai_models(
    body: LocalAIEndpointRequest,
    request: Request,
) -> LocalAIModelDiscoveryResult:
    try:
        return await anyio.to_thread.run_sync(_local_ai_service(request).discover, body)
    except Exception as error:
        _raise_local_ai(error)


@router.post(
    "/local-ai/test",
    response_model=LocalAIConnectionResult,
    responses=ERROR_RESPONSES,
    operation_id="testLocalAIConnection",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "local_ai.connection.test",
            "maxRequestBytes": LOCAL_AI_REQUEST_BYTES,
            "maxResponseBytes": 2048,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def test_local_ai_connection(
    body: LocalAIEndpointRequest,
    request: Request,
) -> LocalAIConnectionResult:
    try:
        return await anyio.to_thread.run_sync(
            _local_ai_service(request).test_connection,
            body,
        )
    except Exception as error:
        _raise_local_ai(error)


@router.post(
    "/events/replay",
    response_model=EventReplayResult,
    responses=ERROR_RESPONSES,
    operation_id="replayCoreEvents",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "events.replay",
            "maxRequestBytes": 128,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "SHELL_INTERNAL",
        }
    },
)
async def replay_core_events(body: EventReplayRequest, request: Request) -> EventReplayResult:
    runtime = request.app.state.runtime
    manager = runtime.vault_manager
    if manager is None or not manager.is_unlocked:
        raise _operation_failure()
    replay = EventReplayRepository(manager.engine).replay(
        manager.manifest.vault_id,
        cursor=body.cursor,
        limit=body.max_events,
    )
    return EventReplayResult(
        disposition=EventReplayDisposition(replay.disposition),
        events=tuple(
            SafeCoreEvent(
                event_id=event.event_id,
                sequence=event.sequence,
                event_type=event.event_type,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                resource_revision=event.resource_revision,
            )
            for event in replay.events
        ),
        next_cursor=replay.next_cursor,
        has_more=replay.has_more,
    )


@router.post(
    "/vaults",
    response_model=VaultLifecycleResult,
    responses=ERROR_RESPONSES,
    operation_id="createVault",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "vault.create",
            "maxRequestBytes": 1024,
            "maxResponseBytes": 65536,
            "requiredLockState": "NO_VAULT",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE_KEYCHAIN",
        }
    },
)
async def create_vault(body: VaultCreateRequest, request: Request) -> VaultLifecycleResult:
    manager, lease_client = _vault_components(request)

    def create() -> VaultManifest:
        manifest = VaultManifest(
            vault_id=body.vault_id,
            format_version=body.format_version,
            database_key_ref=body.database_key_ref,
            backup_key_ref=body.backup_key_ref,
            database_key_version=body.database_key_version,
        )
        if not hmac.compare_digest(manifest.digest().hex(), body.manifest_digest):
            raise VaultLifecycleError("vault manifest binding does not match")
        transaction = lease_client.transaction(
            transaction_id=UUID(body.transaction_id),
            vault_id=UUID(manifest.vault_id),
            manifest_digest=manifest.digest(),
            reference=manifest.database_key_ref,
            key_version=manifest.database_key_version,
            operation=LeaseOperation.DATABASE_CREATE_V1,
        )
        return manager.create_with_lease(
            display_name=body.display_name,
            manifest=manifest,
            transaction=transaction,
        )

    try:
        manifest = await anyio.to_thread.run_sync(create)
    except RuntimeError:
        raise _operation_failure() from None
    return VaultLifecycleResult(
        vault_id=manifest.vault_id,
        lock_state=LockState.UNLOCKED,
        vault_state=VaultState.UNLOCKED,
    )


@router.post(
    "/vaults/current/unlock",
    response_model=VaultLifecycleResult,
    responses=ERROR_RESPONSES,
    operation_id="unlockCurrentVault",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "vault.current.unlock",
            "maxRequestBytes": 1024,
            "maxResponseBytes": 65536,
            "requiredLockState": "LOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE_KEYCHAIN",
        }
    },
)
async def unlock_current_vault(
    body: VaultUnlockRequest,
    request: Request,
) -> VaultLifecycleResult:
    manager, lease_client = _vault_components(request)

    def unlock() -> VaultManifest:
        manifest = manager.descriptor()
        if (
            manifest.vault_id != body.vault_id
            or manifest.database_key_ref != body.database_key_ref
            or manifest.database_key_version != body.database_key_version
            or not hmac.compare_digest(manifest.digest().hex(), body.manifest_digest)
        ):
            lease_client.close()
            raise VaultLifecycleError("vault operation context does not match")
        transaction = lease_client.transaction(
            transaction_id=UUID(body.transaction_id),
            vault_id=UUID(manifest.vault_id),
            manifest_digest=manifest.digest(),
            reference=manifest.database_key_ref,
            key_version=manifest.database_key_version,
            operation=LeaseOperation.DATABASE_UNLOCK_V1,
        )
        return manager.unlock_with_lease(transaction=transaction)

    try:
        manifest = await anyio.to_thread.run_sync(unlock)
    except RuntimeError:
        raise _operation_failure() from None
    return VaultLifecycleResult(
        vault_id=manifest.vault_id,
        lock_state=LockState.UNLOCKED,
        vault_state=VaultState.UNLOCKED,
    )


@router.post(
    "/vaults/current/lock",
    response_model=VaultLifecycleResult,
    responses=ERROR_RESPONSES,
    operation_id="lockCurrentVault",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "vault.current.lock",
            "maxRequestBytes": 0,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def lock_current_vault(request: Request) -> VaultLifecycleResult:
    runtime = request.app.state.runtime
    manager = runtime.vault_manager
    if manager is None or not manager.is_unlocked:
        raise _operation_failure()
    manifest = manager.manifest
    try:
        await anyio.to_thread.run_sync(manager.lock)
    except RuntimeError:
        raise _operation_failure() from None
    return VaultLifecycleResult(
        vault_id=manifest.vault_id,
        lock_state=LockState.LOCKED,
        vault_state=VaultState.LOCKED,
    )


@router.get(
    "/profiles",
    response_model=ProfileListResult,
    responses=ERROR_RESPONSES,
    operation_id="listProfiles",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "profiles.list",
            "maxRequestBytes": 0,
            "maxResponseBytes": 262144,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "SHELL_INTERNAL",
        }
    },
)
async def list_profiles(request: Request) -> ProfileListResult:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.list_profiles)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/profiles",
    response_model=ProfileSummary,
    responses=ERROR_RESPONSES,
    operation_id="createProfile",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "profile.create",
            "maxRequestBytes": PROFILE_CREATE_BODY_BYTES,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "VAULT",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_profile(body: ProfileCreateRequest, request: Request) -> ProfileSummary:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.create_profile, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/intake/paste",
    response_model=IntakeReceipt,
    responses=ERROR_RESPONSES,
    operation_id="createPasteIntake",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "intake.paste",
            "maxRequestBytes": PASTE_INTAKE_BODY_BYTES,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def create_paste_intake(
    body: PasteIntakeRequest,
    request: Request,
) -> IntakeReceipt:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.ingest_paste, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/intake/file",
    response_model=IntakeReceipt,
    responses=ERROR_RESPONSES,
    operation_id="createFileIntake",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "intake.file",
            "maxRequestBytes": FILE_INTAKE_BODY_BYTES,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE_FILE_PICKER",
        }
    },
)
async def create_file_intake(
    body: FileIntakeRequest,
    request: Request,
) -> IntakeReceipt:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.ingest_file, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/intake/review",
    response_model=EntityReviewResult,
    responses=ERROR_RESPONSES,
    operation_id="reviewIntakeEntities",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "entities.review",
            "maxRequestBytes": PROFILE_QUERY_BODY_BYTES,
            "maxResponseBytes": LARGE_PHASE3_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def review_intake_entities(
    body: EntityReviewRequest,
    request: Request,
) -> EntityReviewResult:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.review_entities, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/entities/origins",
    response_model=EntityOriginPageResult,
    responses=ERROR_RESPONSES,
    operation_id="listEntityOrigins",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "entity.origins",
            "maxRequestBytes": PROFILE_QUERY_BODY_BYTES,
            "maxResponseBytes": LARGE_PHASE3_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def list_entity_origins(
    body: EntityOriginPageRequest,
    request: Request,
) -> EntityOriginPageResult:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.list_entity_origins, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/entities/decision",
    response_model=EntitySummary,
    responses=ERROR_RESPONSES,
    operation_id="decideEntity",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "entity.decision",
            "maxRequestBytes": ENTITY_DECISION_BODY_BYTES,
            "maxResponseBytes": 65536,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def decide_entity(
    body: EntityDecisionRequest,
    request: Request,
) -> EntitySummary:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.decide_entity, body)
    except Exception as error:
        _raise_phase3(error)


@router.post(
    "/graph/snapshot",
    response_model=GraphSnapshot,
    responses=ERROR_RESPONSES,
    operation_id="getGraphSnapshot",
    openapi_extra={
        "x-ariadne-capability": {
            "routeId": "graph.snapshot",
            "maxRequestBytes": PROFILE_QUERY_BODY_BYTES,
            "maxResponseBytes": LARGE_PHASE3_RESPONSE_BYTES,
            "requiredLockState": "UNLOCKED",
            "scopeClass": "PROFILE",
            "revealClass": "NONE",
            "authorizationClass": "USER_GESTURE",
        }
    },
)
async def get_graph_snapshot(
    body: GraphSnapshotRequest,
    request: Request,
) -> GraphSnapshot:
    coordinator = _phase3_coordinator(request)
    try:
        return await anyio.to_thread.run_sync(coordinator.graph_snapshot, body)
    except Exception as error:
        _raise_phase3(error)
