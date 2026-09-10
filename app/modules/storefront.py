"""Customer-facing flows missing from the original commerce API."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.domain import emit
from app.core.exceptions import AppError
from app.core.security import TokenPayload, optional_token
from app.db.session import get_session
from app.modules.cart.router import load_cart
from app.modules.cart.quote import quote_cart
from app.modules.checkout.router import (
    confirmation,
    order_payload,
    SandboxWebhook,
    PaymentRequest,
)
from app.modules.orders.models import Order
from app.modules.payments.models import PaymentAttempt

router = APIRouter(tags=["storefront integration"])


@router.get("/storefront/catalog")
async def storefront_catalog(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    from app.modules.catalog.service import list_published_products
    from app.modules.inventory.models import InventoryItem
    from app.modules.pricing.service import effective_price

    products = await list_published_products(session, limit=limit, offset=offset)
    ids = [v.id for p in products for v in p.variants]
    from app.modules.catalog.models import MediaMetadata
    variant_media: dict = {}
    for media in (await session.scalars(select(MediaMetadata).where(MediaMetadata.variant_id.in_(ids), MediaMetadata.media_type == "image").order_by(MediaMetadata.position))).all():
        if media.public_url:
            variant_media.setdefault(media.variant_id, []).append({"url": media.public_url})
    stock = dict(
        (
            await session.execute(
                select(
                    InventoryItem.variant_id,
                    func.sum(
                        func.greatest(
                            InventoryItem.on_hand
                            - InventoryItem.reserved
                            - InventoryItem.safety_stock,
                            0,
                        )
                    ),
                )
                .where(InventoryItem.variant_id.in_(ids))
                .group_by(InventoryItem.variant_id)
            )
        ).all()
    )
    items = []
    for product in products:
        for variant in product.variants:
            if variant.currency != "INR":
                continue
            try:
                price = await effective_price(session, variant, variant.currency)
            except AppError:
                continue
            items.append(
                {
                    "id": str(variant.id),
                    "product_id": str(product.id),
                    "slug": product.slug,
                    "name": product.name,
                    "colour": variant.colour or "",
                    "size": variant.size,
                    "category": product.collections[0].name
                    if product.collections
                    else (
                        product.categories[0].name
                        if product.categories
                        else "Collection"
                    ),
                    "categories": [x.name for x in product.categories],
                    "collections": [x.name for x in product.collections],
                    "material": variant.material or product.materials or "",
                    "care": product.care or "",
                    "description": product.description or "",
                    "development_sample": variant.sku.startswith("DEV-"),
                    "price_minor": price,
                    "currency": variant.currency,
                    "available": stock.get(variant.id, 0),
                    "media": variant_media.get(variant.id, []) + [
                        {"url": x.public_url}
                        for x in product.media
                        if x.media_type == "image" and x.public_url and (variant.id not in variant_media or x.position > 0)
                    ],
                }
            )
    return {
        "items": items,
        "has_more": len(products) == limit,
        "next_offset": offset + len(products),
    }


class CouponRequest(BaseModel):
    code: str = Field(default="", max_length=100)
    version: int | None = None


@router.get("/carts/{cart_id}/quote")
async def cart_quote(
    cart_id: UUID,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
):
    return await quote_cart(session, await load_cart(session, cart_id, x_cart_token))


@router.post("/carts/{cart_id}/coupon")
async def coupon(
    cart_id: UUID,
    payload: CouponRequest,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
):
    cart = await load_cart(session, cart_id, x_cart_token)
    if payload.version is not None and payload.version != cart.version:
        raise AppError(
            409,
            "cart_changed",
            "Your bag changed. Refresh it before applying a coupon.",
        )
    cart.coupon_code = payload.code.strip().upper() or None
    data = await quote_cart(session, cart)
    if data.get("coupon_error"):
        raise AppError(409, "coupon_unavailable", data["coupon_error"])
    cart.version += 1
    data["version"] = cart.version
    await session.commit()
    return data


@router.get("/commerce/config")
async def commerce_config(settings: Settings = Depends(get_settings)):
    sandbox = settings.environment != "prod" and settings.payment_provider == "sandbox"
    return {
        "payment_provider": settings.payment_provider,
        "sandbox_payments": sandbox and settings.sandbox_browser_payments_enabled,
        "payment_methods": ["cod", "card", "upi"] if sandbox else ["cod"],
        "return_window_days": settings.return_window_days,
    }


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: UUID,
    x_order_token: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    actor: TokenPayload | None = Depends(optional_token),
):
    from app.modules.fulfillment.router import change_order
    from app.modules.inventory.service import release
    from app.modules.fulfillment.models import Fulfillment

    await confirmation(order_id, x_order_token, session, actor)
    order = await session.get(
        Order, order_id, with_for_update=True, populate_existing=True
    )
    assert order is not None
    if order.status not in {"confirmed", "allocated"}:
        raise AppError(
            409, "cancellation_unavailable", "This order can no longer be cancelled."
        )
    change_order(session, order, "cancelled", actor.sub if actor else "guest-customer")
    await release(session, order.id)
    fulfillments = (
        await session.scalars(
            select(Fulfillment).where(Fulfillment.order_id == order.id)
        )
    ).all()
    for fulfillment in fulfillments:
        fulfillment.status = "cancelled"
    emit(session, "CancellationReconciliationRequired", "order", order.id)
    await session.commit()
    return await order_payload(session, order)


@router.post("/orders/{order_id}/retry-payment")
async def retry_order(
    order_id: UUID,
    x_cart_token: Annotated[str | None, Header()] = None,
    x_order_token: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: TokenPayload | None = Depends(optional_token),
):
    from app.modules.payments.retry import retry_payment

    await confirmation(order_id, x_order_token, session, actor)
    order = await session.get(Order, order_id)
    assert order is not None
    payment = await retry_payment(
        order.checkout_id,
        PaymentRequest(method=order.payment_method),
        x_cart_token,
        session,
        settings,
        authorized_order_id=order.id,
    )
    return {"order_id": str(order.id), "payment": payment}


@router.get("/carts/{cart_id}/checkout-result")
async def recover_checkout(
    cart_id: UUID,
    x_cart_token: Annotated[str, Header()],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    from app.modules.checkout.router import load_cart_for_checkout, derive_order_token
    from app.modules.checkout.models import IdempotencyKey, Checkout

    await load_cart_for_checkout(session, cart_id, x_cart_token)
    previous = await session.get(IdempotencyKey, "checkout:" + idempotency_key)
    order = await session.get(Order, previous.resource_id) if previous else None
    checkout = await session.get(Checkout, order.checkout_id) if order else None
    if order is None or checkout is None or checkout.cart_id != cart_id:
        raise AppError(404, "checkout_not_found", "Checkout not found")
    # Return current state, even if the HTTP response or provider handoff was lost.
    return await order_payload(
        session,
        order,
        derive_order_token(order.id, idempotency_key, settings.token_signing_secret),
    )


class SandboxAction(BaseModel):
    status: Literal["captured", "failed"]


@router.post("/orders/{order_id}/sandbox-payment/{attempt_id}")
async def sandbox_payment(
    order_id: UUID,
    attempt_id: UUID,
    payload: SandboxAction,
    x_order_token: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: TokenPayload | None = Depends(optional_token),
):
    if (
        settings.environment == "prod"
        or not settings.sandbox_browser_payments_enabled
        or settings.payment_provider != "sandbox"
    ):
        raise AppError(404, "not_found", "Not found")
    await confirmation(order_id, x_order_token, session, actor)
    attempt = await session.get(PaymentAttempt, attempt_id)
    if (
        attempt is None
        or attempt.order_id != order_id
        or attempt.provider != "sandbox"
        or not attempt.provider_reference.startswith("sandbox_")
    ):
        raise AppError(404, "payment_not_found", "Payment not found")
    from app.modules.payments.service import process_payment_event

    return await process_payment_event(
        session,
        SandboxWebhook(
            event_id=f"browser:{attempt.id}:{payload.status}",
            provider_reference=attempt.provider_reference,
            amount_minor=attempt.amount_minor,
            currency=attempt.currency,
            status=payload.status,
        ),
    )
