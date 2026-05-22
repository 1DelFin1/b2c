from __future__ import annotations

import json
from uuid import UUID

from app.core.redis_client import redis_client


class FavoritesService:
    FAVORITES_KEY_PREFIX = "favorites"
    FAVORITES_TTL = 60 * 60 * 24 * 30  # 30 days

    @classmethod
    def _build_key(cls, user_id: UUID) -> str:
        return f"{cls.FAVORITES_KEY_PREFIX}:{user_id}"

    @classmethod
    async def _load_raw(cls, user_id: UUID) -> list[str]:
        raw = await redis_client.get(cls._build_key(user_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item) for item in data]
        except json.JSONDecodeError:
            pass
        return []

    @classmethod
    async def _save_raw(cls, user_id: UUID, items: list[str]) -> None:
        key = cls._build_key(user_id)
        payload = json.dumps(items, ensure_ascii=False)
        await redis_client.set(key, payload)
        await redis_client.expire(key, cls.FAVORITES_TTL)

    @classmethod
    async def get(
        cls,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[UUID], int]:
        raw_items = await cls._load_raw(user_id)
        total = len(raw_items)
        page = raw_items[offset: offset + limit]
        uuids: list[UUID] = []
        for item in page:
            try:
                uuids.append(UUID(item))
            except (ValueError, AttributeError):
                continue
        return uuids, total

    @classmethod
    async def add(cls, user_id: UUID, product_id: UUID) -> None:
        raw_items = await cls._load_raw(user_id)
        pid_str = str(product_id)
        if pid_str not in raw_items:
            raw_items.append(pid_str)
            await cls._save_raw(user_id, raw_items)

    @classmethod
    async def remove(cls, user_id: UUID, product_id: UUID) -> None:
        raw_items = await cls._load_raw(user_id)
        pid_str = str(product_id)
        filtered = [item for item in raw_items if item != pid_str]
        if len(filtered) != len(raw_items):
            await cls._save_raw(user_id, filtered)

    @classmethod
    async def get_buyers_for_product(cls, product_id: UUID) -> list[UUID]:
        """Return all buyer IDs who have product_id in their favorites list.

        Scans all ``favorites:<user_id>`` keys in Redis and checks each list
        for the given product_id.  The scan is done with a MATCH pattern to
        limit the keyspace; results are collected lazily so memory pressure is
        bounded even for large stores.
        """
        pid_str = str(product_id)
        buyer_ids: list[UUID] = []
        pattern = f"{cls.FAVORITES_KEY_PREFIX}:*"
        async for key in redis_client.scan_iter(match=pattern, count=100):
            raw = await redis_client.get(key)
            if not raw:
                continue
            try:
                items = json.loads(raw)
                if not isinstance(items, list):
                    continue
            except json.JSONDecodeError:
                continue
            if pid_str in [str(item) for item in items]:
                # key format: "favorites:<uuid>"
                try:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    user_uuid = UUID(key_str.split(":", 1)[1])
                    buyer_ids.append(user_uuid)
                except (ValueError, IndexError):
                    continue
        return buyer_ids
