import json

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError

from retailflow_orders.api.errors import (
    authentication_error,
    conflict_error,
    dependency_error,
    not_found_error,
    request_validation_error,
    validation_error,
)
from retailflow_orders.application.exceptions import (
    AuthenticationError,
    CheckoutPendingError,
    IdempotencyConflictError,
    OrderNotFoundError,
    ProductUnavailableError,
)


def request() -> Request:
    instance = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/orders",
            "headers": [],
        }
    )
    instance.state.correlation_id = "corr-error-100"
    return instance


async def test_problem_handlers_return_consistent_contract() -> None:
    responses = [
        await authentication_error(request(), AuthenticationError("invalid")),
        await not_found_error(request(), OrderNotFoundError("missing")),
        await validation_error(request(), ProductUnavailableError("unavailable")),
        await conflict_error(request(), IdempotencyConflictError("conflict")),
        await dependency_error(request(), CheckoutPendingError("retry")),
    ]

    assert [response.status_code for response in responses] == [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_409_CONFLICT,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ]
    body = json.loads(bytes(responses[0].body))
    assert body["correlationId"] == "corr-error-100"
    assert body["code"] == "authentication_failed"
    assert responses[-1].headers["retry-after"] == "5"


async def test_request_validation_handler_does_not_echo_sensitive_input() -> None:
    exception = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "paymentMethod"),
                "msg": "Field required",
                "input": None,
            }
        ]
    )

    response = await request_validation_error(request(), exception)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert b"paymentMethod" not in response.body
