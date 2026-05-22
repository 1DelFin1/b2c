from faststream.rabbit import RabbitExchange, RabbitQueue, ExchangeType, RabbitBroker

from app.core.config import settings

rabbit_broker = RabbitBroker(settings.rabbitmq.RABBITMQ_URL)

orders_exchange = RabbitExchange(
    name="orders",
    type=ExchangeType.DIRECT,
    durable=True,
)

orders_reserved_queue = RabbitQueue(
    name=settings.rabbitmq.ORDERS_RESERVED_ROUTING_KEY,
    durable=True,
)
