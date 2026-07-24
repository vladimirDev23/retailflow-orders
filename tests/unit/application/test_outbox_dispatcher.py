from datetime import UTC, datetime
from uuid import UUID, uuid4

from retailflow_orders.application.messaging import OutboxDispatcher, OutboxMessage

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
BATCH_SIZE = 25
MESSAGE_COUNT = 2


def message() -> OutboxMessage:
    message_id = uuid4()
    aggregate_id = uuid4()
    return OutboxMessage(
        id=message_id,
        aggregate_id=aggregate_id,
        event_type="OrderCreated",
        payload={
            "eventId": str(message_id),
            "aggregateId": str(aggregate_id),
            "eventType": "OrderCreated",
        },
        occurred_at=NOW,
        attempts=1,
    )


class StoreFake:
    def __init__(self, messages: tuple[OutboxMessage, ...]) -> None:
        self.messages = messages
        self.limit: int | None = None
        self.published: list[UUID] = []
        self.failed: list[tuple[UUID, str]] = []

    async def claim_batch(self, *, limit: int) -> tuple[OutboxMessage, ...]:
        self.limit = limit
        return self.messages

    async def mark_published(self, message_id: UUID) -> None:
        self.published.append(message_id)

    async def mark_failed(self, message_id: UUID, error: str) -> None:
        self.failed.append((message_id, error))


class PublisherFake:
    def __init__(self, *, fail_id: UUID | None = None) -> None:
        self.fail_id = fail_id
        self.published: list[OutboxMessage] = []

    async def publish(self, pending: OutboxMessage) -> None:
        if pending.id == self.fail_id:
            raise TimeoutError("broker unavailable")
        self.published.append(pending)


async def test_dispatches_claimed_messages_and_marks_success() -> None:
    pending = message()
    store = StoreFake((pending,))
    publisher = PublisherFake()

    result = await OutboxDispatcher(
        store=store,
        publisher=publisher,
    ).dispatch_batch(limit=BATCH_SIZE)

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert store.limit == BATCH_SIZE
    assert store.published == [pending.id]
    assert publisher.published == [pending]


async def test_isolates_publish_failure_and_continues_batch() -> None:
    failed = message()
    delivered = message()
    store = StoreFake((failed, delivered))
    publisher = PublisherFake(fail_id=failed.id)

    result = await OutboxDispatcher(store=store, publisher=publisher).dispatch_batch(limit=10)

    assert result.claimed == MESSAGE_COUNT
    assert result.published == 1
    assert result.failed == 1
    assert store.published == [delivered.id]
    assert store.failed == [(failed.id, "TimeoutError: broker unavailable")]
