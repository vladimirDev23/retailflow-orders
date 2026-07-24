from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from jwt.types import Options
from pwdlib import PasswordHash

from retailflow_orders.application.exceptions import AuthenticationError
from retailflow_orders.domain.identity import AuthenticatedUser, UserAccount, UserRole

JWT_ALGORITHM = "HS256"


class PasswordService:
    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)


class JwtService:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        ttl_seconds: int,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._ttl = timedelta(seconds=ttl_seconds)

    def issue(self, user: UserAccount, *, now: datetime | None = None) -> str:
        issued_at = now or datetime.now(tz=UTC)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "exp": issued_at + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=JWT_ALGORITHM)

    def authenticate(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> AuthenticatedUser:
        options = Options(verify_exp=now is None)
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options=options,
            )
            if now is not None:
                expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
                if expires_at <= now:
                    raise jwt.ExpiredSignatureError
            return AuthenticatedUser(
                id=UUID(str(payload["sub"])),
                email=str(payload["email"]),
                role=UserRole(str(payload["role"])),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exception:
            message = "Access token is invalid or expired"
            raise AuthenticationError(message) from exception
