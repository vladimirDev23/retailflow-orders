from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from retailflow_orders.application.auth import LoginService
from retailflow_orders.application.exceptions import AuthenticationError
from retailflow_orders.domain.identity import UserAccount, UserRole
from retailflow_orders.infrastructure.security import (
    JwtService,
    PasswordService,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)
DEFAULT_TEST_SECRET = "a-secure-local-test-key-with-more-than-32-characters"


def user() -> UserAccount:
    return UserAccount(
        id=uuid4(),
        email="customer@retailflow.local",
        password_hash="unused-in-token-test",
        role=UserRole.CUSTOMER,
        active=True,
    )


def tokens(*, secret: str | None = None) -> JwtService:
    return JwtService(
        secret=secret or DEFAULT_TEST_SECRET,
        issuer="retailflow-orders",
        audience="retailflow-orders-api",
        ttl_seconds=3600,
    )


def test_password_hash_is_salted_and_verifiable() -> None:
    passwords = PasswordService()

    first = passwords.hash("correct horse battery staple")
    second = passwords.hash("correct horse battery staple")

    assert first != second
    assert passwords.verify("correct horse battery staple", first)
    assert not passwords.verify("wrong password", first)


def test_issues_and_authenticates_scoped_access_token() -> None:
    model = user()

    authenticated = tokens().authenticate(tokens().issue(model, now=NOW), now=NOW)

    assert authenticated.id == model.id
    assert authenticated.email == model.email
    assert authenticated.role is UserRole.CUSTOMER


def test_rejects_expired_access_token() -> None:
    model = user()
    token = tokens().issue(model, now=NOW)

    with pytest.raises(AuthenticationError, match="invalid or expired"):
        tokens().authenticate(token, now=NOW + timedelta(hours=2))


def test_rejects_token_signed_with_different_key() -> None:
    token = tokens().issue(user(), now=NOW)

    with pytest.raises(AuthenticationError, match="invalid or expired"):
        tokens(secret="another-secure-test-key-with-more-than-32-characters").authenticate(
            token,
            now=NOW,
        )


class UserDirectoryFake:
    def __init__(self, account: UserAccount | None) -> None:
        self.account = account

    async def get_by_email(self, email: str) -> UserAccount | None:
        return self.account


async def test_login_verifies_hash_and_issues_token() -> None:
    passwords = PasswordService()
    model = user()
    account = UserAccount(
        id=model.id,
        email=model.email,
        password_hash=passwords.hash("correct horse battery staple"),
        role=model.role,
        active=True,
    )
    service = LoginService(
        users=UserDirectoryFake(account),
        passwords=passwords,
        tokens=tokens(),
    )

    token, authenticated = await service.execute(
        email=account.email,
        password="correct horse battery staple",
    )

    assert token
    assert authenticated.id == account.id


async def test_login_rejects_unknown_user() -> None:
    service = LoginService(
        users=UserDirectoryFake(None),
        passwords=PasswordService(),
        tokens=tokens(),
    )

    with pytest.raises(AuthenticationError, match="invalid"):
        await service.execute(email="missing@example.com", password="wrong password")
