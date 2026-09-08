import hashlib
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.exceptions import AppError
from app.modules.audit.models import AuditEntry
from app.workers.models import OutboxEvent


def request_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def lock_key(session: AsyncSession, scope: str, key: str) -> None:
    lock_id = int.from_bytes(
        hashlib.sha256(f"{scope}:{key}".encode()).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


def transition(current: str, target: str, allowed: dict[str, set[str]]) -> str:
    if target not in allowed.get(current, set()):
        raise AppError(
            409, "invalid_transition", f"Cannot transition from {current} to {target}"
        )
    return target


ORDER_TRANSITIONS = {
    "pending_payment": {"confirmed", "payment_failed", "expired"},
    "payment_failed": {"pending_payment", "expired"},
    "confirmed": {"allocated", "cancelled"},
    "allocated": {"partially_fulfilled", "fulfilled", "cancelled"},
    "partially_fulfilled": {"fulfilled"},
    "fulfilled": {"delivered"},
}


def evidence(
    session: AsyncSession,
    actor: str,
    action: str,
    kind: str,
    resource_id: UUID,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session.add(
        AuditEntry(
            actor_id=actor,
            action=action,
            resource_type=kind,
            resource_id=resource_id,
            before_state=before or {},
            after_state=after or {},
            correlation_id=get_correlation_id() or "",
        )
    )


def emit(
    session: AsyncSession,
    event: str,
    kind: str,
    resource_id: UUID,
    payload: dict | None = None,
) -> None:
    session.add(
        OutboxEvent(
            event_type=event,
            aggregate_type=kind,
            aggregate_id=resource_id,
            payload=payload or {},
            correlation_id=get_correlation_id() or "",
        )
    )
