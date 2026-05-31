"""Test fixtures for B2C service tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.rabbit_config import rabbit_broker


@pytest_asyncio.fixture
async def ac():
    """Async test client with RabbitMQ broker mocked out."""
    with patch.object(rabbit_broker, "start", new=AsyncMock()), \
         patch.object(rabbit_broker, "stop", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
