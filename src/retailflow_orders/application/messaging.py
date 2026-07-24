from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class DispatchResult:
    claimed: int
    published: int
    failed: int


class OutboxStore(Protocol):
    async def claim_batch(self, *, limit: int) -> tuple[OutboxMessage, ...]: ...

    async def mark_published(self, message_id: UUID) -> None: ...

    async def mark_failed(self, message_id: UUID, error: str) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None: ...


class OutboxDispatcher:
    def __init__(self, *, store: OutboxStore, publisher: EventPublisher) -> None:
        self._store = store
        self._publisher = publisher

    async def dispatch_batch(self, *, limit: int) -> DispatchResult:
        messages = await self._store.claim_batch(limit=limit)
        published = 0
        failed = 0
        for message in messages:
            try:
                await self._publisher.publish(message)
            except Exception as exception:
                failed += 1
                error = f"{type(exception).__name__}: {exception}"
                await self._store.mark_failed(message.id, error)
                continue
            await self._store.mark_published(message.id)
            published += 1
        return DispatchResult(
            claimed=len(messages),
            published=published,
            failed=failed,
        )
