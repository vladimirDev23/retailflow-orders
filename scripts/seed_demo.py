import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from retailflow_orders.config import get_settings
from retailflow_orders.domain.identity import UserRole
from retailflow_orders.infrastructure.database.models import (
    ProductSnapshotModel,
    UserModel,
)
from retailflow_orders.infrastructure.database.session import Database
from retailflow_orders.infrastructure.security import PasswordService

DEMO_USER_ID = UUID("11111111-1111-4111-8111-111111111111")
DEMO_PRODUCT_ID = UUID("33333333-3333-4333-8333-333333333333")


async def seed() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session, session.begin():
            user = await session.scalar(
                select(UserModel).where(UserModel.email == settings.admin_email.lower())
            )
            if user is None:
                session.add(
                    UserModel(
                        id=DEMO_USER_ID,
                        email=settings.admin_email.lower(),
                        password_hash=PasswordService().hash(
                            settings.admin_password.get_secret_value()
                        ),
                        role=UserRole.ADMIN.value,
                        active=True,
                    )
                )
            product = await session.scalar(
                select(ProductSnapshotModel).where(
                    ProductSnapshotModel.product_id == DEMO_PRODUCT_ID
                )
            )
            if product is None:
                session.add(
                    ProductSnapshotModel(
                        product_id=DEMO_PRODUCT_ID,
                        sku="RF-SCANNER-100",
                        product_name="Industrial barcode scanner",
                        unit_price=Decimal("24990.00"),
                        currency="RUB",
                        available=True,
                        source_version=1,
                        updated_at=datetime.now(tz=UTC),
                    )
                )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(seed())
