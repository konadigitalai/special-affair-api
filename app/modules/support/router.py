from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, EmailStr
import secrets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence
from app.core.exceptions import AppError
from app.core.security import TokenPayload, verify_token, optional_token
from app.modules.cart.router import token_hash
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


async def authorized_case(session, case_id, actor, case_token=None):
    case = await session.get(SupportCase, case_id)
    customer = await customer_for(session, actor.sub) if actor else None
    owned = bool(case and case_token and case.token_hash and secrets.compare_digest(case.token_hash, token_hash(case_token)))
    owned = owned or bool(case and actor and ("support:manage" in actor.permissions or (customer and case.customer_id == customer.id)))
    if not owned:
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
    actor: TokenPayload | None = Depends(optional_token),
    session: AsyncSession = Depends(get_session),
    x_case_token: str | None = Header(default=None),
) -> dict:
    case = await authorized_case(session, case_id, actor, x_case_token)
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
    actor: TokenPayload | None = Depends(optional_token),
    session: AsyncSession = Depends(get_session),
    x_case_token: str | None = Header(default=None),
) -> dict:
    case = await authorized_case(session, case_id, actor, x_case_token)
    actor_id = actor.sub if actor else "guest"
    message = CaseMessage(case_id=case.id, actor_id=actor_id, body=payload.body)
    session.add(message)
    evidence(session, actor_id, "support.message_added", "case", case.id)
    await session.commit()
    return {"id": str(message.id)}


class GuestCase(CaseRequest):
    email: EmailStr


@router.post("/guest", status_code=201)
async def guest_case(payload: GuestCase, session: AsyncSession = Depends(get_session)):
    # A guest case cannot link an unverified order. The customer can share its reference in text.
    if payload.order_id:
        raise AppError(422, "guest_order_link", "Sign in to link an order to this case")
    token = secrets.token_urlsafe(32)
    case = SupportCase(guest_email=str(payload.email).lower(), subject=payload.subject,
                       token_hash=token_hash(token), status="open")
    session.add(case)
    await session.flush()
    session.add(CaseMessage(case_id=case.id, actor_id="guest", body=payload.body))
    evidence(session, "guest", "support.created", "case", case.id)
    await session.commit()
    return {"id": str(case.id), "case_token": token, "status": case.status}


@router.get("")
async def list_cases(actor: TokenPayload = Depends(verify_token), session: AsyncSession = Depends(get_session)):
    customer = await customer_for(session, actor.sub)
    rows = (await session.scalars(select(SupportCase).where(SupportCase.customer_id == customer.id).order_by(SupportCase.id.desc()).limit(100))).all()
    await session.commit()
    return {"items": [{"id": str(x.id), "subject": x.subject, "status": x.status} for x in rows]}
