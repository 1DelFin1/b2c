"""Tests for US-CART-01: избранное покупателя.

DoD scenarios (b2c-cart-flows.md#b2c-6-favorites):
  - add_to_favorites_returns_204
  - repeat_add_returns_204_not_duplicate
  - blocked_product_excluded_from_list
  - user_id_from_query_is_ignored
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.api.deps import get_current_active_auth_buyer
from app.main import app

USER_ID = uuid4()
OTHER_USER_ID = uuid4()
PRODUCT_ID = uuid4()
PRODUCT_ID_2 = uuid4()

_PAYLOAD = {"sub": str(USER_ID), "account_type": "buyer", "email": "buyer@test.com"}
_ADDED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_B2B_PRODUCT = {
    "id": str(PRODUCT_ID),
    "title": "iPhone 15",
    "slug": "iphone-15",
    "status": "MODERATED",
    "skus": [{"price": 9999000, "active_quantity": 5}],
    "images": [{"id": str(uuid4()), "url": "https://cdn.example.com/img.jpg", "ordering": 0}],
}


def _mock_b2b_batch(products: list[dict]):
    resp = MagicMock()
    resp.json.return_value = products
    resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


@pytest.fixture(autouse=True)
def override_auth():
    """Override JWT auth for all tests in this module."""
    app.dependency_overrides[get_current_active_auth_buyer] = lambda: _PAYLOAD
    yield
    app.dependency_overrides.pop(get_current_active_auth_buyer, None)


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_to_favorites_returns_204(ac):
    """PUT /api/v1/favorites/{id} → 204 No Content (idempotent)."""
    with patch(
        "app.api.routers.favorites.FavoritesService.add",
        new=AsyncMock(return_value=(True, _ADDED_AT)),
    ):
        resp = await ac.put(f"/api/v1/favorites/{PRODUCT_ID}")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_repeat_add_returns_204_not_duplicate(ac):
    """PUT /api/v1/favorites/{id} second time → 204 (idempotent, service called once)."""
    add_mock = AsyncMock(return_value=(False, _ADDED_AT))
    with patch("app.api.routers.favorites.FavoritesService.add", new=add_mock):
        resp = await ac.put(f"/api/v1/favorites/{PRODUCT_ID}")

    assert resp.status_code == 204
    add_mock.assert_called_once()


@pytest.mark.asyncio
async def test_get_favorites_enriched_from_b2b(ac):
    """GET /api/v1/favorites → 200, items enriched from B2B batch."""
    with patch(
        "app.api.routers.favorites.FavoritesService.get",
        new=AsyncMock(return_value=([PRODUCT_ID], 1)),
    ), _mock_b2b_batch([_B2B_PRODUCT]):
        resp = await ac.get("/api/v1/favorites")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(PRODUCT_ID)
    assert body["items"][0]["name"] == "iPhone 15"
    assert body["items"][0]["has_stock"] is True


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blocked_product_excluded_from_list(ac):
    """GET /api/v1/favorites — blocked product absent from B2B response is excluded."""
    with patch(
        "app.api.routers.favorites.FavoritesService.get",
        new=AsyncMock(return_value=([PRODUCT_ID, PRODUCT_ID_2], 2)),
    ), _mock_b2b_batch([_B2B_PRODUCT]):  # only PRODUCT_ID returned by B2B
        resp = await ac.get("/api/v1/favorites")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(PRODUCT_ID)
    item_ids = {item["id"] for item in body["items"]}
    assert str(PRODUCT_ID_2) not in item_ids


@pytest.mark.asyncio
async def test_user_id_from_query_is_ignored(ac):
    """Passing user_id in query must not override the JWT user — IDOR prevention."""
    add_mock = AsyncMock(return_value=(True, _ADDED_AT))
    with patch("app.api.routers.favorites.FavoritesService.add", new=add_mock):
        resp = await ac.put(
            f"/api/v1/favorites/{PRODUCT_ID}?user_id={OTHER_USER_ID}"
        )

    assert resp.status_code == 204
    call_args = add_mock.call_args
    actual_user_id = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("user_id")
    assert actual_user_id == USER_ID, (
        f"Expected JWT user_id {USER_ID}, got {actual_user_id} — IDOR vulnerability!"
    )
