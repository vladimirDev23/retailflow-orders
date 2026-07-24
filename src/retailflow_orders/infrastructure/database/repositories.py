from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from retailflow_orders.application.ports import OrderPage
from retailflow_orders.domain.events import DomainEvent
from retailflow_orders.domain.order import Order, OrderLine, OrderStatus
from retailflow_orders.infrastructure.database.models import (
    OrderLineModel,
    OrderModel,
    OrderTransitionModel,
    OutboxEventModel,
)


class ConcurrentOrderUpdateError(Exception):
    """Raised when an optimistic order update loses a race."""


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None:
        events = order.pull_events()
        self._session.add(self._to_model(order))
        self._append_events(
            order_id=order.id,
            events=events,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        await self._session.flush()

    async def get(self, order_id: UUID) -> Order | None:
        statement = (
            select(OrderModel)
            .where(OrderModel.id == order_id)
            .options(selectinload(OrderModel.lines))
        )
        model = await self._session.scalar(statement)
        return None if model is None else self._to_domain(model)

    async def save(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None:
        expected_version = order.version
        statement = (
            update(OrderModel)
            .where(
                OrderModel.id == order.id,
                OrderModel.version == expected_version,
            )
            .values(
                status=order.status.value,
                reservation_id=order.reservation_id,
                payment_reference=order.payment_reference,
                failure_reason=order.failure_reason,
                updated_at=order.updated_at,
                version=expected_version + 1,
            )
        )
        result = await self._session.execute(statement)
        if result.rowcount != 1:  # type: ignore[attr-defined]
            message = f"Order {order.id} was changed concurrently"
            raise ConcurrentOrderUpdateError(message)

        order.version = expected_version + 1
        self._append_events(
            order_id=order.id,
            events=order.pull_events(),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        await self._session.flush()

    async def list_for_customer(
        self,
        customer_id: UUID,
        *,
        status: OrderStatus | None,
        limit: int,
        offset: int,
    ) -> OrderPage:
        filters = [OrderModel.customer_id == customer_id]
        if status is not None:
            filters.append(OrderModel.status == status.value)

        statement: Select[tuple[OrderModel]] = (
            select(OrderModel)
            .where(*filters)
            .options(selectinload(OrderModel.lines))
            .order_by(OrderModel.created_at.desc(), OrderModel.id)
            .limit(limit)
            .offset(offset)
        )
        count_statement = select(func.count()).select_from(OrderModel).where(*filters)
        models = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(count_statement)
        return OrderPage(
            items=tuple(self._to_domain(model) for model in models),
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _to_model(order: Order) -> OrderModel:
        return OrderModel(
            id=order.id,
            customer_id=order.customer_id,
            warehouse_id=order.warehouse_id,
            currency=order.currency,
            total_amount=order.total,
            status=order.status.value,
            reservation_id=order.reservation_id,
            payment_reference=order.payment_reference,
            failure_reason=order.failure_reason,
            version=order.version,
            created_at=order.created_at,
            updated_at=order.updated_at,
            lines=[
                OrderLineModel(
                    product_id=line.product_id,
                    sku=line.sku,
                    product_name=line.product_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                )
                for line in order.lines
            ],
        )

    @staticmethod
    def _to_domain(model: OrderModel) -> Order:
        return Order(
            id=model.id,
            customer_id=model.customer_id,
            warehouse_id=model.warehouse_id,
            currency=model.currency,
            lines=tuple(
                OrderLine(
                    product_id=line.product_id,
                    sku=line.sku,
                    product_name=line.product_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                )
                for line in model.lines
            ),
            status=OrderStatus(model.status),
            reservation_id=model.reservation_id,
            payment_reference=model.payment_reference,
            failure_reason=model.failure_reason,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _append_events(
        self,
        *,
        order_id: UUID,
        events: tuple[DomainEvent, ...],
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None:
        for event in events:
            self._session.add(
                OutboxEventModel(
                    id=event.event_id,
                    aggregate_type="Order",
                    aggregate_id=event.aggregate_id,
                    event_type=event.name,
                    payload=self._json_payload(event),
                    occurred_at=event.occurred_at,
                )
            )
            if event.name == "OrderStatusChanged":
                self._session.add(
                    OrderTransitionModel(
                        order_id=order_id,
                        previous_status=str(event.payload["previousStatus"]),
                        status=str(event.payload["status"]),
                        reason=self._optional_string(event.payload.get("reason")),
                        actor_id=actor_id,
                        correlation_id=correlation_id,
                        occurred_at=event.occurred_at,
                    )
                )

    @staticmethod
    def _json_payload(event: DomainEvent) -> dict[str, Any]:
        return {
            "eventId": str(event.event_id),
            "aggregateId": str(event.aggregate_id),
            "eventType": event.name,
            "occurredAt": event.occurred_at.isoformat(),
            "data": event.payload,
        }

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return None if value is None else str(value)
