from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import exists, select, func
from app.modules.promotions.models import Coupon, Promotion


def line_discount(amount: int, percent: int) -> int:
    return int(
        (Decimal(amount) * percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


async def best_promotion(session, currency, coupon_code=None):
    now = datetime.now(timezone.utc)
    # MVP: automatically applied, non-stacking percentage offers. Coupon campaigns are opt-in.
    coupon_required = exists(
        select(Coupon.id).where(Coupon.promotion_id == Promotion.id)
    )
    if coupon_code:
        from app.core.exceptions import AppError
        coupon = await session.scalar(select(Promotion).join(Coupon).where(
            func.upper(Coupon.code) == coupon_code.upper(), Promotion.currency == currency,
            Promotion.status == "published", Promotion.starts_at <= now, Promotion.ends_at > now,
        ))
        if coupon is None:
            raise AppError(409, "coupon_unavailable", "This coupon is invalid or has expired. Remove it to continue.")
        return coupon
    return await session.scalar(
        select(Promotion)
        .where(
            Promotion.currency == currency,
            Promotion.status == "published",
            Promotion.starts_at <= now,
            Promotion.ends_at > now,
            ~coupon_required,
        )
        .order_by(Promotion.percent_off.desc(), Promotion.id)
        .limit(1)
    )
