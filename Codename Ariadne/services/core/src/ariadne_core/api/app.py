"""FastAPI application factory for the authenticated local boundary.

The factory is the composition root: it wires explicit service dependencies
onto application state while leaving authentication, vault ownership, and
provider adapters behind their existing boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ExceptionHandler

from ariadne_core import __version__
from ariadne_core.api.errors import (
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from ariadne_core.api.middleware import LocalBoundaryMiddleware
from ariadne_core.api.routes import router
from ariadne_core.api.schemas import RuntimeTransport
from ariadne_core.application.hibp import HibpHttpTransport, HibpService
from ariadne_core.application.identity_discovery import IdentityDiscoveryCoordinator
from ariadne_core.application.investigation_planning import InvestigationPlanCompiler
from ariadne_core.application.local_ai_settings import LocalAISettingsService
from ariadne_core.application.local_ai_workspace import LocalAIWorkspaceCoordinator
from ariadne_core.application.local_corpus_ai import LocalCorpusAICoordinator
from ariadne_core.application.phase3 import Phase3Coordinator
from ariadne_core.application.phase5 import Phase5Coordinator
from ariadne_core.application.phase6 import Phase6Coordinator
from ariadne_core.application.public_discovery import (
    PublicDiscoveryHttpTransport,
    PublicDiscoveryService,
)
from ariadne_core.application.public_discovery_capture import (
    PublicDiscoveryCaptureCoordinator,
)
from ariadne_core.application.query_vertical import QueryVerticalCoordinator
from ariadne_core.application.reporting_projection import ReportingProjectionCoordinator
from ariadne_core.application.vault import VaultManager
from ariadne_core.infrastructure.db.engine import CipherRuntime
from ariadne_core.local_ai import LocalAIHttpTransport
from ariadne_core.security.key_lease import KeyLeaseClient
from ariadne_core.security.sessions import LaunchSession


@dataclass(frozen=True, slots=True)
class ApiRuntime:
    transport: RuntimeTransport
    expected_host: str
    allowed_origins: frozenset[str]
    session: LaunchSession
    vault_manager: VaultManager | None = None
    key_lease_client: KeyLeaseClient | None = None
    cipher_runtime: CipherRuntime | None = None
    local_ai_transport: LocalAIHttpTransport | None = None
    public_discovery_transport: PublicDiscoveryHttpTransport | None = None
    hibp_transport: HibpHttpTransport | None = None


def create_app(runtime: ApiRuntime) -> FastAPI:
    app = FastAPI(
        title="Codename Ariadne Local API",
        summary="Authenticated local sidecar contract",
        version=__version__,
        openapi_version="3.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    phase3_available = (
        runtime.vault_manager is not None
        and runtime.key_lease_client is not None
        and runtime.cipher_runtime is not None
    )
    app.state.phase3_coordinator = (
        Phase3Coordinator(
            runtime.vault_manager,
            local_ai_transport=runtime.local_ai_transport,
        )
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.local_ai_settings_service = (
        LocalAISettingsService(
            runtime.vault_manager,
            transport=runtime.local_ai_transport,
        )
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.local_ai_workspace_coordinator = (
        LocalAIWorkspaceCoordinator(
            runtime.vault_manager,
            transport=runtime.local_ai_transport,
        )
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.local_corpus_ai_coordinator = (
        LocalCorpusAICoordinator(
            runtime.vault_manager,
            transport=runtime.local_ai_transport,
        )
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.query_vertical_coordinator = (
        QueryVerticalCoordinator(runtime.vault_manager)
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.phase5_coordinator = (
        Phase5Coordinator(runtime.vault_manager)
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.phase6_coordinator = (
        Phase6Coordinator(runtime.vault_manager)
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.reporting_coordinator = (
        ReportingProjectionCoordinator(runtime.vault_manager)
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    public_discovery_service = PublicDiscoveryService(transport=runtime.public_discovery_transport)
    app.state.public_discovery_service = public_discovery_service
    # Recursive audits reuse the reviewed public-search adapter. The coordinator
    # receives no generic process, filesystem, or unrestricted HTTP capability.
    app.state.identity_discovery_coordinator = (
        IdentityDiscoveryCoordinator(
            runtime.vault_manager,
            public_discovery=public_discovery_service,
        )
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.state.hibp_service = HibpService(transport=runtime.hibp_transport)
    app.state.investigation_plan_compiler = InvestigationPlanCompiler()
    app.state.public_discovery_capture_coordinator = (
        PublicDiscoveryCaptureCoordinator(runtime.vault_manager)
        if phase3_available and runtime.vault_manager is not None
        else None
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_exception_handler),
    )
    app.add_exception_handler(
        StarletteHTTPException,
        cast(ExceptionHandler, http_exception_handler),
    )
    app.add_exception_handler(Exception, unexpected_exception_handler)
    app.add_middleware(
        LocalBoundaryMiddleware,
        session=runtime.session,
        expected_host=runtime.expected_host,
        allowed_origins=runtime.allowed_origins,
    )
    app.include_router(router)
    return app


def create_contract_app() -> FastAPI:
    """Create an offline-only app whose runtime values cannot enter its schema."""
    session = LaunchSession.from_token_bytes(bytes(32), ttl_seconds=None)
    return create_app(
        ApiRuntime(
            transport=RuntimeTransport.DEV_LOOPBACK,
            expected_host="127.0.0.1:1",
            allowed_origins=frozenset({"http://127.0.0.1:1420"}),
            session=session,
        )
    )
