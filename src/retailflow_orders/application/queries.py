from uuid import UUID

from retailflow_orders.application.exceptions import OrderNotFoundError
from retailflow_orders.application.ports import OrderPage, UnitOfWorkFactory
from retailflow_orders.domain.order import Order, OrderStatus


class OrderQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get_for_customer(self, order_id: UUID, customer_id: UUID) -> Order:
        async with self._uow_factory() as uow:
            order = await uow.orders.get(order_id)
        if order is None or order.customer_id != customer_id:
            message = f"Order {order_id} was not found"
            raise OrderNotFoundError(message)
        return order

    async def list_for_customer(
        self,
        customer_id: UUID,
        *,
        status: OrderStatus | None,
        limit: int,
        offset: int,
    ) -> OrderPage:
        async with self._uow_factory() as uow:
            return await uow.orders.list_for_customer(
                customer_id,
                status=status,
                limit=limit,
                offset=offset,
            )
