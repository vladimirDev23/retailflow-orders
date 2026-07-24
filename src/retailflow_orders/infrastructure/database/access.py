import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.application.ports import ProductSnapshot
from retailflow_orders.domain.identity import UserAccount, UserRole
from retailflow_orders.infrastructure.database.models import (
    ProductSnapshotModel,
    UserModel,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> UserModel | None:
        statement = select(UserModel).where(UserModel.email == email.strip().lower())
        model: UserModel | None = await self._session.scalar(statement)
        return model

    async def get(self, user_id: UUID) -> UserModel | None:
        return await self._session.get(UserModel, user_id)

    async def add(self, user: UserModel) -> None:
        self._session.add(user)
        await self._session.flush()


class SqlAlchemyUserDirectory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_email(self, email: str) -> UserAccount | None:
        async with self._session_factory() as session:
            model = await SqlAlchemyUserRepository(session).get_by_email(email)
        if model is None:
            return None
        return UserAccount(
            id=model.id,
            email=model.email,
            password_hash=model.password_hash,
            role=UserRole(model.role),
            active=model.active,
        )


class SqlAlchemyProductCatalog:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        cache_ttl_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds

    async def get_many(
        self,
        product_ids: Sequence[UUID],
    ) -> dict[UUID, ProductSnapshot]:
        unique_ids = tuple(dict.fromkeys(product_ids))
        cached, missing = await self._read_cache(unique_ids)
        if not missing:
            return cached

        async with self._session_factory() as session:
            statement = select(ProductSnapshotModel).where(
                ProductSnapshotModel.product_id.in_(missing)
            )
            models = (await session.scalars(statement)).all()
        loaded = {
            model.product_id: ProductSnapshot(
                product_id=model.product_id,
                sku=model.sku,
                product_name=model.product_name,
                unit_price=model.unit_price,
                currency=model.currency,
                available=model.available,
            )
            for model in models
        }
        await self._write_cache(loaded)
        return cached | loaded

    async def _read_cache(
        self,
        product_ids: tuple[UUID, ...],
    ) -> tuple[dict[UUID, ProductSnapshot], tuple[UUID, ...]]:
        if not product_ids:
            return {}, ()
        try:
            documents = await self._redis.mget(
                [self._key(product_id) for product_id in product_ids]
            )
        except RedisError:
            return {}, product_ids

        cached: dict[UUID, ProductSnapshot] = {}
        missing: list[UUID] = []
        for product_id, document in zip(product_ids, documents, strict=True):
            if document is None:
                missing.append(product_id)
                continue
            try:
                cached[product_id] = self._decode(document)
            except (ValueError, TypeError):
                missing.append(product_id)
        return cached, tuple(missing)

    async def _write_cache(self, snapshots: dict[UUID, ProductSnapshot]) -> None:
        if not snapshots:
            return
        try:
            async with self._redis.pipeline(transaction=False) as pipeline:
                for snapshot in snapshots.values():
                    pipeline.set(
                        self._key(snapshot.product_id),
                        self._encode(snapshot),
                        ex=self._cache_ttl,
                    )
                await pipeline.execute()
        except RedisError:
            return

    @staticmethod
    def _key(product_id: UUID) -> str:
        return f"product-snapshot:{product_id}"

    @staticmethod
    def _encode(snapshot: ProductSnapshot) -> str:
        return json.dumps(
            {
                "productId": str(snapshot.product_id),
                "sku": snapshot.sku,
                "productName": snapshot.product_name,
                "unitPrice": str(snapshot.unit_price),
                "currency": snapshot.currency,
                "available": snapshot.available,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _decode(document: bytes | str) -> ProductSnapshot:
        raw = document.decode() if isinstance(document, bytes) else document
        payload = json.loads(raw)
        return ProductSnapshot(
            product_id=UUID(str(payload["productId"])),
            sku=str(payload["sku"]),
            product_name=str(payload["productName"]),
            unit_price=Decimal(str(payload["unitPrice"])),
            currency=str(payload["currency"]),
            available=bool(payload["available"]),
        )


async def upsert_product_snapshot(
    session: AsyncSession,
    *,
    product_id: UUID,
    sku: str,
    product_name: str,
    unit_price: Decimal,
    currency: str,
    source_version: int,
    updated_at: datetime,
) -> None:
    model = await session.scalar(
        select(ProductSnapshotModel).where(ProductSnapshotModel.product_id == product_id)
    )
    if model is None:
        model = ProductSnapshotModel(
            product_id=product_id,
            sku=sku,
            product_name=product_name,
            unit_price=unit_price,
            currency=currency,
            available=True,
            source_version=source_version,
            updated_at=updated_at,
        )
        session.add(model)
        return
    if source_version <= model.source_version:
        return
    model.sku = sku
    model.product_name = product_name
    model.unit_price = unit_price
    model.currency = currency
    model.available = True
    model.source_version = source_version
    model.updated_at = updated_at
