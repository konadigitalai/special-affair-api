from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.db.session import get_session
from app.modules.catalog.schemas import ProductDetail, ProductList, ProductSummary
from app.modules.catalog.service import _published_product_query, get_published_product, list_published_products
from app.modules.catalog.models import Category, Collection, Product, Variant

router = APIRouter(prefix="/products", tags=["catalog"])


@router.get("", response_model=ProductList)
async def list_products(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ProductList:
    products = await list_published_products(session, limit=limit, offset=offset)
    return ProductList(items=[ProductSummary.model_validate(product) for product in products], limit=limit, offset=offset)


@router.get("/facets")
async def product_facets(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    colours = (await session.execute(select(Variant.colour, func.count(Variant.id)).join(Product).where(Product.status == "published", Variant.status == "active", Variant.colour.is_not(None)).group_by(Variant.colour))).all()
    materials = (await session.execute(select(Variant.material, func.count(Variant.id)).join(Product).where(Product.status == "published", Variant.status == "active", Variant.material.is_not(None)).group_by(Variant.material))).all()
    categories = (await session.execute(select(Category.slug, Category.name, func.count(Product.id)).join(Category.products).where(Product.status == "published").group_by(Category.id))).all()
    return {
        "colours": [{"value": value, "count": count} for value, count in colours],
        "materials": [{"value": value, "count": count} for value, count in materials],
        "categories": [{"value": slug, "label": name, "count": count} for slug, name, count in categories],
    }


@router.get("/{slug}/related", response_model=ProductList)
async def related_products(slug: str, session: AsyncSession = Depends(get_session)) -> ProductList:
    current = await session.scalar(select(Product).where(Product.slug == slug, Product.status == "published"))
    if current is None:
        raise AppError(404, "product_not_found", "Product not found")
    rows = (await session.scalars(select(Product).where(Product.status == "published", Product.id != current.id).options(selectinload(Product.variants), selectinload(Product.media)).limit(8))).all()
    return ProductList(items=[ProductSummary.model_validate(x) for x in rows], limit=8, offset=0)


@router.get("/{slug}", response_model=ProductDetail)
async def get_product(slug: str, session: AsyncSession = Depends(get_session)) -> ProductDetail:
    product = await get_published_product(session, slug)
    if product is None:
        raise AppError(status_code=404, code="product_not_found", message="Product not found")
    return ProductDetail.model_validate(product)


collections_router = APIRouter(prefix="/collections", tags=["catalog"])


@collections_router.get("")
async def list_collections(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    rows = (await session.scalars(select(Collection).order_by(Collection.created_at.desc()))).all()
    return {"items": [{"slug": x.slug, "name": x.name, "description": x.description} for x in rows]}


@collections_router.get("/{slug}")
async def collection_detail(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    row = await session.scalar(select(Collection).where(Collection.slug == slug).options(selectinload(Collection.products).selectinload(Product.variants), selectinload(Collection.products).selectinload(Product.media)))
    if row is None:
        raise AppError(404, "collection_not_found", "Collection not found")
    products = [x for x in row.products if x.status == "published"]
    return {"slug": row.slug, "name": row.name, "description": row.description, "products": [ProductSummary.model_validate(x) for x in products]}


search_router = APIRouter(prefix="/search", tags=["search"])


@search_router.get("/suggestions")
async def suggestions(q: str = Query("", max_length=100), session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    term = f"%{q.strip()}%"
    products = (await session.scalars(select(Product).where(Product.status == "published", or_(Product.name.ilike(term), Product.description.ilike(term))).limit(6))).all()
    collections = (await session.scalars(select(Collection).where(Collection.name.ilike(term)).limit(4))).all()
    return {"products": [{"slug": x.slug, "name": x.name} for x in products], "collections": [{"slug": x.slug, "name": x.name} for x in collections]}


@search_router.get("/popular")
async def popular() -> dict[str, list[str]]:
    return {"terms": ["tote", "shoulder bag", "nappa", "new arrivals"]}


@search_router.get("")
async def search(q: str = Query(..., min_length=1, max_length=100), session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    term = f"%{q.strip()}%"
    rows = (await session.scalars(_published_product_query().where(or_(Product.name.ilike(term), Product.description.ilike(term))).limit(50))).all()
    return {"items": [ProductSummary.model_validate(x) for x in rows], "query": q}
