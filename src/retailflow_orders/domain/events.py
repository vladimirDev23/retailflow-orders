from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DomainEvent:
    name: str
    aggregate_id: UUID
    occurred_at: datetime
    payload: dict[str, JsonValue]
    event_id: UUID

    @classmethod
    def create(
        cls,
        *,
        name: str,
        aggregate_id: UUID,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue],
    ) -> "DomainEvent":
        return cls(
            event_id=uuid4(),
            name=name,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at,
            payload=dict(payload),
        )
