from fastapi import APIRouter

from retailflow_orders.api.auth import router as auth_router
from retailflow_orders.api.health import router as health_router
from retailflow_orders.api.orders import router as orders_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(orders_router)
