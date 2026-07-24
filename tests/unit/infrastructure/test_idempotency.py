from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from retailflow_orders.application.exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from retailflow_orders.infrastructure.database.models import IdempotencyRecordModel
from retailflow_orders.infrastructure.idempotency import (
    IdempotencyState,
    PersistentIdempotencyCoordinator,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def record(*, state: IdempotencyState, locked_until: datetime) -> IdempotencyRecordModel:
    return IdempotencyRecordModel(
        id=uuid4(),
        scope="orders:create",
        key_hash="key-hash",
        request_hash=PersistentIdempotencyCoordinator._request_digest({"quantity": 2}),
        state=state.value,
        resource_id=uuid4(),
        response_status=None,
        response_body=None,
        created_at=NOW,
        locked_until=locked_until,
        expires_at=NOW + timedelta(days=1),
    )


def test_request_fingerprint_is_canonical() -> None:
    first = PersistentIdempotencyCoordinator._request_digest({"sku": "A", "quantity": 2})
    second = PersistentIdempotencyCoordinator._request_digest({"quantity": 2, "sku": "A"})

    assert first == second


def test_completed_claim_replays_resource() -> None:
    model = record(state=IdempotencyState.COMPLETED, locked_until=NOW)
    coordinator = object.__new__(PersistentIdempotencyCoordinator)

    claim = coordinator._reclaim(
        model,
        request_hash=model.request_hash,
        requested_resource_id=None,
        now=NOW,
    )

    assert claim.completed
    assert claim.resource_id == model.resource_id


def test_rejects_same_key_with_different_payload() -> None:
    model = record(state=IdempotencyState.COMPLETED, locked_until=NOW)
    coordinator = object.__new__(PersistentIdempotencyCoordinator)

    with pytest.raises(IdempotencyConflictError, match="different request"):
        coordinator._reclaim(
            model,
            request_hash="different-request-hash",
            requested_resource_id=None,
            now=NOW,
        )


def test_active_lease_rejects_concurrent_equivalent_request() -> None:
    model = record(
        state=IdempotencyState.IN_PROGRESS,
        locked_until=NOW + timedelta(seconds=30),
    )
    coordinator = object.__new__(PersistentIdempotencyCoordinator)

    with pytest.raises(IdempotencyInProgressError, match="already in progress"):
        coordinator._reclaim(
            model,
            request_hash=model.request_hash,
            requested_resource_id=None,
            now=NOW,
        )


def test_expired_record_is_reinitialized_without_reusing_response() -> None:
    model = record(state=IdempotencyState.COMPLETED, locked_until=NOW)
    model.expires_at = NOW - timedelta(seconds=1)
    model.response_status = 201
    model.response_body = {"old": True}
    coordinator = object.__new__(PersistentIdempotencyCoordinator)
    coordinator._lock = timedelta(seconds=30)
    coordinator._ttl = timedelta(days=1)

    claim = coordinator._reclaim(
        model,
        request_hash="new-request-hash",
        requested_resource_id=None,
        now=NOW,
    )

    assert not claim.completed
    assert model.state == IdempotencyState.IN_PROGRESS.value
    assert model.response_status is None
    assert model.response_body is None
