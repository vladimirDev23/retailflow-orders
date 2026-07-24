from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.application.messaging import OutboxMessage
from retailflow_orders.infrastructure.database.models import OutboxEventModel

MAX_ERROR_LENGTH = 4_000


class SqlAlchemyOutboxStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lock_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._lock_seconds = lock_seconds

    async def claim_batch(self, *, limit: int) -> tuple[OutboxMessage, ...]:
        now = datetime.now(tz=UTC)
        statement = (
            select(OutboxEventModel)
            .where(
                OutboxEventModel.published_at.is_(None),
                or_(
                    OutboxEventModel.locked_until.is_(None),
                    OutboxEventModel.locked_until < now,
                ),
            )
            .order_by(OutboxEventModel.occurred_at, OutboxEventModel.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        async with self._session_factory() as session, session.begin():
            models = (await session.scalars(statement)).all()
            locked_until = now + timedelta(seconds=self._lock_seconds)
            for model in models:
                model.locked_until = locked_until
                model.attempts += 1
            messages = tuple(self._to_message(model) for model in models)
        return messages

    async def mark_published(self, message_id: UUID) -> None:
        now = datetime.now(tz=UTC)
        statement = (
            update(OutboxEventModel)
            .where(
                OutboxEventModel.id == message_id,
                OutboxEventModel.published_at.is_(None),
            )
            .values(
                published_at=now,
                locked_until=None,
                last_error=None,
            )
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def mark_failed(self, message_id: UUID, error: str) -> None:
        statement = (
            update(OutboxEventModel)
            .where(
                OutboxEventModel.id == message_id,
                OutboxEventModel.published_at.is_(None),
            )
            .values(
                locked_until=None,
                last_error=error[:MAX_ERROR_LENGTH],
            )
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    @staticmethod
    def _to_message(model: OutboxEventModel) -> OutboxMessage:
        return OutboxMessage(
            id=model.id,
            aggregate_id=model.aggregate_id,
            event_type=model.event_type,
            payload=model.payload,
            occurred_at=model.occurred_at,
            attempts=model.attempts,
        )
