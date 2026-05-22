from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from app.core.redis_client import redis_client
from app.schemas import CartItemStored, CartItemResponse, CartResponse, ImageRef


class CartService:
    CART_KEY_PREFIX = "cart"
    CART_TTL = 60 * 60 * 24 * 7  # 7 days

    @classmethod
    def _build_key(cls, identity: str) -> str:
        return f"{cls.CART_KEY_PREFIX}:{identity}"

    # ------------------------------------------------------------------
    # Low-level Redis helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _load_raw(cls, identity: str) -> list[dict]:
        raw = await redis_client.get(cls._build_key(identity))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        return []

    @classmethod
    async def _save_raw(cls, identity: str, items: list[dict]) -> None:
        key = cls._build_key(identity)
        payload = json.dumps(items, ensure_ascii=False, default=str)
        await redis_client.set(key, payload)
        await redis_client.expire(key, cls.CART_TTL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    async def get_items(cls, identity: str) -> list[CartItemStored]:
        raw_items = await cls._load_raw(identity)
        result: list[CartItemStored] = []
        for raw in raw_items:
            try:
                result.append(CartItemStored.model_validate(raw))
            except Exception:
                continue
        return result

    @classmethod
    async def _save_items(cls, identity: str, items: list[CartItemStored]) -> None:
        """Persist a list of CartItemStored objects back to Redis."""
        raw = [item.model_dump() for item in items]
        await cls._save_raw(identity, raw)

    @classmethod
    async def add_item(
        cls,
        identity: str,
        sku_id: UUID,
        product_id: UUID,
        name: str,
        quantity: int,
        unit_price: int,
        sku_code: str | None = None,
        image_url: str | None = None,
    ) -> list[CartItemStored]:
        raw_items = await cls._load_raw(identity)

        sku_str = str(sku_id)
        found = False
        for item in raw_items:
            if item.get("sku_id") == sku_str:
                item["quantity"] = item.get("quantity", 0) + quantity
                found = True
                break

        if not found:
            raw_items.append(
                {
                    "sku_id": sku_str,
                    "product_id": str(product_id),
                    "name": name,
                    "sku_code": sku_code,
                    "image_url": image_url,
                    "quantity": quantity,
                    "unit_price_at_add": unit_price,
                }
            )

        await cls._save_raw(identity, raw_items)
        return await cls.get_items(identity)

    @classmethod
    async def update_item(
        cls,
        identity: str,
        sku_id: UUID,
        quantity: int,
    ) -> list[CartItemStored]:
        raw_items = await cls._load_raw(identity)

        sku_str = str(sku_id)
        found = False
        for item in raw_items:
            if item.get("sku_id") == sku_str:
                item["quantity"] = quantity
                found = True
                break

        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found in cart",
            )

        await cls._save_raw(identity, raw_items)
        return await cls.get_items(identity)

    @classmethod
    async def remove_item(
        cls,
        identity: str,
        sku_id: UUID,
    ) -> list[CartItemStored]:
        raw_items = await cls._load_raw(identity)

        sku_str = str(sku_id)
        filtered = [item for item in raw_items if item.get("sku_id") != sku_str]
        await cls._save_raw(identity, filtered)
        return await cls.get_items(identity)

    @classmethod
    async def clear(cls, identity: str) -> None:
        await redis_client.delete(cls._build_key(identity))

    @classmethod
    async def remove_product_from_all_carts(cls, product_id: UUID) -> list[str]:
        """
        Scan all cart keys in Redis and remove items matching product_id.
        Returns list of cart identities (user_id or session_id) that were affected.
        """
        product_str = str(product_id)
        pattern = f"{cls.CART_KEY_PREFIX}:*"
        affected: list[str] = []

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis_client.get(key)
                if not raw:
                    continue
                try:
                    import json as _json
                    items = _json.loads(raw)
                    if not isinstance(items, list):
                        continue
                    new_items = [item for item in items if item.get("product_id") != product_str]
                    if len(new_items) != len(items):
                        # Extract identity from key (strip prefix "cart:")
                        identity = key[len(cls.CART_KEY_PREFIX) + 1:]
                        await cls._save_raw(identity, new_items)
                        affected.append(identity)
                except Exception:
                    continue
            if cursor == 0:
                break

        return affected

    @classmethod
    async def remove_sku_from_all_carts(cls, sku_id: UUID) -> list[str]:
        """
        Scan all cart keys in Redis and remove items matching sku_id.
        Returns list of cart identities that were affected.
        """
        sku_str = str(sku_id)
        pattern = f"{cls.CART_KEY_PREFIX}:*"
        affected: list[str] = []

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis_client.get(key)
                if not raw:
                    continue
                try:
                    import json as _json
                    items = _json.loads(raw)
                    if not isinstance(items, list):
                        continue
                    new_items = [item for item in items if item.get("sku_id") != sku_str]
                    if len(new_items) != len(items):
                        identity = key[len(cls.CART_KEY_PREFIX) + 1:]
                        await cls._save_raw(identity, new_items)
                        affected.append(identity)
                except Exception:
                    continue
            if cursor == 0:
                break

        return affected

    # ------------------------------------------------------------------
    # Response builder
    # ------------------------------------------------------------------

    @classmethod
    def to_response(cls, items: list[CartItemStored], identity: str) -> CartResponse:
        response_items: list[CartItemResponse] = []
        for item in items:
            line_total = item.unit_price_at_add * item.quantity
            image = (
                ImageRef(id=uuid4(), url=item.image_url, ordering=0)
                if item.image_url
                else None
            )
            response_items.append(
                CartItemResponse(
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    name=item.name,
                    sku_code=item.sku_code,
                    image=image,
                    quantity=item.quantity,
                    unit_price=item.unit_price_at_add,
                    unit_price_at_add=item.unit_price_at_add,
                    line_total=line_total,
                    available_quantity=999,
                    is_available=True,
                )
            )

        items_count = sum(i.quantity for i in items)
        subtotal = sum(i.unit_price_at_add * i.quantity for i in items)

        try:
            cart_id = UUID(identity)
        except (ValueError, AttributeError):
            cart_id = uuid4()

        return CartResponse(
            id=cart_id,
            items=response_items,
            items_count=items_count,
            subtotal=subtotal,
            is_valid=True,
            updated_at=datetime.now(timezone.utc),
        )
