from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.infrastructure.database.uow import (
    SqlAlchemyUnitOfWork,
    SqlAlchemyUnitOfWorkFactory,
)


def session_factory_mock() -> tuple[
    async_sessionmaker[AsyncSession],
    MagicMock,
]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    factory = MagicMock(return_value=session)
    return cast(async_sessionmaker[AsyncSession], factory), session


async def test_commits_and_closes_entered_unit_of_work() -> None:
    factory, session = session_factory_mock()
    uow = SqlAlchemyUnitOfWork(factory)

    async with uow:
        await uow.commit()

    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


async def test_rolls_back_exception_before_closing() -> None:
    factory, session = session_factory_mock()

    with pytest.raises(RuntimeError, match="simulated"):
        async with SqlAlchemyUnitOfWork(factory):
            message = "simulated failure"
            raise RuntimeError(message)

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


async def test_rejects_commit_before_context_entry() -> None:
    factory, _ = session_factory_mock()

    with pytest.raises(RuntimeError, match="has not been entered"):
        await SqlAlchemyUnitOfWork(factory).commit()


def test_factory_creates_independent_unit_of_work() -> None:
    session_factory, _ = session_factory_mock()
    factory = SqlAlchemyUnitOfWorkFactory(session_factory)

    assert isinstance(factory(), SqlAlchemyUnitOfWork)
    assert factory() is not factory()
