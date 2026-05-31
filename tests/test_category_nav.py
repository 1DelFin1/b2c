"""Tests for US-CAT-05: навигация по категориям.

DoD scenarios (b2c-catalog-flows.md#b2c-5-category-nav):
  - category_tree_returns_nested_structure
  - breadcrumbs_return_path_from_root
  - ambiguous_params_returns_400
  - orphan_node_returns_422
  - unknown_category_returns_404
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

CAT_ROOT_ID = "123e4567-e89b-12d3-a456-426614174002"
CAT_CHILD_ID = "123e4567-e89b-12d3-a456-426614174003"
CAT_GRANDCHILD_ID = "123e4567-e89b-12d3-a456-426614174004"

# B2B returns flat tree (no parent_id)
_B2B_TREE = [
    {
        "id": CAT_ROOT_ID,
        "name": "Электроника",
        "children": [
            {
                "id": CAT_CHILD_ID,
                "name": "Смартфоны",
                "children": [
                    {
                        "id": CAT_GRANDCHILD_ID,
                        "name": "Android",
                        "children": [],
                    }
                ],
            }
        ],
    },
    {
        "id": "123e4567-e89b-12d3-a456-426614174010",
        "name": "Одежда",
        "children": [],
    },
]

# B2B breadcrumbs — list from root to target, includes parent_id
_B2B_BREADCRUMBS = [
    {
        "id": CAT_ROOT_ID,
        "name": "Электроника",
        "parent_id": None,
        "level": 0,
        "path": "электроника",
        "is_active": True,
        "created_at": "2024-01-01T00:00:00Z",
    },
    {
        "id": CAT_CHILD_ID,
        "name": "Смартфоны",
        "parent_id": CAT_ROOT_ID,
        "level": 1,
        "path": "электроника/смартфоны",
        "is_active": True,
        "created_at": "2024-01-01T00:00:00Z",
    },
]

# Orphan: first crumb has non-null parent_id but parent doesn't exist
_B2B_BREADCRUMBS_ORPHAN = [
    {
        "id": CAT_CHILD_ID,
        "name": "Смартфоны",
        "parent_id": str(uuid4()),   # parent exists in DB record but not in chain
        "level": 1,
        "path": "смартфоны",
        "is_active": True,
        "created_at": "2024-01-01T00:00:00Z",
    },
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


def _patch_b2b_seq(*responses):
    """Patch B2B for sequential calls (product_id breadcrumb resolution)."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=list(responses))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=cm)


# ── Happy-path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_category_tree_returns_nested_structure(ac):
    """GET /api/v1/categories → 200, nested tree with parent_id injected at each level."""
    with _patch_b2b(_mock_response(_B2B_TREE)):
        resp = await ac.get("/api/v1/categories")

    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    items = body["items"]
    assert len(items) == 2

    root = items[0]
    assert root["id"] == CAT_ROOT_ID
    assert root["name"] == "Электроника"
    assert root["parent_id"] is None         # root has no parent
    assert len(root["children"]) == 1

    child = root["children"][0]
    assert child["id"] == CAT_CHILD_ID
    assert child["parent_id"] == CAT_ROOT_ID  # child's parent_id injected

    grandchild = child["children"][0]
    assert grandchild["parent_id"] == CAT_CHILD_ID


@pytest.mark.asyncio
async def test_breadcrumbs_return_path_from_root(ac):
    """GET /api/v1/breadcrumbs?category_id=... → 200, chain from root to target."""
    with _patch_b2b(_mock_response(_B2B_BREADCRUMBS)):
        resp = await ac.get(f"/api/v1/breadcrumbs?category_id={CAT_CHILD_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body

    crumbs = body["data"]
    assert len(crumbs) == 2
    assert crumbs[0]["id"] == CAT_ROOT_ID
    assert crumbs[0]["is_current"] is False
    assert crumbs[0]["level"] == 0
    assert crumbs[1]["id"] == CAT_CHILD_ID
    assert crumbs[1]["is_current"] is True
    assert crumbs[1]["level"] == 1
    assert "slug" in crumbs[0]
    assert "url" in crumbs[0]

    assert body["meta"]["resolved_via"] == "category_id"
    assert body["meta"]["category_id"] == CAT_CHILD_ID


# ── Unhappy-path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ambiguous_params_returns_400(ac):
    """GET /api/v1/breadcrumbs?category_id=...&product_id=... → 400."""
    resp = await ac.get(
        f"/api/v1/breadcrumbs?category_id={CAT_CHILD_ID}&product_id={uuid4()}"
    )
    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail", body)
    assert "ambiguous" in str(detail).lower() or "one of" in str(detail).lower()


@pytest.mark.asyncio
async def test_missing_params_returns_400(ac):
    """GET /api/v1/breadcrumbs with no params → 400."""
    resp = await ac.get("/api/v1/breadcrumbs")
    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail", body)
    assert "missing" in str(detail).lower() or "must be provided" in str(detail).lower()


@pytest.mark.asyncio
async def test_orphan_node_returns_422(ac):
    """GET /api/v1/breadcrumbs for a category with broken hierarchy → 422."""
    with _patch_b2b(_mock_response(_B2B_BREADCRUMBS_ORPHAN)):
        resp = await ac.get(f"/api/v1/breadcrumbs?category_id={CAT_CHILD_ID}")

    assert resp.status_code == 422
    body = resp.json()
    detail = body.get("detail", body)
    assert "orphan" in str(detail).lower() or "broken" in str(detail).lower()


@pytest.mark.asyncio
async def test_unknown_category_returns_404(ac):
    """GET /api/v1/breadcrumbs for non-existent category → 404."""
    with _patch_b2b(_mock_response([], status_code=200)):
        resp = await ac.get(f"/api/v1/breadcrumbs?category_id={uuid4()}")

    assert resp.status_code == 404
