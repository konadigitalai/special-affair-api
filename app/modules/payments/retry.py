from datetime import datetime, timezone
from sqlalchemy import select
from app.core.exceptions import AppError
from app.db.base import uuid7
from app.integrations.payments import payment_provider
from app.modules.checkout.models import Checkout
from app.modules.inventory.service import reservations_for_order
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.payments.models import PaymentAttempt


async def retry_payment(checkout_id, payload, cart_token, session, settings):
    from app.modules.checkout.router import load_cart_for_checkout

    checkout = await session.get(Checkout, checkout_id)
    if checkout is None:
        raise AppError(404, "checkout_not_found", "Checkout not found")
    await load_cart_for_checkout(session, checkout.cart_id, cart_token)
    order = await session.scalar(
        select(Order).where(Order.checkout_id == checkout_id).with_for_update()
    )
    if (
        order is None
        or order.payment_method == "cod"
        or payload.method != order.payment_method
    ):
        raise AppError(
            409, "invalid_payment_method", "Payment method must match the order"
        )
    if order.status not in {"pending_payment", "payment_failed"}:
        raise AppError(409, "order_not_payable", "Order cannot accept another payment")
    holds = await reservations_for_order(session, order.id)
    if not holds or any(
        x.status != "held" or x.expires_at <= datetime.now(timezone.utc) for x in holds
    ):
        raise AppError(
            409,
            "reservation_expired",
            "Start a new cart after the inventory hold expires",
        )
    attempt = await session.scalar(
        select(PaymentAttempt)
        .where(PaymentAttempt.order_id == order.id)
        .order_by(PaymentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None or attempt.status == "failed":
        attempt_id = uuid7()
        attempt = PaymentAttempt(
            id=attempt_id,
            order_id=order.id,
            provider=settings.payment_provider,
            method=order.payment_method,
            provider_reference=f"unassigned_{attempt_id.hex}",
            status="initiated",
            amount_minor=order.total_minor,
            currency=order.currency,
        )
        session.add(attempt)
        if order.status == "payment_failed":
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    from_status="payment_failed",
                    to_status="pending_payment",
                    actor_id="payment-retry",
                )
            )
            order.status = "pending_payment"
        checkout.status = "awaiting_payment"
    provider = payment_provider(settings)
    await session.commit()
    result = await provider.create_session(
        attempt.id,
        attempt.amount_minor,
        attempt.currency,
        attempt.method,
        str(attempt.id),
    )
    attempt = await session.get(
        PaymentAttempt, attempt.id, with_for_update=True, populate_existing=True
    )
    attempt.provider_reference = result.reference
    await session.commit()
    return {
        "attempt_id": str(attempt.id),
        "provider": attempt.provider,
        "provider_reference": result.reference,
        "client_secret": result.client_secret,
        "redirect_url": result.redirect_url,
        "status": attempt.status,
    }
