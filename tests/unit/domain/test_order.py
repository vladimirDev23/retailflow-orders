from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from retailflow_orders.domain.exceptions import (
    DomainValidationError,
    InvalidOrderTransitionError,
)
from retailflow_orders.domain.order import Order, OrderLine, OrderStatus

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def line(
    *,
    sku: str = "sku-100",
    quantity: int = 2,
    unit_price: Decimal = Decimal("19.95"),
) -> OrderLine:
    return OrderLine(
        sku=sku,
        product_name="Industrial barcode scanner",
        quantity=quantity,
        unit_price=unit_price,
    )


def order() -> Order:
    return Order.create(
        customer_id=uuid4(),
        currency="rub",
        lines=(line(),),
        now=NOW,
    )


def test_creates_draft_with_normalized_snapshot_and_event() -> None:
    created = order()

    assert created.status is OrderStatus.DRAFT
    assert created.currency == "RUB"
    assert created.lines[0].sku == "SKU-100"
    assert created.total == Decimal("39.90")
    events = created.pull_events()
    assert [event.name for event in events] == ["OrderCreated"]
    assert events[0].payload["total"] == "39.90"
    assert created.pull_events() == ()


def test_completes_happy_path_and_records_each_transition() -> None:
    created = order()
    created.pull_events()
    reservation_id = uuid4()

    created.request_reservation(now=NOW + timedelta(seconds=1))
    created.mark_reserved(reservation_id=reservation_id, now=NOW + timedelta(seconds=2))
    created.request_payment(now=NOW + timedelta(seconds=3))
    created.confirm_payment(
        payment_reference="pay-verified-100",
        now=NOW + timedelta(seconds=4),
    )

    assert created.status is OrderStatus.CONFIRMED
    assert created.is_terminal
    assert created.reservation_id == reservation_id
    assert created.payment_reference == "pay-verified-100"
    assert [event.payload["status"] for event in created.pull_events()] == [
        OrderStatus.PENDING_RESERVATION.value,
        OrderStatus.RESERVED.value,
        OrderStatus.PAYMENT_PENDING.value,
        OrderStatus.CONFIRMED.value,
    ]


def test_declined_payment_requires_inventory_compensation() -> None:
    created = order()
    created.request_reservation(now=NOW)
    created.mark_reserved(reservation_id=uuid4(), now=NOW)
    created.request_payment(now=NOW)

    created.request_compensation(reason="payment declined", now=NOW)
    assert created.pull_events()[-1].payload["status"] == OrderStatus.COMPENSATION_PENDING.value
    assert not created.is_terminal

    created.mark_cancelled(now=NOW)
    assert created.status is OrderStatus.CANCELLED
    assert created.failure_reason == "payment declined"


def test_reservation_failure_is_terminal() -> None:
    created = order()
    created.request_reservation(now=NOW)

    created.mark_reservation_failed(reason="insufficient stock", now=NOW)

    assert created.status is OrderStatus.RESERVATION_FAILED
    assert created.is_terminal


def test_rejects_invalid_transition() -> None:
    created = order()

    with pytest.raises(
        InvalidOrderTransitionError,
        match="DRAFT to CONFIRMED",
    ):
        created.confirm_payment(payment_reference="pay-100", now=NOW)


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            OrderLine(
                sku="sku-1",
                product_name="First",
                quantity=1,
                unit_price=Decimal("1.00"),
            ),
            "duplicate SKUs",
        ),
    ],
)
def test_rejects_duplicate_skus(candidate: OrderLine, message: str) -> None:
    with pytest.raises(DomainValidationError, match=message):
        Order.create(
            customer_id=uuid4(),
            currency="RUB",
            lines=(candidate, candidate),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sku": "", "quantity": 1, "unit_price": Decimal("1.00")}, "SKU"),
        ({"sku": "sku", "quantity": 0, "unit_price": Decimal("1.00")}, "Quantity"),
        ({"sku": "sku", "quantity": 1, "unit_price": Decimal("0.00")}, "positive"),
        ({"sku": "sku", "quantity": 1, "unit_price": Decimal("1.001")}, "decimal"),
    ],
)
def test_rejects_invalid_order_lines(
    kwargs: dict[str, str | int | Decimal],
    message: str,
) -> None:
    with pytest.raises(DomainValidationError, match=message):
        OrderLine(product_name="Product", **kwargs)  # type: ignore[arg-type]


def test_rejects_naive_timestamps() -> None:
    with pytest.raises(DomainValidationError, match="timezone"):
        Order.create(
            customer_id=uuid4(),
            currency="RUB",
            lines=(line(),),
            now=NOW.replace(tzinfo=None),
        )
