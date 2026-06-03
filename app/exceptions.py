from fastapi import HTTPException, status

BUYER_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "BUYER_NOT_FOUND", "message": "Buyer not found"},
)

BUYER_ALREADY_EXISTS = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"code": "BUYER_ALREADY_EXISTS", "message": "A buyer with this email already exists"},
)

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "UNAUTHORIZED", "message": "Not authenticated"},
    headers={"WWW-Authenticate": "Bearer"},
)

INVALID_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "INVALID_TOKEN", "message": "Invalid or expired token"},
    headers={"WWW-Authenticate": "Bearer"},
)

INCORRECT_DATA = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "INCORRECT_CREDENTIALS", "message": "Incorrect email or password"},
)

ADDRESS_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "ADDRESS_NOT_FOUND", "message": "Address not found"},
)

PAYMENT_METHOD_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "PAYMENT_METHOD_NOT_FOUND", "message": "Payment method not found"},
)

ORDER_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "ORDER_NOT_FOUND", "message": "Order not found"},
)

REVIEW_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "REVIEW_NOT_FOUND", "message": "Review not found"},
)

REVIEW_ALREADY_EXISTS = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"code": "REVIEW_ALREADY_EXISTS", "message": "You have already reviewed this product"},
)

SUBSCRIPTION_ALREADY_EXISTS = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"code": "SUBSCRIPTION_ALREADY_EXISTS", "message": "Вы уже подписаны на уведомления об этом товаре"},
)

PRODUCT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "PRODUCT_NOT_FOUND", "message": "Товар с указанным идентификатором не найден"},
)

INVALID_NOTIFY_ON = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail={"code": "INVALID_NOTIFY_ON", "message": "Должен быть указан хотя бы один тип уведомления"},
)
