"""Customer integration: real database, token isolation and authoritative totals."""

from datetime import datetime, timedelta, timezone
import os

import pytest

from app.core.config import get_settings
from app.core.security import optional_token, TokenPayload
from app.core.security import verify_token
from app.main import app
from app.modules.catalog.models import Variant
from app.modules.promotions.models import Promotion, Coupon
from tests.test_commerce_integration import commerce, cart, checkout  # noqa: F401
from tests.test_checkout import valid_checkout

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Requires disposable PostgreSQL TEST_DATABASE_URL",
)


async def test_wishlist_ownership_persistence_merge_and_removal(commerce):
    client, _, variant_id = commerce
    created = (await client.post("/api/v1/wishlists")).json()
    path = f"/api/v1/wishlists/{created['id']}"
    headers = {"X-Wishlist-Token": created["wishlist_token"]}
    assert (await client.get(path)).status_code == 404
    assert (await client.put(path + f"/items/{variant_id}")).status_code == 404
    assert (await client.put(path + f"/items/{variant_id}", headers=headers)).json()["variant_ids"] == [str(variant_id)]
    assert (await client.put(path + f"/items/{variant_id}", headers=headers)).json()["variant_ids"] == [str(variant_id)]
    assert (await client.get(path, headers=headers)).json()["variant_ids"] == [str(variant_id)]
    assert (await client.post(path + "/merge", headers=headers)).status_code == 401
    app.dependency_overrides[optional_token] = lambda: TokenPayload(sub="wishlist-owner")
    try:
        account = (await client.post("/api/v1/wishlists")).json()
        merged = await client.post(path + "/merge", headers=headers)
        assert merged.status_code == 200, merged.text
        assert merged.json()["id"] == account["id"]
        assert merged.json()["variant_ids"] == [str(variant_id)]
        target = f"/api/v1/wishlists/{account['id']}"
        app.dependency_overrides[optional_token] = lambda: TokenPayload(sub="other-wishlist-user")
        assert (await client.get(target, headers=headers)).status_code == 404
        app.dependency_overrides[optional_token] = lambda: TokenPayload(sub="wishlist-owner")
        assert (await client.delete(target + f"/items/{variant_id}")).json()["variant_ids"] == []
    finally:
        app.dependency_overrides.pop(optional_token, None)


