from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions, verify_token
from app.db.base import uuid7
from app.db.session import get_session
from app.modules.approvals.models import Approval
from app.modules.customers.models import Address, Customer
from app.modules.customers.router import customer_for
from app.modules.orders.models import Order
from app.modules.support.models import SupportCase, CaseMessage

router = APIRouter(tags=["privacy"])


@router.get("/customers/me/export")
async def export_profile(actor: TokenPayload = Depends(verify_token), session: AsyncSession = Depends(get_session)):
    from app.modules.customers.models import ConsentRecord
    from app.modules.checkout.router import order_payload
    from app.modules.wishlist_models import Wishlist, WishlistItem
    customer = await customer_for(session, actor.sub)
    addresses = (await session.scalars(select(Address).where(Address.customer_id == customer.id))).all()
    orders = (await session.scalars(select(Order).where(Order.customer_id == customer.id))).all()
    consents = (await session.scalars(select(ConsentRecord).where(ConsentRecord.customer_id == customer.id))).all()
    cases = (await session.scalars(select(SupportCase).where(SupportCase.customer_id == customer.id))).all()
    messages = (await session.scalars(select(CaseMessage).join(SupportCase).where(SupportCase.customer_id == customer.id))).all()
    wishlist = (await session.scalars(select(WishlistItem.variant_id).join(Wishlist).where(Wishlist.customer_id == customer.id))).all()
    result = {"profile": {"display_name": customer.display_name, "email": customer.email},
              "addresses": [x.details for x in addresses], "orders": [await order_payload(session, x) for x in orders],
              "consents": [{"purpose": x.purpose, "action": x.action, "notice_version": x.notice_version} for x in consents],
              "support_cases": [{"id": str(x.id), "subject": x.subject, "status": x.status,
                  "messages": [m.body for m in messages if m.case_id == x.id]} for x in cases]}
    result["wishlist_variant_ids"] = [str(item) for item in wishlist]
    await session.commit()
    return result


@router.post("/customers/me/erasure-requests", status_code=202)
async def request_erasure(
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    existing = await session.scalar(
        select(Approval).where(
            Approval.resource_type == "customer_erasure",
            Approval.resource_id == customer.id,
            Approval.status == "pending",
        )
    )
    if existing is None:
        existing = Approval(
            resource_type="customer_erasure",
            resource_id=customer.id,
            requested_by=actor.sub,
            status="pending",
        )
        session.add(existing)
        evidence(
            session, actor.sub, "privacy.erasure_requested", "customer", customer.id
        )
        await session.commit()
    return {"id": str(existing.id), "status": existing.status}


@router.post("/privacy/erasure-requests/{approval_id}/approve")
async def approve_erasure(
    approval_id: UUID,
    actor: TokenPayload = Depends(require_permissions("privacy:approve")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    approval = await session.get(Approval, approval_id, with_for_update=True)
    if approval is None or approval.resource_type != "customer_erasure":
        raise AppError(404, "request_not_found", "Erasure request not found")
    if actor.sub == approval.requested_by:
        raise AppError(
            403, "maker_checker_violation", "A separate privacy approver is required"
        )
    if approval.status != "pending":
        raise AppError(
            409, "request_already_processed", "Erasure request already processed"
        )
    customer = await session.get(Customer, approval.resource_id, with_for_update=True)
    assert customer is not None
    customer.email, customer.display_name = None, None
    customer.auth_subject = "erased:" + str(uuid7())
    from app.modules.wishlist_models import Wishlist
    await session.execute(delete(Wishlist).where(Wishlist.customer_id == customer.id))
    await session.execute(delete(Address).where(Address.customer_id == customer.id))
    await session.execute(
        update(Order).where(Order.customer_id == customer.id).values(customer_id=None)
    )
    case_ids = select(SupportCase.id).where(SupportCase.customer_id == customer.id)
    await session.execute(
        update(CaseMessage).where(CaseMessage.case_id.in_(case_ids)).values(body=None)
    )
    await session.execute(
        update(SupportCase)
        .where(SupportCase.customer_id == customer.id)
        .values(subject="Erased")
    )
    approval.status, approval.decided_by = "approved", actor.sub
    # Commercial snapshots and consent/audit evidence retain their configured legal purpose.
    evidence(session, actor.sub, "privacy.profile_erased", "customer", customer.id)
    await session.commit()
    return {
        "id": str(approval.id),
        "status": "profile_erased",
        "identity_provider_erasure": "requires_external_action",
    }
