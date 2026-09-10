"""Authoritative bag totals, shared pricing and promotion policy with checkout."""

from app.core.config import get_settings
from typing import cast
from app.core.exceptions import AppError
from app.modules.cart.router import cart_response
from app.modules.pricing.service import effective_price, included_tax
from app.modules.promotions.service import best_promotion, line_discount


async def quote_cart(session, cart):
    settings = get_settings()
    coupon_error = None
    try:
        promotion = await best_promotion(session, cart.currency, cart.coupon_code)
    except AppError as error:
        if error.code != "coupon_unavailable":
            raise
        promotion, coupon_error = None, error.message
    for item in cart.items:
        item.unit_price_minor = await effective_price(
            session, item.variant, cart.currency
        )
    data = cast(dict, cart_response(cart))
    data["coupon_error"] = coupon_error
    discount = tax = 0
    for line in data["items"]:
        saving = (
            line_discount(line["line_total_minor"], promotion.percent_off)
            if promotion
            else 0
        )
        line["line_discount_minor"] = saving
        line["line_total_minor"] -= saving
        line["line_tax_minor"] = included_tax(
            line["line_total_minor"], settings.tax_rate_percent
        )
        discount += saving
        tax += line["line_tax_minor"]
    data.update(
        discount_minor=discount,
        tax_minor=tax,
        shipping_minor=settings.shipping_fee_minor if cart.items else 0,
    )
    data["total_minor"] = data["subtotal_minor"] - discount + data["shipping_minor"]
    return data
