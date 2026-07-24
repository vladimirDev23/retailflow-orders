from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import create_async_engine

from retailflow_orders.domain.identity import UserRole
from retailflow_orders.domain.order import Order, OrderLine
from retailflow_orders.infrastructure.database.models import (
    OrderModel,
    OutboxEventModel,
    UserModel,
)
from retailflow_orders.infrastructure.database.session import Database
from retailflow_orders.infrastructure.database.uow import SqlAlchemyUnitOfWorkFactory
from tests.integration.conftest import run_alembic

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


async def table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


async def test_migrations_upgrade_downgrade_and_reapply(postgres_url: str) -> None:
    run_alembic(postgres_url, "upgrade", "head")
    upgraded = await table_names(postgres_url)
    assert {"orders", "outbox_events", "idempotency_records"} <= upgraded

    run_alembic(postgres_url, "downgrade", "base")
    assert "orders" not in await table_names(postgres_url)

    run_alembic(postgres_url, "upgrade", "head")
    assert "orders" in await table_names(postgres_url)


async def test_order_and_outbox_commit_atomically(migrated_postgres_url: str) -> None:
    database = Database(migrated_postgres_url)
    customer_id = uuid4()
    order = Order.create(
        customer_id=customer_id,
        warehouse_id=uuid4(),
        currency="RUB",
        lines=(
            OrderLine(
                product_id=uuid4(),
                sku="INTEGRATION-100",
                product_name="Integration product",
                quantity=2,
                unit_price=Decimal("1250.00"),
            ),
        ),
        now=NOW,
    )
    try:
        async with database.session_factory() as session, session.begin():
            session.add(
                UserModel(
                    id=customer_id,
                    email=f"{customer_id}@example.test",
                    password_hash="integration-test-hash",
                    role=UserRole.CUSTOMER.value,
                    active=True,
                )
            )

        async with SqlAlchemyUnitOfWorkFactory(database.session_factory)() as uow:
            await uow.orders.add(
                order,
                actor_id=customer_id,
                correlation_id="integration-create-100",
            )
            await uow.commit()

        async with database.session_factory() as session:
            persisted = await session.scalar(
                select(OrderModel).where(OrderModel.id == order.id)
            )
            events = (
                await session.scalars(
                    select(OutboxEventModel).where(
                        OutboxEventModel.aggregate_id == order.id
                    )
                )
            ).all()
        assert persisted is not None
        assert persisted.total_amount == Decimal("2500.00")
        assert [event.event_type for event in events] == ["OrderCreated"]
    finally:
        await database.close()
