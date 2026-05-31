from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

import httpx
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.schemas import CatalogProductCard

logger = logging.getLogger(__name__)

catalog_router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
products_router = APIRouter(prefix="/api/v1", tags=["products"])

_TIMEOUT = 10.0

# Canonical sort values from b2c-catalog-flows.md#b2c-1-catalog-filters
_VALID_SORTS = frozenset({
    "rating", "popularity", "price_asc", "price_desc", "date_desc", "discount_desc",
})
_VALID_SORTS_MSG = "rating, popularity, price_asc, price_desc, date_desc, discount_desc"

# Translate canonical B2C sort values to B2B-understood values
_SORT_TO_B2B: dict[str, str] = {
    "rating": "popular",
    "popularity": "popular",
    "price_asc": "price_asc",
    "price_desc": "price_desc",
    "date_desc": "created_desc",
    "discount_desc": "created_desc",
}


async def _proxy_get(path: str, params: dict | None = None) -> JSONResponse:
    url = f"{settings.service.B2B_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(
                url,
                params=params,
                headers={"X-Service-Key": settings.service.SERVICE_KEY},
            )
        except Exception as exc:
            logger.warning("B2B proxy error for %s: %s", path, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


def _transform_products_response(b2b_data: dict) -> dict:
    """Convert B2B ProductPublicPaginatedResponse to canonical B2C format."""
    items = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "image": item.get("cover_image"),
            "price": item.get("min_price", 0),
            "in_stock": True,
            "is_in_cart": False,
        }
        for item in b2b_data.get("items", [])
    ]
    return {
        "items": items,
        "total_count": b2b_data.get("total_count", 0),
        "limit": b2b_data.get("limit", 20),
        "offset": b2b_data.get("offset", 0),
    }


# ── Canonical products endpoints (GET /api/v1/products) ──────────────────────

@products_router.get("/products")
async def get_products(
    request: Request,
    category_id: UUID | None = None,
    search: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Catalog with filters, sort, and pagination; proxies to B2B."""
    if search is not None:
        if len(search) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Search query must be at least 3 characters"},
            )
        if len(search) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Search query must be at most 255 characters"},
            )
    if sort is not None and sort not in _VALID_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": f"Invalid sort parameter. Allowed: {_VALID_SORTS_MSG}",
            },
        )

    # Start from validated params; pass deepObject filters[*] through as-is
    params: dict = {"limit": limit, "offset": offset}
    if category_id is not None:
        params["category_id"] = str(category_id)
    if search is not None:
        params["search"] = search
    if sort is not None:
        params["sort"] = _SORT_TO_B2B[sort]
    for key, value in request.query_params.multi_items():
        if key.startswith("filters["):
            params[key] = value

    url = f"{settings.service.B2B_URL}/api/v1/public/products"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(
                url,
                params=params,
                headers={"X-Service-Key": settings.service.SERVICE_KEY},
            )
        except Exception as exc:
            logger.warning("B2B proxy error for /api/v1/products: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )

    if resp.status_code != 200:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    return JSONResponse(content=_transform_products_response(resp.json()), status_code=200)


@products_router.get("/products/{product_id}")
async def get_product(product_id: UUID):
    return await _proxy_get(f"/api/v1/public/products/{product_id}")


@products_router.get("/products/{product_id}/similar")
async def get_similar_products(
    product_id: UUID,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
    offset: int = Query(default=0, ge=0),
):
    return await _proxy_get(
        f"/api/v1/public/products/{product_id}/similar",
        params={"limit": limit, "offset": offset},
    )


@products_router.get("/categories")
async def get_categories_tree():
    """Full category tree for B2C navigation."""
    url = f"{settings.service.B2B_URL}/api/v1/categories/tree"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    data = resp.json()
    if resp.status_code == 200 and isinstance(data, list):
        return JSONResponse(content={"items": data}, status_code=200)
    return JSONResponse(content=data, status_code=resp.status_code)


@products_router.get("/categories/{category_id}/filters")
async def get_category_filters(category_id: UUID):
    """Available filter definitions for a category; B2B-7 endpoint."""
    return await _proxy_get(f"/api/v1/public/categories/{category_id}/filters")


@products_router.get("/categories/{category_id}")
async def get_category(category_id: UUID, include_product_count: bool = False):
    return await _proxy_get(
        f"/api/v1/categories/{category_id}",
        params={"include_product_count": include_product_count},
    )


# ── Facets endpoint (GET /api/v1/catalog/facets) ─────────────────────────────

@catalog_router.get("/facets")
async def get_catalog_facets(request: Request, category_id: UUID = Query(...)):
    """Facet counts per characteristic value; proxies to B2B (B2B-7)."""
    params = dict(request.query_params)
    return await _proxy_get("/api/v1/public/catalog/facets", params=params)


# ── Legacy catalog-prefixed endpoints (kept for backward compat) ─────────────

@catalog_router.get("/products")
async def proxy_products(request: Request):
    params = dict(request.query_params)
    return await _proxy_get("/api/v1/public/products", params=params)


@catalog_router.get("/products/{product_id}")
async def proxy_product(product_id: UUID):
    return await _proxy_get(f"/api/v1/public/products/{product_id}")


@catalog_router.get("/products/{product_id}/similar")
async def proxy_similar_products(
    product_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    return await _proxy_get(f"/api/v1/public/products/{product_id}/similar", params={"limit": limit})


def _transform_categories_path(categories: list) -> list:
    for cat in categories:
        if isinstance(cat.get("path"), str):
            cat["path"] = [p for p in cat["path"].split("/") if p]
    return categories


@catalog_router.get("/categories")
async def proxy_categories():
    url = f"{settings.service.B2B_URL}/api/v1/categories"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    data = resp.json()
    if resp.status_code == 200 and isinstance(data, list):
        data = _transform_categories_path(data)
    return JSONResponse(content=data, status_code=resp.status_code)


@catalog_router.get("/categories/tree")
async def proxy_categories_tree():
    url = f"{settings.service.B2B_URL}/api/v1/categories/tree"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    data = resp.json()
    if resp.status_code == 200 and isinstance(data, list):
        data = _transform_categories_path(data)
    return JSONResponse(content=data, status_code=resp.status_code)


class Banner(BaseModel):
    id: UUID
    image_url: str
    link: str
    title: str | None = None
    ordering: int = 0
    active_from: datetime | None = None
    active_to: datetime | None = None


class Collection(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    products: list[CatalogProductCard] = []


@catalog_router.get("/banners", response_model=list[Banner])
async def get_banners():
    return []


@catalog_router.get("/collections", response_model=list[Collection])
async def get_collections():
    return []
