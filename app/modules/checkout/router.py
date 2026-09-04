import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.db.base import uuid7
from app.modules.cart.models import Cart
from app.modules.cart.router import load_cart, token_hash
from app.modules.checkout.models import Checkout, IdempotencyKey
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.models import PaymentAttempt

router = APIRouter(tags=["checkout"])


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=200)
    street: str = Field(min_length=3, max_length=500)
    city: str = Field(min_length=2, max_length=150)
    state: str = Field(default="", max_length=150)
    pin_code: str = Field(pattern=r"^[1-9][0-9]{5}$")
    country: str = "IN"


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cart_id: UUID
    email: EmailStr
    phone: str = Field(pattern=r"^\+?[0-9 -]{8,18}$")
    shipping_address: Address
    payment_method: Literal["card", "upi", "cod"]
    provider_token: str | None = None


class AddressRequest(BaseModel):
    shipping_address: Address


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["card", "upi", "cod"]
    provider_token: str | None = None


class SandboxWebhook(BaseModel):
    provider_reference: str
    status: Literal["captured", "failed"]


def order_number(order_id: UUID) -> str:
    return f"SA-{datetime.now(timezone.utc):%Y%m%d}-{str(order_id).replace('-', '')[-8:].upper()}"


def derive_order_token(order_id: UUID, idempotency_key: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), f"{order_id}:{idempotency_key}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def order_payload(session: AsyncSession, order: Order, token: str | None = None) -> dict[str, object]:
    items = (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.created_at))).all()
    data: dict[str, object] = {"id": str(order.id), "order_number": order.order_number, "status": order.status, "payment_method": order.payment_method, "email": order.email, "shipping_address": order.shipping_address, "items": [{"product_name": x.product_name, "variant_name": x.variant_name, "sku": x.sku, "quantity": x.quantity, "unit_price_minor": x.unit_price_minor, "line_total_minor": x.line_total_minor, "currency": x.currency} for x in items], "subtotal_minor": order.subtotal_minor, "shipping_minor": order.shipping_minor, "tax_included_minor": order.tax_minor, "total_minor": order.total_minor, "currency": order.currency}
    if token:
        data["order_token"] = token
    return data


@router.get("/shipping-methods")
async def shipping_methods() -> dict[str, object]:
    return {"items": [{"id": "complimentary", "name": "Complimentary", "price_minor": 0, "currency": "INR"}]}


