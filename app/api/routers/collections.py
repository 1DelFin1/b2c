from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.core.config import settings
from app.schemas import (
    CollectionProductsResponse,
    CollectionSchema,
    CollectionsMetadata,
    CollectionsResponse,
)
from app.services.collection_service import CollectionService

collections_router = APIRouter(tags=["collections"])

_TIMEOUT = 10.0
_B2B_HEADERS = {"X-Service-Key": settings.service.SERVICE_KEY}


async def _b2b_batch_products(product_ids: list[str]) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.service.B2B_URL}/api/v1/public/products/batch",
                json={"product_ids": product_ids},
                headers=_B2B_HEADERS,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "B2B_UNAVAILABLE", "message": str(exc)},
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "B2B_UNAVAILABLE", "message": "B2B product batch failed"},
        )
    return resp.json()


@collections_router.get("/api/v1/main/collections", response_model=CollectionsResponse)
async def list_collections(
    session: SessionDep,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> CollectionsResponse:
    """Public — list active collections sorted by priority, without product details."""
    rows, total = await CollectionService.list_active(session, limit=limit, offset=offset)
    return CollectionsResponse(
        metadata=CollectionsMetadata(total_count=total, limit=limit, offset=offset),
        collections=[CollectionSchema.model_validate(c) for c in rows],
    )


@collections_router.get(
    "/api/v1/collections/{collection_id}/products",
    response_model=CollectionProductsResponse,
)
async def get_collection_products(
    collection_id: UUID,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CollectionProductsResponse:
    """Return collection products enriched from B2B. Unavailable products go to unavailable_ids."""
    collection = await CollectionService.get_by_id(session, collection_id)
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COLLECTION_NOT_FOUND", "message": "Подборка не найдена"},
        )

    product_ids, total = await CollectionService.get_product_ids(
        session, collection_id, limit=limit, offset=offset
    )

    if not product_ids:
        return CollectionProductsResponse(
            collection_title=collection.title,
            total_products=total,
            items=[],
            unavailable_ids=[],
        )

    b2b_products = await _b2b_batch_products([str(pid) for pid in product_ids])
    return CollectionService.build_products_response(
        collection_title=collection.title,
        total_products=total,
        requested_ids=product_ids,
        b2b_products=b2b_products,
    )
