"""Tests for US-CAT-04: блок похожих товаров.

DoD scenarios (b2c-catalog-flows.md#b2c-4-similar-products):
  - similar_returns_up_to_8_from_same_category
  - empty_category_returns_200_empty_list
  - unknown_product_returns_404
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

PRODUCT_ID = "770e8400-e29b-41d4-a716-446655440002"
CATEGORY_ID = "123e4567-e89b-12d3-a456-426614174001"


def _make_b2b_short(n: int) -> list[dict]:
    return [
        {
            "id": str(uuid4()),
            "title": f"Похожий товар {i}",
            "slug": f"similar-product-{i}",
            "status": "MODERATED",
            "category_id": CATEGORY_ID,
            "min_price": 1000000 + i * 100000,
            "cover_image": f"https://cdn.neomarket.ru/images/similar-{i}.jpg",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(n)
    ]


def _mock_response(json_data, status_code: int = 200):
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
async def test_similar_returns_up_to_8_from_same_category(ac):
    """GET /api/v1/catalog/products/{id}/similar → 200, flat array up to limit items."""
    b2b_items = _make_b2b_short(8)
    with _patch_b2b(_mock_response(b2b_items)):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}/similar?limit=8")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) <= 8

    item = body[0]
    assert "id" in item
    assert "name" in item
    assert "min_price" in item
    assert "has_stock" in item

    # Current product must not appear in results
    item_ids = {i["id"] for i in body}
    assert PRODUCT_ID not in item_ids


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_category_returns_200_empty_list(ac):
    """GET /api/v1/catalog/products/{id}/similar when no similar products → 200 empty array."""
    with _patch_b2b(_mock_response([])):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}/similar")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_unknown_product_returns_404(ac):
    """GET /api/v1/catalog/products/{unknown_id}/similar → 404 from B2B proxied as-is."""
    not_found = {"code": "NOT_FOUND", "message": "Product not found"}
    with _patch_b2b(_mock_response(not_found, status_code=404)):
        resp = await ac.get(f"/api/v1/catalog/products/{uuid4()}/similar")

    assert resp.status_code == 404
