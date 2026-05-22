from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4, UUID

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    ASSEMBLING = "ASSEMBLING"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    CANCEL_PENDING = "CANCEL_PENDING"


class OrderModel(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=OrderStatus.CREATED, nullable=False)
    address_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payment_method_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subtotal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivery_cost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, unique=True, index=True
    )
    request_body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    history: Mapped[list["OrderStatusHistoryModel"]] = relationship(
        "OrderStatusHistoryModel",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="OrderStatusHistoryModel.changed_at",
    )
    items: Mapped[list["OrderItemModel"]] = relationship(
        "OrderItemModel",
        lazy="noload",
        cascade="all, delete-orphan",
    )


class OrderItemModel(Base):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class OrderStatusHistoryModel(Base):
    __tablename__ = "order_status_history"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
