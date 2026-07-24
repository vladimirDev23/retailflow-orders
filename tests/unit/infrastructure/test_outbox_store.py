from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.infrastructure.database.models import OutboxEventModel
from retailflow_orders.infrastructure.database.outbox import (
    MAX_ERROR_LENGTH,
    SqlAlchemyOutboxStore,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
LOCK_SECONDS = 30
BATCH_SIZE = 25
UPDATE_COUNT = 2


def session_context() -> tuple[MagicMock, MagicMock]:
    session = MagicMock(spec=AsyncSession)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value = transaction
    session.scalars = AsyncMock()
    session.execute = AsyncMock()
    factory = MagicMock(return_value=session)
    return session, factory


def store(factory: MagicMock) -> SqlAlchemyOutboxStore:
    return SqlAlchemyOutboxStore(
        cast(async_sessionmaker[AsyncSession], factory),
        lock_seconds=LOCK_SECONDS,
    )


async def test_claims_pending_events_and_sets_delivery_lease() -> None:
    session, factory = session_context()
    model = OutboxEventModel(
        id=uuid4(),
        aggregate_type="Order",
        aggregate_id=uuid4(),
        event_type="OrderCreated",
        payload={"eventType": "OrderCreated"},
        occurred_at=NOW,
        attempts=0,
    )
    scalar_result = MagicMock()
    scalar_result.all.return_value = [model]
    session.scalars.return_value = scalar_result

    claimed = await store(factory).claim_batch(limit=BATCH_SIZE)

    assert len(claimed) == 1
    assert claimed[0].id == model.id
    assert claimed[0].attempts == 1
    assert model.attempts == 1
    assert model.locked_until is not None
    session.scalars.assert_awaited_once()


async def test_marks_published_and_failed_events() -> None:
    session, factory = session_context()
    outbox = store(factory)
    message_id = uuid4()

    await outbox.mark_published(message_id)
    await outbox.mark_failed(message_id, "x" * (MAX_ERROR_LENGTH + 1))

    assert session.execute.await_count == UPDATE_COUNT
    statements = [call.args[0] for call in session.execute.await_args_list]
    assert all(statement.table.name == "outbox_events" for statement in statements)
