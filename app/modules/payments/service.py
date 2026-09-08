from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain import emit, evidence, lock_key
from app.core.exceptions import AppError
from app.db.base import uuid7
from app.modules.checkout.models import Checkout
from app.modules.inventory.service import commit_reservations
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.payments.models import PaymentAttempt, PaymentTransaction, WebhookInbox


async def process_payment_event(session: AsyncSession, payload) -> dict[str, str]:
    await lock_key(session, "payment-event", payload.event_id)
    existing = await session.scalar(
        select(WebhookInbox).where(
            WebhookInbox.provider == "sandbox",
            WebhookInbox.provider_event_id == payload.event_id,
        )
    )
    data = payload.model_dump(mode="json")
    if existing:
        if existing.raw_payload and existing.raw_payload != data:
            raise AppError(
                409, "webhook_conflict", "Event ID reused with a different payload"
            )
        return {
            "status": "already_processed"
            if existing.processed
            else "reconciliation_required"
        }
    inbox = WebhookInbox(
        id=uuid7(),
        provider="sandbox",
        provider_event_id=payload.event_id,
        signature_verified=True,
        raw_payload=data,
    )
    session.add(inbox)
    attempt = await session.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.provider_reference == payload.provider_reference,
            PaymentAttempt.provider == "sandbox",
        )
    )
    error = None
    if attempt is None:
        error = "payment_attempt_not_found"
    else:
        order = await session.get(Order, attempt.order_id, with_for_update=True)
        await session.refresh(attempt, with_for_update=True)
        if (
            payload.amount_minor != attempt.amount_minor
            or payload.currency != attempt.currency
        ):
            error = "payment_amount_mismatch"
        elif attempt.status == payload.status:
            inbox.processed = True
        elif (
            order is None
            or order.status != "pending_payment"
            or attempt.status not in {"initiated", "pending", "requires_action"}
        ):
            error = "invalid_payment_transition"
        else:
            if payload.status == "captured":
                try:
                    await commit_reservations(session, order.id)
                except AppError:
                    error = "reservation_expired"
            if not error:
                attempt.status = payload.status
                attempt.captured_amount_minor = (
                    attempt.amount_minor if payload.status == "captured" else 0
                )
                old = order.status
                order.status = (
                    "confirmed" if payload.status == "captured" else "payment_failed"
                )
                checkout = await session.get(Checkout, order.checkout_id)
                if checkout:
                    checkout.status = (
                        "completed" if payload.status == "captured" else "open"
                    )
                session.add(
                    OrderStatusHistory(
                        order_id=order.id,
                        from_status=old,
                        to_status=order.status,
                        actor_id="payment-webhook",
                    )
                )
                session.add(
                    PaymentTransaction(
                        payment_attempt_id=attempt.id,
                        provider_event_id=payload.event_id,
                        kind=payload.status,
                        amount_minor=payload.amount_minor,
                        currency=payload.currency,
                    )
                )
                emit(
                    session,
                    "OrderConfirmed"
                    if payload.status == "captured"
                    else "PaymentFailed",
                    "order",
                    order.id,
                )
                evidence(
                    session,
                    "payment-webhook",
                    "payment." + payload.status,
                    "order",
                    order.id,
                )
                inbox.processed = True
    if error:
        inbox.processing_error = error
        emit(
            session,
            "PaymentReconciliationRequired",
            "webhook",
            inbox.id,
            {"event_id": payload.event_id, "reason": error},
        )
    await session.commit()  # Keep rejected verified events for reconciliation.
    if error:
        raise AppError(409, error, "Payment event requires reconciliation")
    return {"status": "processed"}
