from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria

from app.modules.catalog.models import MediaMetadata, Product, Variant


def _published_product_query() -> Select[tuple[Product]]:
    return (
        select(Product)
        .where(Product.status == "published")
        .options(
            selectinload(Product.variants),
            selectinload(Product.media),
            selectinload(Product.categories),
            selectinload(Product.collections),
            with_loader_criteria(Variant, Variant.status == "active"),
            with_loader_criteria(MediaMetadata, MediaMetadata.variant_id.is_(None)),
        )
    )


async def list_published_products(session: AsyncSession, *, limit: int, offset: int) -> list[Product]:
    query = _published_product_query().order_by(Product.created_at.desc(), Product.id).limit(limit).offset(offset)
    result = await session.scalars(query)
    return list(result.unique().all())


async def get_published_product(session: AsyncSession, slug: str) -> Product | None:
    query = _published_product_query().where(Product.slug == slug)
    return (await session.scalars(query)).unique().one_or_none()
