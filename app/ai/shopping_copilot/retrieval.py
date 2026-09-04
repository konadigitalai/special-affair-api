import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product, Variant

COLOURS = ("black", "ivory", "blush", "sage", "brown", "sand")
MATERIALS = ("nappa", "leather", "silk")


def parse_price_limit(message: str) -> int | None:
    match = re.search(r"(?:under|below|less than)\s*(?:₹|rs\.?|inr)?\s*([\d,]+)", message.lower())
    return int(match.group(1).replace(",", "")) * 100 if match else None


async def retrieve_products(session: AsyncSession, message: str, limit: int = 6) -> list[tuple[Product, Variant]]:
    lowered = message.lower()
    words = [word for word in re.findall(r"[a-zA-Z]{3,}", lowered) if word not in {"show", "find", "with", "under", "suitable", "product"}]
    query = select(Product, Variant).join(Variant).where(Product.status == "published", Variant.status == "active")
    colour = next((x for x in COLOURS if x in lowered), None)
    material = next((x for x in MATERIALS if x in lowered), None)
    price_limit = parse_price_limit(message)
    if colour:
        query = query.where(Variant.colour.ilike(f"%{colour}%"))
    if material:
        query = query.where(Variant.material.ilike(f"%{material}%"))
    if price_limit is not None:
        query = query.where(Variant.price_minor <= price_limit)
    if words and not colour and not material:
        query = query.where(or_(*[Product.name.ilike(f"%{word}%") for word in words], *[Product.description.ilike(f"%{word}%") for word in words]))
    rows = (await session.execute(query.order_by(Variant.price_minor).limit(limit))).all()
    return [(row[0], row[1]) for row in rows]
