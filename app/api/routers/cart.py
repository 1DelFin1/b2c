from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.deps import get_optional_user_id, get_current_active_auth_buyer, get_user_id
from app.core.config import settings
from app.schemas import (
    CartIssueType,
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartResponse,
    CartValidationIssue,
    CartValidationResponse,
)
from app.services.cart_service import CartService

cart_v1_router = APIRouter(prefix="/api/v1/cart", tags=["cart"])


def _get_identity(request: Request) -> str:
    """Return user_id (from JWT) or X-Session-Id header as the cart identity."""
    user_id = get_optional_user_id(request)
    if user_id is not None:
        return str(user_id)

    session_id = request.headers.get("X-Session-Id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either Authorization Bearer token or X-Session-Id header is required",
        )
    return session_id


@cart_v1_router.get("", response_model=CartResponse)
async def get_cart(request: Request):
    identity = _get_identity(request)
    items = await CartService.get_items(identity)
    return CartService.to_response(items, identity)


@cart_v1_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(request: Request):
    identity = _get_identity(request)
    await CartService.clear(identity)


@cart_v1_router.post("/items", response_model=CartResponse, status_code=status.HTTP_200_OK)
async def add_cart_item(request: Request, body: CartItemAddRequest):
    identity = _get_identity(request)

    # Fetch SKU details from B2B service
    sku_id = body.sku_id
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{settings.service.B2B_URL}/api/v1/public/skus/{sku_id}",
                headers={"X-Service-Key": settings.service.SERVICE_KEY},
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not reach B2B service: {exc}",
            )

    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found")
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="B2B service error",
        )

    sku_data = resp.json()
    product_id = UUID(sku_data["product_id"])
    name = sku_data.get("name") or sku_data.get("title") or str(sku_id)
    unit_price = int(sku_data.get("price", 0))
    sku_code = sku_data.get("article") or None
    images = sku_data.get("images") or []
    image_url = images[0].get("url") if images and isinstance(images[0], dict) else (images[0] if images else None)

    items = await CartService.add_item(
        identity=identity,
        sku_id=sku_id,
        product_id=product_id,
        name=name,
        quantity=body.quantity,
        unit_price=unit_price,
        sku_code=sku_code,
        image_url=image_url,
    )
    return CartService.to_response(items, identity)


@cart_v1_router.patch("/items/{sku_id}", response_model=CartResponse)
async def update_cart_item(request: Request, sku_id: UUID, body: CartItemUpdateRequest):
    identity = _get_identity(request)
    items = await CartService.update_item(identity, sku_id, body.quantity)
    return CartService.to_response(items, identity)


@cart_v1_router.delete("/items/{sku_id}", response_model=CartResponse)
async def remove_cart_item(request: Request, sku_id: UUID):
    identity = _get_identity(request)
    items = await CartService.remove_item(identity, sku_id)
    return CartService.to_response(items, identity)


async def _fetch_sku_from_b2b(sku_id: UUID) -> dict | None:
    """Call B2B public endpoint to get SKU data. Returns None if not found."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.service.B2B_URL}/api/v1/public/skus/{sku_id}",
                headers={"X-Service-Key": settings.service.SERVICE_KEY},
            )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


@cart_v1_router.post("/validate", response_model=CartValidationResponse)
async def validate_cart(request: Request):
    identity = _get_identity(request)
    items = await CartService.get_items(identity)
    issues: list[CartValidationIssue] = []
    is_valid = True

    for item in items:
        sku_data = await _fetch_sku_from_b2b(item.sku_id)
        if sku_data is None:
            issues.append(CartValidationIssue(
                sku_id=item.sku_id,
                type=CartIssueType.OUT_OF_STOCK,
                message="SKU not found or unavailable",
            ))
            is_valid = False
        else:
            available = sku_data.get("active_quantity", 0)
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

    cart = CartService.to_response(items, identity)
    return CartValidationResponse(is_valid=is_valid, issues=issues, cart=cart)


@cart_v1_router.post("/merge", response_model=CartResponse)
async def merge_cart(
    request: Request,
    x_session_id: str = Header(..., alias="X-Session-Id"),
    payload: dict = Depends(get_current_active_auth_buyer),
):
    user_id = str(get_user_id(payload))
    # Load guest cart by session id
    guest_items = await CartService.get_items(x_session_id)
    if not guest_items:
        user_items = await CartService.get_items(user_id)
        return CartService.to_response(user_items, user_id)
    # Load user cart
    user_items = await CartService.get_items(user_id)
    # Merge: for each sku_id take max(quantity)
    merged = {item.sku_id: item for item in user_items}
    for guest_item in guest_items:
        if guest_item.sku_id in merged:
            existing = merged[guest_item.sku_id]
            existing.quantity = max(existing.quantity, guest_item.quantity)
        else:
            merged[guest_item.sku_id] = guest_item
    merged_list = list(merged.values())
    await CartService._save_items(user_id, merged_list)
    # Clear guest cart
    await CartService.clear(x_session_id)
    return CartService.to_response(merged_list, user_id)
