"""Run against a disposable migrated PostgreSQL database via TEST_DATABASE_URL."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import TokenPayload, verify_token
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.modules.catalog.models import Product, Variant
from app.modules.inventory.models import InventoryItem, InventoryReservation, Location
from app.modules.inventory.service import sweep_expired
from app.modules.orders.models import Order
from app.modules.payments.models import PaymentAttempt, WebhookInbox
from app.modules.returns.models import Refund
from app.workers.models import OutboxEvent
from app.workers.outbox import process_one
from tests.test_checkout import valid_checkout

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Requires disposable PostgreSQL TEST_DATABASE_URL",
)


@pytest_asyncio.fixture
async def commerce():
    url = os.environ["TEST_DATABASE_URL"]
    if not url.rsplit("/", 1)[-1].startswith("sf_test"):
        pytest.fail("Integration tests only reset a database named sf_test*")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        names = ",".join('"' + name + '"' for name in Base.metadata.tables)
        await connection.execute(text("TRUNCATE " + names + " CASCADE"))

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    async with factory() as session:
        product = Product(slug="test-bag", name="Test bag", status="published")
        location = Location(name="Test warehouse")
        session.add_all([product, location])
        await session.flush()
        variant = Variant(
            product_id=product.id,
            sku="TEST-1",
            slug="black",
            name="Black",
            status="active",
            price_minor=11800,
            currency="INR",
        )
        session.add(variant)
        await session.flush()
        session.add(
            InventoryItem(
                variant_id=variant.id,
                location_id=location.id,
                on_hand=5,
                reserved=0,
                safety_stock=0,
            )
        )
        await session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, factory, variant.id
    app.dependency_overrides.clear()
    await engine.dispose()


async def cart(client, variant_id, quantity=1):
    response = await client.post("/api/v1/carts")
    assert response.status_code == 201, response.text
    data = response.json()
    headers = {"X-Cart-Token": data["cart_token"]}
    added = await client.post(
        f"/api/v1/carts/{data['id']}/items",
        headers=headers,
        json={"variant_id": str(variant_id), "quantity": quantity},
    )
    assert added.status_code == 200, added.text
    return data, headers


async def checkout(client, variant_id, quantity=1, method="upi", key="test-checkout"):
    data, headers = await cart(client, variant_id, quantity)
    body = {**valid_checkout(), "cart_id": data["id"], "payment_method": method}
    headers["Idempotency-Key"] = key
    response = await client.post("/api/v1/checkout", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json(), headers, body


async def capture(client, order, event_id="capture-1", amount=None):
    return await client.post(
        "/api/v1/webhooks/payments/sandbox",
        headers={"X-Sandbox-Secret": get_settings().sandbox_payment_secret},
        json={
            "event_id": event_id,
            "provider_reference": order["payment"]["provider_reference"],
            "status": "captured",
            "amount_minor": order["total_minor"] if amount is None else amount,
            "currency": "INR",
        },
    )


def actor(subject, *permissions):
    app.dependency_overrides[verify_token] = lambda: TokenPayload(
        sub=subject, permissions=list(permissions)
    )


async def test_checkout_replay_and_stock_protection(commerce):
    client, factory, variant_id = commerce
    order, headers, body = await checkout(client, variant_id, quantity=2)
    replay = await client.post("/api/v1/checkout", headers=headers, json=body)
    assert replay.status_code == 201 and replay.json() == order
    conflict = await client.post(
        "/api/v1/checkout", headers=headers, json={**body, "phone": "+919999999999"}
    )
    assert conflict.status_code == 409
    bad = await client.get(
        f"/api/v1/orders/{order['id']}", headers={"X-Order-Token": "wrong"}
    )
    assert bad.status_code == 404
    async with factory() as session:
        stock = await session.scalar(select(InventoryItem))
        assert stock.reserved == 2 and stock.available == 3
        rows = list((await session.scalars(select(Order))).all())
        assert len(rows) == 1


async def test_concurrent_checkout_cannot_oversell(commerce):
    client, factory, variant_id = commerce
    a, ah = await cart(client, variant_id, 4)
    b, bh = await cart(client, variant_id, 4)
    results = await asyncio.gather(
        *[
            client.post(
                "/api/v1/checkout",
                headers={**h, "Idempotency-Key": key},
                json={**valid_checkout(), "cart_id": data["id"]},
            )
            for data, h, key in [(a, ah, "a"), (b, bh, "b")]
        ]
    )
    assert sorted(x.status_code for x in results) == [201, 409]
    async with factory() as session:
        stock = await session.scalar(select(InventoryItem))
        assert stock.reserved == 4


async def test_payment_mismatch_dedup_and_confirmation(commerce):
    client, factory, variant_id = commerce
    order, _, _ = await checkout(client, variant_id)
    assert (await capture(client, order, "bad-amount", amount=1)).status_code == 409
    assert (await capture(client, order)).status_code == 200
    duplicate = await capture(client, order)
    assert duplicate.json()["status"] == "already_processed"
    async with factory() as session:
        saved = await session.get(Order, UUID(order["id"]))
        hold = await session.scalar(select(InventoryReservation))
        attempt = await session.scalar(select(PaymentAttempt))
        assert saved.status == "confirmed" and hold.status == "committed"
        assert attempt.captured_amount_minor == 11800
        inbox = (await session.scalars(select(WebhookInbox))).all()
        assert len(inbox) == 2


async def test_expiry_releases_inventory_and_late_capture_is_flagged(commerce):
    client, factory, variant_id = commerce
    order, _, _ = await checkout(client, variant_id)
    async with factory() as session:
        hold = await session.scalar(select(InventoryReservation))
        hold.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
        assert await sweep_expired(session) == 1
        await session.commit()
        stock = await session.scalar(select(InventoryItem))
        assert stock.reserved == 0
    assert (await capture(client, order)).status_code == 409


async def test_reprice_and_delisted_variant(commerce):
    client, factory, variant_id = commerce
    data, headers = await cart(client, variant_id)
    async with factory() as session:
        variant = await session.get(Variant, variant_id)
        variant.price_minor = 23600
        await session.commit()
    response = await client.post(
        "/api/v1/checkout",
        headers={**headers, "Idempotency-Key": "reprice"},
        json={**valid_checkout(), "cart_id": data["id"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["total_minor"] == 23600
    data, headers = await cart(client, variant_id)
    async with factory() as session:
        variant = await session.get(Variant, variant_id)
        variant.status = "archived"
        await session.commit()
    response = await client.post(
        "/api/v1/checkout",
        headers={**headers, "Idempotency-Key": "delisted"},
        json={**valid_checkout(), "cart_id": data["id"]},
    )
    assert response.status_code == 409


async def test_refund_bounds_and_worker_settlement(commerce):
    client, factory, variant_id = commerce
    order, _, _ = await checkout(client, variant_id)
    await capture(client, order)
    actor("maker", "refund:request")
    body = {
        "payment_attempt_id": order["payment"]["attempt_id"],
        "amount_minor": 10000,
        "currency": "INR",
    }
    response = await client.post(
        "/api/v1/refunds", headers={"Idempotency-Key": "refund-a"}, json=body
    )
    assert response.status_code == 201, response.text
    excess = await client.post(
        "/api/v1/refunds", headers={"Idempotency-Key": "refund-b"}, json=body
    )
    assert excess.status_code == 409
    for _ in range(5):
        if not await process_one(factory, get_settings()):
            break
    async with factory() as session:
        refund = await session.get(Refund, UUID(response.json()["id"]))
        attempt = await session.scalar(select(PaymentAttempt))
        assert refund.status == "refunded" and attempt.refunded_amount_minor == 10000


async def test_fulfillment_delivery_and_return(commerce):
    client, factory, variant_id = commerce
    order, _, _ = await checkout(client, variant_id, quantity=2, method="cod")
    actor("warehouse", "order:manage", "fulfillment:manage")
    allocated = await client.post(
        f"/api/v1/orders/{order['id']}/status", json={"status": "allocated"}
    )
    assert allocated.status_code == 200, allocated.text
    shipments: list[str] = []
    for quantity in (1, 1):
        response = await client.post(
            f"/api/v1/orders/{order['id']}/shipments",
            json={
                "carrier": "manual",
                "tracking_number": str(len(shipments)),
                "items": [
                    {"order_item_id": order["items"][0]["id"], "quantity": quantity}
                ],
            },
        )
        assert response.status_code == 201, response.text
        shipments.append(response.json()["id"])
    for shipment_id in shipments:
        assert (
            await client.post(f"/api/v1/shipments/{shipment_id}/delivered")
        ).status_code == 200
    response = await client.post(
        "/api/v1/returns",
        headers={"X-Order-Token": order["order_token"]},
        json={
            "order_id": order["id"],
            "reason": "Wrong fit",
            "items": [{"order_item_id": order["items"][0]["id"], "quantity": 1}],
        },
    )
    assert response.status_code == 201, response.text
    async with factory() as session:
        stock = await session.scalar(select(InventoryItem))
        assert stock.on_hand == 3 and stock.reserved == 0


async def test_guest_cart_merge_uses_max_quantity(commerce):
    client, factory, variant_id = commerce
    a, ah = await cart(client, variant_id, 2)
    actor("customer-a")
    saved = await client.post(f"/api/v1/carts/{a['id']}/merge", headers=ah)
    assert saved.status_code == 200, saved.text
    b, bh = await cart(client, variant_id, 3)
    merged = await client.post(f"/api/v1/carts/{b['id']}/merge", headers=bh)
    assert merged.status_code == 200, merged.text
    assert merged.json()["items"][0]["quantity"] == 3


async def test_audit_is_append_only(commerce):
    client, factory, variant_id = commerce
    await checkout(client, variant_id, method="cod")
    async with factory() as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(text("DELETE FROM audit_ledger"))


async def test_unknown_outbox_event_is_quarantined(commerce):
    client, factory, variant_id = commerce
    async with factory() as session:
        event = OutboxEvent(
            aggregate_type="test",
            aggregate_id=variant_id,
            event_type="Unknown",
            payload={},
        )
        session.add(event)
        await session.commit()
        event_id = event.id
    for _ in range(3):
        await process_one(factory, get_settings())
        async with factory() as session:
            event = await session.get(OutboxEvent, event_id)
            event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()
    async with factory() as session:
        event = await session.get(OutboxEvent, event_id)
        assert event.status == "dead" and event.attempts == 3


async def test_concurrent_identical_checkout_replays_same_response(commerce):
    client, factory, variant_id = commerce
    data, headers = await cart(client, variant_id)
    headers["Idempotency-Key"] = "parallel-replay"
    body = {**valid_checkout(), "cart_id": data["id"], "payment_method": "upi"}
    responses = await asyncio.gather(
        *[client.post("/api/v1/checkout", headers=headers, json=body) for _ in range(2)]
    )
    assert [x.status_code for x in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()


async def test_provider_runs_without_database_transaction(commerce, monkeypatch):
    from app.integrations.payments import SandboxProvider
    from app.modules.checkout.router import CheckoutRequest
    from app.modules.checkout.service import submit_checkout

    client, factory, variant_id = commerce
    data, headers = await cart(client, variant_id)
    original = SandboxProvider.create_session
    calls = []
    async with factory() as session:

        async def checked(self, *args):
            calls.append(session.in_transaction())
            return await original(self, *args)

        monkeypatch.setattr(SandboxProvider, "create_session", checked)
        await submit_checkout(
            CheckoutRequest.model_validate(
                {**valid_checkout(), "cart_id": data["id"], "payment_method": "upi"}
            ),
            "boundary",
            headers["X-Cart-Token"],
            get_settings(),
            session,
        )
    assert calls == [False]


async def test_decline_retry_uses_same_order_new_attempt(commerce):
    client, factory, variant_id = commerce
    order, headers, _ = await checkout(client, variant_id)
    response = await client.post(
        "/api/v1/webhooks/payments/sandbox",
        headers={"X-Sandbox-Secret": get_settings().sandbox_payment_secret},
        json={
            "event_id": "decline",
            "provider_reference": order["payment"]["provider_reference"],
            "status": "failed",
            "amount_minor": order["total_minor"],
            "currency": "INR",
        },
    )
    assert response.status_code == 200, response.text
    retry = await client.post(
        f"/api/v1/checkout/{order['checkout_id']}/payment-intent",
        headers=headers,
        json={"method": "upi"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["attempt_id"] != order["payment"]["attempt_id"]
    order["payment"] = retry.json()
    assert (await capture(client, order, "retry-capture")).status_code == 200


async def test_refund_requires_separate_checker(commerce):
    client, factory, variant_id = commerce
    async with factory() as session:
        variant = await session.get(Variant, variant_id)
        variant.price_minor = 200000
        await session.commit()
    order, _, _ = await checkout(client, variant_id)
    await capture(client, order)
    actor("maker", "refund:request")
    body = {
        "payment_attempt_id": order["payment"]["attempt_id"],
        "amount_minor": 150000,
        "currency": "INR",
    }
    response = await client.post(
        "/api/v1/refunds", headers={"Idempotency-Key": "large-refund"}, json=body
    )
    assert response.status_code == 201, response.text
    refund = response.json()
    assert refund["status"] == "awaiting_approval"
    actor("maker", "refund:approve")
    rejected = await client.post(
        f"/api/v1/approvals/{refund['approval_id']}/decision", json={"approved": True}
    )
    assert rejected.status_code == 403
    actor("checker", "refund:approve")
    approved = await client.post(
        f"/api/v1/approvals/{refund['approval_id']}/decision", json={"approved": True}
    )
    assert approved.status_code == 200, approved.text
    for _ in range(4):
        if not await process_one(factory, get_settings()):
            break
    async with factory() as session:
        saved = await session.get(Refund, UUID(refund["id"]))
        assert saved.status == "refunded"


async def test_effective_price_and_promotion_are_snapshotted(commerce):
    from app.modules.pricing.models import Price, PriceBook
    from app.modules.promotions.models import Promotion

    client, factory, variant_id = commerce
    now = datetime.now(timezone.utc)
    async with factory() as session:
        book = PriceBook(name="Current", currency="INR", priority=1)
        session.add(book)
        await session.flush()
        session.add(
            Price(
                price_book_id=book.id,
                variant_id=variant_id,
                amount_minor=23600,
                currency="INR",
                starts_at=now - timedelta(days=1),
            )
        )
        session.add(
            Promotion(
                name="Ten percent",
                percent_off=10,
                currency="INR",
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=1),
                status="published",
            )
        )
        await session.commit()
    order, _, _ = await checkout(client, variant_id, method="cod")
    assert order["subtotal_minor"] == 23600 and order["discount_minor"] == 2360
    assert order["total_minor"] == 21240 and order["tax_included_minor"] == 3240


async def test_customer_support_and_approved_erasure(commerce):
    client, factory, variant_id = commerce
    actor("customer-privacy")
    assert (
        await client.put(
            "/api/v1/customers/me",
            json={"display_name": "Buyer", "email": "buyer@example.com"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/customers/me/consents",
            json={"purpose": "marketing", "granted": True, "notice_version": "v1"},
        )
    ).status_code == 201
    case = await client.post(
        "/api/v1/support/cases",
        json={"subject": "A question", "body": "Personal support text"},
    )
    assert case.status_code == 201, case.text
    request = await client.post("/api/v1/customers/me/erasure-requests")
    assert request.status_code == 202, request.text
    actor("privacy-checker", "privacy:approve")
    approved = await client.post(
        f"/api/v1/privacy/erasure-requests/{request.json()['id']}/approve"
    )
    assert approved.status_code == 200, approved.text
    from app.modules.customers.models import Customer
    from app.modules.support.models import CaseMessage

    async with factory() as session:
        customer = await session.scalar(select(Customer))
        message = await session.scalar(select(CaseMessage))
        assert (
            customer.email is None
            and customer.display_name is None
            and message.body is None
        )


async def test_catalog_publication_and_staff_permissions(commerce):
    client, factory, variant_id = commerce
    payload = {"slug": "new-product", "name": "New product"}
    assert (
        await client.post("/api/v1/admin/products", json=payload)
    ).status_code == 401
    actor("catalog", "product:update", "product:publish")
    response = await client.post("/api/v1/admin/products", json=payload)
    assert response.status_code == 201, response.text
    product_id = response.json()["id"]
    incomplete = await client.post(
        f"/api/v1/admin/products/{product_id}/publication",
        json={"version": 1, "status": "published"},
    )
    assert incomplete.status_code == 409
    variant = await client.post(
        f"/api/v1/admin/products/{product_id}/variants",
        json={
            "sku": "NEW",
            "slug": "new",
            "name": "New",
            "price_minor": 100,
            "currency": "INR",
        },
    )
    assert variant.status_code == 201
    stale = await client.post(
        f"/api/v1/admin/products/{product_id}/publication",
        json={"version": 1, "status": "published"},
    )
    assert stale.status_code == 409
    published = await client.post(
        f"/api/v1/admin/products/{product_id}/publication",
        json={"version": 2, "status": "published"},
    )
    assert published.status_code == 200


async def test_copilot_sessions_require_ownership(commerce):
    client, factory, variant_id = commerce
    response = await client.post("/api/v1/copilot/chat", json={"message": "Show bags"})
    assert response.status_code == 200, response.text
    data = response.json()
    unauthorized = await client.post(
        "/api/v1/copilot/chat",
        json={"message": "Show bags", "session_id": data["session_id"]},
    )
    assert unauthorized.status_code == 404
    authorized = await client.post(
        "/api/v1/copilot/chat",
        json={
            "message": "Show bags",
            "session_id": data["session_id"],
            "session_token": data["session_token"],
        },
    )
    assert authorized.status_code == 200


async def test_native_semantic_search_uses_approved_products(commerce, monkeypatch):
    from app.ai.shopping_copilot import semantic
    from app.ai.shopping_copilot.models import ProductEmbedding

    client, factory, variant_id = commerce
    async with factory() as session:
        native = await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name = 'product_embeddings' AND column_name = 'semantic_vector')"
            )
        )
        if not native:
            pytest.skip("Native pgvector provisioning is optional")
        settings = get_settings()
        monkeypatch.setattr(settings, "embedding_model", "test-embedding")
        vector = [1.0] + [0.0] * (settings.embedding_dimensions - 1)

        async def fake_embed(_):
            return vector

        monkeypatch.setattr(semantic, "embed", fake_embed)
        variant = await session.get(Variant, variant_id)
        session.add(
            ProductEmbedding(
                product_id=variant.product_id,
                source_text="Test bag",
                embedding=vector,
                embedding_model=settings.embedding_model,
            )
        )
        await session.flush()
        await session.execute(
            text(
                "UPDATE product_embeddings SET semantic_vector = CAST(:vector AS vector)"
            ),
            {"vector": semantic.vector_literal(vector, settings.embedding_dimensions)},
        )
        await session.commit()
        results = await semantic.semantic_products(session, "bag", 5)
        assert len(results) == 1 and results[0][1].id == variant_id
        product = await session.get(Product, variant.product_id)
        product.status = "draft"
        await session.commit()
        assert await semantic.semantic_products(session, "bag", 5) == []
