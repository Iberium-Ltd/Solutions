"""Authenticated local-boundary middleware."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ariadne_core.api.errors import error_response
from ariadne_core.api.local_corpus_schemas import MAX_LOCAL_CORPUS_API_REQUEST_BYTES
from ariadne_core.privacy.safe_logging import RequestLogFields, log_request
from ariadne_core.security.sessions import LaunchSession

SESSION_HEADER: Final = "Ariadne-Session"
CONTRACT_HEADER: Final = "Ariadne-Contract-Version"
REQUEST_ID_HEADER: Final = "Ariadne-Request-Id"
MAX_HEADER_BYTES: Final = 16 * 1024


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    maximum_body_bytes: int


ROUTE_POLICIES: Final = {
    ("GET", "/v1/system/capabilities"): RoutePolicy(0),
    ("GET", "/v1/session"): RoutePolicy(0),
    ("POST", "/v1/events/replay"): RoutePolicy(128),
    ("POST", "/v1/vaults"): RoutePolicy(1024),
    ("POST", "/v1/vaults/current/unlock"): RoutePolicy(1024),
    ("POST", "/v1/vaults/current/lock"): RoutePolicy(0),
    ("GET", "/v1/profiles"): RoutePolicy(0),
    ("POST", "/v1/profiles"): RoutePolicy(1024),
    ("POST", "/v1/profiles/delete"): RoutePolicy(512),
    ("POST", "/v1/intake/paste"): RoutePolicy(1_052_672),
    ("POST", "/v1/intake/file"): RoutePolicy(1_402_880),
    ("POST", "/v1/intake/review"): RoutePolicy(512),
    ("POST", "/v1/entities/origins"): RoutePolicy(512),
    ("POST", "/v1/entities/decision"): RoutePolicy(2048),
    ("POST", "/v1/graph/snapshot"): RoutePolicy(512),
    ("GET", "/v1/local-ai/settings"): RoutePolicy(0),
    ("POST", "/v1/local-ai/settings"): RoutePolicy(1024),
    ("POST", "/v1/local-ai/models"): RoutePolicy(1024),
    ("POST", "/v1/local-ai/test"): RoutePolicy(1024),
    ("POST", "/v1/local-ai/workspace/analyze"): RoutePolicy(100_000),
    ("POST", "/v1/local-ai/corpus/analyze"): RoutePolicy(MAX_LOCAL_CORPUS_API_REQUEST_BYTES),
    ("POST", "/v1/query/providers"): RoutePolicy(512),
    ("POST", "/v1/query/plans"): RoutePolicy(2048),
    ("POST", "/v1/query/dry-run"): RoutePolicy(1024),
    ("POST", "/v1/discovery/public/search"): RoutePolicy(8_192),
    ("POST", "/v1/discovery/public/capture"): RoutePolicy(8_192),
    ("POST", "/v1/discovery/hibp/account"): RoutePolicy(4_096),
    ("POST", "/v1/discovery/hibp/domain"): RoutePolicy(4_096),
    ("POST", "/v1/discovery/investigation/plan"): RoutePolicy(40_960),
    # Identity endpoints return bounded projections and accept no file bytes;
    # the middleware enforces this cap before Pydantic or route code sees a body.
    ("POST", "/v1/identity/workspace"): RoutePolicy(32_768),
    ("POST", "/v1/identity/person"): RoutePolicy(32_768),
    ("POST", "/v1/identity/source"): RoutePolicy(32_768),
    ("POST", "/v1/identity/audits"): RoutePolicy(32_768),
    ("POST", "/v1/identity/audits/detail"): RoutePolicy(32_768),
    ("POST", "/v1/identity/audits/execute"): RoutePolicy(32_768),
    ("POST", "/v1/identity/audits/control"): RoutePolicy(32_768),
    ("POST", "/v1/identity/proposals/decision"): RoutePolicy(32_768),
    ("POST", "/v1/phase5/findings/manual"): RoutePolicy(4_096),
    ("POST", "/v1/phase5/findings/list"): RoutePolicy(512),
    ("POST", "/v1/phase5/findings/detail"): RoutePolicy(512),
    ("POST", "/v1/phase5/evidence/manual-import"): RoutePolicy(14_000_000),
    ("POST", "/v1/phase5/evidence/redacted-derivative"): RoutePolicy(14_000_000),
    ("POST", "/v1/phase5/attribution/decision"): RoutePolicy(512),
    ("POST", "/v1/phase6/audits/local-checkpoint"): RoutePolicy(50_000),
    ("POST", "/v1/phase6/audits/list"): RoutePolicy(512),
    ("POST", "/v1/phase6/audits/compare"): RoutePolicy(512),
    ("POST", "/v1/phase6/remediation/list"): RoutePolicy(512),
    ("POST", "/v1/phase6/remediation/detail"): RoutePolicy(512),
    ("POST", "/v1/phase6/remediation/create"): RoutePolicy(50_000),
    ("POST", "/v1/phase6/remediation/draft"): RoutePolicy(50_000),
    ("POST", "/v1/phase6/remediation/require-approval"): RoutePolicy(512),
    ("POST", "/v1/phase6/remediation/status"): RoutePolicy(6_144),
    ("POST", "/v1/phase6/remediation/deadline"): RoutePolicy(512),
    ("POST", "/v1/phase6/remediation/evidence"): RoutePolicy(4_096),
    ("POST", "/v1/phase6/remediation/provider-response"): RoutePolicy(12_288),
    ("POST", "/v1/phase6/remediation/reappearance"): RoutePolicy(4_096),
    ("POST", "/v1/reports/generate"): RoutePolicy(1_024),
}
KNOWN_PATHS: Final = frozenset(path for _method, path in ROUTE_POLICIES)

RequestHandler = Callable[[Request], Awaitable[Response]]


class LocalBoundaryMiddleware(BaseHTTPMiddleware):
    """Authenticate and bound requests before FastAPI parses route bodies."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session: LaunchSession,
        expected_host: str,
        allowed_origins: frozenset[str],
    ) -> None:
        super().__init__(app)
        if not expected_host or not allowed_origins or any("*" in item for item in allowed_origins):
            raise ValueError("local boundary allowlists must be exact")
        self._session = session
        self._expected_host = expected_host
        self._allowed_origins = allowed_origins
        self._logger = structlog.get_logger()

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        # Boundary validation precedes body parsing to cap attacker-controlled
        # allocation and reject unknown paths, proxy headers, and replayed IDs.
        started = time.monotonic()
        request_id = self._canonical_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        payload_bytes = self._payload_bytes(request)
        policy = ROUTE_POLICIES.get((request.method, request.url.path))

        rejection = self._validate_boundary(request, request_id, payload_bytes, policy)
        if rejection is not None:
            self._log(
                request=request,
                request_id=request_id,
                response=rejection,
                started=started,
                payload_bytes=max(payload_bytes, 0),
                actor_class="UNKNOWN",
            )
            return rejection

        try:
            body = await request.body()
        except Exception:
            rejection = self._error(400, "INVALID_REQUEST", "request.body_invalid", request_id)
        else:
            rejection = self._validate_body(
                request=request,
                request_id=request_id,
                declared_bytes=payload_bytes,
                actual_bytes=len(body),
                policy=policy,
            )
        if rejection is not None:
            self._log(
                request=request,
                request_id=request_id,
                response=rejection,
                started=started,
                payload_bytes=max(payload_bytes, 0),
                actor_class="SHELL",
            )
            return rejection

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        self._log(
            request=request,
            request_id=request_id,
            response=response,
            started=started,
            payload_bytes=payload_bytes,
            actor_class="SHELL",
        )
        return response

    def _validate_boundary(
        self,
        request: Request,
        request_id: str,
        payload_bytes: int,
        policy: RoutePolicy | None,
    ) -> Response | None:
        if self._header_bytes(request) > MAX_HEADER_BYTES:
            return self._error(431, "LIMIT_EXCEEDED", "request.headers_too_large", request_id)
        if request.headers.get("host") != self._expected_host:
            return self._error(403, "POLICY_DENIED", "request.host_denied", request_id)
        if request.headers.get("origin") not in self._allowed_origins:
            return self._error(403, "POLICY_DENIED", "request.origin_denied", request_id)
        if "forwarded" in request.headers or any(
            name in request.headers
            for name in ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")
        ):
            return self._error(403, "POLICY_DENIED", "request.proxy_headers_denied", request_id)
        if request.headers.get(CONTRACT_HEADER) != "1":
            return self._error(409, "SERVICE_UNAVAILABLE", "request.contract_mismatch", request_id)
        if request_id == "INVALID":
            return self._error(400, "INVALID_REQUEST", "request.id_invalid", request_id)
        if payload_bytes < 0:
            return self._error(400, "INVALID_REQUEST", "request.content_length_invalid", request_id)
        maximum_body_bytes = 0 if policy is None else policy.maximum_body_bytes
        if (
            payload_bytes > maximum_body_bytes
            or request.headers.get("transfer-encoding") is not None
        ):
            return self._error(413, "LIMIT_EXCEEDED", "request.body_not_allowed", request_id)
        if not self._session.authenticate(request.headers.get(SESSION_HEADER)):
            return self._error(401, "SESSION_EXPIRED", "session.invalid_or_expired", request_id)
        if not self._session.accept_request_id(request_id):
            return self._error(409, "INVALID_REQUEST", "request.replayed", request_id)
        return None

    @classmethod
    def _validate_body(
        cls,
        *,
        request: Request,
        request_id: str,
        declared_bytes: int,
        actual_bytes: int,
        policy: RoutePolicy | None,
    ) -> Response | None:
        maximum_body_bytes = 0 if policy is None else policy.maximum_body_bytes
        if actual_bytes > maximum_body_bytes:
            return cls._error(413, "LIMIT_EXCEEDED", "request.body_not_allowed", request_id)
        if actual_bytes != declared_bytes:
            return cls._error(400, "INVALID_REQUEST", "request.content_length_mismatch", request_id)
        if actual_bytes > 0:
            content_type = request.headers.get("content-type", "")
            if content_type.split(";", 1)[0].strip().casefold() != "application/json":
                return cls._error(
                    400, "INVALID_REQUEST", "request.content_type_invalid", request_id
                )
        return None

    @staticmethod
    def _canonical_request_id(value: str | None) -> str:
        if value is None:
            return "INVALID"
        from uuid import UUID

        try:
            parsed = UUID(value)
        except (ValueError, AttributeError, TypeError):
            return "INVALID"
        return value if str(parsed) == value else "INVALID"

    @staticmethod
    def _header_bytes(request: Request) -> int:
        return sum(len(name) + len(value) for name, value in request.scope.get("headers", ()))

    @staticmethod
    def _payload_bytes(request: Request) -> int:
        raw = request.headers.get("content-length")
        if raw is None:
            return 0
        try:
            value = int(raw)
        except ValueError:
            return -1
        return value if value >= 0 else -1

    @staticmethod
    def _error(status: int, code: str, message: str, request_id: str) -> Response:
        safe_id = request_id
        if safe_id == "INVALID":
            from uuid import uuid4

            safe_id = str(uuid4())
        return error_response(
            status_code=status,
            code=code,
            message_code=message,
            request_id=safe_id,
        )

    def _log(
        self,
        *,
        request: Request,
        request_id: str,
        response: Response,
        started: float,
        payload_bytes: int,
        actor_class: str,
    ) -> None:
        route = request.scope.get("route")
        matched_template = getattr(route, "path", None)
        if not isinstance(matched_template, str) or matched_template not in KNOWN_PATHS:
            matched_template = "UNMATCHED"
        fields: RequestLogFields = {
            "request_id": request_id if request_id != "INVALID" else "INVALID",
            "route_template": matched_template,
            "status": response.status_code,
            "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            "payload_bytes": payload_bytes,
            "actor_class": "SHELL" if actor_class == "SHELL" else "UNKNOWN",
        }
        log_request(logger=self._logger, fields=fields)
