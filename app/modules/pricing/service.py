from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.modules.catalog.models import Variant
from app.modules.pricing.models import Price, PriceBook


def included_tax(amount_minor: int, rate_percent: int) -> int:
    return int(
        (Decimal(amount_minor) * rate_percent / (100 + rate_percent)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


async def effective_price(
    session: AsyncSession, variant: Variant, currency: str
) -> int:
    now = datetime.now(timezone.utc)
    if variant.currency != currency:
        raise AppError(
            409, "currency_mismatch", "Cart items must use the cart currency"
        )
    price = await session.scalar(
        select(Price)
        .join(PriceBook)
        .where(
            Price.variant_id == variant.id,
            Price.currency == currency,
            PriceBook.currency == currency,
            Price.starts_at <= now,
            or_(Price.ends_at.is_(None), Price.ends_at > now),
        )
        .order_by(PriceBook.priority.desc(), Price.starts_at.desc(), Price.id.desc())
        .limit(1)
    )
    if price:
        return price.amount_minor
    # A variant with configured price-book entries may not fall back to stale legacy pricing.
    configured = await session.scalar(
        select(Price.id).where(Price.variant_id == variant.id).limit(1)
    )
    if configured or variant.price_minor < 0:
        raise AppError(409, "price_unavailable", "No currently effective price")
    return variant.price_minor
