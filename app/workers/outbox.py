import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.core.correlation import correlation_id_var
from app.core.domain import evidence
from app.db.base import uuid7
from app.integrations.payments import payment_provider
from app.modules.payments.models import PaymentAttempt
from app.modules.returns.models import Refund, Return
from app.workers.models import OutboxEvent

BACKOFF = (1, 5, 30, 120, 600, 3600, 3600, 3600)


async def claim(session: AsyncSession, lease_seconds: int) -> OutboxEvent | None:
    now = datetime.now(timezone.utc)
    earlier = aliased(OutboxEvent)
    blocked = exists(
        select(earlier.id).where(
            earlier.aggregate_type == OutboxEvent.aggregate_type,
            earlier.aggregate_id == OutboxEvent.aggregate_id,
            earlier.id < OutboxEvent.id,
            earlier.status != "published",
        )
    )
    query = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status.in_(["pending", "processing"]),
            OutboxEvent.next_attempt_at <= now,
            ~blocked,
        )
        .order_by(OutboxEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    event = await session.scalar(query)
    if event:
        event.status = "processing"
        event.attempts += 1
        event.lease_token = uuid7()
        event.next_attempt_at = now + timedelta(seconds=lease_seconds)
    await session.commit()
    return event


async def refund_handler(
    event: OutboxEvent, factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        refund = await session.get(Refund, event.aggregate_id)
        if refund is None:
            raise ValueError("Refund missing")
        if refund.status == "refunded":
            return
        if refund.status != "refund_pending":
            raise ValueError("Refund is not authorized for execution")
        attempt = await session.get(PaymentAttempt, refund.payment_attempt_id)
        assert attempt is not None
        reference, amount, currency, refund_id, attempt_id = (
            attempt.provider_reference,
            refund.amount_minor,
            refund.currency,
            refund.id,
            attempt.id,
        )
    # No database transaction during the provider call. Refund UUID is its idempotency key.
    provider_reference = await payment_provider(settings).refund(
        reference, amount, currency, str(refund_id)
    )
    async with factory() as session:
        attempt = await session.get(PaymentAttempt, attempt_id, with_for_update=True)
        refund = await session.get(Refund, refund_id, with_for_update=True)
        assert attempt is not None and refund is not None
        if refund.status == "refunded":
            return
        # Sandbox settles synchronously. A live adapter must settle from a verified webhook.
        if settings.payment_provider != "sandbox":
            raise ValueError("Live refund settlement must use provider webhooks")
        attempt.refunded_amount_minor += amount
        attempt.status = (
            "refunded"
            if attempt.refunded_amount_minor == attempt.captured_amount_minor
            else "partially_refunded"
        )
        refund.provider_reference = provider_reference
        refund.status = "refunded"
        if refund.return_id:
            rma = await session.get(Return, refund.return_id)
            if rma:
                rma.status = "refunded"
        evidence(
            session,
            "worker",
            "refund.settled",
            "refund",
            refund.id,
            after={"amount_minor": amount},
        )
        await session.commit()


async def handle(
    event: OutboxEvent, factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    if event.event_type == "RefundRequested":
        await refund_handler(event, factory, settings)
    elif event.event_type in {
        "OrderConfirmed",
        "CheckoutExpired",
        "PaymentFailed",
        "OrderStatusChanged",
    }:
        # Durable local receipt. No email/shipping delivery is implied by this handler.
        async with factory() as session:
            from app.modules.audit.models import AuditEntry

            prior = await session.scalar(
                select(AuditEntry.id).where(
                    AuditEntry.resource_id == event.id,
                    AuditEntry.action == "event.received",
                )
            )
            if prior is None:
                evidence(
                    session,
                    "worker",
                    "event.received",
                    "outbox",
                    event.id,
                    after={"event_type": event.event_type},
                )
                await session.commit()
    else:
        # Unknown and reconciliation events require an operator; never acknowledge silently.
        raise NotImplementedError(event.event_type)


async def process_one(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> bool:
    async with factory() as session:
        event = await claim(session, settings.worker_lease_seconds)
    if event is None:
        return False
    error = None
    correlation_token = correlation_id_var.set(event.correlation_id)
    try:
        await asyncio.wait_for(
            handle(event, factory, settings), timeout=settings.worker_lease_seconds / 2
        )
    except Exception as exc:
        error = (
            type(exc).__name__
        )  # Never persist provider exception bodies containing credentials/PII.
    finally:
        correlation_id_var.reset(correlation_token)
    async with factory() as session:
        current = await session.get(OutboxEvent, event.id, with_for_update=True)
        if current is None or current.lease_token != event.lease_token:
            return True
        if error is None:
            current.status = "published"
        else:
            current.consecutive_errors = (
                current.consecutive_errors + 1 if current.last_error == error else 1
            )
            current.last_error = error
            current.status = (
                "dead"
                if current.attempts >= 8 or current.consecutive_errors >= 3
                else "pending"
            )
            current.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                seconds=BACKOFF[min(current.attempts - 1, 7)]
            )
            if current.status == "dead":
                structlog.get_logger().error(
                    "outbox_dead",
                    event_id=str(current.id),
                    event_type=current.event_type,
                    error_class=error,
                )
        await session.commit()
    return True
