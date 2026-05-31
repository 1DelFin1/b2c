from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, List, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Shared sub-objects
# ---------------------------------------------------------------------------

class ImageRef(BaseModel):
    id: UUID
    url: str
    alt: str | None = None
    ordering: int = 0
    is_main: bool = False


# ---------------------------------------------------------------------------
# Buyer / Auth schemas
# ---------------------------------------------------------------------------

class BuyerRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,15}$")


class BuyerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,15}$")
    date_of_birth: date | None = None


class BuyerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    first_name: str
    last_name: str | None
    phone: str | None
    date_of_birth: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class AddressCreateRequest(BaseModel):
    country: str = Field(max_length=100)
    region: str | None = None
    city: str
    street: str
    building: str
    apartment: str | None = None
    postal_code: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    is_default: bool = False
    comment: str | None = None


class AddressResponse(AddressCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class PaymentMethodCreateRequest(BaseModel):
    type: str = Field(pattern="^(CARD|SBP|WALLET)$")
    card_last4: str | None = None
    card_brand: str | None = None
    is_default: bool = False


class PaymentMethodResponse(PaymentMethodCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user_id: UUID


# ---------------------------------------------------------------------------
# Cart schemas
# ---------------------------------------------------------------------------

class CartItemStored(BaseModel):
    """Stored in Redis as part of a cart list."""
    sku_id: UUID
    product_id: UUID
    name: str
    sku_code: str | None = None
    image_url: str | None = None
    quantity: int
    unit_price_at_add: int  # price (in kopecks) when item was added
    unavailable_reason: str | None = None  # set by product events (PRODUCT_BLOCKED etc.)


class CartItemAddRequest(BaseModel):
    sku_id: UUID
    quantity: int = Field(ge=1)


class CartItemUpdateRequest(BaseModel):
    quantity: int = Field(ge=1)


class UnavailableReason(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    PRODUCT_DELISTED = "PRODUCT_DELISTED"
    SKU_DISABLED = "SKU_DISABLED"


class CartItemEnriched(BaseModel):
    """Cart item enriched with live B2B data."""
    item_id: UUID          # equals sku_id (used as position identifier)
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    image_url: str | None = None
    unit_price: int        # current price from B2B (kopecks)
    quantity: int
    available_stock: int
    line_total: int        # 0 for unavailable items
    available: bool
    unavailable_reason: UnavailableReason | None = None


class CartSummary(BaseModel):
    total_amount: int
    total_items: int       # distinct positions
    total_quantity: int    # sum of quantities
    available_items: int
    has_unavailable_items: bool
    checkout_ready: bool
    currency: str = "RUB"


class CheckoutItem(BaseModel):
    product_id: UUID
    sku_id: UUID
    quantity: int
    unit_price: int
    line_total: int


class CheckoutPayload(BaseModel):
    items: list[CheckoutItem]
    total_amount: int
    currency: str = "RUB"


class CartEnrichedResponse(BaseModel):
    items: list[CartItemEnriched]
    summary: CartSummary
    checkout_payload: CheckoutPayload


class CartMutationResponse(BaseModel):
    message: str
    item: CartItemEnriched
    summary: CartSummary


# Legacy response (used by validate endpoint)
class CartItemResponse(BaseModel):
    sku_id: UUID
    product_id: UUID
    name: str
    sku_code: str | None = None
    image: ImageRef | None = None
    quantity: int
    unit_price: int
    unit_price_at_add: int
    line_total: int
    available_quantity: int
    is_available: bool


class CartResponse(BaseModel):
    id: UUID
    items: list[CartItemResponse]
    items_count: int
    subtotal: int
    is_valid: bool
    updated_at: datetime | None


class CartIssueType(str, Enum):
    PRICE_CHANGED = "PRICE_CHANGED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    QUANTITY_REDUCED = "QUANTITY_REDUCED"
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    PRODUCT_DELETED = "PRODUCT_DELETED"


class CartValidationIssue(BaseModel):
    sku_id: UUID
    type: CartIssueType
    message: str
    old_value: Any | None = None
    new_value: Any | None = None


class CartValidationResponse(BaseModel):
    is_valid: bool
    issues: list[CartValidationIssue]
    cart: CartResponse


# ---------------------------------------------------------------------------
# Favorites schemas
# ---------------------------------------------------------------------------

class FavoriteItem(BaseModel):
    product_id: UUID


class CategoryRef(BaseModel):
    id: UUID
    name: str
    level: int = 0
    parent_id: UUID | None = None
    path: list[str] = []


class SellerRef(BaseModel):
    id: UUID
    display_name: str


class CatalogProductCard(BaseModel):
    id: UUID
    name: str
    slug: str | None = None
    min_price: int | None = None
    old_price: int | None = None
    has_stock: bool
    images: list[ImageRef] = []
    category: CategoryRef | None = None
    rating: float | None = None
    reviews_count: int = 0
    seller: SellerRef | None = None


class PaginatedCatalogProducts(BaseModel):
    items: list[CatalogProductCard]
    total_count: int
    limit: int
    offset: int


class FavoritesResponse(BaseModel):
    items: list[UUID]
    total_count: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Checkout schemas (canonical B2C-9 flow)
# ---------------------------------------------------------------------------

class CheckoutRequestItem(BaseModel):
    sku_id: UUID
    quantity: int = Field(ge=1)


class CheckoutRequest(BaseModel):
    idempotency_key: UUID
    items: list[CheckoutRequestItem] = Field(min_length=1)
    delivery_address: str | None = None


class FailedReserveItem(BaseModel):
    sku_id: UUID
    requested: int | None = None
    available: int | None = None
    reason: str  # OUT_OF_STOCK | INSUFFICIENT_STOCK | PRODUCT_BLOCKED | PRODUCT_DELETED | SKU_NOT_FOUND


class CheckoutOrderItemOut(BaseModel):
    id: UUID
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    quantity: int
    unit_price: int
    line_total: int


class CheckoutOrderResponse(BaseModel):
    id: UUID
    status: str
    items: list[CheckoutOrderItemOut]
    total_amount: int
    delivery_address: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Order schemas
# ---------------------------------------------------------------------------

class StatusHistoryEntry(BaseModel):
    status: str
    changed_at: datetime
    reason: str | None = None


class AddressInOrder(BaseModel):
    id: UUID
    country: str | None = None
    region: str | None = None
    city: str
    street: str
    building: str
    apartment: str | None = None
    postal_code: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    is_default: bool = False
    comment: str | None = None
    created_at: datetime | None = None


class PaymentMethodInOrder(BaseModel):
    id: UUID
    type: str
    card_last4: str | None = None
    card_brand: str | None = None
    is_default: bool = False
    created_at: datetime | None = None


class OrderItemSnapshot(BaseModel):
    sku_id: UUID
    quantity: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class OrderCreateRequest(BaseModel):
    address_id: UUID
    payment_method_id: UUID
    comment: str | None = Field(default=None, max_length=1000)
    items_snapshot: list[OrderItemSnapshot] | None = None


class CancelOrderRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class OrderItemResponse(BaseModel):
    sku_id: UUID
    product_id: UUID
    name: str
    sku_code: str | None = None
    image_url: str | None = None
    quantity: int
    unit_price: int
    line_total: int


class OrderResponse(BaseModel):
    id: UUID
    number: str
    buyer_id: UUID
    status: str
    status_history: list[StatusHistoryEntry] = []
    items: list[OrderItemResponse]
    subtotal: int
    delivery_cost: int
    total: int
    address: AddressInOrder | None = None
    payment_method: PaymentMethodInOrder | None = None
    comment: str | None
    cancel_reason: str | None
    created_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None = None


class PaginatedOrders(BaseModel):
    items: list[OrderResponse]
    total_count: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Notification schemas
# ---------------------------------------------------------------------------

class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: Literal["ORDER_STATUS_CHANGED", "BACK_IN_STOCK", "PRICE_DROP", "PROMO", "SYSTEM"]
    title: str
    body: str | None = None
    payload: dict | None = None
    is_read: bool
    created_at: datetime


class PaginatedNotifications(BaseModel):
    items: list[NotificationResponse]
    total_count: int
    unread_count: int = 0
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Collection schemas
# ---------------------------------------------------------------------------

class CollectionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    target_url: str | None = None
    priority: int
    start_date: date | None = None


class CollectionsMetadata(BaseModel):
    total_count: int
    limit: int
    offset: int


class CollectionsResponse(BaseModel):
    metadata: CollectionsMetadata
    collections: list[CollectionSchema]


class CollectionProductCard(BaseModel):
    """Enriched product card returned inside a collection."""
    id: UUID
    title: str
    slug: str | None = None
    price: int | None = None
    in_stock: bool
    images: list[dict] = []


class CollectionProductsResponse(BaseModel):
    collection_title: str
    total_products: int
    items: list[CollectionProductCard]
    unavailable_ids: list[UUID] = []


# ---------------------------------------------------------------------------
# Banner schemas
# ---------------------------------------------------------------------------

class BannerSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    image_url: str
    link: str
    priority: int


class BannerListResponse(BaseModel):
    items: list[BannerSchema]
    total_count: int


class BannerEventItem(BaseModel):
    banner_id: UUID
    event: Literal["impression", "click"]
    timestamp: datetime


class BannerEventsRequest(BaseModel):
    events: list[BannerEventItem] = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# B2B Event schemas
# ---------------------------------------------------------------------------

class B2BEventPayload(BaseModel):
    product_id: UUID | None = None
    sku_id: UUID | None = None
    new_price: int | None = None


class B2BEvent(BaseModel):
    event_type: Literal["PRODUCT_BLOCKED", "PRODUCT_HARD_BLOCKED", "PRODUCT_DELETED", "SKU_OUT_OF_STOCK", "SKU_BACK_IN_STOCK", "PRICE_CHANGED"]
    idempotency_key: UUID
    occurred_at: datetime
    payload: dict


# ---------------------------------------------------------------------------
# Product events (canon format: POST /api/v1/events/product)
# ---------------------------------------------------------------------------

class ProductEventRequest(BaseModel):
    """Incoming event from B2B about product/SKU lifecycle changes.

    Matches the canonical format in b2c-orders-flows.md#b2c-12-handle-events.
    """
    idempotency_key: UUID
    event: Literal["PRODUCT_BLOCKED", "PRODUCT_DELETED", "SKU_OUT_OF_STOCK"]
    product_id: UUID
    sku_ids: list[UUID] = Field(default_factory=list)
    reason: str | None = None
    date: datetime


# ---------------------------------------------------------------------------
# Review schemas
# ---------------------------------------------------------------------------

class ReviewCreate(BaseModel):
    product_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    rating: float = Field(ge=1.0, le=5.0)


class ReviewUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    rating: float | None = Field(default=None, ge=1.0, le=5.0)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    product_id: UUID
    text: str
    rating: float
    created_at: datetime
    updated_at: datetime


class PaginatedReviews(BaseModel):
    items: list[ReviewResponse]
    total_count: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Catalog proxy schemas
# ---------------------------------------------------------------------------

class NotifyEvent(str, Enum):
    IN_STOCK = "IN_STOCK"
    PRICE_DOWN = "PRICE_DOWN"


class SubscribeRequest(BaseModel):
    notify_on: list[NotifyEvent] = Field(
        min_length=1,
        default=[NotifyEvent.IN_STOCK, NotifyEvent.PRICE_DOWN],
    )


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    notify_on: list[str]
    created_at: datetime


class CatalogFilters(BaseModel):
    category_id: UUID | None = None
    search: str | None = None
    min_price: int | None = None
    max_price: int | None = None
    seller_id: UUID | None = None
    sort: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
