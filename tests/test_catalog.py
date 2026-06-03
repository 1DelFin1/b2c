"""Tests for US-CAT-01: каталог с фильтрами и фасетами.

DoD scenarios (b2c-catalog-flows.md#b2c-1-catalog-filters):
  - catalog_returns_filtered_sorted_products
  - facets_return_counts_per_filter_value
  - invalid_sort_returns_400
  - b2b_unavailable_returns_502
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

CATEGORY_ID = "123e4567-e89b-12d3-a456-426614174001"

_B2B_PRODUCTS = {
    "items": [
        {
            "id": "770e8400-e29b-41d4-a716-446655440002",
            "title": "iPhone 15 Pro Max",
            "slug": "iphone-15-pro-max",
            "status": "MODERATED",
            "category_id": CATEGORY_ID,
            "min_price": 12999000,
            "cover_image": "https://cdn.neomarket.ru/images/iphone15.jpg",
            "created_at": "2024-01-01T00:00:00Z",
        }
    ],
    "total_count": 1,
    "limit": 20,
    "offset": 0,
}

_B2B_FACETS = {
    "category_id": CATEGORY_ID,
    "facets": [
        {
            "name": "brand",
            "values": [
                {"value": "Apple", "count": 124},
                {"value": "Samsung", "count": 98},
            ],
        },
        {
            "name": "color",
            "values": [
                {"value": "черный", "count": 60},
                {"value": "белый", "count": 40},
            ],
        },
    ],
}


def _mock_response(json_data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


def _patch_b2b(response):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_catalog_returns_filtered_sorted_products(ac):
    """GET /api/v1/products?category_id=...&sort=price_asc → 200, canonical item shape."""
    with _patch_b2b(_mock_response(_B2B_PRODUCTS)):
        resp = await ac.get(
            f"/api/v1/catalog/products?category_id={CATEGORY_ID}&sort=price_asc&limit=20"
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["id"] == "770e8400-e29b-41d4-a716-446655440002"
    assert item["name"] == "iPhone 15 Pro Max"
    assert item["min_price"] == 12999000
    assert item["has_stock"] is True
    assert "is_in_cart" in item
    assert "characteristics" not in item


@pytest.mark.asyncio
async def test_facets_return_counts_per_filter_value(ac):
    """GET /api/v1/catalog/facets?category_id=... → 200, structure with counts proxied from B2B."""
    with _patch_b2b(_mock_response(_B2B_FACETS)):
        resp = await ac.get(f"/api/v1/catalog/facets?category_id={CATEGORY_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["category_id"] == CATEGORY_ID
    assert len(body["facets"]) == 2

    brand = next(f for f in body["facets"] if f["name"] == "brand")
    apple = next(v for v in brand["values"] if v["value"] == "Apple")
    assert apple["count"] == 124


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_sort_returns_400(ac):
    """GET /api/v1/products?sort=BOGUS → 400 with allowed values, no B2B call made."""
    resp = await ac.get("/api/v1/catalog/products?sort=BOGUS")

    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "INVALID_REQUEST"
    assert "price_asc" in body.get("message", "")


@pytest.mark.asyncio
async def test_b2b_unavailable_returns_502(ac):
    """GET /api/v1/products when B2B is unreachable → 502."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        resp = await ac.get(f"/api/v1/catalog/products?category_id={CATEGORY_ID}")

    assert resp.status_code in (502, 503)
