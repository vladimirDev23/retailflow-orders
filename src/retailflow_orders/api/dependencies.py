from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from retailflow_orders.bootstrap import ApplicationContainer
from retailflow_orders.domain.identity import AuthenticatedUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container  # type: ignore[no-any-return]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> AuthenticatedUser:
    return container.tokens.authenticate(token)
