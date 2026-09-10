from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence, lock_key
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions, verify_token
from app.db.session import get_session
from app.modules.catalog.models import Product, Variant
from app.modules.pricing.models import Price, PriceBook
from app.modules.promotions.models import Promotion, Coupon

router = APIRouter(prefix="/admin", tags=["catalog administration"])

STAFF_PERMISSIONS = frozenset({
    "product:update", "product:publish", "price:manage", "promotion:manage",
    "inventory:adjust", "order:manage", "fulfillment:manage", "support:manage",
    "return:manage", "refund:request", "refund:approve", "audit:read",
    "operations:manage", "privacy:approve",
})


async def staff_session(actor: TokenPayload = Depends(verify_token)) -> TokenPayload:
    if not STAFF_PERMISSIONS.intersection(actor.permissions):
        raise HTTPException(status_code=403, detail="Staff access required")
    return actor


@router.get("/session")
async def admin_session(actor: TokenPayload = Depends(staff_session)) -> dict:
    return {"subject": actor.sub, "permissions": sorted(STAFF_PERMISSIONS.intersection(actor.permissions))}


@router.get("/products")
async def admin_products(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: TokenPayload = Depends(staff_session),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not {"product:update", "product:publish"}.intersection(actor.permissions):
        raise HTTPException(status_code=403, detail="Catalog access required")
    rows = (await session.scalars(select(Product).order_by(Product.created_at.desc(), Product.id).offset(offset).limit(limit + 1))).all()
    return {"items": [{"id": str(p.id), "name": p.name, "slug": p.slug, "status": p.status, "version": p.version} for p in rows[:limit]], "has_more": len(rows) > limit}


class ProductCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=200)
    name: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=20000)


class VariantCreate(BaseModel):
    size: str | None = Field(default=None, max_length=30)
    colour: str | None = Field(default=None, max_length=100)
    material: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=200)
    name: str = Field(min_length=1, max_length=250)
    price_minor: int = Field(ge=0)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")


class PublishRequest(BaseModel):
    version: int = Field(ge=1)
    status: Literal["draft", "published", "archived"]


class PriceRequest(BaseModel):
    book_name: str = Field(min_length=1, max_length=100)
    priority: int = 0
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    starts_at: datetime
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def valid_window(self):
        if self.starts_at.tzinfo is None or (
            self.ends_at
            and (self.ends_at.tzinfo is None or self.ends_at <= self.starts_at)
        ):
            raise ValueError(
                "Effective dates must have time zones and a positive duration"
            )
        return self


class PromotionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    percent_off: int = Field(gt=0, le=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    starts_at: datetime
    ends_at: datetime
    status: Literal["draft", "published", "archived"] = "draft"

    @model_validator(mode="after")
    def valid_window(self):
        if (
            self.starts_at.tzinfo is None
            or self.ends_at.tzinfo is None
            or self.ends_at <= self.starts_at
        ):
            raise ValueError(
                "Effective dates must have time zones and a positive duration"
            )
        return self


@router.post("/products", status_code=201)
async def create_product(
    payload: ProductCreate,
    actor: TokenPayload = Depends(require_permissions("product:update")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await lock_key(session, "product-slug", payload.slug)
    if await session.scalar(select(Product.id).where(Product.slug == payload.slug)):
        raise AppError(409, "product_exists", "Product slug already exists")
    product = Product(**payload.model_dump(), status="draft")
    session.add(product)
    await session.flush()
    evidence(session, actor.sub, "product.created", "product", product.id)
    await session.commit()
    return {"id": str(product.id), "status": product.status, "version": product.version}


@router.post("/products/{product_id}/variants", status_code=201)
async def create_variant(
    product_id: UUID,
    payload: VariantCreate,
    actor: TokenPayload = Depends(require_permissions("product:update")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    product = await session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise AppError(404, "product_not_found", "Product not found")
    await lock_key(session, "sku", payload.sku)
    if await session.scalar(
        select(Variant.id).where(
            (Variant.sku == payload.sku)
            | ((Variant.product_id == product_id) & (Variant.slug == payload.slug))
        )
    ):
        raise AppError(409, "variant_exists", "SKU or variant slug already exists")
    variant = Variant(product_id=product_id, **payload.model_dump())
    session.add(variant)
    product.version += 1
    await session.flush()
    evidence(session, actor.sub, "variant.created", "variant", variant.id)
    await session.commit()
    return {"id": str(variant.id), "sku": variant.sku}


@router.post("/products/{product_id}/publication")
async def publish_product(
    product_id: UUID,
    payload: PublishRequest,
    actor: TokenPayload = Depends(require_permissions("product:publish")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    product = await session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise AppError(404, "product_not_found", "Product not found")
    if product.version != payload.version:
        raise AppError(
            409, "version_conflict", "Product changed; reload before publishing"
        )
    active = await session.scalar(
        select(Variant.id)
        .where(Variant.product_id == product_id, Variant.status == "active")
        .limit(1)
    )
    if payload.status == "published" and active is None:
        raise AppError(
            409, "product_incomplete", "Published products require an active variant"
        )
    old = product.status
    product.status, product.version = payload.status, product.version + 1
    evidence(
        session,
        actor.sub,
        "product.publication",
        "product",
        product.id,
        {"status": old},
        {"status": product.status},
    )
    await session.commit()
    return {"id": str(product.id), "status": product.status, "version": product.version}


@router.post("/variants/{variant_id}/prices", status_code=201)
async def add_price(
    variant_id: UUID,
    payload: PriceRequest,
    actor: TokenPayload = Depends(require_permissions("price:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if await session.get(Variant, variant_id) is None:
        raise AppError(404, "variant_not_found", "Variant not found")
    await lock_key(session, "price-book", payload.book_name)
    book = await session.scalar(
        select(PriceBook).where(PriceBook.name == payload.book_name)
    )
    if book is None:
        book = PriceBook(
            name=payload.book_name, priority=payload.priority, currency=payload.currency
        )
        session.add(book)
        await session.flush()
    if book.currency != payload.currency or book.priority != payload.priority:
        raise AppError(
            409, "price_book_mismatch", "Price book currency and priority must match"
        )
    price = Price(
        price_book_id=book.id,
        variant_id=variant_id,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    session.add(price)
    await session.flush()
    evidence(session, actor.sub, "price.created", "price", price.id)
    await session.commit()
    return {"id": str(price.id)}


@router.post("/promotions", status_code=201)
async def add_promotion(
    payload: PromotionRequest,
    actor: TokenPayload = Depends(require_permissions("promotion:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    promotion = Promotion(**payload.model_dump())
    session.add(promotion)
    await session.flush()
    evidence(session, actor.sub, "promotion.created", "promotion", promotion.id)
    await session.commit()
    return {"id": str(promotion.id), "status": promotion.status}


class CouponCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{2,100}$")


@router.post("/promotions/{promotion_id}/coupons", status_code=201)
async def create_coupon(promotion_id: UUID, payload: CouponCreate,
                        actor: TokenPayload = Depends(require_permissions("promotion:manage")),
                        session: AsyncSession = Depends(get_session)):
    code = payload.code.upper()
    await lock_key(session, "coupon", code)
    if await session.get(Promotion, promotion_id) is None:
        raise AppError(404, "promotion_not_found", "Promotion not found")
    from sqlalchemy import func
    if await session.scalar(select(Coupon.id).where(func.upper(Coupon.code) == code)):
        raise AppError(409, "coupon_exists", "Coupon code already exists")
    coupon = Coupon(promotion_id=promotion_id, code=code)
    session.add(coupon)
    await session.flush()
    evidence(session, actor.sub, "coupon.created", "coupon", coupon.id)
    await session.commit()
    return {"id": str(coupon.id), "code": coupon.code}
