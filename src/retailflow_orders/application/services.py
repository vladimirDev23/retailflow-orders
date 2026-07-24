from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from retailflow_orders.application.exceptions import (
    CheckoutPendingError,
    InventoryRejectedError,
    InventoryUnavailableError,
    OrderNotFoundError,
    ProductUnavailableError,
)
from retailflow_orders.application.ports import (
    Clock,
    InventoryGateway,
    PaymentDecision,
    PaymentGateway,
    ProductCatalog,
    UnitOfWorkFactory,
)
from retailflow_orders.domain.order import Order, OrderLine, OrderStatus

RESERVATION_KEY_SUFFIX = "reserve"
COMMIT_KEY_SUFFIX = "commit"
RELEASE_KEY_SUFFIX = "release"
PAYMENT_KEY_SUFFIX = "charge"


@dataclass(frozen=True, slots=True)
class CreateOrderLineCommand:
    product_id: UUID
    quantity: int


@dataclass(frozen=True, slots=True)
class CreateOrderCommand:
    customer_id: UUID
    warehouse_id: UUID
    lines: tuple[CreateOrderLineCommand, ...]
    correlation_id: str
    order_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CheckoutOrderCommand:
    order_id: UUID
    customer_id: UUID
    payment_token: str
    correlation_id: str


class CreateOrderService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        catalog: ProductCatalog,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._clock = clock

    async def execute(self, command: CreateOrderCommand) -> Order:
        requested_ids = [line.product_id for line in command.lines]
        snapshots = await self._catalog.get_many(requested_ids)
        missing = set(requested_ids).difference(snapshots)
        unavailable = [
            snapshot.product_id for snapshot in snapshots.values() if not snapshot.available
        ]
        if missing or unavailable:
            unavailable_ids = sorted(str(product_id) for product_id in missing.union(unavailable))
            message = f"Products are unavailable: {', '.join(unavailable_ids)}"
            raise ProductUnavailableError(message)

        currencies = {snapshot.currency for snapshot in snapshots.values()}
        if len(currencies) != 1:
            message = "All order lines must use the same currency"
            raise ProductUnavailableError(message)
        currency = currencies.pop()
        quantities = {line.product_id: line.quantity for line in command.lines}
        domain_lines = tuple(
            OrderLine(
                product_id=product_id,
                sku=snapshots[product_id].sku,
                product_name=snapshots[product_id].product_name,
                quantity=quantities[product_id],
                unit_price=snapshots[product_id].unit_price,
            )
            for product_id in requested_ids
        )
        order = Order.create(
            customer_id=command.customer_id,
            warehouse_id=command.warehouse_id,
            currency=currency,
            lines=domain_lines,
            now=self._clock.now(),
            order_id=command.order_id,
        )
        async with self._uow_factory() as uow:
            await uow.orders.add(
                order,
                actor_id=command.customer_id,
                correlation_id=command.correlation_id,
            )
            await uow.commit()
        return order


