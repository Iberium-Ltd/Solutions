"""Safe API error mapping that never echoes rejected values or raw exceptions."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ariadne_core.api.schemas import ApiError, ApiErrorBody, FieldError, SafeMessage
from ariadne_core.privacy.validation import safe_field_path


def safe_request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value:
                return value
    return str(uuid4())


def error_response(
    *,
    status_code: int,
    code: str,
    message_code: str,
    request_id: str,
    retryable: bool = False,
    field_errors: Sequence[FieldError] | None = None,
) -> JSONResponse:
    body = ApiError(
        error=ApiErrorBody(
            code=code,
            message=SafeMessage(message_code=message_code, args=()),
            request_id=request_id,
            retryable=retryable,
            field_errors=None if field_errors is None else tuple(field_errors),
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True, exclude_none=True),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def validation_exception_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    field_errors = tuple(
        FieldError(
            path=safe_field_path(item.get("loc", ())),
            code=str(item.get("type", "invalid")),
            message=SafeMessage(message_code="validation.invalid_field", args=()),
        )
        for item in error.errors()
    )
    return error_response(
        status_code=400,
        code="INVALID_REQUEST",
        message_code="request.validation_failed",
        request_id=safe_request_id(request),
        field_errors=field_errors,
    )


async def http_exception_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
    if error.status_code == 404:
        return error_response(
            status_code=404,
            code="NOT_FOUND",
            message_code="request.route_not_found",
            request_id=safe_request_id(request),
        )
    if error.status_code == 409:
        return error_response(
            status_code=409,
            code="STATE_CONFLICT",
            message_code="vault.operation_conflict",
            request_id=safe_request_id(request),
        )
    if error.status_code == 503:
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message_code="vault.foundation_unavailable",
            request_id=safe_request_id(request),
            retryable=True,
        )
    return error_response(
        status_code=405 if error.status_code == 405 else 400,
        code="INVALID_REQUEST",
        message_code=(
            "request.method_not_allowed" if error.status_code == 405 else "request.invalid"
        ),
        request_id=safe_request_id(request),
    )


async def unexpected_exception_handler(request: Request, _error: Exception) -> JSONResponse:
    structlog.get_logger().error(
        "local_api_internal_error",
        request_id=safe_request_id(request),
        route_template="MATCHED" if request.scope.get("route") is not None else "UNMATCHED",
    )
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message_code="request.internal_error",
        request_id=safe_request_id(request),
    )
