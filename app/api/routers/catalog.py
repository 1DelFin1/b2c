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

_TIMEOUT = 10.0


async def _proxy_get(path: str, params: dict | None = None) -> JSONResponse:
    """Forward a GET request to B2B and return the response as-is."""
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
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"B2B service unavailable: {exc}",
            )

    return JSONResponse(content=resp.json(), status_code=resp.status_code)


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
    """Convert string path to array (e.g. 'electronics/phones' → ['electronics', 'phones'])."""
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
            logger.warning("B2B proxy error for /api/v1/categories: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"B2B service unavailable: {exc}",
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
            logger.warning("B2B proxy error for /api/v1/categories/tree: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"B2B service unavailable: {exc}",
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
