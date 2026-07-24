import json
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from retailflow_orders.application.exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from retailflow_orders.application.ports import IdempotencyClaim
from retailflow_orders.infrastructure.database.base import utc_now
from retailflow_orders.infrastructure.database.models import IdempotencyRecordModel


class IdempotencyState(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class PersistentIdempotencyCoordinator:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ttl_seconds: int,
        lock_seconds: int,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = timedelta(seconds=lock_seconds)
        self._now = now

    async def claim(
        self,
        *,
        scope: str,
        key: str,
        request_payload: dict[str, Any],
        resource_id: UUID | None = None,
    ) -> IdempotencyClaim:
        key_hash = self._digest(key)
        request_hash = self._request_digest(request_payload)
        now = self._now()
        try:
            async with self._session_factory() as session, session.begin():
                record = await self._find_locked(session, scope, key_hash)
                if record is None:
                    claimed_resource = resource_id or uuid4()
                    session.add(
                        IdempotencyRecordModel(
                            scope=scope,
                            key_hash=key_hash,
                            request_hash=request_hash,
                            state=IdempotencyState.IN_PROGRESS.value,
                            resource_id=claimed_resource,
                            locked_until=now + self._lock,
                            expires_at=now + self._ttl,
                        )
                    )
                    await session.flush()
                    return IdempotencyClaim(
                        resource_id=claimed_resource,
                        completed=False,
                    )
                return self._reclaim(
                    record,
                    request_hash=request_hash,
                    requested_resource_id=resource_id,
                    now=now,
                )
        except IntegrityError as exception:
            message = "Another request claimed this idempotency key"
            raise IdempotencyInProgressError(message) from exception

    async def complete(
        self,
        *,
        scope: str,
        key: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            record = await self._find_locked(session, scope, self._digest(key))
            if record is None:
                message = "Idempotency claim no longer exists"
                raise IdempotencyConflictError(message)
            record.state = IdempotencyState.COMPLETED.value
            record.response_status = response_status
            record.response_body = response_body
            record.locked_until = self._now()

    async def abandon(self, *, scope: str, key: str) -> None:
        async with self._session_factory() as session, session.begin():
            record = await self._find_locked(session, scope, self._digest(key))
            if record is not None and record.state == IdempotencyState.IN_PROGRESS.value:
                record.locked_until = self._now()

    def _reclaim(
        self,
        record: IdempotencyRecordModel,
        *,
        request_hash: str,
        requested_resource_id: UUID | None,
        now: datetime,
    ) -> IdempotencyClaim:
        if record.expires_at <= now:
            record.request_hash = request_hash
            record.state = IdempotencyState.IN_PROGRESS.value
            record.resource_id = requested_resource_id or uuid4()
            record.response_status = None
            record.response_body = None
            record.created_at = now
            record.locked_until = now + self._lock
            record.expires_at = now + self._ttl
            return IdempotencyClaim(resource_id=record.resource_id, completed=False)
        if record.request_hash != request_hash:
            message = "Idempotency key was already used with a different request"
            raise IdempotencyConflictError(message)
        if requested_resource_id is not None and record.resource_id != requested_resource_id:
            message = "Idempotency key is bound to a different resource"
            raise IdempotencyConflictError(message)
        if record.resource_id is None:
            message = "Idempotency record has no resource binding"
            raise IdempotencyConflictError(message)
        if record.state == IdempotencyState.COMPLETED.value:
            return IdempotencyClaim(resource_id=record.resource_id, completed=True)
        if record.locked_until > now:
            message = "An equivalent request is already in progress"
            raise IdempotencyInProgressError(message)
        record.locked_until = now + self._lock
        return IdempotencyClaim(resource_id=record.resource_id, completed=False)

    @staticmethod
    async def _find_locked(
        session: AsyncSession,
        scope: str,
        key_hash: str,
    ) -> IdempotencyRecordModel | None:
        statement = (
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.scope == scope,
                IdempotencyRecordModel.key_hash == key_hash,
            )
            .with_for_update()
        )
        record: IdempotencyRecordModel | None = await session.scalar(statement)
        return record

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode()).hexdigest()

    @classmethod
    def _request_digest(cls, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return cls._digest(canonical)
