from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import BuyerDep, SessionDep, get_user_id
from app.core.config import settings
from app.schemas import SubscribeRequest
from app.services.favorites_service import FavoritesService

favorites_v1_router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])

_TIMEOUT = 5.0


@favorites_v1_router.get("")
async def get_favorites(
    session: SessionDep,
    payload: BuyerDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List favorites enriched from B2B. user_id from JWT only (IDOR prevention)."""
    user_id = get_user_id(payload)
    product_ids, total = await FavoritesService.get(session, user_id, limit=limit, offset=offset)

    items: list[dict] = []
    if product_ids:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.service.B2B_URL}/api/v1/public/products/batch",
                    json={"product_ids": [str(pid) for pid in product_ids]},
                    headers={"X-Service-Key": settings.service.SERVICE_KEY},
                )
            if resp.status_code == 200:
                # B2B returns only MODERATED, not-deleted, in-stock products —
                # blocked/deleted ones are simply absent from the response.
                for p in resp.json():
                    skus = p.get("skus") or []
                    prices = [s["price"] for s in skus if s.get("price")]
                    has_stock = any(
                        (s.get("active_quantity") or s.get("stock_quantity", 0)) > 0
                        for s in skus
                    )
                    images_raw = p.get("images") or []
                    images = [
                        {"id": img.get("id"), "url": img["url"], "ordering": img.get("ordering", 0)}
                        for img in images_raw
                        if isinstance(img, dict) and img.get("url")
                    ]
                    items.append({
                        "id": p["id"],
                        "title": p.get("title") or p.get("name") or "",
                        "slug": p.get("slug"),
                        "price": min(prices) if prices else None,
                        "in_stock": has_stock,
                        "images": images,
                    })
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "B2B_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )

    return JSONResponse(
        content={"items": items, "total_count": total, "limit": limit, "offset": offset},
        status_code=200,
    )


@favorites_v1_router.post("/{product_id}")
async def add_favorite(
    product_id: UUID,
    session: SessionDep,
    payload: BuyerDep,
):
    """Add product to favorites. 201 on first add, 200 on repeat (idempotent).
    user_id from JWT only — query/body user_id is never accepted (IDOR prevention).
    """
    user_id = get_user_id(payload)
    is_new, added_at = await FavoritesService.add(session, user_id, product_id)
    body = {"product_id": str(product_id), "added_at": added_at.isoformat()}
    return JSONResponse(content=body, status_code=201 if is_new else 200)


@favorites_v1_router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    product_id: UUID,
    session: SessionDep,
    payload: BuyerDep,
):
    """Remove product from favorites (idempotent — 204 even if not found)."""
    user_id = get_user_id(payload)
    await FavoritesService.remove(session, user_id, product_id)


@favorites_v1_router.post("/{product_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_favorite(
    product_id: UUID,
    payload: BuyerDep,
    body: SubscribeRequest = Body(default_factory=SubscribeRequest),
):
    pass


@favorites_v1_router.delete("/{product_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_favorite(
    product_id: UUID,
    payload: BuyerDep,
):
    pass
