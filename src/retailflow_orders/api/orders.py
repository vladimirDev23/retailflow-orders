from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from retailflow_orders.api.dependencies import get_container, get_current_user
from retailflow_orders.api.models import (
    CheckoutOrderRequest,
    CreateOrderRequest,
    OrderPageResponse,
    OrderResponse,
)
from retailflow_orders.application.services import (
    CheckoutOrderCommand,
    CreateOrderCommand,
    CreateOrderLineCommand,
)
from retailflow_orders.bootstrap import ApplicationContainer
from retailflow_orders.domain.identity import AuthenticatedUser
from retailflow_orders.domain.order import OrderStatus

router = APIRouter(prefix="/orders", tags=["orders"])
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._:-]{8,128}$"
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_PATTERN),
]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createOrder",
)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> OrderResponse:
    command = CreateOrderCommand(
        customer_id=user.id,
        warehouse_id=body.warehouse_id,
        lines=tuple(
            CreateOrderLineCommand(
                product_id=line.product_id,
                quantity=line.quantity,
            )
            for line in body.lines
        ),
        correlation_id=request.state.correlation_id,
    )
    order = await container.orders.create(
        command,
        idempotency_key=idempotency_key,
        request_payload=body.model_dump(mode="json"),
    )
    return OrderResponse.from_domain(order)


@router.post("/{order_id}/checkout", operation_id="checkoutOrder")
async def checkout_order(
    order_id: UUID,
    body: CheckoutOrderRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> OrderResponse:
    order = await container.orders.checkout(
        CheckoutOrderCommand(
            order_id=order_id,
            customer_id=user.id,
            payment_token=body.payment_method,
            correlation_id=request.state.correlation_id,
        ),
        idempotency_key=idempotency_key,
        request_payload=body.model_dump(mode="json"),
    )
    return OrderResponse.from_domain(order)


@router.get("/{order_id}", operation_id="getOrder")
async def get_order(
    order_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> OrderResponse:
    order = await container.order_queries.get_for_customer(order_id, user.id)
    return OrderResponse.from_domain(order)


@router.get("", operation_id="listOrders")
async def list_orders(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    container: Annotated[ApplicationContainer, Depends(get_container)],
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPageResponse:
    page = await container.order_queries.list_for_customer(
        user.id,
        status=order_status,
        limit=limit,
        offset=offset,
    )
    return OrderPageResponse(
        items=tuple(OrderResponse.from_domain(order) for order in page.items),
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
