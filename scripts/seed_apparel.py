"""Optional apparel fixtures for development; never overwrite existing products."""

import asyncio
from sqlalchemy import select
from app.core.config import get_settings
from app.core.domain import lock_key
from app.db.session import get_session_factory
from app.modules.catalog.models import Category, Collection, Product, Variant

ROWS = [
    ("Performance T-shirt", 2490, "Black", "Essential Affair"),
    ("Training Tank", 1990, "Black", "Form"),
    ("Performance Short", 2290, "Black", "First Affair"),
    ("Performance Hoodie", 3490, "Black", "Inner Affair"),
    ("Shell Jacket", 4490, "Taupe", "Shell"),
    ("Lounge Pant", 2490, "Warm Grey", "Inner Affair"),
]


async def seed():
    if get_settings().environment != "dev":
        raise RuntimeError("Apparel fixtures are development-only")
    async with get_session_factory()() as session:
        await lock_key(session, "seed", "apparel")
        category = await session.scalar(
            select(Category).where(Category.slug == "unisex")
        )
        if category is None:
            category = Category(slug="unisex", name="Unisex")
            session.add(category)
        for index, (name, price, colour, world) in enumerate(ROWS):
            slug = name.lower().replace(" ", "-")
            if await session.scalar(select(Product.id).where(Product.slug == slug)):
                continue
            collection_slug = world.lower().replace(" ", "-")
            collection = await session.scalar(
                select(Collection).where(Collection.slug == collection_slug)
            )
            if collection is None:
                collection = Collection(slug=collection_slug, name=world)
                session.add(collection)
            product = Product(
                slug=slug,
                name=name,
                description="Development sample for storefront integration; specifications are illustrative.",
                status="published",
                featured=True,
                categories=[category],
                collections=[collection],
                variants=[
                    Variant(
                        sku=f"DEV-APPAREL-{index}-{size}",
                        slug=f"{colour.lower().replace(' ', '-')}-{size.lower()}",
                        name=f"{colour} / {size}",
                        colour=colour,
                        size=size,
                        price_minor=price * 100,
                        currency="INR",
                        status="active",
                        position=position,
                    )
                    for position, size in enumerate(["XS", "S", "M", "L", "XL"])
                ],
            )
            session.add(product)
        await session.commit()
    print("Apparel fixtures ready; existing products preserved")


if __name__ == "__main__":
    asyncio.run(seed())
