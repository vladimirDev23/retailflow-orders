from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from retailflow_orders.domain.order import Order, OrderLine, OrderStatus
from retailflow_orders.infrastructure.database.models import (
    OrderModel,
    OrderTransitionModel,
    OutboxEventModel,
)
from retailflow_orders.infrastructure.database.repositories import (
    ConcurrentOrderUpdateError,
    SqlAlchemyOrderRepository,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
UPDATED_VERSION = 2
PAGE_SIZE = 20


def order() -> Order:
    return Order.create(
        customer_id=uuid4(),
        currency="RUB",
        lines=(
            OrderLine(
                sku="SKU-100",
                product_name="Barcode scanner",
                quantity=2,
                unit_price=Decimal("1250.00"),
            ),
        ),
        now=NOW,
    )


def session_mock() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    return session


async def test_add_maps_order_and_outbox_event() -> None:
    session = session_mock()
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))
    created = order()

    await repository.add(
        created,
        actor_id=created.customer_id,
        correlation_id="corr-create-100",
    )

    added = [call.args[0] for call in session.add.call_args_list]
    assert isinstance(added[0], OrderModel)
    assert added[0].total_amount == Decimal("2500.00")
    assert added[0].lines[0].sku == "SKU-100"
    assert isinstance(added[1], OutboxEventModel)
    assert added[1].payload["eventType"] == "OrderCreated"
    session.flush.assert_awaited_once()


async def test_get_restores_domain_order() -> None:
    session = session_mock()
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))
    created = order()
    model = repository._to_model(created)
    session.scalar.return_value = model

    restored = await repository.get(created.id)

    assert restored is not None
    assert restored.id == created.id
    assert restored.total == created.total
    assert restored.lines == created.lines
    assert restored.pull_events() == ()


async def test_get_returns_none_when_order_is_missing() -> None:
    session = session_mock()
    session.scalar.return_value = None
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))

    assert await repository.get(uuid4()) is None


async def test_save_uses_optimistic_version_and_writes_audit_transition() -> None:
    session = session_mock()
    session.execute.return_value = SimpleNamespace(rowcount=1)
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))
    created = order()
    created.pull_events()
    created.request_reservation(now=NOW)

    await repository.save(
        created,
        actor_id=created.customer_id,
        correlation_id="corr-checkout-100",
    )

    assert created.version == UPDATED_VERSION
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(candidate, OutboxEventModel) for candidate in added)
    transitions = [candidate for candidate in added if isinstance(candidate, OrderTransitionModel)]
    assert transitions[0].previous_status == OrderStatus.DRAFT.value
    assert transitions[0].status == OrderStatus.PENDING_RESERVATION.value
    assert transitions[0].correlation_id == "corr-checkout-100"


async def test_save_rejects_concurrent_update() -> None:
    session = session_mock()
    session.execute.return_value = SimpleNamespace(rowcount=0)
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))
    created = order()

    with pytest.raises(ConcurrentOrderUpdateError, match="changed concurrently"):
        await repository.save(
            created,
            actor_id=None,
            correlation_id="corr-race-100",
        )


async def test_lists_customer_orders_with_deterministic_page() -> None:
    session = session_mock()
    repository = SqlAlchemyOrderRepository(cast(AsyncSession, session))
    created = order()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [repository._to_model(created)]
    session.scalars.return_value = scalar_result
    session.scalar.return_value = 1

    page = await repository.list_for_customer(
        created.customer_id,
        status=OrderStatus.DRAFT,
        limit=PAGE_SIZE,
        offset=0,
    )

    assert page.total == 1
    assert page.limit == PAGE_SIZE
    assert page.offset == 0
    assert page.items[0].id == created.id
