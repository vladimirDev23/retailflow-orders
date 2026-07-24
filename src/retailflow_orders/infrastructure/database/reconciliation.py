from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.application.reconciliation import RecoverableOrder
from retailflow_orders.domain.order import OrderStatus
from retailflow_orders.infrastructure.database.models import OrderModel


class SqlAlchemyRecoveryQueue:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_batch(self, *, limit: int) -> tuple[RecoverableOrder, ...]:
        statement = (
            select(OrderModel.id, OrderModel.customer_id, OrderModel.status)
            .where(
                or_(
                    OrderModel.status == OrderStatus.COMPENSATION_PENDING.value,
                    (
                        (OrderModel.status == OrderStatus.PAYMENT_PENDING.value)
                        & OrderModel.payment_reference.is_not(None)
                    ),
                )
            )
            .order_by(OrderModel.updated_at, OrderModel.id)
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            RecoverableOrder(
                order_id=row.id,
                customer_id=row.customer_id,
                status=OrderStatus(row.status),
            )
            for row in rows
        )
