from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence
from app.core.exceptions import AppError
from app.core.security import TokenPayload, verify_token
from app.db.session import get_session
from app.modules.customers.router import customer_for
from app.modules.orders.models import Order
from app.modules.support.models import SupportCase, CaseMessage

router = APIRouter(prefix="/support/cases", tags=["support"])


class MessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class CaseRequest(MessageRequest):
    subject: str = Field(min_length=1, max_length=300)
    order_id: UUID | None = None


async def authorized_case(session, case_id, actor):
    case = await session.get(SupportCase, case_id)
    customer = await customer_for(session, actor.sub)
    if case is None or (
        case.customer_id != customer.id and "support:manage" not in actor.permissions
    ):
        raise AppError(404, "case_not_found", "Support case not found")
    return case


@router.post("", status_code=201)
async def create_case(
    payload: CaseRequest,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    if payload.order_id:
        order = await session.get(Order, payload.order_id)
        if order is None or order.customer_id != customer.id:
            raise AppError(404, "order_not_found", "Order not found")
    case = SupportCase(
        customer_id=customer.id,
        order_id=payload.order_id,
        subject=payload.subject,
        status="open",
    )
    session.add(case)
    await session.flush()
    session.add(CaseMessage(case_id=case.id, actor_id=actor.sub, body=payload.body))
    evidence(session, actor.sub, "support.created", "case", case.id)
    await session.commit()
    return {"id": str(case.id), "status": case.status}


@router.get("/{case_id}")
async def get_case(
    case_id: UUID,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    case = await authorized_case(session, case_id, actor)
    rows = (
        await session.scalars(
            select(CaseMessage)
            .where(CaseMessage.case_id == case.id)
            .order_by(CaseMessage.id)
        )
    ).all()
    return {
        "id": str(case.id),
        "status": case.status,
        "subject": case.subject,
        "messages": [
            {"id": str(x.id), "body": x.body, "actor_id": x.actor_id} for x in rows
        ],
    }


@router.post("/{case_id}/messages", status_code=201)
async def add_message(
    case_id: UUID,
    payload: MessageRequest,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    case = await authorized_case(session, case_id, actor)
    message = CaseMessage(case_id=case.id, actor_id=actor.sub, body=payload.body)
    session.add(message)
    evidence(session, actor.sub, "support.message_added", "case", case.id)
    await session.commit()
    return {"id": str(message.id)}
