import asyncio
import os
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DEMO_PRODUCT_ID = UUID("33333333-3333-4333-8333-333333333333")
RESERVATION_NAMESPACE = UUID("99999999-9999-4999-8999-999999999999")
DEFAULT_STOCK = 1_000


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ReservationLine(ApiModel):
    product_id: UUID
    quantity: int = Field(ge=1)


class ReservationRequest(ApiModel):
    order_reference: str
    warehouse_id: UUID
    expires_in_seconds: int = Field(ge=30, le=3600)
    lines: tuple[ReservationLine, ...] = Field(min_length=1)


class ReservationResponse(ApiModel):
    id: UUID
    status: Literal["ACTIVE", "COMMITTED", "RELEASED"]


@dataclass(slots=True)
class Reservation:
    id: UUID
    status: Literal["ACTIVE", "COMMITTED", "RELEASED"]


app = FastAPI(
    title="RetailFlow Inventory Contract Stub",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
reservations: dict[UUID, Reservation] = {}
lock = asyncio.Lock()


def authorize(authorization: str) -> None:
    expected = os.environ.get("INVENTORY_SERVICE_TOKEN", "local-inventory-token")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/health/live")
async def health() -> dict[str, str]:
    return {"status": "UP"}


@app.post(
    "/api/v1/reservations",
    status_code=status.HTTP_201_CREATED,
)
async def reserve(
    request: ReservationRequest,
    authorization: Annotated[str, Header(alias="Authorization")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ReservationResponse:
    authorize(authorization)
    if any(
        line.product_id != DEMO_PRODUCT_ID or line.quantity > DEFAULT_STOCK
        for line in request.lines
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "insufficient_stock",
                "detail": "The development stub cannot reserve the requested product quantity",
            },
        )
    reservation_id = uuid5(
        RESERVATION_NAMESPACE,
        f"{request.order_reference}:{idempotency_key}",
    )
    async with lock:
        reservation = reservations.setdefault(
            reservation_id,
            Reservation(id=reservation_id, status="ACTIVE"),
        )
    return ReservationResponse(id=reservation.id, status=reservation.status)


@app.post(
    "/api/v1/reservations/{reservation_id}/commit",
)
async def commit(
    reservation_id: UUID,
    authorization: Annotated[str, Header(alias="Authorization")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ReservationResponse:
    del idempotency_key
    authorize(authorization)
    return await change_status(reservation_id, "COMMITTED")


@app.post(
    "/api/v1/reservations/{reservation_id}/release",
)
async def release(
    reservation_id: UUID,
    authorization: Annotated[str, Header(alias="Authorization")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ReservationResponse:
    del idempotency_key
    authorize(authorization)
    return await change_status(reservation_id, "RELEASED")


async def change_status(
    reservation_id: UUID,
    target: Literal["COMMITTED", "RELEASED"],
) -> ReservationResponse:
    async with lock:
        reservation = reservations.get(reservation_id)
        if reservation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        if reservation.status not in {"ACTIVE", target}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reservation is already finalized",
            )
        reservation.status = target
    return ReservationResponse(id=reservation.id, status=reservation.status)
