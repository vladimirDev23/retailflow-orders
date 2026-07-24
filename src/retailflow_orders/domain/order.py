from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from retailflow_orders.domain.events import DomainEvent
from retailflow_orders.domain.exceptions import (
    DomainValidationError,
    InvalidOrderTransitionError,
)

MONEY_SCALE = Decimal("0.01")
MIN_QUANTITY = 1
MAX_QUANTITY = 10_000
MAX_SKU_LENGTH = 64
MAX_PRODUCT_NAME_LENGTH = 200
MAX_FAILURE_REASON_LENGTH = 500
CURRENCY_CODE_LENGTH = 3


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_RESERVATION = "PENDING_RESERVATION"
    RESERVED = "RESERVED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    COMPENSATION_PENDING = "COMPENSATION_PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RESERVATION_FAILED = "RESERVATION_FAILED"


TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELLED,
        OrderStatus.RESERVATION_FAILED,
    }
)

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT: frozenset({OrderStatus.PENDING_RESERVATION}),
    OrderStatus.PENDING_RESERVATION: frozenset(
        {OrderStatus.RESERVED, OrderStatus.RESERVATION_FAILED}
    ),
    OrderStatus.RESERVED: frozenset({OrderStatus.PAYMENT_PENDING}),
    OrderStatus.PAYMENT_PENDING: frozenset(
        {OrderStatus.CONFIRMED, OrderStatus.COMPENSATION_PENDING}
    ),
    OrderStatus.COMPENSATION_PENDING: frozenset({OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.RESERVATION_FAILED: frozenset(),
}


def _require_aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        message = "Domain timestamps must include a timezone"
        raise DomainValidationError(message)


@dataclass(frozen=True, slots=True)
class OrderLine:
    product_id: UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal

    def __post_init__(self) -> None:
        normalized_sku = self.sku.strip().upper()
        normalized_name = self.product_name.strip()
        if not normalized_sku or len(normalized_sku) > MAX_SKU_LENGTH:
            message = f"SKU must contain 1-{MAX_SKU_LENGTH} characters"
            raise DomainValidationError(message)
        if not normalized_name or len(normalized_name) > MAX_PRODUCT_NAME_LENGTH:
            message = f"Product name must contain 1-{MAX_PRODUCT_NAME_LENGTH} characters"
            raise DomainValidationError(message)
        if not MIN_QUANTITY <= self.quantity <= MAX_QUANTITY:
            message = f"Quantity must be between {MIN_QUANTITY} and {MAX_QUANTITY}"
            raise DomainValidationError(message)
        if not self.unit_price.is_finite() or self.unit_price < MONEY_SCALE:
            message = "Unit price must be a positive finite amount"
            raise DomainValidationError(message)
        if self.unit_price.quantize(MONEY_SCALE) != self.unit_price:
            message = "Unit price must have at most two decimal places"
            raise DomainValidationError(message)
        object.__setattr__(self, "sku", normalized_sku)
        object.__setattr__(self, "product_name", normalized_name)

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(slots=True)
class Order:
    id: UUID
    customer_id: UUID
    warehouse_id: UUID
    currency: str
    lines: tuple[OrderLine, ...]
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    reservation_id: UUID | None = None
    payment_reference: str | None = None
    failure_reason: str | None = None
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        customer_id: UUID,
        warehouse_id: UUID,
        currency: str,
        lines: tuple[OrderLine, ...],
        now: datetime,
        order_id: UUID | None = None,
    ) -> Self:
        _require_aware(now)
        normalized_currency = currency.strip().upper()
        if len(normalized_currency) != CURRENCY_CODE_LENGTH or not normalized_currency.isalpha():
            message = "Currency must be a three-letter ISO-style code"
            raise DomainValidationError(message)
        if not lines:
            message = "An order must contain at least one line"
            raise DomainValidationError(message)
        skus = [line.sku for line in lines]
        if len(skus) != len(set(skus)):
            message = "An order cannot contain duplicate SKUs"
            raise DomainValidationError(message)

        order = cls(
            id=order_id or uuid4(),
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            currency=normalized_currency,
            lines=lines,
            status=OrderStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        order._record_event(
            "OrderCreated",
            now,
            {
                "customerId": str(customer_id),
                "warehouseId": str(warehouse_id),
                "currency": normalized_currency,
                "total": str(order.total),
                "status": order.status.value,
            },
        )
        return order

    @property
    def total(self) -> Decimal:
        return sum((line.subtotal for line in self.lines), start=Decimal("0.00"))

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def request_reservation(self, *, now: datetime) -> None:
        self._transition(OrderStatus.PENDING_RESERVATION, now=now)

    def mark_reserved(self, *, reservation_id: UUID, now: datetime) -> None:
        if self.reservation_id is not None and self.reservation_id != reservation_id:
            message = "Order already references a different reservation"
            raise DomainValidationError(message)
        self._transition(OrderStatus.RESERVED, now=now)
        self.reservation_id = reservation_id

    def mark_reservation_failed(self, *, reason: str, now: datetime) -> None:
        self.failure_reason = self._validated_reason(reason)
        self._transition(OrderStatus.RESERVATION_FAILED, now=now, reason=self.failure_reason)

    def request_payment(self, *, now: datetime) -> None:
        if self.reservation_id is None:
            message = "Payment cannot start before an inventory reservation exists"
            raise DomainValidationError(message)
        self._transition(OrderStatus.PAYMENT_PENDING, now=now)

    def record_payment_approval(self, *, payment_reference: str, now: datetime) -> None:
        _require_aware(now)
        if self.status is not OrderStatus.PAYMENT_PENDING:
            message = "Payment approval can only be recorded while payment is pending"
            raise InvalidOrderTransitionError(message)
        normalized_reference = payment_reference.strip()
        if not normalized_reference:
            message = "Payment reference cannot be empty"
            raise DomainValidationError(message)
        if self.payment_reference is not None and self.payment_reference != normalized_reference:
            message = "Order already references a different payment"
            raise DomainValidationError(message)
        self.payment_reference = normalized_reference
        self.updated_at = now
        self._record_event(
            "OrderPaymentApproved",
            now,
            {"paymentReference": normalized_reference},
        )

    def confirm_payment(self, *, payment_reference: str, now: datetime) -> None:
        normalized_reference = payment_reference.strip()
        if not normalized_reference:
            message = "Payment reference cannot be empty"
            raise DomainValidationError(message)
        if self.payment_reference is not None and self.payment_reference != normalized_reference:
            message = "Order already references a different payment"
            raise DomainValidationError(message)
        self._transition(OrderStatus.CONFIRMED, now=now)
        self.payment_reference = normalized_reference

    def request_compensation(self, *, reason: str, now: datetime) -> None:
        self.failure_reason = self._validated_reason(reason)
        self._transition(OrderStatus.COMPENSATION_PENDING, now=now, reason=self.failure_reason)

    def mark_cancelled(self, *, now: datetime) -> None:
        self._transition(OrderStatus.CANCELLED, now=now, reason=self.failure_reason)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        pending = tuple(self._events)
        self._events.clear()
        return pending

    def _transition(
        self,
        target: OrderStatus,
        *,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        _require_aware(now)
        previous = self.status
        if target not in ALLOWED_TRANSITIONS[previous]:
            message = f"Order cannot transition from {previous.value} to {target.value}"
            raise InvalidOrderTransitionError(message)
        self.status = target
        self.updated_at = now
        self._record_event(
            "OrderStatusChanged",
            now,
            {
                "previousStatus": previous.value,
                "status": target.value,
                "reason": reason,
            },
        )

    def _record_event(
        self,
        name: str,
        occurred_at: datetime,
        payload: dict[str, str | None],
    ) -> None:
        self._events.append(
            DomainEvent.create(
                name=name,
                aggregate_id=self.id,
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    @staticmethod
    def _validated_reason(reason: str) -> str:
        normalized = reason.strip()
        if not normalized or len(normalized) > MAX_FAILURE_REASON_LENGTH:
            message = f"Failure reason must contain 1-{MAX_FAILURE_REASON_LENGTH} characters"
            raise DomainValidationError(message)
        return normalized
