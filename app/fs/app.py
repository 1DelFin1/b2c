from faststream import FastStream

from app.core.rabbit_config import rabbit_broker
from app.fs.routers import orders_router

app = FastStream(rabbit_broker)

rabbit_broker.include_router(orders_router)
