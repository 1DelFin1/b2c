"""Tests for US-CAT-03: карточка товара для покупателя.

DoD scenarios (b2c-catalog-flows.md#b2c-3-product-card):
  - product_card_returns_full_data_with_skus
  - cost_price_absent_in_response
  - blocked_product_returns_404
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

PRODUCT_ID = "770e8400-e29b-41d4-a716-446655440002"
SKU_ID_1 = "660e8400-e29b-41d4-a716-446655440001"
SKU_ID_2 = "660e8400-e29b-41d4-a716-446655440002"

# Full B2B response — includes seller-internal fields that B2C must strip
_B2B_PRODUCT = {
    "id": PRODUCT_ID,
    "seller_id": str(uuid4()),
    "category_id": "123e4567-e89b-12d3-a456-426614174001",
    "slug": "iphone-15-pro-max",
    "title": "iPhone 15 Pro Max",
    "description": "Флагманский смартфон Apple 2024 года с чипом A17 Pro",
    "status": "MODERATED",
    "images": [
        {"id": str(uuid4()), "url": "https://cdn.neomarket.ru/images/iphone15-front.jpg", "ordering": 0},
        {"id": str(uuid4()), "url": "https://cdn.neomarket.ru/images/iphone15-back.jpg", "ordering": 1},
    ],
    "characteristics": [
        {"name": "Бренд", "value": "Apple"},
        {"name": "Страна-производитель", "value": "Китай"},
    ],
    "skus": [
        {
            "id": SKU_ID_1,
            "product_id": PRODUCT_ID,
            "name": "256GB Black",
            "price": 12999000,
            "discount": 0,
            "cost_price": 8500000,        # must be absent in B2C response
            "stock_quantity": 10,
            "reserved_quantity": 0,       # must be absent in B2C response
            "active_quantity": 10,
            "article": "IPH-BLK-256",
            "images": [
                {"id": str(uuid4()), "url": "/s3/iphone15-black-256.jpg", "ordering": 0},
            ],
            "characteristics": [
                {"name": "Цвет", "value": "Чёрный"},
                {"name": "Объём памяти", "value": "256 ГБ"},
            ],
        },
        {
            "id": SKU_ID_2,
            "product_id": PRODUCT_ID,
            "name": "256GB White",
            "price": 12999000,
            "discount": 500000,
            "cost_price": 8500000,        # must be absent
            "stock_quantity": 3,
            "reserved_quantity": 0,       # must be absent
            "active_quantity": 3,
            "article": "IPH-WHT-256",
            "images": [
                {"id": str(uuid4()), "url": "/s3/iphone15-white-256.jpg", "ordering": 0},
            ],
            "characteristics": [
                {"name": "Цвет", "value": "Белый"},
                {"name": "Объём памяти", "value": "256 ГБ"},
            ],
        },
    ],
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
}

_B2B_NOT_FOUND = {"code": "NOT_FOUND", "message": "Product not found"}


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
async def test_product_card_returns_full_data_with_skus(ac):
    """GET /api/v1/catalog/products/{id} → 200, full card: images, description, SKUs."""
    with _patch_b2b(_mock_response(_B2B_PRODUCT)):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}")

    assert resp.status_code == 200
    body = resp.json()

    # Top-level product fields (CatalogProductDetail)
    assert body["id"] == PRODUCT_ID
    assert body["slug"] == "iphone-15-pro-max"
    assert body["name"] == "iPhone 15 Pro Max"
    assert body["description"]
    assert body["has_stock"] is True

    # Images
    assert len(body["images"]) == 2
    assert "url" in body["images"][0]
    assert "ordering" in body["images"][0]

    # Attributes (converted from characteristics array → dict)
    assert isinstance(body["attributes"], dict)
    assert len(body["attributes"]) == 2
    assert body["attributes"]["Бренд"] == "Apple"

    # SKUs
    assert len(body["skus"]) == 2
    sku = body["skus"][0]
    assert sku["id"] == SKU_ID_1
    assert sku["name"] == "256GB Black"
    assert sku["price"] == 12999000
    assert sku["old_price"] is None          # discount=0 → no old price
    assert sku["images"][0]["url"] == "/s3/iphone15-black-256.jpg"
    assert sku["available_quantity"] == 10
    assert isinstance(sku["attributes"], dict)
    assert len(sku["attributes"]) == 2

    # SKU with discount: old_price = price + discount
    sku2 = body["skus"][1]
    assert sku2["old_price"] == 12999000 + 500000


# ── Security: forbidden fields must not leak ──────────────────────────────────

@pytest.mark.asyncio
async def test_cost_price_absent_in_response(ac):
    """cost_price and reserved_quantity must not appear in any SKU in the B2C response."""
    with _patch_b2b(_mock_response(_B2B_PRODUCT)):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}")

    assert resp.status_code == 200
    body = resp.json()

    for sku in body["skus"]:
        assert "cost_price" not in sku, "cost_price must not be exposed to buyers"
        assert "reserved_quantity" not in sku, "reserved_quantity must not be exposed to buyers"
        assert "stock_quantity" not in sku, "internal stock_quantity must not be exposed to buyers"


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blocked_product_returns_404(ac):
    """GET /api/v1/catalog/products/{id} for a blocked/deleted product → 404."""
    with _patch_b2b(_mock_response(_B2B_NOT_FOUND, status_code=404)):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}")

    assert resp.status_code == 404
    body = resp.json()
    assert body.get("code") == "NOT_FOUND" or body.get("message")


@pytest.mark.asyncio
async def test_sku_without_stock_is_shown_as_unavailable(ac):
    """SKU with active_quantity=0 is present with available_quantity=0 (not hidden)."""
    product_out_of_stock = {
        **_B2B_PRODUCT,
        "skus": [
            {
                **_B2B_PRODUCT["skus"][0],
                "active_quantity": 0,
                "stock_quantity": 0,
                "reserved_quantity": 0,
            }
        ],
    }
    with _patch_b2b(_mock_response(product_out_of_stock)):
        resp = await ac.get(f"/api/v1/catalog/products/{PRODUCT_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["skus"]) == 1
    assert body["skus"][0]["available_quantity"] == 0
