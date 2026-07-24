from typing import Annotated

from fastapi import APIRouter, Depends

from retailflow_orders.api.dependencies import get_container
from retailflow_orders.api.models import TokenRequest, TokenResponse
from retailflow_orders.bootstrap import ApplicationContainer

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/token", operation_id="issueAccessToken")
async def issue_token(
    request: TokenRequest,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> TokenResponse:
    token, _ = await container.login.execute(
        email=str(request.email),
        password=request.password,
    )
    return TokenResponse(
        access_token=token,
        expires_in=container.settings.access_token_ttl_seconds,
    )
