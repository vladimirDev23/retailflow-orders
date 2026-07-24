from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

import pytest

from retailflow_orders.application.exceptions import (
    CheckoutPendingError,
    InventoryRejectedError,
    InventoryUnavailableError,
    OrderNotFoundError,
    ProductUnavailableError,
)
from retailflow_orders.application.facade import IdempotentOrderFacade
from retailflow_orders.application.ports import (
    IdempotencyClaim,
    OrderPage,
    PaymentDecision,
    ProductSnapshot,
    ReservationResult,
)
from retailflow_orders.application.queries import OrderQueryService
from retailflow_orders.application.services import (
    CheckoutOrderCommand,
    CheckoutOrderService,
    CreateOrderCommand,
    CreateOrderLineCommand,
    CreateOrderService,
)
from retailflow_orders.domain.order import Order, OrderStatus

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
CUSTOMER_ID = uuid4()
OTHER_CUSTOMER_ID = uuid4()
WAREHOUSE_ID = uuid4()
PRODUCT_ID = uuid4()
RESERVATION_ID = uuid4()


class FixedClock:
    def now(self) -> datetime:
        return NOW


class MemoryOrderRepository:
    def __init__(self, orders: dict[UUID, Order]) -> None:
        self._orders = orders

    async def add(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None:
        self._orders[order.id] = order

    async def get(self, order_id: UUID) -> Order | None:
        return self._orders.get(order_id)

    async def save(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None:
        order.version += 1
        order.pull_events()
        self._orders[order.id] = order

    async def list_for_customer(
        self,
        customer_id: UUID,
        *,
        status: OrderStatus | None,
        limit: int,
        offset: int,
    ) -> OrderPage:
        orders = tuple(
            order
            for order in self._orders.values()
            if order.customer_id == customer_id and (status is None or order.status is status)
        )
        return OrderPage(items=orders, total=len(orders), limit=limit, offset=offset)


class MemoryUnitOfWork:
    def __init__(self, orders: dict[UUID, Order]) -> None:
        self.orders = MemoryOrderRepository(orders)
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class MemoryUnitOfWorkFactory:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}

    def __call__(self) -> MemoryUnitOfWork:
        return MemoryUnitOfWork(self.orders)


class MemoryIdempotencyCoordinator:
    def __init__(self) -> None:
        self.claims: dict[tuple[str, str], tuple[UUID, bool]] = {}

    async def claim(
        self,
        *,
        scope: str,
        key: str,
        request_payload: dict[str, object],
        resource_id: UUID | None = None,
    ) -> IdempotencyClaim:
        stored = self.claims.get((scope, key))
        if stored is not None:
            return IdempotencyClaim(resource_id=stored[0], completed=stored[1])
        claimed_id = resource_id or uuid4()
        self.claims[(scope, key)] = (claimed_id, False)
        return IdempotencyClaim(resource_id=claimed_id, completed=False)

    async def complete(
        self,
        *,
        scope: str,
        key: str,
        response_status: int,
        response_body: dict[str, object],
    ) -> None:
        resource_id, _ = self.claims[(scope, key)]
        self.claims[(scope, key)] = (resource_id, True)

    async def abandon(self, *, scope: str, key: str) -> None:
        resource_id, _ = self.claims[(scope, key)]
        self.claims[(scope, key)] = (resource_id, False)


class MemoryCatalog:
    def __init__(self, snapshots: dict[UUID, ProductSnapshot]) -> None:
        self._snapshots = snapshots

    async def get_many(
        self,
        product_ids: Sequence[UUID],
    ) -> dict[UUID, ProductSnapshot]:
        return {
            product_id: self._snapshots[product_id]
            for product_id in product_ids
            if product_id in self._snapshots
        }


class InventoryFake:
    def __init__(
        self,
        *,
        reserve_error: Exception | None = None,
        commit_error: Exception | None = None,
        release_error: Exception | None = None,
    ) -> None:
        self.reserve_error = reserve_error
        self.commit_error = commit_error
        self.release_error = release_error
        self.calls: list[str] = []

    async def reserve(
        self,
        order: Order,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ReservationResult:
        self.calls.append("reserve")
        if self.reserve_error is not None:
            raise self.reserve_error
        return ReservationResult(reservation_id=RESERVATION_ID)

    async def commit(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        self.calls.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    async def release(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        self.calls.append("release")
        if self.release_error is not None:
            raise self.release_error


class PaymentFake:
    def __init__(self, decision: PaymentDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def charge(
        self,
        *,
        order_id: UUID,
        amount: Decimal,
        currency: str,
        payment_token: str,
        idempotency_key: str,
    ) -> PaymentDecision:
        self.calls += 1
        return self.decision


def snapshot(*, available: bool = True, currency: str = "RUB") -> ProductSnapshot:
    return ProductSnapshot(
        product_id=PRODUCT_ID,
        sku="SKU-100",
        product_name="Barcode scanner",
        unit_price=Decimal("2500.00"),
        currency=currency,
        available=available,
    )


def create_command(
    *,
    customer_id: UUID = CUSTOMER_ID,
) -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=customer_id,
        warehouse_id=WAREHOUSE_ID,
        lines=(CreateOrderLineCommand(product_id=PRODUCT_ID, quantity=2),),
        correlation_id="corr-create-100",
    )


async def create_order(uow_factory: MemoryUnitOfWorkFactory) -> Order:
    service = CreateOrderService(
        uow_factory=uow_factory,
        catalog=MemoryCatalog({PRODUCT_ID: snapshot()}),
        clock=FixedClock(),
    )
    return await service.execute(create_command())


def checkout_service(
    *,
    uow_factory: MemoryUnitOfWorkFactory,
    inventory: InventoryFake,
    payment: PaymentFake,
) -> CheckoutOrderService:
    return CheckoutOrderService(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=payment,
        clock=FixedClock(),
    )


def checkout_command(
    order: Order,
    *,
    customer_id: UUID = CUSTOMER_ID,
) -> CheckoutOrderCommand:
    return CheckoutOrderCommand(
        order_id=order.id,
        customer_id=customer_id,
        payment_token="pm_demo_approved",
        correlation_id="corr-checkout-100",
    )


async def test_create_uses_server_side_product_snapshot() -> None:
    uow_factory = MemoryUnitOfWorkFactory()

    created = await create_order(uow_factory)

    assert created.customer_id == CUSTOMER_ID
    assert created.warehouse_id == WAREHOUSE_ID
    assert created.total == Decimal("5000.00")
    assert created.lines[0].product_id == PRODUCT_ID
    assert uow_factory.orders[created.id] is created


@pytest.mark.parametrize(
    "catalog_factory",
    [
        lambda: MemoryCatalog({}),
        lambda: MemoryCatalog({PRODUCT_ID: snapshot(available=False)}),
    ],
)
async def test_create_rejects_unavailable_products(
    catalog_factory: Callable[[], MemoryCatalog],
) -> None:
    service = CreateOrderService(
        uow_factory=MemoryUnitOfWorkFactory(),
        catalog=catalog_factory(),
        clock=FixedClock(),
    )

    with pytest.raises(ProductUnavailableError, match="unavailable"):
        await service.execute(create_command())


async def test_checkout_completes_reservation_payment_and_inventory_commit() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    inventory = InventoryFake()
    payment = PaymentFake(PaymentDecision(approved=True, reference="pay-100", reason=None))
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=payment,
    )

    checked_out = await service.execute(checkout_command(created))

    assert checked_out.status is OrderStatus.CONFIRMED
    assert checked_out.payment_reference == "pay-100"
    assert inventory.calls == ["reserve", "commit"]
    assert payment.calls == 1


async def test_explicit_inventory_rejection_finishes_order() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    inventory = InventoryFake(
        reserve_error=InventoryRejectedError("insufficient stock"),
    )
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=PaymentFake(PaymentDecision(approved=True, reference="unused", reason=None)),
    )

    result = await service.execute(checkout_command(created))

    assert result.status is OrderStatus.RESERVATION_FAILED
    assert result.failure_reason == "insufficient stock"


async def test_declined_payment_releases_reservation_and_cancels_order() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    inventory = InventoryFake()
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=PaymentFake(
            PaymentDecision(
                approved=False,
                reference=None,
                reason="card declined",
            )
        ),
    )

    result = await service.execute(checkout_command(created))

    assert result.status is OrderStatus.CANCELLED
    assert result.failure_reason == "card declined"
    assert inventory.calls == ["reserve", "release"]


async def test_approved_payment_without_reference_stays_pending() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=InventoryFake(),
        payment=PaymentFake(PaymentDecision(approved=True, reference=None, reason=None)),
    )

    with pytest.raises(CheckoutPendingError, match="did not contain a reference"):
        await service.execute(checkout_command(created))

    assert created.status is OrderStatus.PAYMENT_PENDING
    assert created.payment_reference is None


