from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.domain import emit, evidence, lock_key, request_digest, transition
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions, optional_token
from app.db.base import uuid7
from app.db.session import get_session
from app.modules.approvals.models import Approval
from app.modules.checkout.models import IdempotencyKey
from app.modules.checkout.router import confirmation
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.payments.models import PaymentAttempt
from app.modules.returns.models import Refund, Return, ReturnItem

router = APIRouter(tags=["returns and refunds"])


class ReturnLine(BaseModel):
    order_item_id: UUID
    quantity: int = Field(gt=0)


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID
    reason: str = Field(min_length=3, max_length=1000)
    items: list[ReturnLine] = Field(min_length=1, max_length=100)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_attempt_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    return_id: UUID | None = None


class Decision(BaseModel):
    approved: bool


class ReturnTransition(BaseModel):
    status: Literal["approved", "rejected", "in_transit", "received", "inspected"]


@router.post("/returns", status_code=201)
async def request_return(
    payload: ReturnRequest,
    x_order_token: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: TokenPayload | None = Depends(optional_token),
) -> dict:
    await confirmation(payload.order_id, x_order_token, session, actor)
    order = await session.get(Order, payload.order_id, with_for_update=True)
    if order is None or order.status != "delivered":
        raise AppError(409, "return_ineligible", "Only delivered orders are eligible")
    delivered_at = await session.scalar(
        select(func.max(OrderStatusHistory.created_at)).where(
            OrderStatusHistory.order_id == order.id,
            OrderStatusHistory.to_status == "delivered",
        )
    )
    if not delivered_at or delivered_at < datetime.now(timezone.utc) - timedelta(
        days=settings.return_window_days
    ):
        raise AppError(409, "return_window_closed", "Return window is closed")
    if len({x.order_item_id for x in payload.items}) != len(payload.items):
        raise AppError(422, "duplicate_return_item", "Return items must be unique")
    result = Return(order_id=order.id, reason=payload.reason, status="requested")
    session.add(result)
    await session.flush()
    for line in payload.items:
        item = await session.get(OrderItem, line.order_item_id)
        used = await session.scalar(
            select(func.coalesce(func.sum(ReturnItem.quantity), 0))
            .join(Return)
            .where(
                ReturnItem.order_item_id == line.order_item_id,
                Return.status != "rejected",
            )
        )
        if (
            item is None
            or item.order_id != order.id
            or line.quantity + (used or 0) > item.quantity
        ):
            raise AppError(
                409, "invalid_return_quantity", "Return exceeds purchased quantity"
            )
        session.add(
            ReturnItem(
                return_id=result.id, order_item_id=item.id, quantity=line.quantity
            )
        )
    evidence(session, "customer", "return.requested", "return", result.id)
    await session.commit()
    return {"id": str(result.id), "status": result.status}


