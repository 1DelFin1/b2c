from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from app.core.redis_client import redis_client
from app.schemas import (
    CartEnrichedResponse,
    CartItemEnriched,
    CartItemResponse,
    CartItemStored,
    CartMutationResponse,
    CartResponse,
    CartSummary,
    CheckoutItem,
    CheckoutPayload,
    ImageRef,
    UnavailableReason,
)


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

    @classmethod
    async def mark_skus_unavailable_in_all_carts(
        cls,
        sku_ids: list[UUID],
        reason: str,
    ) -> int:
        """Scan all carts and set unavailable_reason on items matching any of the given sku_ids.

        Returns the number of cart items updated across all carts.
        Items are kept in the cart (not deleted) so buyers see the reason on next visit.
        """
        import json as _json

        sku_strs = {str(sid) for sid in sku_ids}
        pattern = f"{cls.CART_KEY_PREFIX}:*"
        updated_count = 0

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis_client.get(key)
                if not raw:
                    continue
                try:
                    items: list[dict] = _json.loads(raw)
                    if not isinstance(items, list):
                        continue
                    changed = False
                    for item in items:
                        if item.get("sku_id") in sku_strs:
                            item["unavailable_reason"] = reason
                            changed = True
                            updated_count += 1
                    if changed:
                        identity = key[len(cls.CART_KEY_PREFIX) + 1:]
                        await cls._save_raw(identity, items)
                except Exception:
                    continue
            if cursor == 0:
                break

        return updated_count

    # ------------------------------------------------------------------
    # B2B enrichment — spec-compliant CartResponse
    # ------------------------------------------------------------------

    @classmethod
    def enrich_to_cart_response(
        cls,
        stored: list[CartItemStored],
        b2b_products: list[dict],
        identity: str = "",
    ) -> CartResponse:
        """Build CartResponse (spec shape) from stored items and live B2B data."""
        product_map: dict[str, dict] = {}
        product_status: dict[str, str] = {}
        product_title: dict[str, str] = {}
        for p in b2b_products:
            pid = str(p["id"])
            product_status[pid] = p.get("status", "MODERATED")
            product_title[pid] = p.get("title") or p.get("name") or ""
            product_map[pid] = {str(s["id"]): s for s in (p.get("skus") or [])}

        response_items: list[CartItemResponse] = []
        for item in stored:
            pid = str(item.product_id)
            sid = str(item.sku_id)
            image: ImageRef | None = None

            # Defaults when B2B data unavailable
            unit_price = item.unit_price_at_add
            available_quantity = 0
            is_available = False
            name = item.name

            if pid in product_map and product_status.get(pid) in ("MODERATED", "ACTIVE"):
                sku_map = product_map[pid]
                if sid in sku_map:
                    sku = sku_map[sid]
                    unit_price = int(sku.get("price") or item.unit_price_at_add)
                    available_quantity = int(sku.get("active_quantity") or 0)
                    is_available = available_quantity > 0
                    name = product_title.get(pid) or sku.get("name") or item.name
                    imgs = sku.get("images") or []
                    if imgs and isinstance(imgs[0], dict) and imgs[0].get("url"):
                        image = ImageRef(id=uuid4(), url=imgs[0]["url"], ordering=imgs[0].get("ordering", 0))

            line_total = unit_price * item.quantity if is_available else 0
            response_items.append(CartItemResponse(
                sku_id=item.sku_id,
                product_id=item.product_id,
                name=name,
                sku_code=item.sku_code,
                image=image,
                quantity=item.quantity,
                unit_price=unit_price,
                unit_price_at_add=item.unit_price_at_add,
                line_total=line_total,
                available_quantity=available_quantity,
                is_available=is_available,
            ))

        items_count = sum(i.quantity for i in response_items)
        subtotal = sum(i.line_total for i in response_items)
        is_valid = all(i.is_available for i in response_items) if response_items else True

        try:
            cart_id = UUID(identity)
        except (ValueError, AttributeError):
            cart_id = uuid4()

        return CartResponse(
            id=cart_id,
            items=response_items,
            items_count=items_count,
            subtotal=subtotal,
            is_valid=is_valid,
            updated_at=datetime.now(timezone.utc),
        )

    @classmethod
    def enrich(
        cls,
        stored: list[CartItemStored],
        b2b_products: list[dict],
    ) -> CartEnrichedResponse:
        """Build CartEnrichedResponse from stored items and B2B product list."""
        # Build lookup: {product_id: {sku_id: sku_dict}}
        product_map: dict[str, dict] = {}
        product_status: dict[str, str] = {}
        for p in b2b_products:
            pid = str(p["id"])
            product_status[pid] = p.get("status", "MODERATED")
            product_map[pid] = {str(s["id"]): s for s in (p.get("skus") or [])}

        enriched: list[CartItemEnriched] = []
        for item in stored:
            pid = str(item.product_id)
            sid = str(item.sku_id)

            if pid not in product_map:
                enriched.append(CartItemEnriched(
                    item_id=item.sku_id,
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    product_title=item.name,
                    sku_name=item.name,
                    image_url=item.image_url,
                    unit_price=item.unit_price_at_add,
                    quantity=item.quantity,
                    available_stock=0,
                    line_total=0,
                    available=False,
                    unavailable_reason=UnavailableReason.PRODUCT_DELISTED,
                ))
                continue

            status_val = product_status.get(pid, "MODERATED")
            if status_val not in ("MODERATED", "ACTIVE"):
                enriched.append(CartItemEnriched(
                    item_id=item.sku_id,
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    product_title=item.name,
                    sku_name=item.name,
                    image_url=item.image_url,
                    unit_price=item.unit_price_at_add,
                    quantity=item.quantity,
                    available_stock=0,
                    line_total=0,
                    available=False,
                    unavailable_reason=UnavailableReason.PRODUCT_BLOCKED,
                ))
                continue

            sku_map = product_map[pid]
            if sid not in sku_map:
                enriched.append(CartItemEnriched(
                    item_id=item.sku_id,
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    product_title=item.name,
                    sku_name=item.name,
                    image_url=item.image_url,
                    unit_price=item.unit_price_at_add,
                    quantity=item.quantity,
                    available_stock=0,
                    line_total=0,
                    available=False,
                    unavailable_reason=UnavailableReason.SKU_DISABLED,
                ))
                continue

            sku = sku_map[sid]
            price = int(sku.get("price") or item.unit_price_at_add)
            stock = int(sku.get("active_quantity") or 0)
            p_data = next((p for p in b2b_products if str(p["id"]) == pid), {})
            p_title = p_data.get("title") or item.name
            images = sku.get("images") or []
            img_url = (
                images[0].get("url") if images and isinstance(images[0], dict)
                else item.image_url
            )

            if stock == 0:
                enriched.append(CartItemEnriched(
                    item_id=item.sku_id,
                    sku_id=item.sku_id,
                    product_id=item.product_id,
                    product_title=p_title,
                    sku_name=sku.get("name") or item.name,
                    image_url=img_url,
                    unit_price=price,
                    quantity=item.quantity,
                    available_stock=0,
                    line_total=0,
                    available=False,
                    unavailable_reason=UnavailableReason.OUT_OF_STOCK,
                ))
                continue

            enriched.append(CartItemEnriched(
                item_id=item.sku_id,
                sku_id=item.sku_id,
                product_id=item.product_id,
                product_title=p_title,
                sku_name=sku.get("name") or item.name,
                image_url=img_url,
                unit_price=price,
                quantity=item.quantity,
                available_stock=stock,
                line_total=price * item.quantity,
                available=True,
                unavailable_reason=None,
            ))

        return cls._build_cart_response(enriched)

    @classmethod
    def _build_cart_response(cls, items: list[CartItemEnriched]) -> CartEnrichedResponse:
        available = [i for i in items if i.available]
        total_amount = sum(i.line_total for i in available)
        summary = CartSummary(
            total_amount=total_amount,
            total_items=len(items),
            total_quantity=sum(i.quantity for i in items),
            available_items=len(available),
            has_unavailable_items=len(available) < len(items),
            checkout_ready=len(available) > 0 and len(available) == len(items),
        )
        checkout_payload = CheckoutPayload(
            items=[
                CheckoutItem(
                    product_id=i.product_id,
                    sku_id=i.sku_id,
                    quantity=i.quantity,
                    unit_price=i.unit_price,
                    line_total=i.line_total,
                )
                for i in available
            ],
            total_amount=total_amount,
        )
        return CartEnrichedResponse(items=items, summary=summary, checkout_payload=checkout_payload)

    @classmethod
    def make_mutation_response(
        cls,
        message: str,
        item: CartItemEnriched,
        all_stored: list[CartItemStored],
    ) -> CartMutationResponse:
        """Quick summary using stored prices (no B2B round-trip needed for mutations)."""
        total_amount = sum(s.unit_price_at_add * s.quantity for s in all_stored)
        summary = CartSummary(
            total_amount=total_amount,
            total_items=len(all_stored),
            total_quantity=sum(s.quantity for s in all_stored),
            available_items=len(all_stored),
            has_unavailable_items=False,
            checkout_ready=len(all_stored) > 0,
        )
        return CartMutationResponse(message=message, item=item, summary=summary)

    # ------------------------------------------------------------------
    # Response builder (legacy — used by validate endpoint)
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
