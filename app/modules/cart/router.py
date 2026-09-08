import hashlib
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.db.session import get_session
from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import Product, Variant

router = APIRouter(prefix="/carts", tags=["cart"])


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ItemRequest(BaseModel):
    variant_id: UUID
    quantity: int = Field(ge=1, le=20)


class QuantityRequest(BaseModel):
    quantity: int = Field(ge=1, le=20)


async def load_cart(session: AsyncSession, cart_id: UUID, token: str) -> Cart:
    query = (
        select(Cart)
        .where(Cart.id == cart_id)
        .with_for_update()
        .options(
            selectinload(Cart.items)
            .selectinload(CartItem.variant)
            .selectinload(Variant.product)
        )
        .execution_options(populate_existing=True)
    )
    cart = await session.scalar(query)
    if (
        cart is None
        or not secrets.compare_digest(cart.token_hash, token_hash(token))
        or cart.status != "open"
    ):
        raise AppError(404, "cart_not_found", "Cart not found")
    return cart


def cart_response(cart: Cart, token: str | None = None) -> dict[str, object]:
    items = [
        {
            "id": str(x.id),
            "variant_id": str(x.variant_id),
            "product_slug": x.variant.product.slug,
            "product_name": x.variant.product.name,
            "variant_name": x.variant.name,
            "colour": x.variant.colour,
            "quantity": x.quantity,
            "unit_price_minor": x.unit_price_minor,
            "line_total_minor": x.unit_price_minor * x.quantity,
            "currency": x.currency,
        }
        for x in cart.items
    ]
    subtotal = sum(item.unit_price_minor * item.quantity for item in cart.items)
    result: dict[str, object] = {
        "id": str(cart.id),
        "status": cart.status,
        "items": items,
        "subtotal_minor": subtotal,
        "shipping_minor": 0,
        "total_minor": subtotal,
        "currency": cart.currency,
    }
    if token:
        result["cart_token"] = token
    return result


@router.post("", status_code=201)
async def create_cart(
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    token = secrets.token_urlsafe(32)
    cart = Cart(token_hash=token_hash(token))
    session.add(cart)
    await session.commit()
    return cart_response(await load_cart(session, cart.id, token), token)


@router.get("/{cart_id}")
async def get_cart(
    cart_id: UUID,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return cart_response(await load_cart(session, cart_id, x_cart_token))


@router.post("/{cart_id}/items")
async def add_item(
    cart_id: UUID,
    payload: ItemRequest,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    cart = await load_cart(session, cart_id, x_cart_token)
    variant = await session.scalar(
        select(Variant)
        .join(Product)
        .where(
            Variant.id == payload.variant_id,
            Variant.status == "active",
            Product.status == "published",
        )
    )
    if variant is None:
        raise AppError(404, "variant_not_found", "Variant not found")
    from app.modules.pricing.service import effective_price

    price = await effective_price(session, variant, cart.currency)
    existing = next((x for x in cart.items if x.variant_id == variant.id), None)
    if existing:
        existing.quantity = payload.quantity
        existing.unit_price_minor = price
    else:
        session.add(
            CartItem(
                cart_id=cart.id,
                variant_id=variant.id,
                quantity=payload.quantity,
                unit_price_minor=price,
                currency=variant.currency,
            )
        )
    await session.commit()
    return cart_response(await load_cart(session, cart.id, x_cart_token))


@router.patch("/{cart_id}/items/{item_id}")
async def update_item(
    cart_id: UUID,
    item_id: UUID,
    payload: QuantityRequest,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    cart = await load_cart(session, cart_id, x_cart_token)
    item = next((x for x in cart.items if x.id == item_id), None)
    if item is None:
        raise AppError(404, "cart_item_not_found", "Cart item not found")
    item.quantity = payload.quantity
    await session.commit()
    return cart_response(await load_cart(session, cart.id, x_cart_token))


@router.delete("/{cart_id}/items/{item_id}")
async def remove_item(
    cart_id: UUID,
    item_id: UUID,
    x_cart_token: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    cart = await load_cart(session, cart_id, x_cart_token)
    item = next((x for x in cart.items if x.id == item_id), None)
    if item is None:
        raise AppError(404, "cart_item_not_found", "Cart item not found")
    await session.delete(item)
    await session.commit()
    return cart_response(await load_cart(session, cart.id, x_cart_token))
