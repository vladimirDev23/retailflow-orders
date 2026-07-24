from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import cast
from uuid import uuid4

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.types import ExceptionHandler

from retailflow_orders import __version__
from retailflow_orders.api.errors import (
    authentication_error,
    conflict_error,
    dependency_error,
    not_found_error,
    request_validation_error,
    validation_error,
)
from retailflow_orders.api.router import api_router
from retailflow_orders.application.exceptions import (
    AuthenticationError,
    CheckoutPendingError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InventoryUnavailableError,
    OrderNotFoundError,
    ProductUnavailableError,
)
from retailflow_orders.bootstrap import build_container
from retailflow_orders.config import get_settings
from retailflow_orders.domain.exceptions import (
    DomainValidationError,
    InvalidOrderTransitionError,
)
from retailflow_orders.infrastructure.database.repositories import (
    ConcurrentOrderUpdateError,
)
from retailflow_orders.observability import configure_logging

CORRELATION_HEADER = "X-Correlation-ID"
MAX_CORRELATION_LENGTH = 100


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    application.state.container = container
    try:
        yield
    finally:
        await container.close()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        summary="Idempotent order orchestration and checkout service",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix=settings.api_prefix)

    @application.middleware("http")
    async def request_context(request, call_next):  # type: ignore[no-untyped-def]
        supplied = request.headers.get(CORRELATION_HEADER, "").strip()
        correlation_id = (
            supplied if supplied and len(supplied) <= MAX_CORRELATION_LENGTH else str(uuid4())
        )
        request.state.correlation_id = correlation_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
        )
        started = perf_counter()
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        structlog.get_logger().info(
            "http_request_completed",
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return response

    application.add_exception_handler(
        AuthenticationError,
        cast(ExceptionHandler, authentication_error),
    )
    application.add_exception_handler(
        OrderNotFoundError,
        cast(ExceptionHandler, not_found_error),
    )
    application.add_exception_handler(
        DomainValidationError,
        cast(ExceptionHandler, validation_error),
    )
    application.add_exception_handler(
        ProductUnavailableError,
        cast(ExceptionHandler, validation_error),
    )
    application.add_exception_handler(
        InvalidOrderTransitionError,
        cast(ExceptionHandler, conflict_error),
    )
    application.add_exception_handler(
        ConcurrentOrderUpdateError,
        cast(ExceptionHandler, conflict_error),
    )
    application.add_exception_handler(
        IdempotencyConflictError,
        cast(ExceptionHandler, conflict_error),
    )
    application.add_exception_handler(
        IdempotencyInProgressError,
        cast(ExceptionHandler, conflict_error),
    )
    application.add_exception_handler(
        CheckoutPendingError,
        cast(ExceptionHandler, dependency_error),
    )
    application.add_exception_handler(
        InventoryUnavailableError,
        cast(ExceptionHandler, dependency_error),
    )
    application.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, request_validation_error),
    )
    Instrumentator().instrument(application).expose(
        application,
        endpoint="/metrics",
        include_in_schema=False,
    )
    return application


app = create_app()
