"""Tests for US-CAT-02: текстовый поиск товаров.

DoD scenarios (b2c-catalog-flows.md#b2c-2-search):
  - search_returns_matching_products
  - short_query_returns_400
  - special_chars_do_not_break_query
  - empty_results_returns_200
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_B2B_SEARCH_RESULTS = {
    "items": [
        {
            "id": "770e8400-e29b-41d4-a716-446655440010",
            "title": "Беспроводные наушники Sony WH-1000XM5",
            "slug": "sony-wh-1000xm5",
            "status": "MODERATED",
            "category_id": "123e4567-e89b-12d3-a456-426614174001",
            "min_price": 3499000,
            "cover_image": "https://cdn.neomarket.ru/images/sony-wh.jpg",
            "created_at": "2024-03-01T00:00:00Z",
        },
        {
            "id": "770e8400-e29b-41d4-a716-446655440011",
            "title": "Беспроводные наушники Bose QC45",
            "slug": "bose-qc45",
            "status": "MODERATED",
            "category_id": "123e4567-e89b-12d3-a456-426614174001",
            "min_price": 2999000,
            "cover_image": "https://cdn.neomarket.ru/images/bose-qc45.jpg",
            "created_at": "2024-02-01T00:00:00Z",
        },
    ],
    "total_count": 2,
    "limit": 20,
    "offset": 0,
}

_B2B_EMPTY = {"items": [], "total_count": 0, "limit": 20, "offset": 0}


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
async def test_search_returns_matching_products(ac):
    """GET /api/v1/catalog/products?q=наушники → 200, items matching title/description."""
    with _patch_b2b(_mock_response(_B2B_SEARCH_RESULTS)):
        resp = await ac.get("/api/v1/catalog/products?q=наушники")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 2
    assert len(body["items"]) == 2

    names = {item["name"] for item in body["items"]}
    assert any("наушники" in n.lower() for n in names)

    item = body["items"][0]
    assert "id" in item
    assert "name" in item
    assert "min_price" in item
    assert "has_stock" in item
    assert "is_in_cart" in item


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_short_query_returns_400(ac):
    """GET /api/v1/catalog/products?q=ab → 400, search query shorter than 3 chars."""
    resp = await ac.get("/api/v1/catalog/products?q=ab")

    assert resp.status_code == 400
    body = resp.json()
    assert body.get("code") == "INVALID_REQUEST"
    assert "3" in body.get("message", "")


@pytest.mark.asyncio
async def test_special_chars_do_not_break_query(ac):
    """GET /api/v1/catalog/products?q=iPhone%2515 — special chars proxied safely."""
    with _patch_b2b(_mock_response(_B2B_SEARCH_RESULTS)):
        resp = await ac.get("/api/v1/catalog/products?q=iPhone%2515")

    assert resp.status_code == 200

    with _patch_b2b(_mock_response(_B2B_EMPTY)):
        resp2 = await ac.get("/api/v1/catalog/products?q=кофе'машина")
    assert resp2.status_code == 200

    with _patch_b2b(_mock_response(_B2B_EMPTY)):
        resp3 = await ac.get("/api/v1/catalog/products?q=super_deal")
    assert resp3.status_code == 200


@pytest.mark.asyncio
async def test_empty_results_returns_200(ac):
    """GET /api/v1/catalog/products?q=несуществующий → 200 with empty items list."""
    with _patch_b2b(_mock_response(_B2B_EMPTY)):
        resp = await ac.get("/api/v1/catalog/products?q=несуществующийтовар")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total_count"] == 0
