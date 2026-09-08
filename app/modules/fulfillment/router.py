from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.domain import ORDER_TRANSITIONS, emit, evidence, transition
from app.core.exceptions import AppError
from app.core.security import TokenPayload, require_permissions
from app.db.session import get_session
from app.modules.fulfillment.models import Fulfillment, Shipment, ShipmentItem
from app.modules.inventory.models import (
    InventoryItem,
    InventoryReservation,
    StockMovement,
)
from app.modules.inventory.service import release
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory

router = APIRouter(tags=["fulfillment"])


class OrderAction(BaseModel):
    status: Literal["allocated", "cancelled"]


class DispatchLine(BaseModel):
    order_item_id: UUID
    quantity: int = Field(gt=0)


class Dispatch(BaseModel):
    carrier: str = Field(min_length=1, max_length=100)
    tracking_number: str = Field(min_length=1, max_length=200)
    items: list[DispatchLine] = Field(min_length=1, max_length=100)


def change_order(session: AsyncSession, order: Order, target: str, actor: str) -> None:
    previous = order.status
    order.status = transition(previous, target, ORDER_TRANSITIONS)
    session.add(
        OrderStatusHistory(
            order_id=order.id, from_status=previous, to_status=target, actor_id=actor
        )
    )
    evidence(
        session,
        actor,
        "order." + target,
        "order",
        order.id,
        {"status": previous},
        {"status": target},
    )
    emit(session, "OrderStatusChanged", "order", order.id, {"status": target})


@router.post("/orders/{order_id}/status")
async def order_action(
    order_id: UUID,
    payload: OrderAction,
    actor: TokenPayload = Depends(require_permissions("order:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise AppError(404, "order_not_found", "Order not found")
    change_order(session, order, payload.status, actor.sub)
    if payload.status == "cancelled":
        await release(session, order.id)
        emit(session, "CancellationReconciliationRequired", "order", order.id)
    else:
        session.add(Fulfillment(order_id=order.id, status="allocated"))
    await session.commit()
    return {"id": str(order.id), "status": order.status}


@router.post("/orders/{order_id}/shipments", status_code=201)
async def dispatch(
    order_id: UUID,
    payload: Dispatch,
    actor: TokenPayload = Depends(require_permissions("fulfillment:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None or order.status not in {"allocated", "partially_fulfilled"}:
        raise AppError(
            409, "order_not_dispatchable", "Order must be allocated before dispatch"
        )
    if len({x.order_item_id for x in payload.items}) != len(payload.items):
        raise AppError(422, "duplicate_shipment_item", "Shipment items must be unique")
    fulfillment = await session.scalar(
        select(Fulfillment).where(Fulfillment.order_id == order.id)
    )
    assert fulfillment is not None
    shipment = Shipment(
        fulfillment_id=fulfillment.id,
        carrier=payload.carrier,
        tracking_number=payload.tracking_number,
        status="dispatched",
    )
    session.add(shipment)
    await session.flush()
    for line in sorted(payload.items, key=lambda x: x.order_item_id):
        item = await session.get(OrderItem, line.order_item_id)
        shipped = await session.scalar(
            select(func.coalesce(func.sum(ShipmentItem.quantity), 0)).where(
                ShipmentItem.order_item_id == line.order_item_id
            )
        )
        if (
            item is None
            or item.order_id != order.id
            or line.quantity + (shipped or 0) > item.quantity
        ):
            raise AppError(
                409, "invalid_shipment_quantity", "Shipment exceeds purchased quantity"
            )
        holds = (
            await session.scalars(
                select(InventoryReservation)
                .join(InventoryItem)
                .where(
                    InventoryReservation.order_id == order.id,
                    InventoryReservation.status == "committed",
                    InventoryItem.variant_id == item.variant_id,
                )
                .order_by(InventoryReservation.inventory_item_id)
                .with_for_update(of=InventoryReservation)
            )
        ).all()
        remaining = line.quantity
        for hold in holds:
            taken = min(hold.quantity, remaining)
            if not taken:
                break
            stock = await session.get(
                InventoryItem, hold.inventory_item_id, with_for_update=True
            )
            assert stock is not None
            stock.on_hand -= taken
            stock.reserved -= taken
            session.add(
                StockMovement(
                    inventory_item_id=stock.id,
                    quantity=-taken,
                    reason="shipment:" + str(shipment.id),
                    actor_id=actor.sub,
                )
            )
            if taken == hold.quantity:
                hold.status = "consumed"
            else:
                hold.quantity -= taken
                session.add(
                    InventoryReservation(
                        order_id=order.id,
                        inventory_item_id=stock.id,
                        quantity=taken,
                        status="consumed",
                        expires_at=hold.expires_at,
                    )
                )
            remaining -= taken
        if remaining:
            raise AppError(
                409, "reservation_shortfall", "Committed stock is insufficient"
            )
        session.add(
            ShipmentItem(
                shipment_id=shipment.id, order_item_id=item.id, quantity=line.quantity
            )
        )
    await session.flush()
    ordered = await session.scalar(
        select(func.sum(OrderItem.quantity)).where(OrderItem.order_id == order.id)
    )
    shipped_total = await session.scalar(
        select(func.sum(ShipmentItem.quantity))
        .join(OrderItem)
        .where(OrderItem.order_id == order.id)
    )
    target = "fulfilled" if shipped_total == ordered else "partially_fulfilled"
    if target != order.status:
        change_order(session, order, target, actor.sub)
    evidence(session, actor.sub, "shipment.dispatched", "shipment", shipment.id)
    await session.commit()
    return {
        "id": str(shipment.id),
        "status": shipment.status,
        "order_status": order.status,
    }


@router.post("/shipments/{shipment_id}/delivered")
async def delivered(
    shipment_id: UUID,
    actor: TokenPayload = Depends(require_permissions("fulfillment:manage")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise AppError(404, "shipment_not_found", "Shipment not found")
    fulfillment = await session.get(Fulfillment, shipment.fulfillment_id)
    assert fulfillment is not None
    order = await session.get(Order, fulfillment.order_id, with_for_update=True)
    assert order is not None
    shipment.status = "delivered"
    await session.flush()
    pending = await session.scalar(
        select(Shipment.id)
        .where(
            Shipment.fulfillment_id == fulfillment.id, Shipment.status != "delivered"
        )
        .limit(1)
    )
    if pending is None and order.status == "fulfilled":
        change_order(session, order, "delivered", actor.sub)
        fulfillment.status = "delivered"
    await session.commit()
    return {"id": str(shipment.id), "status": shipment.status}