@router.post("/returns/{return_id}/status")
async def advance_return(
    return_id: UUID,
    payload: ReturnTransition,
    actor: TokenPayload = Depends(require_permissions("return:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    item = await session.get(Return, return_id, with_for_update=True)
    if item is None:
        raise AppError(404, "return_not_found", "Return not found")
    old = item.status
    item.status = transition(
        old,
        payload.status,
        {
            "requested": {"approved", "rejected"},
            "approved": {"in_transit"},
            "in_transit": {"received"},
            "received": {"inspected"},
            "inspected": {"rejected"},
        },
    )
    evidence(
        session,
        actor.sub,
        "return.transition",
        "return",
        item.id,
        {"status": old},
        {"status": item.status},
    )
    await session.commit()
    return {"id": str(item.id), "status": item.status}


@router.post("/refunds", status_code=201)
async def request_refund(
    payload: RefundRequest,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
    actor: TokenPayload = Depends(require_permissions("refund:request")),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    if "refund:approve" in actor.permissions:
        raise AppError(
            403,
            "conflicting_permissions",
            "Refund requester cannot also hold refund approval permission",
        )
    key = "refund:" + idempotency_key
    digest = request_digest({**payload.model_dump(mode="json"), "actor": actor.sub})
    await lock_key(session, "refund", key)
    previous = await session.get(IdempotencyKey, key)
    if previous:
        if previous.request_hash != digest:
            raise AppError(
                409,
                "idempotency_conflict",
                "Idempotency key reused with different request",
            )
        return previous.response_body or {"id": str(previous.resource_id)}
    attempt = await session.get(
        PaymentAttempt, payload.payment_attempt_id, with_for_update=True
    )
    if (
        attempt is None
        or attempt.currency != payload.currency
        or attempt.status not in {"captured", "partially_refunded"}
    ):
        raise AppError(409, "payment_not_refundable", "Payment is not refundable")
    reserved = await session.scalar(
        select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
            Refund.payment_attempt_id == attempt.id, Refund.status != "rejected"
        )
    )
    if (reserved or 0) + payload.amount_minor > attempt.captured_amount_minor:
        raise AppError(
            409,
            "refund_exceeds_capture",
            "Refund exceeds captured and unreserved value",
        )
    if payload.return_id:
        rma = await session.get(Return, payload.return_id, with_for_update=True)
        if rma is None or rma.order_id != attempt.order_id or rma.status != "inspected":
            raise AppError(
                409,
                "return_not_refundable",
                "Return must pass inspection before refund",
            )
        eligible = await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.floor(
                            OrderItem.line_total_minor
                            * ReturnItem.quantity
                            / OrderItem.quantity
                        )
                    ),
                    0,
                )
            )
            .join(ReturnItem, ReturnItem.order_item_id == OrderItem.id)
            .where(ReturnItem.return_id == rma.id)
        )
        return_reserved = await session.scalar(
            select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                Refund.return_id == rma.id, Refund.status != "rejected"
            )
        )
        if payload.amount_minor + (return_reserved or 0) > (eligible or 0):
            raise AppError(
                409,
                "refund_exceeds_return",
                "Refund exceeds returned merchandise value",
            )
    refund = Refund(
        id=uuid7(),
        payment_attempt_id=attempt.id,
        return_id=payload.return_id,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        requested_by=actor.sub,
        status="refund_pending",
    )
    if payload.amount_minor > settings.refund_approval_threshold_minor:
        approval = Approval(
            id=uuid7(),
            resource_type="refund",
            resource_id=refund.id,
            requested_by=actor.sub,
            status="pending",
        )
        session.add(approval)
        await session.flush()
        refund.approval_id = approval.id
        refund.status = "awaiting_approval"
    if payload.return_id and refund.status == "refund_pending":
        assert rma is not None
        rma.status = "refund_pending"
    session.add(refund)
    if refund.status == "refund_pending":
        emit(session, "RefundRequested", "refund", refund.id)
    result = {
        "id": str(refund.id),
        "status": refund.status,
        "approval_id": str(refund.approval_id) if refund.approval_id else None,
    }
    session.add(
        IdempotencyKey(
            key=key,
            operation="refund",
            request_hash=digest,
            resource_id=refund.id,
            response_body=result,
            response_status=201,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    )
    evidence(
        session,
        actor.sub,
        "refund.requested",
        "refund",
        refund.id,
        after={"amount_minor": refund.amount_minor},
    )
    await session.commit()
    return result


@router.post("/approvals/{approval_id}/decision")
async def decide_refund(
    approval_id: UUID,
    payload: Decision,
    actor: TokenPayload = Depends(require_permissions("refund:approve")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    approval = await session.get(Approval, approval_id, with_for_update=True)
    if approval is None or approval.resource_type != "refund":
        raise AppError(404, "approval_not_found", "Approval not found")
    if actor.sub == approval.requested_by or "refund:request" in actor.permissions:
        raise AppError(
            403,
            "maker_checker_violation",
            "A different approver with separate permissions is required",
        )
    if approval.status != "pending":
        raise AppError(409, "approval_already_decided", "Approval was already decided")
    refund = await session.get(Refund, approval.resource_id, with_for_update=True)
    assert refund is not None
    approval.status = "approved" if payload.approved else "rejected"
    approval.decided_by = actor.sub
    refund.status = "refund_pending" if payload.approved else "rejected"
    if payload.approved:
        if refund.return_id:
            rma = await session.get(Return, refund.return_id, with_for_update=True)
            if rma is None or rma.status != "inspected":
                raise AppError(
                    409, "return_not_refundable", "Return must still be inspected"
                )
            rma.status = "refund_pending"
        emit(session, "RefundRequested", "refund", refund.id)
    evidence(session, actor.sub, "approval." + approval.status, "approval", approval.id)
    await session.commit()
    return {"id": str(approval.id), "status": approval.status}