async def test_catalog_sizes_stock_coupon_and_checkout_total(commerce):
    client, factory, variant_id = commerce
    async with factory() as session:
        variant = await session.get(Variant, variant_id)
        variant.size = "M"
        offer = Promotion(
            name="Storefront test",
            percent_off=10,
            currency="INR",
            status="published",
            starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add(offer)
        await session.flush()
        session.add(Coupon(promotion_id=offer.id, code="TEST10"))
        await session.commit()
    products = (await client.get("/api/v1/storefront/catalog")).json()["items"]
    assert products[0]["size"] == "M" and products[0]["available"] == 5
    bag, headers = await cart(client, variant_id, 2)
    path = f"/api/v1/carts/{bag['id']}"
    assert (
        await client.get(path + "/quote", headers={"X-Cart-Token": "wrong"})
    ).status_code == 404
    quote = (
        await client.post(path + "/coupon", headers=headers, json={"code": "test10"})
    ).json()
    assert quote["discount_minor"] == 2360 and quote["total_minor"] == 21240
    assert quote["items"][0]["size"] == "M"
    payload = {**valid_checkout(), "cart_id": bag["id"], "expected_total_minor": 1}
    checkout_headers = {**headers, "Idempotency-Key": "quoted-order"}
    assert (
        await client.post("/api/v1/checkout", headers=checkout_headers, json=payload)
    ).status_code == 409
    payload["expected_total_minor"] = quote["total_minor"]
    result = await client.post(
        "/api/v1/checkout", headers=checkout_headers, json=payload
    )
    assert result.status_code == 201, result.text
    order = result.json()
    assert (
        order["total_minor"] == quote["total_minor"] and order["status"] == "confirmed"
    )
    recovered = await client.get(path + "/checkout-result", headers=checkout_headers)
    assert (
        recovered.status_code == 200
        and recovered.json()["order_token"] == order["order_token"]
    )
    assert "M" == quote["items"][0]["size"]
    order_headers = {"X-Order-Token": order["order_token"]}
    assert (
        await client.post(
            f"/api/v1/orders/{order['id']}/cancel", headers={"X-Order-Token": "wrong"}
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/orders/{order['id']}/cancel", headers=order_headers)
    ).json()["status"] == "cancelled"
    assert (
        await client.post(f"/api/v1/orders/{order['id']}/cancel", headers=order_headers)
    ).status_code == 409
    assert (await client.get(f"/api/v1/inventory/{variant_id}")).json()[
        "available"
    ] == 5


async def test_sandbox_browser_payment_ownership_and_production_guard(commerce):
    client, _, variant_id = commerce
    order, headers, _ = await checkout(client, variant_id)
    settings = get_settings()
    path = (
        f"/api/v1/orders/{order['id']}/sandbox-payment/{order['payment']['attempt_id']}"
    )
    original = settings.sandbox_browser_payments_enabled
    settings.sandbox_browser_payments_enabled = True
    try:
        assert (await client.post(path, json={"status": "captured"})).status_code == 404
        response = await client.post(
            path,
            headers={"X-Order-Token": order["order_token"]},
            json={"status": "captured"},
        )
        assert response.status_code == 200, response.text
        view = (
            await client.get(
                f"/api/v1/orders/{order['id']}",
                headers={"X-Order-Token": order["order_token"]},
            )
        ).json()
        assert (
            view["status"] == "confirmed"
            and view["payments"][0]["status"] == "captured"
        )
        settings.sandbox_browser_payments_enabled = False
        assert (
            await client.post(
                path,
                headers={"X-Order-Token": order["order_token"]},
                json={"status": "captured"},
            )
        ).status_code == 404
        settings.sandbox_browser_payments_enabled = True
        settings.environment = "prod"
        assert (
            await client.post(
                path,
                headers={"X-Order-Token": order["order_token"]},
                json={"status": "captured"},
            )
        ).status_code == 404
    finally:
        settings.environment = "dev"
        settings.sandbox_browser_payments_enabled = original


async def test_guest_support_case_token_isolation(commerce):
    client, _, _ = commerce
    response = await client.post(
        "/api/v1/support/cases/guest",
        json={
            "email": "guest@example.com",
            "subject": "Size advice",
            "body": "Please help me choose the right size.",
        },
    )
    assert response.status_code == 201, response.text
    case = response.json()
    path = f"/api/v1/support/cases/{case['id']}"
    assert (await client.get(path)).status_code == 404
    assert (
        await client.get(path, headers={"X-Case-Token": "wrong"})
    ).status_code == 404
    headers = {"X-Case-Token": case["case_token"]}
    assert (
        await client.post(
            path + "/messages",
            headers=headers,
            json={"body": "Following up on sizing."},
        )
    ).status_code == 201
    result = (await client.get(path, headers=headers)).json()
    assert len(result["messages"]) == 2


async def test_account_order_access_requires_matching_customer(commerce):
    client, _, variant_id = commerce
    bag, headers = await cart(client, variant_id)
    app.dependency_overrides[verify_token] = lambda: TokenPayload(sub="customer-owner")
    merged = await client.post(f"/api/v1/carts/{bag['id']}/merge", headers=headers)
    assert merged.status_code == 200
    body = {**valid_checkout(), "cart_id": bag["id"]}
    order = (
        await client.post(
            "/api/v1/checkout",
            headers={**headers, "Idempotency-Key": "owner-order"},
            json=body,
        )
    ).json()
    app.dependency_overrides[optional_token] = lambda: TokenPayload(
        sub="customer-owner"
    )
    assert (await client.get(f"/api/v1/orders/{order['id']}")).status_code == 200
    app.dependency_overrides[optional_token] = lambda: TokenPayload(
        sub="another-customer"
    )
    assert (await client.get(f"/api/v1/orders/{order['id']}")).status_code == 404
    assert (
        await client.post(f"/api/v1/orders/{order['id']}/cancel")
    ).status_code == 404


async def test_account_addresses_export_and_coupon_administration(commerce):
    client, factory, _ = commerce
    app.dependency_overrides[verify_token] = lambda: TokenPayload(
        sub="profile-owner", permissions=["promotion:manage"]
    )
    profile = await client.put(
        "/api/v1/customers/me",
        json={"display_name": "Local Test", "email": "profile@example.com"},
    )
    assert profile.status_code == 200
    address = (
        await client.post(
            "/api/v1/customers/me/addresses", json=valid_checkout()["shipping_address"]
        )
    ).json()
    result = (await client.get("/api/v1/customers/me/export")).json()
    assert (
        result["profile"]["email"] == "profile@example.com"
        and len(result["addresses"]) == 1
    )
    app.dependency_overrides[verify_token] = lambda: TokenPayload(sub="different-owner")
    assert (
        await client.delete(f"/api/v1/customers/me/addresses/{address['id']}")
    ).status_code == 404
    app.dependency_overrides[verify_token] = lambda: TokenPayload(
        sub="profile-owner", permissions=["promotion:manage"]
    )
    assert (
        await client.delete(f"/api/v1/customers/me/addresses/{address['id']}")
    ).status_code == 200
    promotion = await client.post(
        "/api/v1/admin/promotions",
        json={
            "name": "Coupon test",
            "percent_off": 10,
            "currency": "INR",
            "status": "published",
            "starts_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    path = f"/api/v1/admin/promotions/{promotion.json()['id']}/coupons"
    assert (await client.post(path, json={"code": "Welcome10"})).json()[
        "code"
    ] == "WELCOME10"
    assert (await client.post(path, json={"code": "welcome10"})).status_code == 409
