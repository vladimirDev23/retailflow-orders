from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Self
from uuid import UUID

from retailflow_orders.domain.order import Order


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    product_id: UUID
    sku: str
    product_name: str
    unit_price: Decimal
    currency: str
    available: bool


@dataclass(frozen=True, slots=True)
class ReservationResult:
    reservation_id: UUID


@dataclass(frozen=True, slots=True)
class PaymentDecision:
    approved: bool
    reference: str | None
    reason: str | None


class Clock(Protocol):
    def now(self) -> datetime: ...


class ProductCatalog(Protocol):
    async def get_many(self, product_ids: Sequence[UUID]) -> dict[UUID, ProductSnapshot]: ...


class InventoryGateway(Protocol):
    async def reserve(
        self,
        order: Order,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ReservationResult: ...

    async def commit(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None: ...

    async def release(
        self,
        reservation_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> None: ...


class PaymentGateway(Protocol):
    async def charge(
        self,
        *,
        order_id: UUID,
        amount: Decimal,
        currency: str,
        payment_token: str,
        idempotency_key: str,
    ) -> PaymentDecision: ...


class OrderRepository(Protocol):
    async def add(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None: ...

    async def get(self, order_id: UUID) -> Order | None: ...

    async def save(
        self,
        order: Order,
        *,
        actor_id: UUID | None,
        correlation_id: str,
    ) -> None: ...


class UnitOfWork(Protocol):
    @property
    def orders(self) -> OrderRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
