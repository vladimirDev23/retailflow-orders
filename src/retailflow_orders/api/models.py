from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from retailflow_orders.domain.order import Order


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class TokenRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class TokenResponse(ApiModel):
    access_token: str
    kind: str = Field(default="Bearer", alias="tokenType")
    expires_in: int


class CreateOrderLineRequest(ApiModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=10_000)


class CreateOrderRequest(ApiModel):
    warehouse_id: UUID
    lines: tuple[CreateOrderLineRequest, ...] = Field(min_length=1, max_length=100)


class CheckoutOrderRequest(ApiModel):
    payment_method: str = Field(
        min_length=3,
        max_length=100,
        examples=["pm_demo_approved", "pm_demo_declined"],
    )


class OrderLineResponse(ApiModel):
    product_id: UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderResponse(ApiModel):
    id: UUID
    customer_id: UUID
    warehouse_id: UUID
    status: str
    currency: str
    total: Decimal
    lines: tuple[OrderLineResponse, ...]
    reservation_id: UUID | None
    payment_reference: str | None
    failure_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, order: Order) -> "OrderResponse":
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            warehouse_id=order.warehouse_id,
            status=order.status.value,
            currency=order.currency,
            total=order.total,
            lines=tuple(
                OrderLineResponse(
                    product_id=line.product_id,
                    sku=line.sku,
                    product_name=line.product_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    subtotal=line.subtotal,
                )
                for line in order.lines
            ),
            reservation_id=order.reservation_id,
            payment_reference=order.payment_reference,
            failure_reason=order.failure_reason,
            version=order.version,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )


class OrderPageResponse(ApiModel):
    items: tuple[OrderResponse, ...]
    total: int
    limit: int
    offset: int


class ProblemResponse(ApiModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str
