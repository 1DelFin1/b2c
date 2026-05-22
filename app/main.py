from contextlib import asynccontextmanager

import uvicorn
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import main_router
from app.core.rabbit_config import rabbit_broker
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    await rabbit_broker.start()
    yield
    await rabbit_broker.stop()


app = FastAPI(title="b2c", lifespan=lifespan)
app.include_router(main_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.cors.CORS_METHODS,
    allow_headers=settings.cors.CORS_HEADERS,
)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8012, reload=True)
