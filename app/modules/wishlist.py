"""Token-owned guest wishlists and account wishlist merging."""
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wishlist_models import Wishlist, WishlistItem
from app.db.session import get_session
from app.core.domain import lock_key
from app.core.exceptions import AppError
from app.core.security import TokenPayload, optional_token
from app.modules.cart.router import token_hash
from app.modules.catalog.models import Product, Variant
from app.modules.customers.models import Customer
from app.modules.customers.router import customer_for


router = APIRouter(tags=["wishlist"])


async def owned(session: AsyncSession, wishlist_id: UUID, token: str | None, actor: TokenPayload | None):
    await lock_key(session, "wishlist", str(wishlist_id))
    row = await session.get(Wishlist, wishlist_id)
    customer = await session.scalar(select(Customer).where(Customer.auth_subject == actor.sub)) if actor else None
    allowed = row and ((customer and row.customer_id == customer.id) or (not row.customer_id and token and secrets.compare_digest(row.token_hash, token_hash(token))))
    if not allowed:
        raise AppError(404, "wishlist_not_found", "Wishlist not found")
    return row


async def response(session: AsyncSession, row: Wishlist):
    items = list((await session.scalars(select(WishlistItem.variant_id).where(WishlistItem.wishlist_id == row.id).order_by(WishlistItem.created_at))).all())
    return {"id": str(row.id), "variant_ids": [str(i) for i in items]}


@router.post("/wishlists")
async def create_wishlist(actor: TokenPayload | None = Depends(optional_token), session: AsyncSession = Depends(get_session)):
    customer = await customer_for(session, actor.sub) if actor else None
    row = await session.scalar(select(Wishlist).where(Wishlist.customer_id == customer.id)) if customer else None
    token = secrets.token_urlsafe(32)
    if row is None:
        row = Wishlist(token_hash=token_hash(token), customer_id=customer.id if customer else None)
        session.add(row)
        await session.flush()
    result = await response(session, row)
    if not customer:
        result["wishlist_token"] = token
    await session.commit()
    return result


@router.get("/wishlists/{wishlist_id}")
async def get_wishlist(wishlist_id: UUID, x_wishlist_token: Annotated[str | None, Header()] = None, actor: TokenPayload | None = Depends(optional_token), session: AsyncSession = Depends(get_session)):
    return await response(session, await owned(session, wishlist_id, x_wishlist_token, actor))


@router.put("/wishlists/{wishlist_id}/items/{variant_id}")
async def add_item(wishlist_id: UUID, variant_id: UUID, x_wishlist_token: Annotated[str | None, Header()] = None, actor: TokenPayload | None = Depends(optional_token), session: AsyncSession = Depends(get_session)):
    row = await owned(session, wishlist_id, x_wishlist_token, actor)
    variant = await session.scalar(select(Variant).join(Product).where(Variant.id == variant_id, Variant.status == "active", Product.status == "published"))
    if variant is None:
        raise AppError(404, "product_not_found", "Product not found")
    if await session.get(WishlistItem, (row.id, variant.id)) is None:
        count = await session.scalar(select(func.count()).select_from(WishlistItem).where(WishlistItem.wishlist_id == row.id))
        if (count or 0) >= 100:
            raise AppError(422, "wishlist_full", "Your wishlist can hold up to 100 pieces")
        session.add(WishlistItem(wishlist_id=row.id, variant_id=variant.id))
        await session.flush()
    result = await response(session, row)
    await session.commit()
    return result


@router.delete("/wishlists/{wishlist_id}/items/{variant_id}")
async def remove_item(wishlist_id: UUID, variant_id: UUID, x_wishlist_token: Annotated[str | None, Header()] = None, actor: TokenPayload | None = Depends(optional_token), session: AsyncSession = Depends(get_session)):
    row = await owned(session, wishlist_id, x_wishlist_token, actor)
    await session.execute(delete(WishlistItem).where(WishlistItem.wishlist_id == row.id, WishlistItem.variant_id == variant_id))
    result = await response(session, row)
    await session.commit()
    return result


@router.post("/wishlists/{wishlist_id}/merge")
async def merge_wishlist(wishlist_id: UUID, x_wishlist_token: Annotated[str | None, Header()] = None, actor: TokenPayload | None = Depends(optional_token), session: AsyncSession = Depends(get_session)):
    if actor is None:
        raise AppError(401, "sign_in_required", "Sign in to save your wishlist to your account")
    customer = await customer_for(session, actor.sub)
    source = await owned(session, wishlist_id, x_wishlist_token, actor)
    target = await session.scalar(select(Wishlist).where(Wishlist.customer_id == customer.id))
    if target is None:
        source.customer_id = customer.id
        target = source
    elif target.id != source.id:
        await lock_key(session, "wishlist", str(target.id))
        ids = (await response(session, source))["variant_ids"]
        current = set((await response(session, target))["variant_ids"])
        for variant in ids:
            if variant not in current and len(current) < 100:
                session.add(WishlistItem(wishlist_id=target.id, variant_id=UUID(variant)))
                current.add(variant)
        await session.delete(source)
    await session.flush()
    result = await response(session, target)
    await session.commit()
    return result
