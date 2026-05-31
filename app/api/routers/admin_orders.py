"""Internal admin endpoints for order status management.

FastAPI equivalent of Django Admin actions:
- Protected by X-Service-Key (operator / warehouse tooling)
- Not exposed to buyers

ADR (fulfill trigger mechanism):
  Chosen approach: explicit service-method call inside an admin endpoint
  (equivalent to a Django Admin action).

  Alternatives considered:
  1. SQLAlchemy event listener (equivalent to post_save signal) — fires on every
     session.commit() that touches the order; hard to distinguish intentional DELIVERED
     transitions from data-fix patches, and difficult to inject the async httpx client
     into a sync ORM event.  Double-call risk: any UPDATE touching the row triggers it.
  2. Override model __setattr__ / a custom save() wrapper — same double-call risk as
     the signal; couples the domain model to an HTTP side effect, making unit tests
     require mocking httpx even for unrelated model mutations.
  3. Explicit service-method call (this approach) — the call to fulfill happens only
     when the admin explicitly POSTs to /admin/orders/{id}/deliver; no accidental
     double-calls; httpx is easy to mock in tests; the service method is a pure
     function testable without an HTTP request at all.

  Selection criteria:
  - Risk of accidental double-call: event-based approaches fire on any write;
    explicit action fires only when the endpoint is hit.
  - Testability without admin UI: service method is directly callable in pytest;
    event-based approach requires triggering a real ORM commit.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ServiceKeyDep, SessionDep
from app.schemas import OrderResponse
from app.services.order_service import OrderService

admin_orders_router = APIRouter(prefix="/api/v1/admin/orders", tags=["admin-orders"])


@admin_orders_router.post("/{order_id}/deliver", response_model=OrderResponse)
async def deliver_order(
    session: SessionDep,
    order_id: UUID,
    _service_key: ServiceKeyDep,
) -> dict:
    """Mark order as DELIVERED and trigger B2B fulfill (canonical B2C-13 flow).

    Requires X-Service-Key header (warehouse / operator tooling only).
    The order must be in DELIVERING status.
    """
    return await OrderService.mark_delivered(session, order_id=order_id)
