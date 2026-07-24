from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from retailflow_orders.api.models import ProblemResponse
from retailflow_orders.application.exceptions import (
    AuthenticationError,
    CheckoutPendingError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InventoryUnavailableError,
    OrderNotFoundError,
    ProductUnavailableError,
)
from retailflow_orders.domain.exceptions import (
    DomainValidationError,
    InvalidOrderTransitionError,
)
from retailflow_orders.infrastructure.database.repositories import (
    ConcurrentOrderUpdateError,
)


def problem(
    request: Request,
    *,
    http_status: int,
    code: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemResponse(
        type=f"urn:retailflow:problem:{code}",
        title=title,
        status=http_status,
        detail=detail,
        code=code,
        correlation_id=getattr(request.state, "correlation_id", "unavailable"),
    )
    return JSONResponse(
        status_code=http_status,
        content=body.model_dump(mode="json", by_alias=True),
        headers=headers,
        media_type="application/problem+json",
    )


async def authentication_error(request: Request, exception: AuthenticationError) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_401_UNAUTHORIZED,
        code="authentication_failed",
        title="Unauthorized",
        detail=str(exception),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def not_found_error(request: Request, exception: OrderNotFoundError) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_404_NOT_FOUND,
        code="order_not_found",
        title="Not Found",
        detail=str(exception),
    )


async def validation_error(
    request: Request,
    exception: DomainValidationError | ProductUnavailableError,
) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="business_rule_violation",
        title="Unprocessable Content",
        detail=str(exception),
    )


async def conflict_error(
    request: Request,
    exception: (
        InvalidOrderTransitionError
        | ConcurrentOrderUpdateError
        | IdempotencyConflictError
        | IdempotencyInProgressError
    ),
) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_409_CONFLICT,
        code="conflict",
        title="Conflict",
        detail=str(exception),
    )


async def dependency_error(
    request: Request,
    exception: CheckoutPendingError | InventoryUnavailableError,
) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="external_dependency_pending",
        title="Service Unavailable",
        detail=str(exception),
        headers={"Retry-After": "5"},
    )


async def request_validation_error(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    return problem(
        request,
        http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_failed",
        title="Unprocessable Content",
        detail=f"Request validation failed with {len(exception.errors())} error(s)",
    )
