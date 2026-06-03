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
            "name": item.get("title"),
            "images": [{"url": item["cover_image"], "ordering": 0}] if item.get("cover_image") else [],
            "min_price": item.get("min_price", 0),
            "has_stock": bool(item.get("min_price")),
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


# ── Canonical products endpoints (GET /api/v1/catalog/products) ──────────────

@catalog_router.get("/products")
async def get_products(
    request: Request,
    category_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Catalog with filters, sort, and pagination; proxies to B2B."""
    if q is not None and len(q) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Search query must be at least 3 characters"},
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
    if q is not None:
        params["search"] = q  # B2B expects "search"
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


def _chars_to_attrs(characteristics: list) -> dict:
    """Convert B2B [{id, name, value}] array to B2C {name: value} attributes object."""
    return {c["name"]: c["value"] for c in characteristics if "name" in c and "value" in c}


def _transform_product_card(b2b_data: dict) -> dict:
    """Convert B2B ProductPublicResponse to B2C CatalogProductDetail.

    Strips seller-internal fields at the B2C boundary.
    Maps characteristics[] → attributes {}, active_quantity → available_quantity.
    """
    b2b_skus = b2b_data.get("skus", [])

    skus = []
    for sku in b2b_skus:
        images = sku.get("images") or []
        sorted_images = sorted(images, key=lambda i: i.get("ordering", 0))
        discount = sku.get("discount") or 0
        skus.append({
            "id": sku.get("id"),
            "name": sku.get("name"),
            "sku_code": sku.get("article"),
            "price": sku.get("price"),
            "old_price": (sku["price"] + discount) if discount > 0 and sku.get("price") is not None else None,
            "available_quantity": sku.get("active_quantity"),
            "attributes": _chars_to_attrs(sku.get("characteristics") or []),
            "images": [
                {"id": img.get("id"), "url": img.get("url"), "ordering": img.get("ordering", 0)}
                for img in sorted_images
            ],
        })

    in_stock_prices = [s["price"] for s in skus if (s.get("available_quantity") or 0) > 0 and s.get("price") is not None]
    min_price = min(in_stock_prices) if in_stock_prices else None
    has_stock = bool(in_stock_prices)

    return {
        "id": b2b_data.get("id"),
        "name": b2b_data.get("title"),
        "slug": b2b_data.get("slug"),
        "min_price": min_price,
        "has_stock": has_stock,
        "images": [
            {"id": img.get("id"), "url": img.get("url"), "ordering": img.get("ordering", 0)}
            for img in sorted(b2b_data.get("images", []), key=lambda i: i.get("ordering", 0))
        ],
        "description": b2b_data.get("description"),
        "attributes": _chars_to_attrs(b2b_data.get("characteristics") or []),
        "skus": skus,
    }


@catalog_router.get("/products/{product_id}")
async def get_product(product_id: UUID):
    url = f"{settings.service.B2B_URL}/api/v1/public/products/{product_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
        except Exception as exc:
            logger.warning("B2B proxy error for /products/%s: %s", product_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    if resp.status_code != 200:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    return JSONResponse(content=_transform_product_card(resp.json()), status_code=200)


@catalog_router.get("/products/{product_id}/similar")
async def get_similar_products(
    product_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    url = f"{settings.service.B2B_URL}/api/v1/public/products/{product_id}/similar"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(
                url,
                params={"limit": limit},
                headers={"X-Service-Key": settings.service.SERVICE_KEY},
            )
        except Exception as exc:
            logger.warning("B2B proxy error for /products/%s/similar: %s", product_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )
    if resp.status_code != 200:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    b2b_items = resp.json() if isinstance(resp.json(), list) else []
    items = [
        {
            "id": item.get("id"),
            "name": item.get("title"),
            "images": [{"url": item["cover_image"], "ordering": 0}] if item.get("cover_image") else [],
            "min_price": item.get("min_price", 0),
            "has_stock": bool(item.get("min_price")),
        }
        for item in b2b_items
    ]
    return JSONResponse(content=items, status_code=200)


def _enrich_tree_with_parent_id(nodes: list, parent_id: str | None = None) -> list:
    """Inject parent_id into each tree node — B2B CategoryTreeResponse omits it."""
    result = []
    for node in nodes:
        result.append({
            "id": node.get("id"),
            "name": node.get("name"),
            "parent_id": parent_id,
            "children": _enrich_tree_with_parent_id(node.get("children", []), parent_id=node.get("id")),
        })
    return result


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
        return JSONResponse(content={"items": _enrich_tree_with_parent_id(data)}, status_code=200)
    return JSONResponse(content=data, status_code=resp.status_code)


@products_router.get("/breadcrumbs")
async def get_breadcrumbs(
    category_id: UUID | None = Query(default=None),
    product_id: UUID | None = Query(default=None),
):
    """Canonical breadcrumb chain from root to target category or product's category."""
    if category_id is not None and product_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AMBIGUOUS_PARAM", "message": "only one of category_id or product_id must be provided"},
        )
    if category_id is None and product_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MISSING_PARAM", "message": "category_id or product_id must be provided"},
        )

    resolved_via = "category_id"
    resolved_category_id: UUID = category_id  # type: ignore[assignment]

    if product_id is not None:
        resolved_via = "product_id"
        url = f"{settings.service.B2B_URL}/api/v1/public/products/{product_id}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
                )
        if resp.status_code != 200:
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
        resolved_category_id = resp.json().get("category_id")

    url = f"{settings.service.B2B_URL}/api/v1/categories/{resolved_category_id}/breadcrumbs"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers={"X-Service-Key": settings.service.SERVICE_KEY})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "UPSTREAM_UNAVAILABLE", "message": f"B2B service unavailable: {exc}"},
            )

    if resp.status_code != 200:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    crumbs: list[dict] = resp.json()

    if not crumbs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Category not found"},
        )

    # Orphan detection: a valid chain must start at a root node (parent_id is None).
    # If the first crumb still has a parent_id, the hierarchy is broken.
    if crumbs[0].get("parent_id") is not None:
        raise HTTPException(
            status_code=422,
            detail={"code": "ORPHAN_NODE", "message": "category hierarchy is broken"},
        )

    data = []
    for i, crumb in enumerate(crumbs):
        path: str = crumb.get("path", "")
        slug = path.split("/")[-1] if path else str(crumb.get("id"))
        data.append({
            "id": crumb.get("id"),
            "slug": slug,
            "name": crumb.get("name"),
            "url": f"/catalog/{path}" if path else f"/catalog/{crumb.get('id')}",
            "level": crumb.get("level", i),
            "is_current": i == len(crumbs) - 1,
        })

    return JSONResponse(
        content={
            "data": data,
            "meta": {
                "resolved_via": resolved_via,
                "category_id": str(resolved_category_id),
            },
        },
        status_code=200,
    )


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


