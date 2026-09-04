from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.session import get_session
from app.modules.catalog.models import Collection, Product
from app.modules.content.models import ConsentRecord, ContentPage, NavigationItem, StorefrontSetting

router = APIRouter(tags=["storefront"])


class NewsletterRequest(BaseModel):
    email: EmailStr


@router.get("/navigation")
async def navigation(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(NavigationItem).where(NavigationItem.published.is_(True)).order_by(NavigationItem.position))).all()
    items = [{"id": str(row.id), "parent_id": str(row.parent_id) if row.parent_id else None, "label": row.label, "url": row.url} for row in rows]
    return {"items": items}


@router.get("/settings/storefront")
async def storefront_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(StorefrontSetting))).all()
    return {row.key: row.value for row in rows}


@router.get("/home")
async def home(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    settings = await storefront_settings(session)
    collections = (await session.scalars(select(Collection).order_by(Collection.created_at.desc()).limit(6))).all()
    products = (await session.scalars(select(Product).where(Product.status == "published", Product.featured.is_(True)).limit(8))).all()
    stories = (await session.scalars(select(ContentPage).where(ContentPage.kind == "story", ContentPage.published.is_(True)).order_by(ContentPage.position).limit(3))).all()
    return {
        "settings": settings,
        "featured_collections": [{"slug": x.slug, "name": x.name, "description": x.description} for x in collections],
        "featured_products": [{"slug": x.slug, "name": x.name, "description": x.description} for x in products],
        "stories": [{"slug": x.slug, "title": x.title, "excerpt": x.excerpt, "hero_url": x.hero_url} for x in stories],
    }


@router.get("/stories")
async def stories(limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(ContentPage).where(ContentPage.kind == "story", ContentPage.published.is_(True)).order_by(ContentPage.position).limit(limit))).all()
    return {"items": [{"slug": x.slug, "title": x.title, "excerpt": x.excerpt, "hero_url": x.hero_url} for x in rows]}


async def _content(slug: str, kind: str, session: AsyncSession) -> dict[str, Any]:
    row = await session.scalar(select(ContentPage).where(ContentPage.slug == slug, ContentPage.kind == kind, ContentPage.published.is_(True)))
    if row is None:
        raise AppError(404, "content_not_found", "Content not found")
    return {"slug": row.slug, "title": row.title, "excerpt": row.excerpt, "body": row.body, "hero_url": row.hero_url}


@router.get("/stories/{slug}")
async def story(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await _content(slug, "story", session)


@router.get("/pages/{slug}")
async def page(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await _content(slug, "page", session)


@router.post("/newsletter/subscribe", status_code=201)
async def subscribe(payload: NewsletterRequest, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    session.add(ConsentRecord(email=str(payload.email).lower(), purpose="newsletter", action="granted"))
    await session.commit()
    return {"status": "subscribed"}


@router.post("/newsletter/unsubscribe", status_code=201)
async def unsubscribe(payload: NewsletterRequest, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    session.add(ConsentRecord(email=str(payload.email).lower(), purpose="newsletter", action="withdrawn"))
    await session.commit()
    return {"status": "unsubscribed"}
