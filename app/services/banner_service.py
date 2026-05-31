from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banners import Banner, BannerEvent


class BannerService:
    @classmethod
    async def get_active(cls, session: AsyncSession) -> list[Banner]:
        """Return banners where is_active=True and now() is within [start_at, end_at]."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(Banner)
            .where(
                Banner.is_active.is_(True),
                or_(Banner.start_at.is_(None), Banner.start_at <= now),
                or_(Banner.end_at.is_(None), Banner.end_at >= now),
            )
            .order_by(Banner.priority.asc())
        )
        rows = (await session.scalars(stmt)).all()
        return list(rows)

    @classmethod
    async def exists(cls, session: AsyncSession, banner_id: UUID) -> bool:
        result = await session.scalar(
            select(Banner.id).where(Banner.id == banner_id).limit(1)
        )
        return result is not None

    @classmethod
    async def record_events(
        cls,
        session: AsyncSession,
        events: list[dict],
        user_id: UUID | None,
    ) -> None:
        """Bulk-insert banner events. Caller must have validated banner_ids exist."""
        for ev in events:
            session.add(BannerEvent(
                banner_id=ev["banner_id"],
                user_id=user_id,
                event=ev["event"],
                occurred_at=ev["timestamp"],
            ))
        await session.commit()
