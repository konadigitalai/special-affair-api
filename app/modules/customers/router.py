import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain import evidence, lock_key
from app.core.exceptions import AppError
from app.core.security import TokenPayload, verify_token
from app.db.session import get_session
from app.modules.cart.models import Cart, CartItem
from app.modules.cart.router import cart_response, load_cart, token_hash
from app.modules.checkout.router import Address as AddressSchema
from app.modules.customers.models import Address, ConsentRecord, Customer
from app.modules.inventory.models import InventoryItem
from app.modules.pricing.service import effective_price

router = APIRouter(tags=["customers"])


async def customer_for(session: AsyncSession, subject: str) -> Customer:
    await lock_key(session, "customer", subject)
    customer = await session.scalar(
        select(Customer).where(Customer.auth_subject == subject)
    )
    if customer is None:
        customer = Customer(auth_subject=subject)
        session.add(customer)
        await session.flush()
    return customer


class Profile(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: EmailStr


class Consent(BaseModel):
    purpose: str = Field(min_length=1, max_length=100)
    granted: bool
    notice_version: str = Field(min_length=1, max_length=100)


@router.get("/customers/me")
async def get_profile(
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    await session.commit()
    return {
        "id": str(customer.id),
        "display_name": customer.display_name,
        "email": customer.email,
    }


@router.get("/customers/me/orders")
async def customer_orders(
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.modules.orders.models import Order

    customer = await customer_for(session, actor.sub)
    rows = (
        await session.scalars(
            select(Order)
            .where(Order.customer_id == customer.id)
            .order_by(Order.id.desc())
            .limit(100)
        )
    ).all()
    await session.commit()
    return {
        "items": [
            {
                "id": str(x.id),
                "order_number": x.order_number,
                "status": x.status,
                "total_minor": x.total_minor,
                "currency": x.currency,
            }
            for x in rows
        ]
    }


@router.post("/customers/me/cart")
async def saved_cart(
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    cart = await session.scalar(
        select(Cart)
        .where(Cart.customer_id == customer.id, Cart.status == "open")
        .with_for_update()
    )
    token = secrets.token_urlsafe(32)
    if cart is None:
        cart = Cart(customer_id=customer.id, token_hash=token_hash(token))
        session.add(cart)
    else:
        cart.token_hash = token_hash(token)
    await session.commit()
    return cart_response(await load_cart(session, cart.id, token), token)


@router.put("/customers/me")
async def update_profile(
    payload: Profile,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    customer.display_name, customer.email = payload.display_name, str(payload.email)
    evidence(session, actor.sub, "customer.updated", "customer", customer.id)
    await session.commit()
    return {"id": str(customer.id), **payload.model_dump()}


@router.post("/customers/me/addresses", status_code=201)
async def add_address(
    payload: AddressSchema,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    address = Address(customer_id=customer.id, details=payload.model_dump())
    session.add(address)
    await session.commit()
    return {"id": str(address.id), **address.details}


@router.get("/customers/me/addresses")
async def addresses(
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    rows = (
        await session.scalars(select(Address).where(Address.customer_id == customer.id))
    ).all()
    await session.commit()
    return {"items": [{"id": str(row.id), **row.details} for row in rows]}


@router.post("/customers/me/consents", status_code=201)
async def add_consent(
    payload: Consent,
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    record = ConsentRecord(
        customer_id=customer.id,
        email=customer.email or "",
        purpose=payload.purpose,
        action="granted" if payload.granted else "withdrawn",
        notice_version=payload.notice_version,
    )
    session.add(record)
    evidence(
        session,
        actor.sub,
        "consent.recorded",
        "customer",
        customer.id,
        after=payload.model_dump(),
    )
    await session.commit()
    return {"id": str(record.id), **payload.model_dump()}


@router.delete("/customers/me/addresses/{address_id}")
async def delete_address(address_id: UUID, actor: TokenPayload = Depends(verify_token), session: AsyncSession = Depends(get_session)):
    customer = await customer_for(session, actor.sub)
    address = await session.get(Address, address_id)
    if address is None or address.customer_id != customer.id:
        raise AppError(404, "address_not_found", "Address not found")
    await session.delete(address)
    await session.commit()
    return {"deleted": True}


@router.post("/carts/{cart_id}/merge")
async def merge_cart(
    cart_id: UUID,
    x_cart_token: Annotated[str, Header()],
    actor: TokenPayload = Depends(verify_token),
    session: AsyncSession = Depends(get_session),
) -> dict:
    customer = await customer_for(session, actor.sub)
    guest = await load_cart(session, cart_id, x_cart_token)
    if guest.customer_id and guest.customer_id != customer.id:
        raise AppError(404, "cart_not_found", "Cart not found")
    saved = await session.scalar(
        select(Cart)
        .where(
            Cart.customer_id == customer.id, Cart.status == "open", Cart.id != guest.id
        )
        .with_for_update()
    )
    changes = []
    if saved:
        # A fresh token is returned only after proving both customer and guest ownership.
        new_token = secrets.token_urlsafe(32)
        saved.token_hash = token_hash(new_token)
        await session.flush()
        target = await load_cart(session, saved.id, new_token)
        quantities = {x.variant_id: x.quantity for x in target.items}
        for item in guest.items:
            quantities[item.variant_id] = max(
                quantities.get(item.variant_id, 0), item.quantity
            )
        sources = {x.variant_id: x for x in [*guest.items, *target.items]}
        existing = {x.variant_id: x for x in target.items}
        guest.status = "expired"
    else:
        target, new_token = guest, x_cart_token
        target.customer_id = customer.id
        quantities = {x.variant_id: x.quantity for x in target.items}
        sources = existing = {x.variant_id: x for x in target.items}
    for variant_id, requested in sorted(quantities.items()):
        source = sources[variant_id]
        stock = (
            await session.scalars(
                select(InventoryItem)
                .where(InventoryItem.variant_id == variant_id)
                .order_by(InventoryItem.id)
                .with_for_update()
            )
        ).all()
        quantity = min(requested, sum(x.available for x in stock), 20)
        try:
            if (
                source.variant.status != "active"
                or source.variant.product.status != "published"
            ):
                raise AppError(409, "unavailable", "Unavailable")
            price = await effective_price(session, source.variant, target.currency)
        except AppError:
            quantity, price = 0, 0
        if quantity != requested:
            changes.append(
                {
                    "variant_id": str(variant_id),
                    "requested_quantity": requested,
                    "quantity": quantity,
                }
            )
        target_item = existing.get(variant_id)
        if quantity == 0:
            if target_item:
                await session.delete(target_item)
        elif target_item:
            target_item.quantity, target_item.unit_price_minor, target_item.currency = (
                quantity,
                price,
                target.currency,
            )
        else:
            session.add(
                CartItem(
                    cart_id=target.id,
                    variant_id=variant_id,
                    quantity=quantity,
                    unit_price_minor=price,
                    currency=target.currency,
                )
            )
    evidence(session, actor.sub, "cart.merged", "cart", target.id)
    target.version += 1
    await session.commit()
    result = cart_response(await load_cart(session, target.id, new_token), new_token)
    result["adjustments"] = changes
    return result
