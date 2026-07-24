from typing import Any

from retailflow_orders.application.exceptions import OrderNotFoundError
from retailflow_orders.application.ports import IdempotencyCoordinator
from retailflow_orders.application.queries import OrderQueryService
from retailflow_orders.application.services import (
    CheckoutOrderCommand,
    CheckoutOrderService,
    CreateOrderCommand,
    CreateOrderService,
)
from retailflow_orders.domain.order import Order

CREATE_SCOPE = "orders:create"
CHECKOUT_SCOPE = "orders:checkout"
CREATED_STATUS = 201
SUCCESS_STATUS = 200


class IdempotentOrderFacade:
    def __init__(
        self,
        *,
        coordinator: IdempotencyCoordinator,
        create_service: CreateOrderService,
        checkout_service: CheckoutOrderService,
        query_service: OrderQueryService,
    ) -> None:
        self._coordinator = coordinator
        self._create_service = create_service
        self._checkout_service = checkout_service
        self._query_service = query_service

    async def create(
        self,
        command: CreateOrderCommand,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
    ) -> Order:
        claim = await self._coordinator.claim(
            scope=CREATE_SCOPE,
            key=idempotency_key,
            request_payload=request_payload,
        )
        if claim.completed:
            return await self._query_service.get_for_customer(
                claim.resource_id,
                command.customer_id,
            )
        try:
            try:
                existing = await self._query_service.get_for_customer(
                    claim.resource_id,
                    command.customer_id,
                )
            except OrderNotFoundError:
                existing = None
            order = existing or await self._create_service.execute(
                CreateOrderCommand(
                    customer_id=command.customer_id,
                    warehouse_id=command.warehouse_id,
                    lines=command.lines,
                    correlation_id=command.correlation_id,
                    order_id=claim.resource_id,
                )
            )
            await self._coordinator.complete(
                scope=CREATE_SCOPE,
                key=idempotency_key,
                response_status=CREATED_STATUS,
                response_body={"orderId": str(order.id)},
            )
            return order
        except Exception:
            await self._coordinator.abandon(scope=CREATE_SCOPE, key=idempotency_key)
            raise

    async def checkout(
        self,
        command: CheckoutOrderCommand,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
    ) -> Order:
        claim = await self._coordinator.claim(
            scope=f"{CHECKOUT_SCOPE}:{command.order_id}",
            key=idempotency_key,
            request_payload=request_payload,
            resource_id=command.order_id,
        )
        if claim.completed:
            return await self._query_service.get_for_customer(
                command.order_id,
                command.customer_id,
            )
        try:
            order = await self._checkout_service.execute(command)
            await self._coordinator.complete(
                scope=f"{CHECKOUT_SCOPE}:{command.order_id}",
                key=idempotency_key,
                response_status=SUCCESS_STATUS,
                response_body={"orderId": str(order.id), "status": order.status.value},
            )
            return order
        except Exception:
            await self._coordinator.abandon(
                scope=f"{CHECKOUT_SCOPE}:{command.order_id}",
                key=idempotency_key,
            )
            raise
