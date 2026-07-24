from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.application.ports import ProductSnapshot
from retailflow_orders.infrastructure.database.access import (
    SqlAlchemyProductCatalog,
    upsert_product_snapshot,
)
from retailflow_orders.infrastructure.database.models import ProductSnapshotModel

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
NEW_SOURCE_VERSION = 3


def test_product_cache_round_trip_preserves_delimiters_and_money() -> None:
    snapshot = ProductSnapshot(
        product_id=uuid4(),
        sku="SKU-100",
        product_name="Scanner | industrial",
        unit_price=Decimal("1250.50"),
        currency="RUB",
        available=True,
    )

    document = SqlAlchemyProductCatalog._encode(snapshot)
    restored = SqlAlchemyProductCatalog._decode(document.encode())

    assert restored == snapshot


def catalog_with_redis(redis: MagicMock) -> SqlAlchemyProductCatalog:
    return SqlAlchemyProductCatalog(
        session_factory=cast(async_sessionmaker[AsyncSession], MagicMock()),
        redis=cast(Redis, redis),
        cache_ttl_seconds=300,
    )


async def test_reads_complete_product_set_from_cache() -> None:
    product = ProductSnapshot(
        product_id=uuid4(),
        sku="SKU-100",
        product_name="Scanner",
        unit_price=Decimal("100.00"),
        currency="RUB",
        available=True,
    )
    redis = MagicMock(spec=Redis)
    redis.mget = AsyncMock(return_value=[SqlAlchemyProductCatalog._encode(product).encode()])

    result = await catalog_with_redis(redis).get_many([product.product_id])

    assert result == {product.product_id: product}


async def test_redis_failure_falls_back_to_database_miss_list() -> None:
    product_id = uuid4()
    redis = MagicMock(spec=Redis)
    redis.mget = AsyncMock(side_effect=RedisError("unavailable"))

    cached, missing = await catalog_with_redis(redis)._read_cache((product_id,))

    assert cached == {}
    assert missing == (product_id,)


async def test_upsert_inserts_new_snapshot() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    product_id = uuid4()

    await upsert_product_snapshot(
        cast(AsyncSession, session),
        product_id=product_id,
        sku="SKU-100",
        product_name="Scanner",
        unit_price=Decimal("100.00"),
        currency="RUB",
        source_version=1,
        updated_at=NOW,
    )

    added = session.add.call_args.args[0]
    assert isinstance(added, ProductSnapshotModel)
    assert added.product_id == product_id


async def test_upsert_ignores_stale_event_and_applies_newer_event() -> None:
    model = ProductSnapshotModel(
        product_id=uuid4(),
        sku="SKU-OLD",
        product_name="Old name",
        unit_price=Decimal("50.00"),
        currency="RUB",
        available=True,
        source_version=2,
        updated_at=NOW,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=model)

    await upsert_product_snapshot(
        cast(AsyncSession, session),
        product_id=model.product_id,
        sku="SKU-STALE",
        product_name="Stale",
        unit_price=Decimal("60.00"),
        currency="RUB",
        source_version=1,
        updated_at=NOW,
    )
    assert model.sku == "SKU-OLD"

    await upsert_product_snapshot(
        cast(AsyncSession, session),
        product_id=model.product_id,
        sku="SKU-NEW",
        product_name="New name",
        unit_price=Decimal("75.00"),
        currency="RUB",
        source_version=NEW_SOURCE_VERSION,
        updated_at=NOW,
    )
    assert model.sku == "SKU-NEW"
    assert model.source_version == NEW_SOURCE_VERSION
