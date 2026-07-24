import asyncio
import json

from confluent_kafka import KafkaError, Message, Producer

from retailflow_orders.application.messaging import OutboxMessage

DELIVERY_TIMEOUT_SECONDS = 10


class KafkaEventPublisher:
    def __init__(self, *, bootstrap_servers: str, topic: str) -> None:
        self._topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": "retailflow-orders-outbox",
                "enable.idempotence": True,
                "acks": "all",
            }
        )

    async def publish(self, message: OutboxMessage) -> None:
        await asyncio.to_thread(self._publish_sync, message)

    def _publish_sync(self, message: OutboxMessage) -> None:
        delivery_error: list[KafkaError] = []

        def delivered(error: KafkaError | None, _: Message) -> None:
            if error is not None:
                delivery_error.append(error)

        self._producer.produce(
            topic=self._topic,
            key=str(message.aggregate_id).encode(),
            value=json.dumps(
                message.payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode(),
            headers={
                "event-id": str(message.id),
                "event-type": message.event_type,
                "content-type": "application/json",
            },
            on_delivery=delivered,
        )
        outstanding = self._producer.flush(DELIVERY_TIMEOUT_SECONDS)
        if delivery_error:
            raise RuntimeError(str(delivery_error[0]))
        if outstanding:
            message_text = f"Kafka delivery timed out with {outstanding} message(s) pending"
            raise TimeoutError(message_text)
