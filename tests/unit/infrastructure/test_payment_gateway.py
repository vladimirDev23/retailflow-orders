from decimal import Decimal
from uuid import uuid4

from retailflow_orders.infrastructure.integrations.payment import (
    DeterministicPaymentGateway,
)


async def test_approved_payment_is_deterministic_for_idempotency_key() -> None:
    gateway = DeterministicPaymentGateway()
    order_id = uuid4()

    first = await gateway.charge(
        order_id=order_id,
        amount=Decimal("100.00"),
        currency="RUB",
        payment_token="pm_demo_approved",
        idempotency_key="order:100:charge",
    )
    second = await gateway.charge(
        order_id=order_id,
        amount=Decimal("100.00"),
        currency="RUB",
        payment_token="pm_demo_approved",
        idempotency_key="order:100:charge",
    )

    assert first.approved
    assert first.reference == second.reference


async def test_unknown_token_is_declined_without_echoing_it() -> None:
    decision = await DeterministicPaymentGateway().charge(
        order_id=uuid4(),
        amount=Decimal("100.00"),
        currency="RUB",
        payment_token="sensitive-unknown-token",
        idempotency_key="order:100:charge",
    )

    assert not decision.approved
    assert decision.reference is None
    assert decision.reason == "Unknown local payment token"