async def test_inventory_timeout_leaves_reconcilable_reservation_state() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=InventoryFake(
            reserve_error=InventoryUnavailableError("timeout"),
        ),
        payment=PaymentFake(PaymentDecision(approved=True, reference="unused", reason=None)),
    )

    with pytest.raises(CheckoutPendingError, match="pending reconciliation"):
        await service.execute(checkout_command(created))

    assert created.status is OrderStatus.PENDING_RESERVATION


async def test_commit_timeout_leaves_payment_pending_for_safe_retry() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    inventory = InventoryFake(
        commit_error=InventoryUnavailableError("timeout"),
    )
    payment = PaymentFake(PaymentDecision(approved=True, reference="pay-100", reason=None))
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=payment,
    )

    with pytest.raises(CheckoutPendingError, match="commit outcome"):
        await service.execute(checkout_command(created))

    assert created.status is OrderStatus.PAYMENT_PENDING
    assert created.payment_reference == "pay-100"

    inventory.commit_error = None
    result = await service.execute(checkout_command(created))

    assert result.status is OrderStatus.CONFIRMED
    assert result.payment_reference == "pay-100"
    assert payment.calls == 1


async def test_customer_cannot_observe_another_customers_order() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    service = checkout_service(
        uow_factory=uow_factory,
        inventory=InventoryFake(),
        payment=PaymentFake(PaymentDecision(approved=True, reference="pay-100", reason=None)),
    )

    with pytest.raises(OrderNotFoundError, match="not found"):
        await service.execute(checkout_command(created, customer_id=OTHER_CUSTOMER_ID))


