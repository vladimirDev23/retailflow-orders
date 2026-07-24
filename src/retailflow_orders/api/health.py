from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from retailflow_orders.api.dependencies import get_container
from retailflow_orders.bootstrap import ApplicationContainer

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["UP", "DOWN"]


@router.get("/health/live", operation_id="getLiveness")
async def liveness() -> HealthResponse:
    return HealthResponse(status="UP")


@router.get("/health/ready", operation_id="getReadiness")
async def readiness(
    response: Response,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> HealthResponse:
    try:
        await container.database.ping()
        await container.redis.ping()
    except (SQLAlchemyError, RedisError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="DOWN")
    return HealthResponse(status="UP")
