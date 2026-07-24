from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.domain.order import OrderStatus
from retailflow_orders.infrastructure.database.reconciliation import (
    SqlAlchemyRecoveryQueue,
)

BATCH_SIZE = 20


async def test_finds_only_database_selected_recoverable_orders() -> None:
    customer_id = uuid4()
    order_id = uuid4()
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            id=order_id,
            customer_id=customer_id,
            status=OrderStatus.PAYMENT_PENDING.value,
        )
    ]
    session = MagicMock(spec=AsyncSession)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    factory = MagicMock(return_value=session)
    queue = SqlAlchemyRecoveryQueue(
        cast(async_sessionmaker[AsyncSession], factory)
    )

    candidates = await queue.find_batch(limit=BATCH_SIZE)

    assert len(candidates) == 1
    assert candidates[0].order_id == order_id
    assert candidates[0].customer_id == customer_id
    assert candidates[0].status is OrderStatus.PAYMENT_PENDING
    session.execute.assert_awaited_once()
