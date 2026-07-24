from typing import Any
from uuid import UUID

import httpx2
from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from retailflow_orders.application.exceptions import (
    InventoryRejectedError,
    InventoryUnavailableError,
)
from retailflow_orders.application.ports import ReservationResult
from retailflow_orders.domain.order import Order

SUCCESS_CODES = frozenset({200, 201})
UNPROCESSABLE_CONTENT = 422
CONFLICT = 409
SERVER_ERROR_START = 500


class InventoryReservationResponse(BaseModel):
    id: UUID
    status: str


class InventoryProblemResponse(BaseModel):
    code: str = "inventory_rejected"
    detail: str = "Inventory rejected the request"


class RetryableInventoryError(InventoryUnavailableError):
    """An idempotent request can be retried within its bounded budget."""


class HttpInventoryGateway:
    def __init__(
        self,
        *,
        client: httpx2.AsyncClient,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 2.0,
        max_attempts: int = 3,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout = httpx2.Timeout(timeout_seconds)
        self._max_attempts = max_attempts

    async def reserve(
        self,
        order: Order,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ReservationResult:
        payload = {
            "orderReference": str(order.id),
            "warehouseId": str(order.warehouse_id),
            "expiresInSeconds": 900,
            "lines": [
                {
                    "productId": str(line.product_id),
                    "quantity": line.quantity,
                }
                for line in order.lines
            ],
        }
        response = await self._post_with_retry(
            "/api/v1/reservations",
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        reservation = InventoryReservationResponse.model_validate(response.json())
        return ReservationResult(reservation_id=reservation.id)

    async def commit(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        await self._post_with_retry(
            f"/api/v1/reservations/{reservation_id}/commit",
            payload=None,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def release(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        await self._post_with_retry(
            f"/api/v1/reservations/{reservation_id}/release",
            payload=None,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def _post_with_retry(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> httpx2.Response:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.05, max=0.2),
            retry=retry_if_exception_type(RetryableInventoryError),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._post(
                    path,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                )
        message = "Inventory retry loop ended without a response"
        raise InventoryUnavailableError(message)

    async def _post(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> httpx2.Response:
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "Idempotency-Key": idempotency_key,
                    "X-Correlation-ID": correlation_id,
                },
                timeout=self._timeout,
            )
        except httpx2.TransportError as exception:
            message = f"Inventory transport failed: {type(exception).__name__}"
            raise RetryableInventoryError(message) from exception

        if response.status_code in SUCCESS_CODES:
            return response
        if response.status_code == UNPROCESSABLE_CONTENT:
            problem = self._problem(response)
            raise InventoryRejectedError(f"{problem.code}: {problem.detail}")
        if response.status_code == CONFLICT or response.status_code >= SERVER_ERROR_START:
            message = f"Inventory returned retryable HTTP {response.status_code}"
            raise RetryableInventoryError(message)
        message = f"Inventory returned non-retryable HTTP {response.status_code}"
        raise InventoryUnavailableError(message)

    @staticmethod
    def _problem(response: httpx2.Response) -> InventoryProblemResponse:
        try:
            return InventoryProblemResponse.model_validate(response.json())
        except ValueError:
            return InventoryProblemResponse()
