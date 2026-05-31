from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4, UUID

from sqlalchemy import DateTime, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FavoriteModel(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
