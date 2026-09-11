"""Idempotent client-review catalogue matching the approved storefront range."""
import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.domain import lock_key
from app.db.session import get_session_factory
from app.modules.catalog.models import (
    Category,
    Collection,
    MediaMetadata,
    Product,
    Variant,
)
from app.modules.content.models import ContentPage
from app.modules.inventory.models import InventoryItem, Location, StockMovement

ROWS = [
    ("Core Bra", 3200, "Black", "Inner Affair", "Sports Bras", "Women", "/images/flagship/core-bra.webp"),
    ("Move Legging", 4800, "Black", "Form", "Bottoms", "Women", "/images/flagship/move-legging.webp"),
    ("Essential Tee", 3600, "White", "Essential Affair", "Tops", "Unisex", "/images/flagship/essential-tee-packshot-hd-v2.png"),
    ("Active Short", 4200, "Black", "Form", "Bottoms", "Unisex", "/images/flagship/active-short-packshot-hd-v2.png"),
    ("The Hoodie", 6800, "Warm Grey", "Shell", "Outerwear", "Unisex", "/images/flagship/hoodie-packshot-hd-v2.png"),
    ("Relaxed Pant", 5800, "Black", "Essential Affair", "Bottoms", "Unisex", "/images/flagship/relaxed-pant-packshot-hd-v2.png"),
    ("Balance Bra", 3400, "Ivory", "Inner Affair", "Sports Bras", "Women", "/images/flagship/balance-bra-packshot-hd-v2.png"),
    ("Move Jacket", 8900, "Black", "Shell", "Outerwear", "Unisex", "/images/flagship/move-jacket-packshot-hd-v2.png"),
    ("Lift Tank", 3200, "Black", "Form", "Tops", "Women", "/images/flagship/lift-tank-packshot-hd-v2.png"),
    ("Everyday Sweat", 5400, "Warm Grey", "Essential Affair", "Tops", "Unisex", "/images/flagship/everyday-sweat-packshot-hd-v2.png"),
    ("Core Cap", 2800, "Black", "Shell", "Accessories", "Unisex", "/images/flagship/core-cap-packshot-hd-v2.png"),
    ("Daily Socks (2 Pack)", 1200, "White", "Essential Affair", "Accessories", "Unisex", "/images/flagship/daily-socks-packshot-hd-v2.png"),
]

RETIRED_SLUGS = ["dev-layer-shell-jacket", "dev-everyday-tank"]
STORIES = [
    ("a-different-kind-of-movement", "A Different Kind of Movement", "Places that move us, and why they matter.", "coast", "Movement does not always mean moving faster. Sometimes it is the slower walk, the longer route home, the moment spent looking out at the sea.\n\nThis first visual study looks outward: open coastlines, changing light and the space between one part of a day and the next. A wardrobe can make room for those transitions, too."),
    ("material-matters", "Material Matters", "A closer look at what goes into every piece.", "material", "Before a silhouette, there is a surface. The grain of a knit. The fall of a sleeve. The way a fabric catches the light.\n\nOur material studies begin with these everyday observations. Texture and construction are part of the experience of wearing a garment.\n\nExplore the product pages for the available fabric and care information. Final composition and performance specifications will accompany the approved collection."),
    ("the-first-affair", "The First Affair", "From the first layer outward.", "essential-affair", "The first layer sets the tone for everything that follows. A familiar tee, a shape you return to, a piece that makes getting dressed feel simple.\n\nSpecial Affair is imagined as a house of four connected worlds: Inner Affair, Essential Affair, Form and Shell. Different expressions, brought together by everyday life."),
    ("people-in-motion", "People in Motion", "Small choices. A different rhythm.", "form", "A pause between efforts. A breath before the next step. Movement has its own quiet moments.\n\nThis campaign study follows those moments through light, shape and the human form. It is an invitation to find a rhythm that feels like your own."),
    ("a-closer-look", "A Closer Look", "A study in movement, texture and form.", "form", "Look a little closer. The line of a shoulder, the fold of a fabric, the space around a moving body.\n\nThis photographic campaign study brings together the visual language of the house. The full campaign film will take its place when the final footage is available."),
    ("our-philosophy", "Our Philosophy", "A contemporary lifestyle house, from the first layer outward.", "first-affair", "Special Affair is a contemporary lifestyle house for movement, intimacy and everyday life.\n\nInner Affair begins closest to you. Essential Affair brings considered staples to the everyday. Form explores movement. Shell looks to the layer that takes you further.\n\nFour worlds, connected by one point of view: clothing should feel like a part of your life."),
]

