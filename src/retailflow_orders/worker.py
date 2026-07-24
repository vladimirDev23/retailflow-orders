import asyncio
from dataclasses import asdict
from typing import Any

from celery import Celery

from retailflow_orders.application.messaging import OutboxDispatcher
from retailflow_orders.application.reconciliation import CheckoutReconciler
from retailflow_orders.bootstrap import build_container
from retailflow_orders.config import Settings
from retailflow_orders.infrastructure.database.outbox import SqlAlchemyOutboxStore
from retailflow_orders.infrastructure.database.reconciliation import SqlAlchemyRecoveryQueue
from retailflow_orders.infrastructure.database.session import Database
from retailflow_orders.infrastructure.messaging.kafka import KafkaEventPublisher

settings = Settings()
celery_app = Celery(
    "retailflow-orders",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    beat_schedule={
        "dispatch-order-outbox": {
            "task": "retailflow_orders.dispatch_outbox",
            "schedule": 2.0,
        },
        "reconcile-order-checkouts": {
            "task": "retailflow_orders.reconcile_checkouts",
            "schedule": 30.0,
        },
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


async def _dispatch_outbox() -> dict[str, int]:
    database = Database(settings.database_url)
    try:
        dispatcher = OutboxDispatcher(
            store=SqlAlchemyOutboxStore(
                database.session_factory,
                lock_seconds=settings.outbox_lock_seconds,
            ),
            publisher=KafkaEventPublisher(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                topic=settings.kafka_order_events_topic,
            ),
        )
        result = await dispatcher.dispatch_batch(limit=settings.outbox_batch_size)
        return asdict(result)
    finally:
        await database.close()


async def _reconcile_checkouts() -> dict[str, int]:
    container = build_container(settings)
    try:
        reconciler = CheckoutReconciler(
            queue=SqlAlchemyRecoveryQueue(container.database.session_factory),
            checkout=container.checkout,
        )
        result = await reconciler.reconcile_batch(limit=settings.reconciliation_batch_size)
        return asdict(result)
    finally:
        await container.close()


@celery_app.task(name="retailflow_orders.dispatch_outbox")  # type: ignore[untyped-decorator]
def dispatch_outbox() -> dict[str, Any]:
    return asyncio.run(_dispatch_outbox())


@celery_app.task(name="retailflow_orders.reconcile_checkouts")  # type: ignore[untyped-decorator]
def reconcile_checkouts() -> dict[str, Any]:
    return asyncio.run(_reconcile_checkouts())
