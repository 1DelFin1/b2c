"""Tests for US-CART-03: корзина покупателя.

DoD scenarios (b2c-cart-flows.md#b2c-8-cart):
  - add_sku_increments_quantity_if_already_in_cart
  - get_cart_enriched_with_b2b_data
  - unavailable_sku_shown_with_reason
  - guest_cart_merged_on_login
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.api.deps import get_current_active_auth_buyer
from app.main import app
from app.schemas import CartItemStored

USER_ID = uuid4()
SESSION_ID = "guest-session-abc123"
SKU_ID_1 = uuid4()
SKU_ID_2 = uuid4()
PRODUCT_ID_1 = uuid4()
PRODUCT_ID_2 = uuid4()

_PAYLOAD = {"sub": str(USER_ID), "account_type": "buyer", "email": "buyer@test.com"}
_USER_IDENTITY = (str(USER_ID), True)

# Stored cart items (Redis)
_ITEM_1 = CartItemStored(
    sku_id=SKU_ID_1,
    product_id=PRODUCT_ID_1,
    name="iPhone 15",
    quantity=1,
    unit_price_at_add=12999_00,
)
_ITEM_2 = CartItemStored(
    sku_id=SKU_ID_2,
    product_id=PRODUCT_ID_2,
    name="Nike Air Max",
    quantity=1,
    unit_price_at_add=899_00,
)

# B2B SKU responses
def _sku_resp(sku_id: UUID, product_id: UUID, price: int, stock: int, name: str = "SKU"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "id": str(sku_id),
        "product_id": str(product_id),
        "name": name,
        "price": price,
        "active_quantity": stock,
        "images": [],
        "article": None,
    }
    return resp


def _mock_b2b_sku(sku_id: UUID, product_id: UUID, price: int, stock: int, name: str = "SKU"):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_sku_resp(sku_id, product_id, price, stock, name))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


def _mock_b2b_batch(products: list[dict]):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = products
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


def _b2b_product(product_id: UUID, sku_id: UUID, price: int, stock: int, title: str = "Product", status: str = "MODERATED"):
    return {
        "id": str(product_id),
        "title": title,
        "status": status,
        "skus": [
            {
                "id": str(sku_id),
                "name": "SKU Name",
                "price": price,
                "active_quantity": stock,
                "images": [],
            }
        ],
    }


@pytest.fixture(autouse=True)
def override_auth():
    """Override JWT dep AND _get_identity for all non-merge cart tests."""
    app.dependency_overrides[get_current_active_auth_buyer] = lambda: _PAYLOAD
    yield
    app.dependency_overrides.pop(get_current_active_auth_buyer, None)


@pytest.fixture()
def mock_identity():
    """Patch _get_identity to return authenticated user identity."""
    with patch("app.api.routers.cart._get_identity", return_value=_USER_IDENTITY):
        yield


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_sku_increments_quantity_if_already_in_cart(ac, mock_identity):
    """Adding the same SKU twice increments quantity; second call returns 200."""
    # First: cart already has SKU_ID_1 with qty=2
    existing = [CartItemStored(
        sku_id=SKU_ID_1, product_id=PRODUCT_ID_1,
        name="iPhone 15", quantity=2, unit_price_at_add=12999_00,
    )]
    after_add = [CartItemStored(
        sku_id=SKU_ID_1, product_id=PRODUCT_ID_1,
        name="iPhone 15", quantity=3, unit_price_at_add=12999_00,
    )]

    with _mock_b2b_sku(SKU_ID_1, PRODUCT_ID_1, 12999_00, 10, "iPhone 15"), \
         patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=existing)), \
         patch("app.api.routers.cart.CartService.add_item", new=AsyncMock(return_value=after_add)):
        resp = await ac.post(
            "/api/v1/cart/items",
            json={"sku_id": str(SKU_ID_1), "quantity": 1},
        )

    assert resp.status_code == 200  # existing item → 200
    body = resp.json()
    assert body["item"]["quantity"] == 3
    assert body["item"]["sku_id"] == str(SKU_ID_1)


@pytest.mark.asyncio
async def test_add_new_sku_returns_201(ac, mock_identity):
    """Adding a brand-new SKU returns 201."""
    with _mock_b2b_sku(SKU_ID_1, PRODUCT_ID_1, 12999_00, 5, "iPhone 15"), \
         patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=[])), \
         patch("app.api.routers.cart.CartService.add_item", new=AsyncMock(return_value=[_ITEM_1])):
        resp = await ac.post(
            "/api/v1/cart/items",
            json={"sku_id": str(SKU_ID_1), "quantity": 1},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["item"]["sku_id"] == str(SKU_ID_1)
    assert body["item"]["available"] is True


@pytest.mark.asyncio
async def test_get_cart_enriched_with_b2b_data(ac, mock_identity):
    """GET /cart enriches prices and availability from B2B."""
    stored = [_ITEM_1]
    b2b_products = [_b2b_product(PRODUCT_ID_1, SKU_ID_1, 15000_00, 3, "iPhone 15 Pro")]

    with patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=stored)), \
         _mock_b2b_batch(b2b_products):
        resp = await ac.get("/api/v1/cart", headers={"Authorization": "Bearer fake"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["sku_id"] == str(SKU_ID_1)
    assert item["product_title"] == "iPhone 15 Pro"
    assert item["unit_price"] == 15000_00       # live B2B price, not stored price
    assert item["available"] is True
    assert item["available_stock"] == 3
    assert item["line_total"] == 15000_00 * 1   # qty=1

    summary = body["summary"]
    assert summary["total_amount"] == 15000_00
    assert summary["total_items"] == 1
    assert summary["available_items"] == 1
    assert summary["has_unavailable_items"] is False
    assert summary["checkout_ready"] is True

    assert "checkout_payload" in body
    assert len(body["checkout_payload"]["items"]) == 1


@pytest.mark.asyncio
async def test_get_empty_cart_returns_zeros(ac, mock_identity):
    """GET /cart with no items returns empty response with zero summary."""
    with patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=[])):
        resp = await ac.get("/api/v1/cart")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["summary"]["total_amount"] == 0
    assert body["summary"]["checkout_ready"] is False


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unavailable_sku_shown_with_reason(ac, mock_identity):
    """Out-of-stock SKU appears in cart with available=False and reason=OUT_OF_STOCK."""
    stored = [_ITEM_1]
    # B2B returns product but SKU has zero stock
    b2b_products = [_b2b_product(PRODUCT_ID_1, SKU_ID_1, 12999_00, 0, "iPhone 15")]

    with patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=stored)), \
         _mock_b2b_batch(b2b_products):
        resp = await ac.get("/api/v1/cart")

    assert resp.status_code == 200
    body = resp.json()
    item = body["items"][0]
    assert item["available"] is False
    assert item["unavailable_reason"] == "OUT_OF_STOCK"
    assert item["line_total"] == 0              # unavailable → 0

    summary = body["summary"]
    assert summary["total_amount"] == 0
    assert summary["has_unavailable_items"] is True
    assert summary["available_items"] == 0
    assert summary["checkout_ready"] is False


@pytest.mark.asyncio
async def test_deleted_product_shown_with_delisted_reason(ac, mock_identity):
    """Product missing from B2B (deleted/blocked) → available=False, reason=PRODUCT_DELISTED."""
    stored = [_ITEM_1]
    # B2B returns empty list — product deleted/blocked
    with patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=stored)), \
         _mock_b2b_batch([]):
        resp = await ac.get("/api/v1/cart")

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["available"] is False
    assert item["unavailable_reason"] == "PRODUCT_DELISTED"


@pytest.mark.asyncio
async def test_insufficient_stock_returns_422(ac, mock_identity):
    """Adding more than available stock → 422 INSUFFICIENT_STOCK."""
    with _mock_b2b_sku(SKU_ID_1, PRODUCT_ID_1, 12999_00, 2, "iPhone 15"), \
         patch("app.api.routers.cart.CartService.get_items", new=AsyncMock(return_value=[])):
        resp = await ac.post(
            "/api/v1/cart/items",
            json={"sku_id": str(SKU_ID_1), "quantity": 5},
        )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INSUFFICIENT_STOCK"


@pytest.mark.asyncio
async def test_sku_not_found_returns_404(ac, mock_identity):
    """Adding non-existent SKU → 404 SKU_NOT_FOUND."""
    not_found = MagicMock()
    not_found.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=not_found)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        resp = await ac.post(
            "/api/v1/cart/items",
            json={"sku_id": str(SKU_ID_1), "quantity": 1},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SKU_NOT_FOUND"


@pytest.mark.asyncio
async def test_guest_cart_merged_on_login(ac):
    """POST /cart/merge: guest qty=3, user qty=1 → merged qty=3 (MAX strategy)."""
    guest_items = [CartItemStored(
        sku_id=SKU_ID_1, product_id=PRODUCT_ID_1,
        name="iPhone 15", quantity=3, unit_price_at_add=12999_00,
    )]
    user_items = [CartItemStored(
        sku_id=SKU_ID_1, product_id=PRODUCT_ID_1,
        name="iPhone 15", quantity=1, unit_price_at_add=12999_00,
    )]
    saved: list = []

    async def fake_get_items(identity):
        if identity == SESSION_ID:
            return guest_items
        return user_items

    async def fake_save(identity, items):
        saved.extend(items)

    b2b_products = [_b2b_product(PRODUCT_ID_1, SKU_ID_1, 12999_00, 5)]

    with patch("app.api.routers.cart.CartService.get_items", side_effect=fake_get_items), \
         patch("app.api.routers.cart.CartService._save_items", side_effect=fake_save), \
         patch("app.api.routers.cart.CartService.clear", new=AsyncMock()), \
         _mock_b2b_batch(b2b_products):
        resp = await ac.post(
            "/api/v1/cart/merge",
            headers={
                "X-Session-Id": SESSION_ID,
                "Authorization": "Bearer fake-jwt",
            },
        )

    assert resp.status_code == 200
    assert len(saved) == 1
    # MAX(3, 1) = 3
    assert saved[0].quantity == 3


@pytest.mark.asyncio
async def test_guest_cart_merge_unique_items_transferred(ac):
    """POST /cart/merge: unique guest item is transferred to user cart."""
    guest_items = [CartItemStored(
        sku_id=SKU_ID_2, product_id=PRODUCT_ID_2,
        name="Nike Air Max", quantity=2, unit_price_at_add=899_00,
    )]
    # User has a different item
    user_items = [CartItemStored(
        sku_id=SKU_ID_1, product_id=PRODUCT_ID_1,
        name="iPhone 15", quantity=1, unit_price_at_add=12999_00,
    )]
    saved: list = []

    async def fake_get_items(identity):
        if identity == SESSION_ID:
            return guest_items
        return user_items

    async def fake_save(identity, items):
        saved.extend(items)

    b2b_products = [
        _b2b_product(PRODUCT_ID_1, SKU_ID_1, 12999_00, 5),
        _b2b_product(PRODUCT_ID_2, SKU_ID_2, 899_00, 10),
    ]

    with patch("app.api.routers.cart.CartService.get_items", side_effect=fake_get_items), \
         patch("app.api.routers.cart.CartService._save_items", side_effect=fake_save), \
         patch("app.api.routers.cart.CartService.clear", new=AsyncMock()), \
         _mock_b2b_batch(b2b_products):
        resp = await ac.post(
            "/api/v1/cart/merge",
            headers={
                "X-Session-Id": SESSION_ID,
                "Authorization": "Bearer fake-jwt",
            },
        )

    assert resp.status_code == 200
    assert len(saved) == 2   # both items present after merge


@pytest.mark.asyncio
async def test_missing_identity_returns_400(ac):
    """GET /cart without auth and without X-Session-Id → 400."""
    # Override to remove auth
    app.dependency_overrides.pop(get_current_active_auth_buyer, None)
    resp = await ac.get("/api/v1/cart")
    assert resp.status_code == 400
    # Restore for other tests
    app.dependency_overrides[get_current_active_auth_buyer] = lambda: _PAYLOAD
