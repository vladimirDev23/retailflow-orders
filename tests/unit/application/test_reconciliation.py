from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from retailflow_orders.application.exceptions import CheckoutPendingError
from retailflow_orders.application.reconciliation import (
    RECOVERY_PAYMENT_PLACEHOLDER,
    CheckoutReconciler,
    RecoverableOrder,
)
from retailflow_orders.application.services import CheckoutOrderCommand
from retailflow_orders.domain.order import Order, OrderLine, OrderStatus

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
BATCH_SIZE = 20
SELECTED_COUNT = 2


class QueueFake:
    def __init__(self, candidates: tuple[RecoverableOrder, ...]) -> None:
        self.candidates = candidates
        self.limit: int | None = None

    async def find_batch(self, *, limit: int) -> tuple[RecoverableOrder, ...]:
        self.limit = limit
        return self.candidates


class CheckoutFake:
    def __init__(self, *, pending_id: UUID | None = None) -> None:
        self.pending_id = pending_id
        self.commands: list[CheckoutOrderCommand] = []

    async def execute(self, command: CheckoutOrderCommand) -> Order:
        self.commands.append(command)
        if command.order_id == self.pending_id:
            raise CheckoutPendingError("still pending")
        return Order.create(
            order_id=command.order_id,
            customer_id=command.customer_id,
            warehouse_id=uuid4(),
            currency="RUB",
            lines=(
                OrderLine(
                    product_id=uuid4(),
                    sku="SKU-100",
                    product_name="Scanner",
                    quantity=1,
                    unit_price=Decimal("100.00"),
                ),
            ),
            now=NOW,
        )


async def test_reconciles_safe_states_and_reports_pending_items() -> None:
    payment_pending = RecoverableOrder(
        order_id=uuid4(),
        customer_id=uuid4(),
        status=OrderStatus.PAYMENT_PENDING,
    )
    compensation_pending = RecoverableOrder(
        order_id=uuid4(),
        customer_id=uuid4(),
        status=OrderStatus.COMPENSATION_PENDING,
    )
    queue = QueueFake((payment_pending, compensation_pending))
    checkout = CheckoutFake(pending_id=payment_pending.order_id)

    result = await CheckoutReconciler(
        queue=queue,
        checkout=checkout,
    ).reconcile_batch(limit=BATCH_SIZE)

    assert result.selected == SELECTED_COUNT
    assert result.recovered == 1
    assert result.still_pending == 1
    assert queue.limit == BATCH_SIZE
    assert [command.order_id for command in checkout.commands] == [
        payment_pending.order_id,
        compensation_pending.order_id,
    ]
    assert all(
        command.payment_token == RECOVERY_PAYMENT_PLACEHOLDER
        for command in checkout.commands
    )