async def seed():
    if get_settings().environment != "dev":
        raise RuntimeError("Client-review fixtures require development mode")
    async with get_session_factory()() as session:
        await lock_key(session, "seed", "flagship-client-review")
        location = await session.scalar(select(Location).where(Location.name == "Client review sample warehouse"))
        if location is None:
            location = Location(name="Client review sample warehouse")
            session.add(location)
            await session.flush()
        for slug in RETIRED_SLUGS:
            retired = await session.scalar(select(Product).where(Product.slug == slug))
            if retired is not None:
                retired.status = "archived"
        created = 0
        for name, price, colour, world, category, gender, photo in ROWS:
            slug = "dev-" + name.lower().replace(" ", "-").replace("(", "").replace(")", "")
            categories = []
            for label in [gender, category]:
                cat_slug = label.lower().replace(" ", "-")
                row = await session.scalar(select(Category).where(Category.slug == cat_slug))
                if row is None:
                    row = Category(slug=cat_slug, name=label)
                    session.add(row)
                    await session.flush()
                categories.append(row)
            world_slug = world.lower().replace(" ", "-")
            collection = await session.scalar(select(Collection).where(Collection.slug == world_slug))
            if collection is None:
                collection = Collection(slug=world_slug, name=world)
                session.add(collection)
                await session.flush()
            product = await session.scalar(select(Product).where(Product.slug == slug))
            if product is None:
                product = Product(slug=slug, name=name, description="A considered silhouette for movement and everyday life. Development sample for client review; specifications and pricing are illustrative.", materials="Illustrative fabric study. Final composition awaits the approved product range.", care="Follow the approved garment care label. Sample imagery does not establish fabric specifications.", status="published", featured=True, categories=categories, collections=[collection])
                session.add(product)
                await session.flush()
                # Product-level media keeps catalogue, PDP and search imagery consistent.
                for position, url in enumerate([photo, "/images/flagship/material.webp"]):
                    session.add(MediaMetadata(product_id=product.id, storage_key=f"dev-flagship/{slug}/{position}", public_url=url, alt_text=name if position == 0 else "Illustrative material study", position=position))
                created += 1
            else:
                product.status = "published"
                product.featured = True
                product.name = name
                primary_media = await session.scalar(
                    select(MediaMetadata).where(
                        MediaMetadata.product_id == product.id,
                        MediaMetadata.variant_id.is_(None),
                        MediaMetadata.position == 0,
                    )
                )
                if primary_media is not None:
                    primary_media.public_url = photo
                    primary_media.alt_text = name
            sizes = [None] if category == "Accessories" else ["XS", "S", "M", "L", "XL", "XXL"]
            for position, size in enumerate(sizes):
                variant = await session.scalar(select(Variant).where(Variant.product_id == product.id, Variant.colour == colour, Variant.size == size))
                if variant is not None:
                    variant.price_minor = price * 100
                    variant.status = "active"
                    continue
                size_code = size or "OS"
                sku_name = slug.removeprefix("dev-").upper()
                variant = Variant(product_id=product.id, sku=f"DEV-FLAGSHIP-{sku_name}-{size_code}", slug=f"{colour.lower().replace(' ', '-')}-{size_code.lower()}", name=f"{colour} / {size_code}", colour=colour, size=size, price_minor=price*100, currency="INR", status="active", position=position)
                session.add(variant)
                await session.flush()
                stock = InventoryItem(variant_id=variant.id, location_id=location.id, on_hand=20, reserved=0, safety_stock=0)
                session.add(stock)
                await session.flush()
                session.add(StockMovement(inventory_item_id=stock.id, quantity=20, reason="User-approved development apparel fixture", actor_id="dev-flagship-seed"))
        core = await session.scalar(select(Product).where(Product.slug == "dev-core-bra"))
        if core is not None:
            for position, size in enumerate(["XS", "S", "M", "L", "XL"]):
                sku = f"DEV-FLAGSHIP-0-IVORY-{size}"
                if await session.scalar(select(Variant.id).where(Variant.sku == sku)):
                    continue
                variant = Variant(product_id=core.id, sku=sku, slug=f"ivory-{size.lower()}", name=f"Ivory / {size}", colour="Ivory", size=size, price_minor=320000, currency="INR", status="active", position=10+position)
                session.add(variant)
                await session.flush()
                session.add(MediaMetadata(product_id=core.id, variant_id=variant.id, storage_key=f"dev-flagship/core-bra-ivory/{size}", public_url="/images/flagship/core-bra-ivory.webp", alt_text="Core Bra in Ivory", position=0))
                stock = InventoryItem(variant_id=variant.id, location_id=location.id, on_hand=20, reserved=0, safety_stock=0)
                session.add(stock)
                await session.flush()
                session.add(StockMovement(inventory_item_id=stock.id, quantity=20, reason="User-approved development colour fixture", actor_id="dev-flagship-seed"))
        for i, (slug, title, excerpt, image, body) in enumerate(STORIES):
            if not await session.scalar(select(ContentPage.id).where(ContentPage.slug == slug)):
                session.add(ContentPage(slug=slug, kind="story", title=title, excerpt=excerpt, body=body, hero_url=f"/images/flagship/{image}.webp", published=True, position=i))
        for slug, title, body in [
            ("size-guide", "Size Guide", "The development apparel collection offers XS, S, M, L and XL. Select a size on the product page to see its availability.\n\nThe images and sample garments do not establish final measurements. Contact the house through the support form for fit questions; approved measurements will be added with the final range."),
            ("shipping", "Shipping & Returns", "Shipping charges are included in the bag total before you place an order. Order status and any available shipment tracking appear under Orders & returns.\n\nReturn requests are checked against the configured eligibility window and the items on your order. Sample orders in this development store are for review and will not be physically fulfilled."),
            ("terms", "Terms", "This development storefront is available for design and integration review. Sample product descriptions, images and prices are illustrative. Sample orders do not represent a production purchase or promise of delivery.\n\nFinal purchase terms will be provided by the house before public launch. Please use Contact for questions about the review collection."),
            ("privacy", "Privacy", "The review store saves cart, wishlist, order and support information in its connected development database. Your browser retains access tokens and identifiers so you can return to your guest bag and orders.\n\nNewsletter signup records your preference. You can withdraw consent in your account. Signed-in customers can download their data or submit an erasure request for review.\n\nPlease use test contact information for sample orders. The final privacy notice will be supplied before public launch."),
        ]:
            if not await session.scalar(select(ContentPage.id).where(ContentPage.slug == slug)):
                session.add(ContentPage(slug=slug, title=title, body=body, kind="page", published=True, hero_url="/images/flagship/material.webp"))
        await session.commit()
    print(f"Created {created} development apparel products; catalogue synchronized")

if __name__ == "__main__":
    asyncio.run(seed())
