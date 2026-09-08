from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.domain import emit, evidence, lock_key, request_digest
from app.core.exceptions import AppError
from app.db.base import uuid7
from app.integrations.payments import payment_provider
from app.modules.cart.router import load_cart, token_hash
from app.modules.checkout.models import Checkout, IdempotencyKey
from app.modules.inventory.service import commit_reservations, reserve
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.payments.models import PaymentAttempt
from app.modules.pricing.service import effective_price, included_tax
from app.modules.promotions.service import best_promotion, line_discount


async def submit_checkout(
    payload, key: str, cart_token: str, settings: Settings, session: AsyncSession
) -> dict:
    from app.modules.checkout.router import (
        derive_order_token,
        order_number,
        order_payload,
    )

    if not key.strip() or len(key) > 160:
        raise AppError(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must contain 1 to 160 characters",
        )
    # Scope key in storage while preserving the legacy table's primary key for rolling upgrades.
    stored_key = f"checkout:{key}"
    digest = request_digest(payload.model_dump(mode="json"))
    await lock_key(session, "checkout", key)
    previous = await session.get(IdempotencyKey, stored_key)
    if previous:
        from app.modules.checkout.router import load_cart_for_checkout

        await load_cart_for_checkout(session, payload.cart_id, cart_token)
        if previous.request_hash != digest:
            raise AppError(
                409,
                "idempotency_conflict",
                "Idempotency key was used with a different request",
            )
        if previous.response_body:
            return previous.response_body
        order = await session.get(Order, previous.resource_id)
        if order is None:
            raise AppError(
                409, "idempotency_incomplete", "Previous request needs reconciliation"
            )
        attempt = await session.scalar(
            select(PaymentAttempt)
            .where(PaymentAttempt.order_id == order.id)
            .order_by(PaymentAttempt.created_at.desc())
            .limit(1)
        )
        if attempt and order.status not in {"pending_payment", "confirmed"}:
            raise AppError(
                409,
                "checkout_not_recoverable",
                "Checkout expired or failed; use the payment retry flow or start a new cart",
            )
        raw_token = derive_order_token(order.id, key, settings.token_signing_secret)
        await session.commit()
    else:
        cart = await load_cart(session, payload.cart_id, cart_token)
        if not cart.items:
            raise AppError(409, "empty_cart", "Cart is empty")
        if payload.payment_method != "cod":
            payment_provider(
                settings
            )  # Fail before reserving if provider is unavailable.
        for item in cart.items:
            if (
                item.variant.status != "active"
                or item.variant.product.status != "published"
            ):
                raise AppError(
                    409, "variant_not_sellable", "A cart item is no longer available"
                )
            item.unit_price_minor = await effective_price(
                session, item.variant, cart.currency
            )
            item.currency = cart.currency
        promotion = await best_promotion(session, cart.currency)
        discounts = {
            x.variant_id: line_discount(
                x.unit_price_minor * x.quantity, promotion.percent_off
            )
            if promotion
            else 0
            for x in cart.items
        }
        discount_total = sum(discounts.values())
        subtotal = sum(x.unit_price_minor * x.quantity for x in cart.items)
        tax = sum(
            included_tax(
                x.unit_price_minor * x.quantity - discounts[x.variant_id],
                settings.tax_rate_percent,
            )
            for x in cart.items
        )
        checkout = Checkout(
            cart_id=cart.id,
            status="awaiting_payment",
            email=str(payload.email).lower(),
            phone=payload.phone,
            shipping_address=payload.shipping_address.model_dump(),
            subtotal_minor=subtotal,
            shipping_minor=settings.shipping_fee_minor,
            tax_minor=tax,
            total_minor=subtotal - discount_total + settings.shipping_fee_minor,
            currency=cart.currency,
        )
        session.add(checkout)
        await session.flush()
        order_id = uuid7()
        raw_token = derive_order_token(order_id, key, settings.token_signing_secret)
        order = Order(
            id=order_id,
            checkout_id=checkout.id,
            customer_id=cart.customer_id,
            order_number=order_number(order_id),
            order_token_hash=token_hash(raw_token),
            email=checkout.email,
            phone=checkout.phone,
            shipping_address=checkout.shipping_address,
            status="pending_payment",
            payment_method=payload.payment_method,
            discount_minor=discount_total,
            subtotal_minor=subtotal,
            shipping_minor=checkout.shipping_minor,
            tax_minor=tax,
            total_minor=checkout.total_minor,
            currency=cart.currency,
        )
        session.add(order)
        await session.flush()
        for item in cart.items:
            session.add(
                OrderItem(
                    order_id=order.id,
                    variant_id=item.variant.id,
                    product_name=item.variant.product.name,
                    variant_name=item.variant.name,
                    sku=item.variant.sku,
                    quantity=item.quantity,
                    unit_price_minor=item.unit_price_minor,
                    line_discount_minor=discounts[item.variant_id],
                    line_tax_minor=included_tax(
                        item.unit_price_minor * item.quantity
                        - discounts[item.variant_id],
                        settings.tax_rate_percent,
                    ),
                    promotion_id=promotion.id if promotion else None,
                    line_total_minor=item.unit_price_minor * item.quantity
                    - discounts[item.variant_id],
                    currency=item.currency,
                )
            )
        await reserve(
            session,
            order.id,
            {item.variant_id: item.quantity for item in cart.items},
            settings.reservation_ttl_minutes,
        )
        cart.status = "converted"
        previous = IdempotencyKey(
            key=stored_key,
            operation="checkout",
            request_hash=digest,
            resource_id=order.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(previous)
        attempt = None
        if payload.payment_method == "cod":
            await session.flush()
            await commit_reservations(session, order.id)
            order.status = "confirmed"
            checkout.status = "completed"
            emit(session, "OrderConfirmed", "order", order.id)
        else:
            attempt_id = uuid7()
            attempt = PaymentAttempt(
                id=attempt_id,
                order_id=order.id,
                provider=settings.payment_provider,
                method=payload.payment_method,
                provider_reference=f"unassigned_{attempt_id.hex}",
                status="initiated",
                amount_minor=order.total_minor,
                currency=order.currency,
            )
            session.add(attempt)
        session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=None,
                to_status=order.status,
                actor_id="checkout",
            )
        )
        evidence(session, "checkout", "checkout.prepared", "order", order.id)
        await session.commit()  # Phase A complete: no locks held across provider work.

    payment = None
    if attempt:
        provider_session = await payment_provider(settings).create_session(
            attempt.id,
            attempt.amount_minor,
            attempt.currency,
            attempt.method,
            str(attempt.id),
        )
        # The external call above runs without an open transaction.
        await lock_key(session, "checkout", key)
        refreshed_key = await session.get(
            IdempotencyKey, stored_key, populate_existing=True
        )
        if refreshed_key and refreshed_key.response_body:
            return refreshed_key.response_body
        attempt = await session.get(
            PaymentAttempt, attempt.id, with_for_update=True, populate_existing=True
        )
        assert attempt is not None
        attempt.provider_reference = provider_session.reference
        payment = {
            "attempt_id": str(attempt.id),
            "provider": attempt.provider,
            "provider_reference": provider_session.reference,
            "client_secret": provider_session.client_secret,
            "redirect_url": provider_session.redirect_url,
            "status": attempt.status,
        }
    result = await order_payload(session, order, raw_token)
    result["checkout_id"] = str(order.checkout_id)
    if payment:
        result["payment"] = payment
    previous.response_body = result
    previous.response_status = 201
    await session.commit()
    return result
