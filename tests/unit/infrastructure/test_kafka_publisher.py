from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from retailflow_orders.application.messaging import OutboxMessage
from retailflow_orders.infrastructure.messaging import kafka

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def message() -> OutboxMessage:
    message_id = uuid4()
    aggregate_id = uuid4()
    return OutboxMessage(
        id=message_id,
        aggregate_id=aggregate_id,
        event_type="OrderConfirmed",
        payload={
            "eventId": str(message_id),
            "aggregateId": str(aggregate_id),
            "eventType": "OrderConfirmed",
        },
        occurred_at=NOW,
        attempts=1,
    )


class ProducerFake:
    def __init__(self, *, delivery_error: object | None = None, outstanding: int = 0) -> None:
        self.delivery_error = delivery_error
        self.outstanding = outstanding
        self.configuration: dict[str, Any] | None = None
        self.produced: dict[str, Any] | None = None

    def produce(self, **kwargs: Any) -> None:
        self.produced = kwargs
        kwargs["on_delivery"](self.delivery_error, MagicMock())

    def flush(self, timeout: int) -> int:
        assert timeout == kafka.DELIVERY_TIMEOUT_SECONDS
        return self.outstanding


def publisher(
    monkeypatch: pytest.MonkeyPatch,
    producer: ProducerFake,
) -> kafka.KafkaEventPublisher:
    def build_producer(configuration: dict[str, Any]) -> ProducerFake:
        producer.configuration = configuration
        return producer

    monkeypatch.setattr(kafka, "Producer", build_producer)
    return kafka.KafkaEventPublisher(
        bootstrap_servers="kafka:9092",
        topic="retailflow.order-events.v1",
    )


async def test_publishes_json_with_stable_key_and_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = ProducerFake()
    event = message()

    await publisher(monkeypatch, producer).publish(event)

    assert producer.configuration is not None
    assert producer.configuration["enable.idempotence"] is True
    assert producer.produced is not None
    assert producer.produced["key"] == str(event.aggregate_id).encode()
    assert producer.produced["headers"]["event-id"] == str(event.id)


def test_raises_delivery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = ProducerFake(delivery_error=RuntimeError("broker rejected message"))

    with pytest.raises(RuntimeError, match="broker rejected"):
        publisher(monkeypatch, producer)._publish_sync(message())


def test_raises_timeout_for_undelivered_message(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = ProducerFake(outstanding=1)

    with pytest.raises(TimeoutError, match="1 message"):
        publisher(monkeypatch, producer)._publish_sync(message())
