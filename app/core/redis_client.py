from redis import asyncio as redis
from app.core.config import settings

redis_client = redis.Redis(**settings.redis.REDIS_URL_ASYNC)