async def test_idempotent_facade_replays_created_order() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    coordinator = MemoryIdempotencyCoordinator()
    create_service = CreateOrderService(
        uow_factory=uow_factory,
        catalog=MemoryCatalog({PRODUCT_ID: snapshot()}),
        clock=FixedClock(),
    )
    query_service = OrderQueryService(uow_factory)
    facade = IdempotentOrderFacade(
        coordinator=coordinator,
        create_service=create_service,
        checkout_service=checkout_service(
            uow_factory=uow_factory,
            inventory=InventoryFake(),
            payment=PaymentFake(PaymentDecision(approved=True, reference="pay-100", reason=None)),
        ),
        query_service=query_service,
    )

    first = await facade.create(
        create_command(),
        idempotency_key="create-key-100",
        request_payload={"warehouseId": str(WAREHOUSE_ID)},
    )
    replay = await facade.create(
        create_command(),
        idempotency_key="create-key-100",
        request_payload={"warehouseId": str(WAREHOUSE_ID)},
    )

    assert replay.id == first.id
    assert len(uow_factory.orders) == 1


async def test_idempotent_facade_completes_checkout_and_query_page() -> None:
    uow_factory = MemoryUnitOfWorkFactory()
    created = await create_order(uow_factory)
    coordinator = MemoryIdempotencyCoordinator()
    query_service = OrderQueryService(uow_factory)
    facade = IdempotentOrderFacade(
        coordinator=coordinator,
        create_service=CreateOrderService(
            uow_factory=uow_factory,
            catalog=MemoryCatalog({PRODUCT_ID: snapshot()}),
            clock=FixedClock(),
        ),
        checkout_service=checkout_service(
            uow_factory=uow_factory,
            inventory=InventoryFake(),
            payment=PaymentFake(PaymentDecision(approved=True, reference="pay-100", reason=None)),
        ),
        query_service=query_service,
    )

    checked_out = await facade.checkout(
        checkout_command(created),
        idempotency_key="checkout-key-100",
        request_payload={"paymentMethod": "pm_demo_approved"},
    )
    page = await query_service.list_for_customer(
        CUSTOMER_ID,
        status=OrderStatus.CONFIRMED,
        limit=20,
        offset=0,
    )

    assert checked_out.status is OrderStatus.CONFIRMED
    assert page.total == 1
    assert page.items == (checked_out,)