def _b2b_category_to_ref(cat: dict) -> dict:
    """Convert B2B CategoryResponse to B2C CategoryRef.

    B2B sends path as a materialized string "a/b/c"; B2C spec wants an array.
    """
    raw_path: str = cat.get("path") or ""
    return {
        "id": cat.get("id"),
        "name": cat.get("name"),
        "parent_id": cat.get("parent_id"),
        "level": cat.get("level", 0),
        "path": [seg for seg in raw_path.split("/") if seg],
    }


def _enrich_tree_node(node: dict, parent_id: str | None, level: int, path: list[str]) -> dict:
    """Recursively convert B2B CategoryTreeResponse node to B2C CategoryTreeNode.

    B2B tree only carries {id, name, children}; level, path and parent_id are computed here.
    """
    current_path = path + [node["id"]]
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "parent_id": parent_id,
        "level": level,
        "path": current_path,
        "children": [
            _enrich_tree_node(child, parent_id=node.get("id"), level=level + 1, path=current_path)
            for child in node.get("children", [])
        ],
    }


@catalog_router.get("/categories")
async def get_categories_flat():
    """Flat category list; B2B already carries level and path."""
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
        return JSONResponse(content=[_b2b_category_to_ref(c) for c in data], status_code=200)
    return JSONResponse(content=data, status_code=resp.status_code)


@catalog_router.get("/categories/tree")
async def get_categories_tree():
    """Category tree; B2B tree omits level/path/parent_id — computed during traversal."""
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
        return JSONResponse(
            content=[_enrich_tree_node(node, parent_id=None, level=0, path=[]) for node in data],
            status_code=200,
        )
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