class CheckoutOrderService:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        inventory: InventoryGateway,
        payment: PaymentGateway,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._inventory = inventory
        self._payment = payment
        self._clock = clock

    async def execute(self, command: CheckoutOrderCommand) -> Order:
        order = await self._load_visible(command.order_id, command.customer_id)
        if order.is_terminal:
            return order

        if order.status is OrderStatus.DRAFT:
            order = await self._change(
                command,
                lambda current: current.request_reservation(now=self._clock.now()),
            )

        if order.status is OrderStatus.PENDING_RESERVATION:
            order = await self._reserve(order, command)

        if order.status is OrderStatus.RESERVED:
            order = await self._change(
                command,
                lambda current: current.request_payment(now=self._clock.now()),
            )

        if order.status is OrderStatus.PAYMENT_PENDING:
            order = await self._pay(order, command)

        if order.status is OrderStatus.COMPENSATION_PENDING:
            order = await self._release(order, command)

        return order

    async def _reserve(
        self,
        order: Order,
        command: CheckoutOrderCommand,
    ) -> Order:
        try:
            reservation = await self._inventory.reserve(
                order,
                idempotency_key=self._key(order.id, RESERVATION_KEY_SUFFIX),
                correlation_id=command.correlation_id,
            )
        except InventoryRejectedError as exception:
            rejection_reason = str(exception)
            return await self._change(
                command,
                lambda current: current.mark_reservation_failed(
                    reason=rejection_reason,
                    now=self._clock.now(),
                ),
            )
        except InventoryUnavailableError as exception:
            message = "Inventory reservation outcome is pending reconciliation"
            raise CheckoutPendingError(message) from exception

        return await self._change(
            command,
            lambda current: current.mark_reserved(
                reservation_id=reservation.reservation_id,
                now=self._clock.now(),
            ),
        )

    async def _pay(
        self,
        order: Order,
        command: CheckoutOrderCommand,
    ) -> Order:
        decision = await self._payment.charge(
            order_id=order.id,
            amount=order.total,
            currency=order.currency,
            payment_token=command.payment_token,
            idempotency_key=self._key(order.id, PAYMENT_KEY_SUFFIX),
        )
        if not decision.approved:
            reason = decision.reason or "Payment provider declined the charge"
            return await self._change(
                command,
                lambda current: current.request_compensation(
                    reason=reason,
                    now=self._clock.now(),
                ),
            )

        return await self._commit_reservation(order, command, decision)

    async def _commit_reservation(
        self,
        order: Order,
        command: CheckoutOrderCommand,
        decision: PaymentDecision,
    ) -> Order:
        reservation_id = self._reservation_id(order)
        try:
            await self._inventory.commit(
                reservation_id,
                idempotency_key=self._key(order.id, COMMIT_KEY_SUFFIX),
                correlation_id=command.correlation_id,
            )
        except InventoryUnavailableError as exception:
            message = "Inventory commit outcome is pending reconciliation"
            raise CheckoutPendingError(message) from exception

        reference = decision.reference
        if reference is None:
            message = "Approved payment response did not contain a reference"
            raise CheckoutPendingError(message)
        return await self._change(
            command,
            lambda current: current.confirm_payment(
                payment_reference=reference,
                now=self._clock.now(),
            ),
        )

    async def _release(
        self,
        order: Order,
        command: CheckoutOrderCommand,
    ) -> Order:
        try:
            await self._inventory.release(
                self._reservation_id(order),
                idempotency_key=self._key(order.id, RELEASE_KEY_SUFFIX),
                correlation_id=command.correlation_id,
            )
        except InventoryUnavailableError as exception:
            message = "Inventory release outcome is pending reconciliation"
            raise CheckoutPendingError(message) from exception
        return await self._change(
            command,
            lambda current: current.mark_cancelled(now=self._clock.now()),
        )

    async def _load_visible(self, order_id: UUID, customer_id: UUID) -> Order:
        async with self._uow_factory() as uow:
            order = await uow.orders.get(order_id)
        if order is None or order.customer_id != customer_id:
            message = f"Order {order_id} was not found"
            raise OrderNotFoundError(message)
        return order

    async def _change(
        self,
        command: CheckoutOrderCommand,
        mutate: Callable[[Order], None],
    ) -> Order:
        async with self._uow_factory() as uow:
            current = await uow.orders.get(command.order_id)
            if current is None or current.customer_id != command.customer_id:
                message = f"Order {command.order_id} was not found"
                raise OrderNotFoundError(message)
            mutate(current)
            await uow.orders.save(
                current,
                actor_id=command.customer_id,
                correlation_id=command.correlation_id,
            )
            await uow.commit()
            return current

    @staticmethod
    def _key(order_id: UUID, suffix: str) -> str:
        return f"order:{order_id}:{suffix}"

    @staticmethod
    def _reservation_id(order: Order) -> UUID:
        if order.reservation_id is None:
            message = f"Order {order.id} does not reference an inventory reservation"
            raise CheckoutPendingError(message)
        return order.reservation_id
