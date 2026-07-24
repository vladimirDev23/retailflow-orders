from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from retailflow_orders.application.exceptions import CheckoutPendingError
from retailflow_orders.application.services import CheckoutOrderCommand
from retailflow_orders.domain.order import Order, OrderStatus

RECOVERY_PAYMENT_PLACEHOLDER = "not-used"


@dataclass(frozen=True, slots=True)
class RecoverableOrder:
    order_id: UUID
    customer_id: UUID
    status: OrderStatus


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    selected: int
    recovered: int
    still_pending: int


class RecoveryQueue(Protocol):
    async def find_batch(self, *, limit: int) -> tuple[RecoverableOrder, ...]: ...


class CheckoutProcessor(Protocol):
    async def execute(self, command: CheckoutOrderCommand) -> Order: ...


class CheckoutReconciler:
    def __init__(self, *, queue: RecoveryQueue, checkout: CheckoutProcessor) -> None:
        self._queue = queue
        self._checkout = checkout

    async def reconcile_batch(self, *, limit: int) -> ReconciliationResult:
        selected = await self._queue.find_batch(limit=limit)
        recovered = 0
        still_pending = 0
        for candidate in selected:
            try:
                await self._checkout.execute(
                    CheckoutOrderCommand(
                        order_id=candidate.order_id,
                        customer_id=candidate.customer_id,
                        payment_token=RECOVERY_PAYMENT_PLACEHOLDER,
                        correlation_id=f"reconcile-{candidate.order_id}",
                    )
                )
            except CheckoutPendingError:
                still_pending += 1
                continue
            recovered += 1
        return ReconciliationResult(
            selected=len(selected),
            recovered=recovered,
            still_pending=still_pending,
        )
