import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import httpx2
import pytest

from retailflow_orders.application.exceptions import (
    InventoryRejectedError,
    InventoryUnavailableError,
)
from retailflow_orders.domain.order import Order, OrderLine
from retailflow_orders.infrastructure.integrations.inventory import HttpInventoryGateway

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
RESERVATION_ID = uuid4()
PRODUCT_ID = uuid4()
WAREHOUSE_ID = uuid4()
EXPECTED_ATTEMPTS = 3


def order() -> Order:
    return Order.create(
        customer_id=uuid4(),
        warehouse_id=WAREHOUSE_ID,
        currency="RUB",
        lines=(
            OrderLine(
                product_id=PRODUCT_ID,
                sku="SKU-100",
                product_name="Barcode scanner",
                quantity=2,
                unit_price=Decimal("100.00"),
            ),
        ),
        now=NOW,
    )


async def test_reserve_matches_published_inventory_contract() -> None:
    captured: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured
        captured = request
        return httpx2.Response(
            201,
            json={
                "id": str(RESERVATION_ID),
                "status": "ACTIVE",
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        gateway = HttpInventoryGateway(
            client=client,
            base_url="http://inventory",
            service_token="local-token",
        )
        result = await gateway.reserve(
            order(),
            idempotency_key="order:100:reserve",
            correlation_id="corr-100",
        )

    assert result.reservation_id == RESERVATION_ID
    assert captured is not None
    assert captured.headers["idempotency-key"] == "order:100:reserve"
    assert captured.headers["x-correlation-id"] == "corr-100"
    assert captured.headers["authorization"] == "Bearer local-token"
    payload = json.loads(captured.content)
    assert payload["warehouseId"] == str(WAREHOUSE_ID)
    assert payload["lines"] == [{"productId": str(PRODUCT_ID), "quantity": 2}]


async def test_explicit_business_rejection_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(
            422,
            json={"code": "insufficient_stock", "detail": "Not enough stock"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        gateway = HttpInventoryGateway(
            client=client,
            base_url="http://inventory",
            service_token="local-token",
        )
        with pytest.raises(InventoryRejectedError, match="insufficient_stock"):
            await gateway.reserve(
                order(),
                idempotency_key="order:100:reserve",
                correlation_id="corr-100",
            )

    assert attempts == 1


async def test_retryable_conflict_uses_bounded_idempotent_retry() -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(409)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        gateway = HttpInventoryGateway(
            client=client,
            base_url="http://inventory",
            service_token="local-token",
            max_attempts=EXPECTED_ATTEMPTS,
        )
        with pytest.raises(InventoryUnavailableError, match="retryable"):
            await gateway.commit(
                UUID(int=1),
                idempotency_key="order:100:commit",
                correlation_id="corr-100",
            )

    assert attempts == EXPECTED_ATTEMPTS


async def test_transport_failure_does_not_leak_token() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        gateway = HttpInventoryGateway(
            client=client,
            base_url="http://inventory",
            service_token="do-not-leak-token",
            max_attempts=1,
        )
        with pytest.raises(InventoryUnavailableError) as raised:
            await gateway.release(
                UUID(int=1),
                idempotency_key="order:100:release",
                correlation_id="corr-100",
            )

    assert "do-not-leak-token" not in str(raised.value)