@router.post("/checkout", status_code=201)
async def create_checkout(payload: CheckoutRequest, idempotency_key: Annotated[str, Header(alias="Idempotency-Key")], x_cart_token: Annotated[str, Header()], settings: Settings = Depends(get_settings), session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    cart = await load_cart(session, payload.cart_id, x_cart_token)
    if not cart.items:
        raise AppError(409, "empty_cart", "Cart is empty")
    request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    previous = await session.get(IdempotencyKey, idempotency_key)
    if previous:
        if previous.request_hash != request_hash:
            raise AppError(409, "idempotency_conflict", "Idempotency key was used with a different request")
        existing = await session.get(Order, previous.resource_id)
        if existing is None:
            raise AppError(409, "idempotency_incomplete", "Previous request did not complete")
        replay = await order_payload(session, existing, derive_order_token(existing.id, idempotency_key, settings.token_signing_secret))
        replay["checkout_id"] = str(existing.checkout_id)
        return replay
    subtotal = sum(x.unit_price_minor * x.quantity for x in cart.items)
    checkout = Checkout(cart_id=cart.id, status="open", email=str(payload.email).lower(), phone=payload.phone, shipping_address=payload.shipping_address.model_dump(), subtotal_minor=subtotal, shipping_minor=0, tax_minor=subtotal * 18 // 118, total_minor=subtotal, currency=cart.currency)
    session.add(checkout)
    await session.flush()
    pending_order_id = uuid7()
    raw_order_token = derive_order_token(pending_order_id, idempotency_key, settings.token_signing_secret)
    order = Order(id=pending_order_id, checkout_id=checkout.id, order_number="pending", order_token_hash=token_hash(raw_order_token), email=checkout.email, phone=checkout.phone, shipping_address=checkout.shipping_address, status="confirmed" if payload.payment_method == "cod" else "pending_payment", payment_method=payload.payment_method, subtotal_minor=subtotal, shipping_minor=0, tax_minor=checkout.tax_minor, total_minor=subtotal, currency=cart.currency)
    order.order_number = order_number(order.id)
    session.add(order)
    await session.flush()
    for item in cart.items:
        session.add(OrderItem(order_id=order.id, variant_id=item.variant.id, product_name=item.variant.product.name, variant_name=item.variant.name, sku=item.variant.sku, quantity=item.quantity, unit_price_minor=item.unit_price_minor, line_total_minor=item.unit_price_minor * item.quantity, currency=item.currency))
    checkout.status = "completed" if payload.payment_method == "cod" else "awaiting_payment"
    cart.status = "converted"
    session.add(IdempotencyKey(key=idempotency_key, operation="checkout", request_hash=request_hash, resource_id=order.id))
    attempt = None
    if payload.payment_method != "cod":
        if payload.payment_method == "card" and not payload.provider_token:
            raise AppError(422, "provider_token_required", "Card payment requires a provider token; raw card data is forbidden")
        reference = f"sandbox_{secrets.token_hex(12)}"
        attempt = PaymentAttempt(order_id=order.id, provider="sandbox", method=payload.payment_method, provider_reference=reference, status="pending", amount_minor=order.total_minor, currency=order.currency)
        session.add(attempt)
    await session.commit()
    result = await order_payload(session, order, raw_order_token)
    result["checkout_id"] = str(checkout.id)
    if attempt:
        result["payment"] = {"attempt_id": str(attempt.id), "provider": "sandbox", "provider_reference": attempt.provider_reference, "client_secret": attempt.provider_reference if attempt.method == "card" else None, "redirect_url": f"http://localhost:3000/payment/upi-return?reference={attempt.provider_reference}" if attempt.method == "upi" else None, "status": attempt.status}
    return result


@router.get("/checkout/{checkout_id}")
async def get_checkout(checkout_id: UUID, x_cart_token: Annotated[str, Header()], session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    checkout = await session.get(Checkout, checkout_id)
    if checkout is None:
        raise AppError(404, "checkout_not_found", "Checkout not found")
    await load_cart_for_checkout(session, checkout.cart_id, x_cart_token)
    return {"id": str(checkout.id), "status": checkout.status, "email": checkout.email, "shipping_address": checkout.shipping_address, "total_minor": checkout.total_minor, "currency": checkout.currency}


async def load_cart_for_checkout(session: AsyncSession, cart_id: UUID, token: str) -> None:
    cart = await session.get(Cart, cart_id)
    if cart is None or not secrets.compare_digest(cart.token_hash, token_hash(token)):
        raise AppError(404, "checkout_not_found", "Checkout not found")


@router.post("/checkout/{checkout_id}/shipping-address")
async def update_address(checkout_id: UUID, payload: AddressRequest, x_cart_token: Annotated[str, Header()], session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    checkout = await session.get(Checkout, checkout_id)
    if checkout is None or checkout.status != "open":
        raise AppError(409, "checkout_not_editable", "Checkout cannot be updated")
    await load_cart_for_checkout(session, checkout.cart_id, x_cart_token)
    checkout.shipping_address = payload.shipping_address.model_dump()
    await session.commit()
    return {"id": str(checkout.id), "status": checkout.status, "shipping_address": checkout.shipping_address}


@router.post("/checkout/{checkout_id}/payment-intent")
async def payment_intent(checkout_id: UUID, payload: PaymentRequest, x_cart_token: Annotated[str, Header()], session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    checkout = await session.get(Checkout, checkout_id)
    if checkout is None:
        raise AppError(404, "checkout_not_found", "Checkout not found")
    await load_cart_for_checkout(session, checkout.cart_id, x_cart_token)
    order = await session.scalar(select(Order).where(Order.checkout_id == checkout.id))
    if order is None:
        raise AppError(409, "order_not_created", "Order has not been created")
    attempt = await session.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).order_by(PaymentAttempt.created_at.desc()))
    if attempt is None:
        raise AppError(409, "payment_not_required", "This order does not require online payment")
    return {"attempt_id": str(attempt.id), "provider": attempt.provider, "provider_reference": attempt.provider_reference, "client_secret": attempt.provider_reference if attempt.method == "card" else None, "redirect_url": f"http://localhost:3000/payment/upi-return?reference={attempt.provider_reference}" if attempt.method == "upi" else None, "status": attempt.status}


@router.post("/webhooks/payments/sandbox")
async def sandbox_webhook(payload: SandboxWebhook, x_sandbox_secret: Annotated[str, Header()], settings: Settings = Depends(get_settings), session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    if settings.environment != "dev" or not secrets.compare_digest(x_sandbox_secret, settings.sandbox_payment_secret):
        raise AppError(401, "invalid_webhook_signature", "Invalid webhook signature")
    attempt = await session.scalar(select(PaymentAttempt).where(PaymentAttempt.provider_reference == payload.provider_reference))
    if attempt is None:
        raise AppError(404, "payment_attempt_not_found", "Payment attempt not found")
    if attempt.status == "captured":
        return {"status": "already_processed"}
    attempt.status = payload.status
    order = await session.get(Order, attempt.order_id)
    if order and payload.status == "captured":
        order.status = "confirmed"
        checkout = await session.get(Checkout, order.checkout_id)
        if checkout:
            checkout.status = "completed"
    await session.commit()
    return {"status": "processed"}


@router.get("/orders/{order_id}/confirmation")
async def confirmation(order_id: UUID, x_order_token: Annotated[str, Header()], session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    order = await session.get(Order, order_id)
    if order is None or not secrets.compare_digest(order.order_token_hash, token_hash(x_order_token)):
        raise AppError(404, "order_not_found", "Order not found")
    return await order_payload(session, order)
