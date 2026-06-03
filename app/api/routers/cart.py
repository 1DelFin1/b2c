from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status

from app.api.deps import get_current_active_auth_buyer, get_optional_user_id, get_user_id
from app.core.config import settings
from app.schemas import (
    CartEnrichedResponse,
    CartItemAddRequest,
    CartItemEnriched,
    CartItemUpdateRequest,
    CartIssueType,
    CartMutationResponse,
    CartResponse,
    CartValidationIssue,
    CartValidationResponse,
    UnavailableReason,
)
# CartEnrichedResponse and CartMutationResponse kept for internal/validate use
from app.services.cart_service import CartService

cart_v1_router = APIRouter(prefix="/api/v1/cart", tags=["cart"])

_TIMEOUT = 10.0
_B2B_HEADERS = {"X-Service-Key": settings.service.SERVICE_KEY}


def _get_identity(request: Request) -> tuple[str, bool]:
    """Return (identity, is_user). Identity is user_id string or session_id."""
    user_id = get_optional_user_id(request)
    if user_id is not None:
        return str(user_id), True

    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MISSING_CART_IDENTITY",
                "message": "Передайте Authorization Bearer или X-Session-Id заголовок",
            },
        )
    return session_id, False


async def _b2b_fetch_sku(sku_id: UUID) -> dict:
    """Fetch SKU from B2B. Raises 404/410/503 as appropriate."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{settings.service.B2B_URL}/api/v1/public/skus/{sku_id}",
                headers=_B2B_HEADERS,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "B2B_UNAVAILABLE", "message": str(exc)},
        )

    if resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SKU_NOT_FOUND", "message": "SKU с указанным id не существует"},
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "B2B_ERROR", "message": "B2B service error"},
        )

    return resp.json()


async def _b2b_batch_products(product_ids: list[str]) -> list[dict]:
    """Batch-fetch products from B2B for cart enrichment."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.service.B2B_URL}/api/v1/public/products/batch",
                json={"product_ids": product_ids},
                headers=_B2B_HEADERS,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "B2B_UNAVAILABLE", "message": str(exc)},
        )

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "B2B_UNAVAILABLE", "message": "B2B product batch failed"},
        )

    return resp.json()


# ── GET /cart ──────────────────────────────────────────────────────────────

@cart_v1_router.get("", response_model=CartResponse)
async def get_cart(request: Request) -> CartResponse:
    """Return cart enriched with live B2B data (prices, availability)."""
    identity, _ = _get_identity(request)
    stored = await CartService.get_items(identity)

    if not stored:
        return CartService.to_response([], identity)

    product_ids = list({str(item.product_id) for item in stored})
    b2b_products = await _b2b_batch_products(product_ids)
    return CartService.enrich_to_cart_response(stored, b2b_products, identity)


# ── DELETE /cart ───────────────────────────────────────────────────────────

@cart_v1_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(request: Request) -> None:
    identity, _ = _get_identity(request)
    await CartService.clear(identity)


# ── POST /cart/items ───────────────────────────────────────────────────────

@cart_v1_router.post("/items", response_model=CartResponse)
async def add_cart_item(
    request: Request,
    body: CartItemAddRequest = Body(...),
) -> CartResponse:
    """Add SKU to cart. Returns 201 for new position, 200 for quantity increment."""
    identity, _ = _get_identity(request)

    sku_data = await _b2b_fetch_sku(body.sku_id)

    # Availability check
    product_status = sku_data.get("product_status") or sku_data.get("status") or "MODERATED"
    active_qty = int(sku_data.get("active_quantity") or 0)

    if active_qty < body.quantity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_STOCK",
                "message": f"Нельзя добавить {body.quantity}, доступно только {active_qty}",
            },
        )

    product_id = UUID(str(sku_data["product_id"]))
    name = sku_data.get("name") or sku_data.get("title") or str(body.sku_id)
    price = int(sku_data.get("price") or 0)
    sku_code = sku_data.get("article") or None
    images = sku_data.get("images") or []
    image_url = (
        images[0].get("url") if images and isinstance(images[0], dict)
        else None
    )

    # Detect if item is new (for 201 vs 200)
    existing = await CartService.get_items(identity)
    is_new = not any(str(i.sku_id) == str(body.sku_id) for i in existing)

    updated = await CartService.add_item(
        identity=identity,
        sku_id=body.sku_id,
        product_id=product_id,
        name=name,
        quantity=body.quantity,
        unit_price=price,
        sku_code=sku_code,
        image_url=image_url,
    )

    cart = CartService.to_response(updated, identity)

    from fastapi.responses import JSONResponse
    response_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
    return JSONResponse(content=cart.model_dump(mode="json"), status_code=response_code)


