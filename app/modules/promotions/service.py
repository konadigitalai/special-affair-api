from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import exists, select
from app.modules.promotions.models import Coupon, Promotion


def line_discount(amount: int, percent: int) -> int:
    return int(
        (Decimal(amount) * percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


async def best_promotion(session, currency):
    now = datetime.now(timezone.utc)
    # MVP: automatically applied, non-stacking percentage offers. Coupon campaigns are opt-in.
    coupon_required = exists(
        select(Coupon.id).where(Coupon.promotion_id == Promotion.id)
    )
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
