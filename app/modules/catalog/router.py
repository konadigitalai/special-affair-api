from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.session import get_session
from app.modules.catalog.schemas import ProductDetail, ProductList, ProductSummary
from app.modules.catalog.service import get_published_product, list_published_products

router = APIRouter(prefix="/products", tags=["catalog"])


@router.get("", response_model=ProductList)
async def list_products(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ProductList:
    products = await list_published_products(session, limit=limit, offset=offset)
    return ProductList(items=[ProductSummary.model_validate(product) for product in products], limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(product_id: UUID, session: AsyncSession = Depends(get_session)) -> ProductDetail:
    product = await get_published_product(session, product_id)
    if product is None:
        raise AppError(status_code=404, code="product_not_found", message="Product not found")
    return ProductDetail.model_validate(product)
