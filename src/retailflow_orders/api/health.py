from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["UP"]


@router.get("/health/live", operation_id="getLiveness")
async def liveness() -> HealthResponse:
    return HealthResponse(status="UP")
