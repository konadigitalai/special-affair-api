from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions
from app.db.session import get_session
from app.modules.audit.models import AuditEntry
from app.workers.models import OutboxEvent

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/audit")
async def audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    actor: TokenPayload = Depends(require_permissions("audit:read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.scalars(
            select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(x.id),
                "actor_id": x.actor_id,
                "action": x.action,
                "resource_type": x.resource_type,
                "resource_id": str(x.resource_id),
                "correlation_id": x.correlation_id,
                "created_at": x.created_at,
            }
            for x in rows
        ]
    }


@router.get("/outbox/dead")
async def dead_events(
    actor: TokenPayload = Depends(require_permissions("operations:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.status == "dead")
            .order_by(OutboxEvent.id)
            .limit(200)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(x.id),
                "event_type": x.event_type,
                "attempts": x.attempts,
                "last_error": x.last_error,
                "aggregate_id": str(x.aggregate_id),
            }
            for x in rows
        ]
    }


@router.post("/outbox/{event_id}/replay")
async def replay_event(
    event_id: UUID,
    actor: TokenPayload = Depends(require_permissions("operations:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    event = await session.get(OutboxEvent, event_id, with_for_update=True)
    if event is None or event.status != "dead":
        raise AppError(409, "event_not_replayable", "Only dead events can be replayed")
    event.status, event.attempts, event.consecutive_errors = "pending", 0, 0
    event.last_error, event.lease_token = None, None
    event.next_attempt_at = datetime.now(timezone.utc)
    evidence(session, actor.sub, "outbox.replayed", "outbox", event.id)
    await session.commit()
    return {"id": str(event.id), "status": event.status}
