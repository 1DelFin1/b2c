from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import get_current_active_auth_buyer, get_user_id
from app.core.config import settings
from app.schemas import CatalogProductCard, CategoryRef, ImageRef, FavoritesResponse, PaginatedCatalogProducts, SellerRef, SubscribeRequest
from app.services.favorites_service import FavoritesService

favorites_v1_router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@favorites_v1_router.get("", response_model=PaginatedCatalogProducts)
async def get_favorites(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    product_ids, total = await FavoritesService.get(user_id, limit=limit, offset=offset)

    cards: list[CatalogProductCard] = []
    if product_ids:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{settings.service.B2B_URL}/api/v1/public/products/batch",
                    json={"product_ids": [str(pid) for pid in product_ids]},
                    headers={"X-Service-Key": settings.service.SERVICE_KEY},
                )
            if resp.status_code == 200:
                for p in resp.json():
                    images_raw = p.get("images") or []
                    image_urls = [
                        ImageRef(
                            id=UUID(img["id"]) if img.get("id") else UUID(int=0),
                            url=img["url"],
                            alt=img.get("alt"),
                            ordering=img.get("ordering", 0),
                            is_main=img.get("is_main", False),
                        )
                        for img in images_raw
                        if isinstance(img, dict) and img.get("url")
                    ]
                    skus = p.get("skus") or []
                    prices = [s.get("price", 0) for s in skus if s.get("price")]
                    min_price = min(prices) if prices else None
                    has_stock = any((s.get("active_quantity") or s.get("stock_quantity", 0)) > 0 for s in skus)

                    # Build CategoryRef if available
                    category: CategoryRef | None = None
                    cat_data = p.get("category")
                    if cat_data and isinstance(cat_data, dict) and cat_data.get("id"):
                        cat_path_raw = cat_data.get("path", "")
                        cat_path = (
                            [seg for seg in cat_path_raw.split("/") if seg]
                            if isinstance(cat_path_raw, str)
                            else (cat_path_raw if isinstance(cat_path_raw, list) else [])
                        )
                        category = CategoryRef(
                            id=UUID(cat_data["id"]),
                            name=cat_data.get("name") or "",
                            path=cat_path,
                        )

                    # Build SellerRef if available
                    seller: SellerRef | None = None
                    seller_id_raw = p.get("seller_id")
                    if seller_id_raw:
                        try:
                            seller = SellerRef(id=UUID(str(seller_id_raw)), display_name="")
                        except (ValueError, AttributeError):
                            pass

                    cards.append(CatalogProductCard(
                        id=UUID(p["id"]),
                        name=p.get("title") or p.get("name") or "",
                        slug=p.get("slug"),
                        min_price=min_price,
                        has_stock=has_stock,
                        images=image_urls,
                        category=category,
                        rating=p.get("rating"),
                        reviews_count=p.get("reviews_count") or 0,
                        seller=seller,
                    ))
        except Exception:
            cards = [CatalogProductCard(id=pid, name="", has_stock=False) for pid in product_ids]

    return PaginatedCatalogProducts(items=cards, total_count=total, limit=limit, offset=offset)


@favorites_v1_router.put("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    product_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    await FavoritesService.add(user_id, product_id)


@favorites_v1_router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    product_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = get_user_id(payload)
    await FavoritesService.remove(user_id, product_id)


@favorites_v1_router.post("/{product_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_favorite(
    product_id: UUID,
    body: SubscribeRequest = Body(default_factory=SubscribeRequest),
    payload: dict = Depends(get_current_active_auth_buyer),
):
    pass


@favorites_v1_router.delete("/{product_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_favorite(
    product_id: UUID,
    payload: dict = Depends(get_current_active_auth_buyer),
):
    pass
