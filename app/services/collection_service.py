from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collections import Collection, CollectionProduct
from app.schemas import CollectionProductCard, CollectionProductsResponse


class CollectionService:
    @classmethod
    async def list_active(
        cls,
        session: AsyncSession,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Collection], int]:
        """Return paginated active collections (start_date <= today), sorted by priority."""
        today = date.today()
        base_filter = Collection.is_active.is_(True) & (
            (Collection.start_date.is_(None)) | (Collection.start_date <= today)
        )
        total: int = (
            await session.scalar(select(func.count(Collection.id)).where(base_filter))
        ) or 0
        rows = (
            await session.scalars(
                select(Collection)
                .where(base_filter)
                .order_by(Collection.priority.asc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return list(rows), total

    @classmethod
    async def get_by_id(cls, session: AsyncSession, collection_id: UUID) -> Collection | None:
        return await session.scalar(
            select(Collection).where(Collection.id == collection_id)
        )

    @classmethod
    async def get_product_ids(
        cls,
        session: AsyncSession,
        collection_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UUID], int]:
        """Return paginated product_ids for a collection, ordered by `ordering`."""
        total: int = (
            await session.scalar(
                select(func.count(CollectionProduct.product_id)).where(
                    CollectionProduct.collection_id == collection_id
                )
            )
        ) or 0
        rows = (
            await session.scalars(
                select(CollectionProduct.product_id)
                .where(CollectionProduct.collection_id == collection_id)
                .order_by(CollectionProduct.ordering.asc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return list(rows), total

    @classmethod
    def build_products_response(
        cls,
        collection_title: str,
        total_products: int,
        requested_ids: list[UUID],
        b2b_products: list[dict],
    ) -> CollectionProductsResponse:
        """Match B2B response against requested product IDs."""
        found: dict[str, dict] = {str(p["id"]): p for p in b2b_products}
        items: list[CollectionProductCard] = []
        unavailable_ids: list[UUID] = []

        for pid in requested_ids:
            p = found.get(str(pid))
            if p is None:
                unavailable_ids.append(pid)
                continue
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
            items.append(CollectionProductCard(
                id=UUID(str(p["id"])),
                title=p.get("title") or p.get("name") or "",
                slug=p.get("slug"),
                price=min(prices) if prices else None,
                in_stock=has_stock,
                images=images,
            ))

        return CollectionProductsResponse(
            collection_title=collection_title,
            total_products=total_products,
            items=items,
            unavailable_ids=unavailable_ids,
        )
