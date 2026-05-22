from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import SessionDep, get_current_active_auth_buyer, get_user_id
from app.schemas import PaginatedNotifications
from app.services.notification_service import NotificationService

notifications_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@notifications_router.get("", response_model=PaginatedNotifications)
async def list_notifications(
    session: SessionDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    return await NotificationService.get_list(
        session, user_id, unread_only=unread_only, limit=limit, offset=offset
    )


@notifications_router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    session: SessionDep,
    notification_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    await NotificationService.mark_read(session, user_id, notification_id)


@notifications_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    session: SessionDep,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    await NotificationService.mark_all_read(session, user_id)
