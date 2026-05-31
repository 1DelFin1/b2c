from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.models.favorites import FavoriteModel


class FavoritesService:
    @classmethod
    async def add(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
    ) -> tuple[bool, datetime]:
        """Add product to favorites. Returns (is_new, added_at)."""
        existing = await session.scalar(
            select(FavoriteModel).where(
                FavoriteModel.user_id == user_id,
                FavoriteModel.product_id == product_id,
            )
        )
        if existing is not None:
            return False, existing.added_at

        fav = FavoriteModel(user_id=user_id, product_id=product_id)
        session.add(fav)
        await session.commit()
        await session.refresh(fav)
        return True, fav.added_at

    @classmethod
    async def remove(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
    ) -> None:
        """Remove product from favorites (idempotent — no error if not found)."""
        await session.execute(
            delete(FavoriteModel).where(
                FavoriteModel.user_id == user_id,
                FavoriteModel.product_id == product_id,
            )
        )
        await session.commit()

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UUID], int]:
        """Return paginated product_ids and total count for the user."""
        total = (
            await session.scalar(
                select(func.count(FavoriteModel.id)).where(FavoriteModel.user_id == user_id)
            )
        ) or 0

        rows = (
            await session.scalars(
                select(FavoriteModel.product_id)
                .where(FavoriteModel.user_id == user_id)
                .order_by(FavoriteModel.added_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        return list(rows), total

    # ── Redis helper: used by notification service to find subscribers ────────

    @classmethod
    async def get_buyers_for_product(cls, product_id: UUID) -> list[UUID]:
        """Scan Redis-backed favorites index for subscribers to a product."""
        pid_str = str(product_id)
        buyer_ids: list[UUID] = []
        pattern = "favorites:*"
        async for key in redis_client.scan_iter(match=pattern, count=100):
            raw = await redis_client.get(key)
            if not raw:
                continue
            try:
                items = json.loads(raw)
                if not isinstance(items, list):
                    continue
            except json.JSONDecodeError:
                continue
            if pid_str in [str(item) for item in items]:
                try:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    buyer_ids.append(UUID(key_str.split(":", 1)[1]))
                except (ValueError, IndexError):
                    continue
        return buyer_ids
