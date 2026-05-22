from fastapi import APIRouter

from app.api.routers.auth import auth_router
from app.api.routers.buyers import buyers_router
from app.api.routers.cart import cart_v1_router
from app.api.routers.favorites import favorites_v1_router
from app.api.routers.orders import orders_v1_router
from app.api.routers.notifications import notifications_router
from app.api.routers.b2b_events import b2b_events_router
from app.api.routers.catalog import catalog_router

main_router = APIRouter()

main_router.include_router(auth_router)
main_router.include_router(buyers_router)
main_router.include_router(cart_v1_router)
main_router.include_router(favorites_v1_router)
main_router.include_router(orders_v1_router)
main_router.include_router(notifications_router)
main_router.include_router(b2b_events_router)
main_router.include_router(catalog_router)

__all__ = [
    "main_router",
    "auth_router",
    "buyers_router",
    "cart_v1_router",
    "favorites_v1_router",
    "orders_v1_router",
    "notifications_router",
    "b2b_events_router",
    "catalog_router",
]
