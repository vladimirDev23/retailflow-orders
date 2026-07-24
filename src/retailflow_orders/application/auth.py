from typing import Protocol

from retailflow_orders.application.exceptions import AuthenticationError
from retailflow_orders.domain.identity import AuthenticatedUser, UserAccount


class UserDirectory(Protocol):
    async def get_by_email(self, email: str) -> UserAccount | None: ...


class PasswordVerifier(Protocol):
    def verify(self, password: str, password_hash: str) -> bool: ...


class TokenIssuer(Protocol):
    def issue(self, user: UserAccount) -> str: ...


class LoginService:
    def __init__(
        self,
        *,
        users: UserDirectory,
        passwords: PasswordVerifier,
        tokens: TokenIssuer,
    ) -> None:
        self._users = users
        self._passwords = passwords
        self._tokens = tokens

    async def execute(self, *, email: str, password: str) -> tuple[str, AuthenticatedUser]:
        user = await self._users.get_by_email(email)
        if (
            user is None
            or not user.active
            or not self._passwords.verify(password, user.password_hash)
        ):
            message = "Email or password is invalid"
            raise AuthenticationError(message)
        token = self._tokens.issue(user)
        authenticated = AuthenticatedUser(
            id=user.id,
            email=user.email,
            role=user.role,
        )
        return token, authenticated
