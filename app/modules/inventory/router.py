from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import evidence, lock_key
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions
from app.db.session import get_session
from app.modules.inventory.models import InventoryItem, Location, StockMovement

router = APIRouter(prefix="/inventory", tags=["inventory"])


class LocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class StockAdjustment(BaseModel):
    variant_id: UUID
    location_id: UUID
    quantity: int
    reason: str = Field(min_length=3, max_length=500)


@router.post("/locations", status_code=201)
async def create_location(
    payload: LocationRequest,
    actor: TokenPayload = Depends(require_permissions("inventory:adjust")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await lock_key(session, "location", payload.name)
    location = await session.scalar(
        select(Location).where(Location.name == payload.name)
    )
    if location is None:
        location = Location(name=payload.name)
        session.add(location)
        await session.flush()
        evidence(session, actor.sub, "location.created", "location", location.id)
    await session.commit()
    return {"id": str(location.id), "name": location.name}


@router.post("/adjustments", status_code=201)
async def adjust_stock(
    payload: StockAdjustment,
    actor: TokenPayload = Depends(require_permissions("inventory:adjust")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.modules.catalog.models import Variant

    if (
        await session.get(Variant, payload.variant_id) is None
        or await session.get(Location, payload.location_id) is None
    ):
        raise AppError(
            404, "inventory_reference_missing", "Variant or location does not exist"
        )
    await lock_key(session, "inventory", f"{payload.variant_id}:{payload.location_id}")
    item = await session.scalar(
        select(InventoryItem)
        .where(
            InventoryItem.variant_id == payload.variant_id,
            InventoryItem.location_id == payload.location_id,
        )
        .with_for_update()
    )
    if item is None:
        item = InventoryItem(
            variant_id=payload.variant_id,
            location_id=payload.location_id,
            on_hand=0,
            reserved=0,
            safety_stock=0,
        )
        session.add(item)
        await session.flush()
    if item.available + payload.quantity < 0:
        raise AppError(
            409,
            "stock_below_reserved",
            "Adjustment would remove reserved or safety stock",
        )
    item.on_hand += payload.quantity
    session.add(
        StockMovement(
            inventory_item_id=item.id,
            quantity=payload.quantity,
            reason=payload.reason,
            actor_id=actor.sub,
        )
    )
    evidence(
        session,
        actor.sub,
        "inventory.adjusted",
        "inventory",
        item.id,
        after={"on_hand": item.on_hand, "delta": payload.quantity},
    )
    await session.commit()
    return {
        "id": str(item.id),
        "on_hand": item.on_hand,
        "reserved": item.reserved,
        "available": item.available,
    }


@router.get("/{variant_id}")
async def availability(
    variant_id: UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    rows = (
        await session.scalars(
            select(InventoryItem).where(InventoryItem.variant_id == variant_id)
        )
    ).all()
    return {"variant_id": str(variant_id), "available": sum(x.available for x in rows)}
