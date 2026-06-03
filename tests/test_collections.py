"""Tests for US-CART-05: подборки товаров на главной.

DoD scenarios (b2c-cart-flows.md#b2c-15-collections):
  - collections_list_returns_metadata_without_products
  - collection_products_enriched_from_b2b
  - unavailable_products_in_unavailable_ids
  - unknown_collection_returns_404
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

COLLECTION_ID = uuid4()
COLLECTION_ID_2 = uuid4()
UNKNOWN_ID = uuid4()

PRODUCT_ID_1 = uuid4()
PRODUCT_ID_2 = uuid4()
PRODUCT_ID_GONE = uuid4()   # deleted in B2B


def _make_collection(cid, title, priority=10, start_date=None):
    c = MagicMock()
    c.id = cid
    c.title = title
    c.description = "Some description"
    c.cover_image_url = "https://cdn.example.com/cover.jpg"
    c.target_url = f"/collections/{cid}"
    c.priority = priority
    c.start_date = start_date
    c.is_active = True
    return c


def _make_b2b_product(product_id, title, price=9999_00, stock=5):
    return {
        "id": str(product_id),
        "title": title,
        "slug": title.lower().replace(" ", "-"),
        "status": "MODERATED",
        "skus": [{"price": price, "active_quantity": stock}],
        "images": [{"id": str(uuid4()), "url": f"https://cdn.example.com/{title}.jpg", "ordering": 0}],
    }


def _mock_b2b_batch(products: list[dict]):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = products
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collections_list_returns_metadata_without_products(ac):
    """GET /api/v1/main/collections returns metadata + collection list — no products inside."""
    col1 = _make_collection(COLLECTION_ID, "Хиты продаж", priority=10)
    col2 = _make_collection(COLLECTION_ID_2, "Новинки", priority=20)

    with patch(
        "app.api.routers.collections.CollectionService.list_active",
        new=AsyncMock(return_value=([col1, col2], 2)),
    ):
        resp = await ac.get("/api/v1/main/collections")

    assert resp.status_code == 200
    body = resp.json()

    # Metadata present
    assert body["metadata"]["total_count"] == 2
    assert body["metadata"]["limit"] == 10
    assert body["metadata"]["offset"] == 0

    # Two collections, sorted by priority
    cols = body["collections"]
    assert len(cols) == 2
    assert cols[0]["title"] == "Хиты продаж"
    assert cols[0]["priority"] == 10
    assert cols[1]["title"] == "Новинки"

    # No products inside collection metadata
    assert "items" not in cols[0]
    assert "product_ids" not in cols[0]


@pytest.mark.asyncio
async def test_collections_list_empty_returns_200(ac):
    """No active collections → 200 with empty list and total_count=0."""
    with patch(
        "app.api.routers.collections.CollectionService.list_active",
        new=AsyncMock(return_value=([], 0)),
    ):
        resp = await ac.get("/api/v1/main/collections")

    assert resp.status_code == 200
    body = resp.json()
    assert body["collections"] == []
    assert body["metadata"]["total_count"] == 0


@pytest.mark.asyncio
async def test_collection_products_enriched_from_b2b(ac):
    """GET /collections/{id}/products enriches product data from B2B."""
    col = _make_collection(COLLECTION_ID, "Хиты продаж")
    product_ids = [PRODUCT_ID_1, PRODUCT_ID_2]
    b2b_products = [
        _make_b2b_product(PRODUCT_ID_1, "iPhone 15", price=12999_00, stock=3),
        _make_b2b_product(PRODUCT_ID_2, "Nike Air Max", price=899_00, stock=10),
    ]

    with patch(
        "app.api.routers.collections.CollectionService.get_by_id",
        new=AsyncMock(return_value=col),
    ), patch(
        "app.api.routers.collections.CollectionService.get_product_ids",
        new=AsyncMock(return_value=(product_ids, 2)),
    ), _mock_b2b_batch(b2b_products):
        resp = await ac.get(f"/api/v1/collections/{COLLECTION_ID}/products")

    assert resp.status_code == 200
    body = resp.json()

    assert body["collection_title"] == "Хиты продаж"
    assert body["total_products"] == 2
    assert len(body["items"]) == 2
    assert body["unavailable_ids"] == []

    item = body["items"][0]
    assert item["id"] == str(PRODUCT_ID_1)
    assert item["title"] == "iPhone 15"
    assert item["price"] == 12999_00
    assert item["in_stock"] is True
    assert len(item["images"]) == 1


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unavailable_products_in_unavailable_ids(ac):
    """Products missing from B2B go to unavailable_ids, not items."""
    col = _make_collection(COLLECTION_ID, "Хиты продаж")
    # Three products requested, but only one returned by B2B
    product_ids = [PRODUCT_ID_1, PRODUCT_ID_GONE, PRODUCT_ID_2]
    b2b_products = [
        _make_b2b_product(PRODUCT_ID_1, "iPhone 15"),
        # PRODUCT_ID_GONE and PRODUCT_ID_2 absent (deleted/blocked in B2B)
    ]

    with patch(
        "app.api.routers.collections.CollectionService.get_by_id",
        new=AsyncMock(return_value=col),
    ), patch(
        "app.api.routers.collections.CollectionService.get_product_ids",
        new=AsyncMock(return_value=(product_ids, 3)),
    ), _mock_b2b_batch(b2b_products):
        resp = await ac.get(f"/api/v1/collections/{COLLECTION_ID}/products")

    assert resp.status_code == 200
    body = resp.json()

    # Only the available product in items
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(PRODUCT_ID_1)

    # The two missing ones in unavailable_ids
    unavailable = {UUID(uid) for uid in body["unavailable_ids"]}
    assert PRODUCT_ID_GONE in unavailable
    assert PRODUCT_ID_2 in unavailable
    assert PRODUCT_ID_1 not in unavailable


@pytest.mark.asyncio
async def test_all_products_unavailable_returns_empty_items(ac):
    """All products gone from B2B → items=[], unavailable_ids has all of them."""
    col = _make_collection(COLLECTION_ID, "Хиты продаж")
    product_ids = [PRODUCT_ID_1, PRODUCT_ID_2]

    with patch(
        "app.api.routers.collections.CollectionService.get_by_id",
        new=AsyncMock(return_value=col),
    ), patch(
        "app.api.routers.collections.CollectionService.get_product_ids",
        new=AsyncMock(return_value=(product_ids, 2)),
    ), _mock_b2b_batch([]):   # B2B returns nothing
        resp = await ac.get(f"/api/v1/collections/{COLLECTION_ID}/products")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert len(body["unavailable_ids"]) == 2


@pytest.mark.asyncio
async def test_unknown_collection_returns_404(ac):
    """Non-existent collection_id → 404 COLLECTION_NOT_FOUND."""
    with patch(
        "app.api.routers.collections.CollectionService.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        resp = await ac.get(f"/api/v1/collections/{UNKNOWN_ID}/products")

    assert resp.status_code == 404
    assert resp.json()["code"] == "COLLECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_empty_collection_returns_200(ac):
    """Collection with no products → 200, items=[], total_products=0."""
    col = _make_collection(COLLECTION_ID, "Пустая подборка")

    with patch(
        "app.api.routers.collections.CollectionService.get_by_id",
        new=AsyncMock(return_value=col),
    ), patch(
        "app.api.routers.collections.CollectionService.get_product_ids",
        new=AsyncMock(return_value=([], 0)),
    ):
        resp = await ac.get(f"/api/v1/collections/{COLLECTION_ID}/products")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total_products"] == 0
    assert body["unavailable_ids"] == []


@pytest.mark.asyncio
async def test_collections_pagination(ac):
    """Pagination params are passed to service and reflected in metadata."""
    with patch(
        "app.api.routers.collections.CollectionService.list_active",
        new=AsyncMock(return_value=([], 42)),
    ) as mock_list:
        resp = await ac.get("/api/v1/main/collections?limit=5&offset=10")

    assert resp.status_code == 200
    body = resp.json()
    assert body["metadata"]["limit"] == 5
    assert body["metadata"]["offset"] == 10
    assert body["metadata"]["total_count"] == 42
    mock_list.assert_called_once()
    _, kwargs = mock_list.call_args
    assert kwargs.get("limit") == 5 or mock_list.call_args.args[1] == 5
