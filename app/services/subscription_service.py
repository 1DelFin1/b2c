from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscriptions import ProductSubscription


class SubscriptionService:
    @classmethod
    async def subscribe(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
        notify_on: list[str],
    ) -> ProductSubscription:
        """Create a subscription. Raises IntegrityError on duplicate (user+product)."""
        sub = ProductSubscription(
            user_id=user_id,
            product_id=product_id,
            notify_on=notify_on,
        )
        session.add(sub)
        try:
            await session.commit()
            await session.refresh(sub)
        except IntegrityError:
            await session.rollback()
            raise
        return sub

    @classmethod
    async def unsubscribe(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
    ) -> None:
        """Remove subscription (idempotent — no error if not found)."""
        await session.execute(
            delete(ProductSubscription).where(
                ProductSubscription.user_id == user_id,
                ProductSubscription.product_id == product_id,
            )
        )
        await session.commit()

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        user_id: UUID,
        product_id: UUID,
    ) -> ProductSubscription | None:
        return await session.scalar(
            select(ProductSubscription).where(
                ProductSubscription.user_id == user_id,
                ProductSubscription.product_id == product_id,
            )
        )
