"""Tests for US-CART-02: подписки на изменения товара.

DoD scenarios (b2c-cart-flows.md#b2c-7-subscriptions):
  - subscribe_returns_201_with_notify_on
  - duplicate_subscription_returns_409
  - invalid_notify_on_returns_400
  - subscribe_to_unknown_product_returns_404
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_current_active_auth_buyer
from app.main import app

USER_ID = uuid4()
OTHER_USER_ID = uuid4()
PRODUCT_ID = uuid4()

_PAYLOAD = {"sub": str(USER_ID), "account_type": "buyer", "email": "buyer@test.com"}
_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_SUBSCRIPTION = MagicMock()
_SUBSCRIPTION.id = uuid4()
_SUBSCRIPTION.product_id = PRODUCT_ID
_SUBSCRIPTION.notify_on = ["IN_STOCK", "PRICE_DOWN"]
_SUBSCRIPTION.created_at = _CREATED_AT


def _mock_b2b_product(status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_active_auth_buyer] = lambda: _PAYLOAD
    yield
    app.dependency_overrides.pop(get_current_active_auth_buyer, None)


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_returns_201_with_notify_on(ac):
    """POST /api/v1/favorites/{id}/subscribe → 201 with notify_on in response."""
    with _mock_b2b_product(200), patch(
        "app.api.routers.favorites.SubscriptionService.subscribe",
        new=AsyncMock(return_value=_SUBSCRIPTION),
    ):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe",
            json={"notify_on": ["IN_STOCK", "PRICE_DOWN"]},
        )

    assert resp.status_code == 201
    body = resp.json()
    assert body["product_id"] == str(PRODUCT_ID)
    assert set(body["notify_on"]) == {"IN_STOCK", "PRICE_DOWN"}
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_unsubscribe_returns_204(ac):
    """DELETE /api/v1/favorites/{id}/subscribe → 204."""
    with patch(
        "app.api.routers.favorites.SubscriptionService.unsubscribe",
        new=AsyncMock(return_value=None),
    ):
        resp = await ac.delete(f"/api/v1/favorites/{PRODUCT_ID}/subscribe")

    assert resp.status_code == 204


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_subscription_returns_409(ac):
    """POST subscribe second time → 409 SUBSCRIPTION_ALREADY_EXISTS."""
    with _mock_b2b_product(200), patch(
        "app.api.routers.favorites.SubscriptionService.subscribe",
        new=AsyncMock(side_effect=IntegrityError("duplicate", {}, None)),
    ):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe",
            json={"notify_on": ["IN_STOCK"]},
        )

    assert resp.status_code == 409
    assert resp.json()["code"] == "SUBSCRIPTION_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_invalid_notify_on_returns_400(ac):
    """POST subscribe with empty notify_on → 422 (Pydantic minItems=1)."""
    with _mock_b2b_product(200):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe",
            json={"notify_on": []},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_notify_on_bad_value_returns_422(ac):
    """POST subscribe with invalid enum value in notify_on → 422."""
    with _mock_b2b_product(200):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe",
            json={"notify_on": ["INVALID_EVENT"]},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_subscribe_to_unknown_product_returns_404(ac):
    """POST subscribe to non-existent product → 404 PRODUCT_NOT_FOUND."""
    with _mock_b2b_product(404):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe",
            json={"notify_on": ["IN_STOCK"]},
        )

    assert resp.status_code == 404
    assert resp.json()["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_user_id_from_jwt_only(ac):
    """user_id must come from JWT, not query — IDOR prevention."""
    subscribe_mock = AsyncMock(return_value=_SUBSCRIPTION)
    with _mock_b2b_product(200), patch(
        "app.api.routers.favorites.SubscriptionService.subscribe",
        new=subscribe_mock,
    ):
        resp = await ac.post(
            f"/api/v1/favorites/{PRODUCT_ID}/subscribe?user_id={OTHER_USER_ID}",
            json={"notify_on": ["IN_STOCK"]},
        )

    assert resp.status_code == 201
    call_args = subscribe_mock.call_args
    actual_user_id = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("user_id")
    assert actual_user_id == USER_ID, (
        f"Expected JWT user_id {USER_ID}, got {actual_user_id} — IDOR vulnerability!"
    )
