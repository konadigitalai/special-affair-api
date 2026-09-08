"""Purge eligible non-financial payloads in bounded batches; retain error evidence."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.modules.payments.models import WebhookInbox
from app.modules.support.models import CaseMessage


async def prune_payloads(session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    # 13 calendar months, clamped at the end of the destination month.
    import calendar

    year, month = now.year, now.month - 13
    while month < 1:
        year, month = year - 1, month + 12
    cutoff = now.replace(
        year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])
    )
    inbox = (
        await session.scalars(
            select(WebhookInbox)
            .where(
                WebhookInbox.created_at < cutoff,
                WebhookInbox.processed.is_(True),
                WebhookInbox.raw_payload != {},
            )
            .order_by(WebhookInbox.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in inbox:
        # Keep the event ID as a durable deduplication tombstone.
        row.raw_payload = {}
    messages = (
        await session.scalars(
            select(CaseMessage)
            .where(
                CaseMessage.created_at < now - timedelta(days=1096),
                CaseMessage.body.is_not(None),
            )
            .order_by(CaseMessage.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for message in messages:
        message.body = None
    return {"webhooks": len(inbox), "messages": len(messages)}
