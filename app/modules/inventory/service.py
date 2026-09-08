from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain import emit
from app.core.exceptions import AppError
from app.modules.checkout.models import Checkout
from app.modules.inventory.models import InventoryItem, InventoryReservation
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.payments.models import PaymentAttempt


async def reserve(
    session: AsyncSession, order_id: UUID, quantities: dict[UUID, int], ttl_minutes: int
) -> None:
    for variant_id, quantity in sorted(quantities.items()):
        stock = (
            await session.scalars(
                select(InventoryItem)
                .where(InventoryItem.variant_id == variant_id)
                .order_by(InventoryItem.id)
                .with_for_update()
            )
        ).all()
        if sum(item.available for item in stock) < quantity:
            raise AppError(
                409,
                "insufficient_stock",
                f"Insufficient stock for variant {variant_id}",
            )
        remaining = quantity
        for item in stock:
            taken = min(item.available, remaining)
            if taken:
                item.reserved += taken
                session.add(
                    InventoryReservation(
                        inventory_item_id=item.id,
                        order_id=order_id,
                        quantity=taken,
                        status="held",
                        expires_at=datetime.now(timezone.utc)
                        + timedelta(minutes=ttl_minutes),
                    )
                )
                remaining -= taken


async def reservations_for_order(
    session: AsyncSession, order_id: UUID
) -> list[InventoryReservation]:
    return list(
        (
            await session.scalars(
                select(InventoryReservation)
                .where(InventoryReservation.order_id == order_id)
                .order_by(InventoryReservation.inventory_item_id)
                .with_for_update()
            )
        ).all()
    )


async def release(
    session: AsyncSession, order_id: UUID, status: str = "released"
) -> None:
    for hold in await reservations_for_order(session, order_id):
        if hold.status in {"held", "committed"}:
            stock = await session.get(
                InventoryItem, hold.inventory_item_id, with_for_update=True
            )
            assert stock is not None
            stock.reserved -= hold.quantity
            hold.status = status


async def commit_reservations(session: AsyncSession, order_id: UUID) -> None:
    holds = await reservations_for_order(session, order_id)
    if not holds or any(
        h.status != "held" or h.expires_at <= datetime.now(timezone.utc) for h in holds
    ):
        raise AppError(
            409,
            "reservation_expired",
            "Inventory hold expired; payment needs reconciliation",
        )
    for hold in holds:
        hold.status = "committed"


async def sweep_expired(session: AsyncSession) -> int:
    # Order first everywhere: webhook, cancellation, dispatch and sweeper share a lock order.
    expired_order_ids = select(InventoryReservation.order_id).where(
        InventoryReservation.status == "held",
        InventoryReservation.expires_at <= datetime.now(timezone.utc),
    )
    orders = (
        await session.scalars(
            select(Order)
            .where(
                Order.id.in_(expired_order_ids),
                Order.status.in_(["pending_payment", "payment_failed"]),
            )
            .order_by(Order.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for order in orders:
        previous = order.status
        await release(session, order.id, "expired")
        order.status = "expired"
        checkout = await session.get(Checkout, order.checkout_id)
        if checkout:
            checkout.status = "expired"
        attempts = (
            await session.scalars(
                select(PaymentAttempt)
                .where(PaymentAttempt.order_id == order.id)
                .with_for_update()
            )
        ).all()
        for attempt in attempts:
            if attempt.status in {"initiated", "pending", "requires_action"}:
                attempt.status = "expired"
        session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=previous,
                to_status="expired",
                actor_id="worker",
            )
        )
        emit(session, "CheckoutExpired", "order", order.id)
    return len(orders)
