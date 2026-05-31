from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request, status

from app.api.deps import SessionDep, get_optional_user_id
from app.schemas import BannerEventsRequest, BannerListResponse, BannerSchema
from app.services.banner_service import BannerService

banners_router = APIRouter(tags=["banners"])


@banners_router.get("/api/v1/home/banners", response_model=BannerListResponse)
async def get_home_banners(session: SessionDep) -> BannerListResponse:
    """Public — no auth required. Returns active banners sorted by priority."""
    banners = await BannerService.get_active(session)
    return BannerListResponse(
        items=[BannerSchema.model_validate(b) for b in banners],
        total_count=len(banners),
    )


@banners_router.post("/api/v1/banner-events", status_code=status.HTTP_204_NO_CONTENT)
async def post_banner_events(
    request: Request,
    session: SessionDep,
    body: BannerEventsRequest = Body(...),
) -> None:
    """Accept impression/click events for CTR analytics. Works for guests and auth users."""
    user_id = get_optional_user_id(request)

    # Validate all banner_ids exist
    for ev in body.events:
        if not await BannerService.exists(session, ev.banner_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "BANNER_NOT_FOUND", "message": "Баннер с указанным id не найден"},
            )

    events_data = [
        {"banner_id": ev.banner_id, "event": ev.event, "timestamp": ev.timestamp}
        for ev in body.events
    ]
    await BannerService.record_events(session, events_data, user_id)
