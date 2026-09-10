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
from app.core.security import TokenPayload, optional_token

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
    expected_total_minor: int | None = Field(default=None, ge=0)


class AddressRequest(BaseModel):
    shipping_address: Address


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["card", "upi", "cod"]
    provider_token: str | None = None


class SandboxWebhook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    provider_reference: str
    status: Literal["captured", "failed"]


def order_number(order_id: UUID) -> str:
    return f"SA-{datetime.now(timezone.utc):%Y%m%d}-{str(order_id).replace('-', '')[-8:].upper()}"


def derive_order_token(order_id: UUID, idempotency_key: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode(), f"{order_id}:{idempotency_key}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def order_payload(
    session: AsyncSession, order: Order, token: str | None = None
) -> dict[str, object]:
    items = (
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.created_at)
        )
    ).all()
    from app.modules.fulfillment.models import Fulfillment, Shipment
    from app.modules.returns.models import Return, ReturnItem
    payments = (await session.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).order_by(PaymentAttempt.id))).all()
    shipments = (await session.scalars(select(Shipment).join(Fulfillment).where(Fulfillment.order_id == order.id))).all()
    returns = (await session.scalars(select(Return).where(Return.order_id == order.id))).all()
    return_lines = (await session.scalars(select(ReturnItem).join(Return).where(Return.order_id == order.id))).all()
    data: dict[str, object] = {
        "checkout_id": str(order.checkout_id),
        "payments": [{"id": str(x.id), "status": x.status, "provider": x.provider} for x in payments],
        "shipments": [{"carrier": x.carrier, "tracking_number": x.tracking_number, "status": x.status} for x in shipments],
        "returns": [{"id": str(x.id), "status": x.status, "items": [{"order_item_id": str(i.order_item_id), "quantity": i.quantity} for i in return_lines if i.return_id == x.id]} for x in returns],
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "payment_method": order.payment_method,
        "email": order.email,
        "shipping_address": order.shipping_address,
        "items": [
            {
                "id": str(x.id),
                "variant_id": str(x.variant_id),
                "product_name": x.product_name,
                "variant_name": x.variant_name,
                "sku": x.sku,
                "quantity": x.quantity,
                "unit_price_minor": x.unit_price_minor,
                "line_discount_minor": x.line_discount_minor,
                "line_tax_minor": x.line_tax_minor,
                "line_total_minor": x.line_total_minor,
                "currency": x.currency,
            }
            for x in items
        ],
        "discount_minor": order.discount_minor,
        "subtotal_minor": order.subtotal_minor,
        "shipping_minor": order.shipping_minor,
        "tax_included_minor": order.tax_minor,
        "total_minor": order.total_minor,
        "currency": order.currency,
    }
    if token:
        data["order_token"] = token
    return data


@router.get("/shipping-methods")
async def shipping_methods(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "items": [
            {
                "id": "complimentary",
                "name": "Complimentary" if settings.shipping_fee_minor == 0 else "Standard",
                "price_minor": settings.shipping_fee_minor,
                "currency": "INR",
            }
        ]
    }


@router.post("/checkout", status_code=201)
async def create_checkout(
    payload: CheckoutRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    x_cart_token: Annotated[str, Header()],
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    from app.modules.checkout.service import submit_checkout

    return await submit_checkout(
        payload, idempotency_key, x_cart_token, settings, session
    )


@router.get("/checkout/{checkout_id}")
async def get_checkout(
    checkout_id: UUID,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    checkout = await session.get(Checkout, checkout_id)
    if checkout is None:
        raise AppError(404, "checkout_not_found", "Checkout not found")
    await load_cart_for_checkout(session, checkout.cart_id, x_cart_token)
    return {
        "id": str(checkout.id),
        "status": checkout.status,
        "email": checkout.email,
        "shipping_address": checkout.shipping_address,
        "total_minor": checkout.total_minor,
        "currency": checkout.currency,
    }


async def load_cart_for_checkout(
    session: AsyncSession, cart_id: UUID, token: str
) -> None:
    cart = await session.get(Cart, cart_id)
    if cart is None or not secrets.compare_digest(cart.token_hash, token_hash(token)):
        raise AppError(404, "checkout_not_found", "Checkout not found")


@router.post("/checkout/{checkout_id}/shipping-address")
async def update_address(
    checkout_id: UUID,
    payload: AddressRequest,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    checkout = await session.get(Checkout, checkout_id)
    if checkout is None or checkout.status != "open":
        raise AppError(409, "checkout_not_editable", "Checkout cannot be updated")
    await load_cart_for_checkout(session, checkout.cart_id, x_cart_token)
    checkout.shipping_address = payload.shipping_address.model_dump()
    await session.commit()
    return {
        "id": str(checkout.id),
        "status": checkout.status,
        "shipping_address": checkout.shipping_address,
    }


@router.post("/checkout/{checkout_id}/payment-intent")
async def payment_intent(
    checkout_id: UUID,
    payload: PaymentRequest,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    from app.modules.payments.retry import retry_payment

    return await retry_payment(checkout_id, payload, x_cart_token, session, settings)


@router.post("/webhooks/payments/sandbox")
async def sandbox_webhook(
    payload: SandboxWebhook,
    x_sandbox_secret: Annotated[str, Header()],
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if settings.environment == "prod" or not secrets.compare_digest(
        x_sandbox_secret, settings.sandbox_payment_secret
    ):
        raise AppError(401, "invalid_webhook_signature", "Invalid webhook signature")
    from app.modules.payments.service import process_payment_event

    return await process_payment_event(session, payload)


@router.get("/orders/{order_id}")
@router.get("/orders/{order_id}/confirmation")
async def confirmation(
    order_id: UUID,
    x_order_token: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    actor: TokenPayload | None = Depends(optional_token),
) -> dict[str, object]:
    order = await session.get(Order, order_id)
    owned = bool(order and x_order_token and secrets.compare_digest(order.order_token_hash, token_hash(x_order_token)))
    if order and actor and order.customer_id:
        from app.modules.customers.models import Customer
        customer = await session.get(Customer, order.customer_id)
        owned = owned or bool(customer and customer.auth_subject == actor.sub)
    if not owned or order is None:
        raise AppError(404, "order_not_found", "Order not found")
    return await order_payload(session, order)
