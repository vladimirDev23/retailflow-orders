import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from confluent_kafka import Consumer

from retailflow_orders.application.messaging import OutboxMessage
from retailflow_orders.infrastructure.messaging.kafka import KafkaEventPublisher

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
TOPIC = "retailflow.order-events.integration.v1"
POLL_TIMEOUT_SECONDS = 20


async def test_publishes_outbox_envelope_to_real_kafka(
    kafka_bootstrap_servers: str,
) -> None:
    event_id = uuid4()
    order_id = uuid4()
    message = OutboxMessage(
        id=event_id,
        aggregate_id=order_id,
        event_type="OrderCreated",
        payload={
            "eventId": str(event_id),
            "aggregateId": str(order_id),
            "eventType": "OrderCreated",
        },
        occurred_at=NOW,
        attempts=1,
    )
    publisher = KafkaEventPublisher(
        bootstrap_servers=kafka_bootstrap_servers,
        topic=TOPIC,
    )

    await publisher.publish(message)

    consumer = Consumer(
        {
            "bootstrap.servers": kafka_bootstrap_servers,
            "group.id": f"retailflow-integration-{uuid4()}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC])
    try:
        received = None
        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            candidate = await asyncio.to_thread(consumer.poll, 1.0)
            if candidate is not None and candidate.error() is None:
                received = candidate
                break
        assert received is not None
        value = received.value()
        key = received.key()
        assert value is not None
        assert key is not None
        assert json.loads(value)["aggregateId"] == str(order_id)
        assert key.decode() == str(order_id)
    finally:
        consumer.close()