# ── PATCH /cart/items/{sku_id} ────────────────────────────────────────────

@cart_v1_router.patch("/items/{sku_id}", response_model=CartResponse)
async def update_cart_item(
    request: Request,
    sku_id: UUID,
    body: CartItemUpdateRequest = Body(...),
) -> CartResponse:
    """Update quantity of a cart position. Validates stock against B2B."""
    identity, _ = _get_identity(request)

    sku_data = await _b2b_fetch_sku(sku_id)
    active_qty = int(sku_data.get("active_quantity") or 0)

    if active_qty == 0:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "SKU_NOT_AVAILABLE", "message": "Товар недоступен"},
        )
    if active_qty < body.quantity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_STOCK",
                "message": f"Нельзя установить {body.quantity}, доступно только {active_qty}",
            },
        )

    updated = await CartService.update_item(identity, sku_id, body.quantity)
    return CartService.to_response(updated, identity)


# ── DELETE /cart/items/{sku_id} ────────────────────────────────────────────

@cart_v1_router.delete("/items/{sku_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_cart_item(request: Request, sku_id: UUID) -> None:
    identity, _ = _get_identity(request)
    stored = await CartService.get_items(identity)
    if not any(str(i.sku_id) == str(sku_id) for i in stored):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CART_ITEM_NOT_FOUND", "message": "Позиция не найдена в корзине"},
        )
    await CartService.remove_item(identity, sku_id)


# ── POST /cart/merge ───────────────────────────────────────────────────────

@cart_v1_router.post("/merge", response_model=CartResponse)
async def merge_cart(
    request: Request,
    x_session_id: str = Header(..., alias="X-Session-Id"),
    payload: dict = Depends(get_current_active_auth_buyer),
) -> CartResponse:
    """Merge guest cart into authenticated user cart. Conflict strategy: MAX(quantities)."""
    user_id = str(get_user_id(payload))
    guest_items = await CartService.get_items(x_session_id)

    if not guest_items:
        stored = await CartService.get_items(user_id)
        if not stored:
            return CartService.to_response([], user_id)
        product_ids = list({str(i.product_id) for i in stored})
        b2b = await _b2b_batch_products(product_ids)
        return CartService.enrich_to_cart_response(stored, b2b, user_id)

    user_items = await CartService.get_items(user_id)
    # MAX-merge strategy
    merged: dict[str, object] = {str(i.sku_id): i for i in user_items}
    for g in guest_items:
        key = str(g.sku_id)
        if key in merged:
            existing = merged[key]
            existing.quantity = max(existing.quantity, g.quantity)
        else:
            merged[key] = g

    merged_list = list(merged.values())
    await CartService._save_items(user_id, merged_list)
    await CartService.clear(x_session_id)

    product_ids = list({str(i.product_id) for i in merged_list})
    b2b = await _b2b_batch_products(product_ids)
    return CartService.enrich_to_cart_response(merged_list, b2b, user_id)


# ── POST /cart/validate ────────────────────────────────────────────────────

@cart_v1_router.post("/validate", response_model=CartValidationResponse)
async def validate_cart(request: Request) -> CartValidationResponse:
    identity, _ = _get_identity(request)
    stored = await CartService.get_items(identity)
    issues: list[CartValidationIssue] = []
    is_valid = True

    for item in stored:
        try:
            sku_data = await _b2b_fetch_sku(item.sku_id)
        except HTTPException:
            issues.append(CartValidationIssue(
                sku_id=item.sku_id,
                type=CartIssueType.OUT_OF_STOCK,
                message="SKU not found or unavailable",
            ))
            is_valid = False
            continue

        available = int(sku_data.get("active_quantity") or 0)
        if available == 0:
            issues.append(CartValidationIssue(
                sku_id=item.sku_id,
                type=CartIssueType.OUT_OF_STOCK,
                message="Item is out of stock",
                old_value=item.quantity,
                new_value=0,
            ))
            is_valid = False
        elif available < item.quantity:
            issues.append(CartValidationIssue(
                sku_id=item.sku_id,
                type=CartIssueType.QUANTITY_REDUCED,
                message=f"Only {available} items available",
                old_value=item.quantity,
                new_value=available,
            ))
            is_valid = False

    cart = CartService.to_response(stored, identity)
    return CartValidationResponse(is_valid=is_valid, issues=issues, cart=cart)
