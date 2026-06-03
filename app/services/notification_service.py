from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import NotificationModel
from app.schemas import PaginatedNotifications, NotificationResponse


class NotificationService:
    @staticmethod
    async def get_list(
        session: AsyncSession,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> PaginatedNotifications:
        base_q = select(NotificationModel).where(NotificationModel.user_id == user_id)
        if unread_only:
            base_q = base_q.where(NotificationModel.is_read.is_(False))

        count_stmt = select(func.count()).select_from(base_q.subquery())
        total = (await session.scalar(count_stmt)) or 0

        unread_stmt = select(func.count()).select_from(
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id, NotificationModel.is_read.is_(False))
            .subquery()
        )
        unread_count = (await session.scalar(unread_stmt)) or 0

        notifications_stmt = (
            base_q
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        notifications = list((await session.scalars(notifications_stmt)).all())

        return PaginatedNotifications(
            items=notifications,
            total_count=int(total),
            unread_count=int(unread_count),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    async def mark_read(
        session: AsyncSession,
        user_id: UUID,
        notification_id: UUID,
    ) -> None:
        stmt = select(NotificationModel).where(
            NotificationModel.id == notification_id,
            NotificationModel.user_id == user_id,
        )
        notification = await session.scalar(stmt)
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Notification not found"},
            )
        notification.is_read = True
        await session.commit()

    @staticmethod
    async def mark_all_read(session: AsyncSession, user_id: UUID) -> None:
        stmt = (
            update(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await session.execute(stmt)
        await session.commit()

    _EVENT_TYPE_MAP: dict[str, str] = {
        "PRODUCT_BLOCKED": "SYSTEM",
        "PRODUCT_HARD_BLOCKED": "SYSTEM",
        "PRODUCT_DELETED": "SYSTEM",
        "SKU_OUT_OF_STOCK": "SYSTEM",
        "SKU_BACK_IN_STOCK": "BACK_IN_STOCK",
        "PRICE_CHANGED": "PRICE_DROP",
    }

    @staticmethod
    async def create_for_buyer(
        session: AsyncSession,
        buyer_id: UUID,
        message: str,
        event_type: str,
    ) -> NotificationModel:
        notification_type = NotificationService._EVENT_TYPE_MAP.get(event_type, "SYSTEM")
        notification = NotificationModel(
            user_id=buyer_id,
            type=notification_type,
            title=message,
            body=None,
            payload={"event_type": event_type},
            is_read=False,
        )
        session.add(notification)
        await session.flush()
        return notification
