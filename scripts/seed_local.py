"""Idempotent development seed data. Never run against production."""
import asyncio

from sqlalchemy import select

from app.db.session import get_session_factory
from app.modules.catalog.models import Category, Collection, Product, Variant
from app.modules.content.models import ContentPage, NavigationItem, StorefrontSetting


async def seed() -> None:
    async with get_session_factory()() as session:
        if await session.scalar(select(Product.id).limit(1)) is not None:
            print("Seed skipped: catalog data already exists")
            return

        bags = Category(slug="bags", name="Bags")
        collection = Collection(slug="petal-collection", name="The Petal Collection", description="Signature sculptural forms.")
        product = Product(
            slug="petal-tote",
            name="Petal Tote",
            description="A structured everyday tote.",
            materials="Full-grain leather; silk-blend lining",
            care="Store in its dust bag and wipe with a soft dry cloth.",
            status="published",
            featured=True,
            categories=[bags],
            collections=[collection],
            variants=[
                Variant(slug="oak-brown", sku="SA-PETAL-OAK", name="Oak Brown", colour="Oak Brown", material="Full-grain leather", price_minor=3550000, currency="INR"),
                Variant(slug="black-nappa", sku="SA-PETAL-BLK", name="Black Nappa", colour="Black Nappa", material="Nappa", price_minor=3550000, currency="INR"),
            ],
        )
        session.add_all(
            [
                product,
                StorefrontSetting(key="announcement", value={"text": "Complimentary shipping across India"}),
                StorefrontSetting(key="region", value={"country": "India", "currency": "INR", "symbol": "₹"}),
                NavigationItem(label="New In", url="/shop?sort=newest", position=1, published=True),
                NavigationItem(label="Shop", url="/shop", position=2, published=True),
                NavigationItem(label="Collections", url="/collections", position=3, published=True),
                ContentPage(slug="art-of-embellishment", kind="story", title="The Art of Embellishment", excerpt="An affair with craft.", body="A study in patient craft and enduring materials.", published=True),
                ContentPage(slug="care-guide", kind="page", title="Care Guide", body="Store leather goods away from direct heat and moisture.", published=True),
            ]
        )
        await session.commit()
        print("Local seed data created")


if __name__ == "__main__":
    asyncio.run(seed())
