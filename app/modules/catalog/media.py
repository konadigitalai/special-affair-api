from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, get_settings
from app.core.domain import evidence
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions
from app.db.session import get_session
from app.modules.catalog.models import MediaMetadata, Product

router = APIRouter(prefix="/admin/products", tags=["media"])


class MediaRequest(BaseModel):
    storage_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9/_-]*\.(jpg|jpeg|png|webp|avif)$",
        max_length=500,
    )
    alt_text: str = Field(min_length=1, max_length=500)
    position: int = Field(default=0, ge=0)


@router.post("/{product_id}/media", status_code=201)
async def register_media(
    product_id: UUID,
    payload: MediaRequest,
    actor: TokenPayload = Depends(require_permissions("product:update")),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    product = await session.get(Product, product_id)
    if product is None:
        raise AppError(404, "product_not_found", "Product not found")
    if not settings.azure_storage_account_url.startswith("https://"):
        raise AppError(
            503,
            "media_storage_unconfigured",
            "Configure Azure Blob Storage before registering media",
        )
    # Upload bytes separately using managed-identity storage tooling; only approved metadata enters commerce.
    from sqlalchemy import select

    existing = await session.scalar(
        select(MediaMetadata).where(MediaMetadata.storage_key == payload.storage_key)
    )
    if existing:
        raise AppError(409, "media_exists", "Storage key is already registered")
    url = (
        settings.azure_storage_account_url.rstrip("/")
        + "/"
        + settings.azure_storage_container
        + "/"
        + payload.storage_key
    )
    media = MediaMetadata(
        product_id=product_id,
        storage_key=payload.storage_key,
        alt_text=payload.alt_text,
        position=payload.position,
        public_url=url,
        media_type="image",
    )
    session.add(media)
    await session.flush()
    evidence(session, actor.sub, "media.registered", "media", media.id)
    await session.commit()
    return {"id": str(media.id), "url": url}
