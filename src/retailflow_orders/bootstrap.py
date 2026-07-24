from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2
from redis.asyncio import Redis

from retailflow_orders.application.auth import LoginService
from retailflow_orders.application.facade import IdempotentOrderFacade
from retailflow_orders.application.queries import OrderQueryService
from retailflow_orders.application.services import CheckoutOrderService, CreateOrderService
from retailflow_orders.config import Settings
from retailflow_orders.infrastructure.database.access import (
    SqlAlchemyProductCatalog,
    SqlAlchemyUserDirectory,
)
from retailflow_orders.infrastructure.database.session import Database
from retailflow_orders.infrastructure.database.uow import SqlAlchemyUnitOfWorkFactory
from retailflow_orders.infrastructure.idempotency import PersistentIdempotencyCoordinator
from retailflow_orders.infrastructure.integrations.inventory import HttpInventoryGateway
from retailflow_orders.infrastructure.integrations.payment import DeterministicPaymentGateway
from retailflow_orders.infrastructure.security import JwtService, PasswordService


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    database: Database
    redis: Redis
    http_client: httpx2.AsyncClient
    passwords: PasswordService
    tokens: JwtService
    login: LoginService
    orders: IdempotentOrderFacade
    order_queries: OrderQueryService

    async def close(self) -> None:
        await self.http_client.aclose()
        await self.redis.aclose()
        await self.database.close()


def build_container(settings: Settings) -> ApplicationContainer:
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    http_client = httpx2.AsyncClient()
    clock = SystemClock()
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    catalog = SqlAlchemyProductCatalog(
        session_factory=database.session_factory,
        redis=redis,
        cache_ttl_seconds=settings.product_cache_ttl_seconds,
    )
    inventory = HttpInventoryGateway(
        client=http_client,
        base_url=str(settings.inventory_base_url),
        service_token=settings.inventory_service_token.get_secret_value(),
    )
    payment = DeterministicPaymentGateway()
    create_service = CreateOrderService(
        uow_factory=uow_factory,
        catalog=catalog,
        clock=clock,
    )
    checkout_service = CheckoutOrderService(
        uow_factory=uow_factory,
        inventory=inventory,
        payment=payment,
        clock=clock,
    )
    query_service = OrderQueryService(uow_factory)
    coordinator = PersistentIdempotencyCoordinator(
        session_factory=database.session_factory,
        ttl_seconds=settings.idempotency_ttl_seconds,
        lock_seconds=settings.idempotency_lock_seconds,
    )
    passwords = PasswordService()
    tokens = JwtService(
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        ttl_seconds=settings.access_token_ttl_seconds,
    )
    return ApplicationContainer(
        settings=settings,
        database=database,
        redis=redis,
        http_client=http_client,
        passwords=passwords,
        tokens=tokens,
        login=LoginService(
            users=SqlAlchemyUserDirectory(database.session_factory),
            passwords=passwords,
            tokens=tokens,
        ),
        orders=IdempotentOrderFacade(
            coordinator=coordinator,
            create_service=create_service,
            checkout_service=checkout_service,
            query_service=query_service,
        ),
        order_queries=query_service,
    )
