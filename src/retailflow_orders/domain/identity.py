from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"
    SERVICE = "SERVICE"


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    email: str
    password_hash: str
    role: UserRole
    active: bool


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str
    role: UserRole
