from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from retailflow_orders.domain.identity import UserRole
from retailflow_orders.domain.order import OrderStatus
from retailflow_orders.infrastructure.database.base import Base, utc_now

JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")
MONEY_TYPE = Numeric(19, 2)


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.CUSTOMER.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )


class OrderModel(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint("version > 0", name="version_positive"),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        Index("ix_orders_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    warehouse_id: Mapped[UUID] = mapped_column(Uuid)
    currency: Mapped[str] = mapped_column(String(3))
    total_amount: Mapped[Decimal] = mapped_column(MONEY_TYPE)
    status: Mapped[str] = mapped_column(String(40), default=OrderStatus.DRAFT.value)
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payment_reference: Mapped[str | None] = mapped_column(String(120))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    lines: Mapped[list["OrderLineModel"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderLineModel(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        UniqueConstraint("order_id", "sku"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
    )
    product_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MONEY_TYPE)

    order: Mapped[OrderModel] = relationship(back_populates="lines")


class OrderTransitionModel(Base):
    __tablename__ = "order_transitions"
    __table_args__ = (Index("ix_order_transitions_order_time", "order_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
    )
    previous_status: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "key_hash"),
        Index("ix_idempotency_records_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_pending",
            "published_at",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class InboxMessageModel(Base):
    __tablename__ = "inbox_messages"
    __table_args__ = (
        UniqueConstraint("consumer", "message_id"),
        Index("ix_inbox_messages_processed", "processed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    consumer: Mapped[str] = mapped_column(String(100))
    message_id: Mapped[str] = mapped_column(String(150))
    payload_hash: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )


class ProductSnapshotModel(Base):
    __tablename__ = "product_snapshots"
    __table_args__ = (
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        Index("ix_product_snapshots_updated", "updated_at"),
    )

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    product_name: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[Decimal] = mapped_column(MONEY_TYPE)
    currency: Mapped[str] = mapped_column(String(3))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    source_version: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
