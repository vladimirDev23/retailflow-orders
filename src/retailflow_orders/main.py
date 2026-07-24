from fastapi import FastAPI

from retailflow_orders import __version__
from retailflow_orders.api.router import api_router
from retailflow_orders.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        summary="Idempotent order orchestration and checkout service",
        version=__version__,
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
