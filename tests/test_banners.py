"""Tests for US-CART-04: баннеры на главной.

DoD scenarios (b2c-cart-flows.md#b2c-14-banners):
  - active_banners_returned_sorted_by_priority
  - no_active_banners_returns_200_empty
  - click_on_unknown_banner_returns_400
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

BANNER_ID_1 = uuid4()
BANNER_ID_2 = uuid4()
BANNER_ID_3 = uuid4()
UNKNOWN_BANNER_ID = uuid4()


def _make_banner(banner_id, title, priority, is_active=True, start_at=None, end_at=None):
    b = MagicMock()
    b.id = banner_id
    b.title = title
    b.image_url = f"/cdn/banners/{title.lower().replace(' ', '-')}.jpg"
    b.link = "/catalog"
    b.priority = priority
    b.is_active = is_active
    b.start_at = start_at
    b.end_at = end_at
    return b


_BANNER_HIGH = _make_banner(BANNER_ID_1, "Sale Electronics", priority=10)
_BANNER_MID = _make_banner(BANNER_ID_2, "New Arrivals", priority=20)
_BANNER_LOW = _make_banner(BANNER_ID_3, "Promo Summer", priority=30)

_NOW = datetime.now(timezone.utc)
_TIMESTAMP = _NOW.isoformat()


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_banners_returned_sorted_by_priority(ac):
    """GET /api/v1/home/banners returns active banners sorted by priority asc."""
    # Service returns already-sorted list (DB ORDER BY priority ASC)
    sorted_banners = [_BANNER_HIGH, _BANNER_MID, _BANNER_LOW]

    with patch(
        "app.api.routers.banners.BannerService.get_active",
        new=AsyncMock(return_value=sorted_banners),
    ):
        resp = await ac.get("/api/v1/home/banners")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 3
    items = body["items"]
    assert len(items) == 3
    # Priority ascending: 10 < 20 < 30
    assert items[0]["priority"] == 10
    assert items[1]["priority"] == 20
    assert items[2]["priority"] == 30
    assert items[0]["id"] == str(BANNER_ID_1)
    assert items[0]["title"] == "Sale Electronics"
    assert "image_url" in items[0]
    assert "link" in items[0]


@pytest.mark.asyncio
async def test_banners_no_auth_required(ac):
    """GET /api/v1/home/banners works without any Authorization header."""
    with patch(
        "app.api.routers.banners.BannerService.get_active",
        new=AsyncMock(return_value=[_BANNER_HIGH]),
    ):
        # Deliberately no Authorization header
        resp = await ac.get("/api/v1/home/banners")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_no_active_banners_returns_200_empty(ac):
    """No active banners → 200 with empty items list and total_count=0."""
    with patch(
        "app.api.routers.banners.BannerService.get_active",
        new=AsyncMock(return_value=[]),
    ):
        resp = await ac.get("/api/v1/home/banners")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total_count"] == 0


@pytest.mark.asyncio
async def test_banner_event_click_accepted(ac):
    """POST /api/v1/banner-events with a valid click → 204."""
    with patch(
        "app.api.routers.banners.BannerService.exists",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.api.routers.banners.BannerService.record_events",
        new=AsyncMock(return_value=None),
    ):
        resp = await ac.post(
            "/api/v1/banner-events",
            json={
                "events": [
                    {"banner_id": str(BANNER_ID_1), "event": "click", "timestamp": _TIMESTAMP}
                ]
            },
        )

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_banner_event_batch_impressions(ac):
    """POST /api/v1/banner-events with multiple impressions → 204."""
    with patch(
        "app.api.routers.banners.BannerService.exists",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.api.routers.banners.BannerService.record_events",
        new=AsyncMock(return_value=None),
    ):
        resp = await ac.post(
            "/api/v1/banner-events",
            json={
                "events": [
                    {"banner_id": str(BANNER_ID_1), "event": "impression", "timestamp": _TIMESTAMP},
                    {"banner_id": str(BANNER_ID_2), "event": "impression", "timestamp": _TIMESTAMP},
                ]
            },
        )

    assert resp.status_code == 204


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_click_on_unknown_banner_returns_400(ac):
    """POST /api/v1/banner-events with non-existent banner_id → 400 BANNER_NOT_FOUND."""
    with patch(
        "app.api.routers.banners.BannerService.exists",
        new=AsyncMock(return_value=False),
    ):
        resp = await ac.post(
            "/api/v1/banner-events",
            json={
                "events": [
                    {"banner_id": str(UNKNOWN_BANNER_ID), "event": "click", "timestamp": _TIMESTAMP}
                ]
            },
        )

    assert resp.status_code == 400
    assert resp.json()["code"] == "BANNER_NOT_FOUND"


@pytest.mark.asyncio
async def test_empty_events_array_returns_422(ac):
    """POST /api/v1/banner-events with empty events array → 422 (Pydantic minItems=1)."""
    resp = await ac.post(
        "/api/v1/banner-events",
        json={"events": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_event_type_returns_422(ac):
    """POST /api/v1/banner-events with invalid event type → 422."""
    resp = await ac.post(
        "/api/v1/banner-events",
        json={
            "events": [
                {"banner_id": str(BANNER_ID_1), "event": "pageview", "timestamp": _TIMESTAMP}
            ]
        },
    )
    assert resp.status_code == 422
