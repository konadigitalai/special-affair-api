"""Explicit development-only stock fixture; preserve existing balances."""

import asyncio
from sqlalchemy import select
from app.core.config import get_settings
from app.core.domain import lock_key
from app.db.session import get_session_factory
from app.modules.catalog.models import Variant
from app.modules.inventory.models import InventoryItem, Location, StockMovement


async def main():
    if get_settings().environment != "dev":
        raise RuntimeError("Inventory fixtures are development-only")
    async with get_session_factory()() as session:
        await lock_key(session, "seed", "inventory")
        location = await session.scalar(
            select(Location).where(Location.name == "Development warehouse")
        )
        if location is None:
            location = Location(name="Development warehouse")
            session.add(location)
            await session.flush()
        variants = (
            await session.scalars(select(Variant).where(Variant.status == "active"))
        ).all()
        created = 0
        for variant in variants:
            existing = await session.scalar(
                select(InventoryItem.id).where(
                    InventoryItem.variant_id == variant.id,
                    InventoryItem.location_id == location.id,
                )
            )
            if existing:
                continue
            item = InventoryItem(
                variant_id=variant.id,
                location_id=location.id,
                on_hand=20,
                reserved=0,
                safety_stock=0,
            )
            session.add(item)
            await session.flush()
            session.add(
                StockMovement(
                    inventory_item_id=item.id,
                    quantity=20,
                    reason="Explicit development fixture",
                    actor_id="dev-seed",
                )
            )
            created += 1
        await session.commit()
    print(f"Created stock fixtures for {created} variants; existing balances preserved")


if __name__ == "__main__":
    asyncio.run(main())
