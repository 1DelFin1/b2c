from faststream.rabbit import RabbitRouter

from app.core.rabbit_config import orders_reserved_queue
from app.services.order_service import OrderService

orders_router = RabbitRouter()


@orders_router.subscriber(orders_reserved_queue)
async def reserve_order(order_data: dict):
    """
    RabbitMQ consumer: receives a reservation confirmation and moves the order
    from CREATED → PAID status.
    """
    await OrderService.move_order_to_reserved(order_data)
