"""Create the order orchestration schema.

Revision ID: 20260724_0001
Revises:
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=19, scale=2), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("payment_reference", sa.String(length=120), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "total_amount >= 0",
            name=op.f("ck_orders_total_amount_non_negative"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_orders_version_positive")),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_orders_customer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index(
        "ix_orders_customer_created",
        "orders",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_orders_status_updated",
        "orders",
        ["status", "updated_at"],
    )
    op.create_table(
        "order_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=19, scale=2), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_lines_quantity_positive")),
        sa.CheckConstraint(
            "unit_price > 0",
            name=op.f("ck_order_lines_unit_price_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_lines_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_lines")),
        sa.UniqueConstraint(
            "order_id",
            "sku",
            name=op.f("uq_order_lines_order_id"),
        ),
    )
    op.create_table(
        "order_transitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_transitions_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_transitions")),
    )
    op.create_index(
        "ix_order_transitions_order_time",
        "order_transitions",
        ["order_id", "occurred_at"],
    )
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=2), nullable=False),
        sa.Column("provider_reference", sa.String(length=120), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payment_attempts_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_attempts")),
        sa.UniqueConstraint(
            "order_id",
            "idempotency_key",
            name=op.f("uq_payment_attempts_order_id"),
        ),
    )
    op.create_index(
        "ix_payment_attempts_order_created",
        "payment_attempts",
        ["order_id", "created_at"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint(
            "scope",
            "key_hash",
            name=op.f("uq_idempotency_records_scope"),
        ),
    )
    op.create_index(
        "ix_idempotency_records_expires",
        "idempotency_records",
        ["expires_at"],
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["published_at", "occurred_at"],
    )
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=100), nullable=False),
        sa.Column("message_id", sa.String(length=150), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_messages")),
        sa.UniqueConstraint(
            "consumer",
            "message_id",
            name=op.f("uq_inbox_messages_consumer"),
        ),
    )
    op.create_index(
        "ix_inbox_messages_processed",
        "inbox_messages",
        ["processed_at"],
    )
    op.create_table(
        "product_snapshots",
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=19, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("source_version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "unit_price > 0",
            name=op.f("ck_product_snapshots_unit_price_positive"),
        ),
        sa.PrimaryKeyConstraint("sku", name=op.f("pk_product_snapshots")),
    )
    op.create_index(
        "ix_product_snapshots_updated",
        "product_snapshots",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_snapshots_updated", table_name="product_snapshots")
    op.drop_table("product_snapshots")
    op.drop_index("ix_inbox_messages_processed", table_name="inbox_messages")
    op.drop_table("inbox_messages")
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_idempotency_records_expires", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_payment_attempts_order_created", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index("ix_order_transitions_order_time", table_name="order_transitions")
    op.drop_table("order_transitions")
    op.drop_table("order_lines")
    op.drop_index("ix_orders_status_updated", table_name="orders")
    op.drop_index("ix_orders_customer_created", table_name="orders")
    op.drop_table("orders")
    op.drop_table("users")
