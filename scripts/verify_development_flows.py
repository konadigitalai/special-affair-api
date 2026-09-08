"""Exercise development commerce inside a transaction that is always rolled back.

Uses test identity overrides for route-level business checks, not a real Auth0 login.
Only the development sandbox provider may run. No customer messages are sent.
"""

import asyncio
from uuid import uuid4
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import TokenPayload, verify_token
from app.db.session import get_session
from app.main import app
from app.modules.catalog.models import Product, Variant
from app.modules.inventory.models import InventoryItem, Location


async def main():
    settings = get_settings()
    if settings.environment != "dev" or settings.payment_provider != "sandbox":
        raise RuntimeError(
            "Flow verification requires development sandbox configuration"
        )
    database = settings.application_database
    engine = create_async_engine(database.url, connect_args=database.connect_args)
    original_overrides = app.dependency_overrides.copy()
    checks = []
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:

                async def sessions():
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                subject = "verification|" + str(uuid4())
                app.dependency_overrides[get_session] = sessions
                app.dependency_overrides[verify_token] = lambda: TokenPayload(
                    sub=subject
                )
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    variant = await session.scalar(
                        select(Variant)
                        .join(Product)
                        .where(
                            Variant.status == "active", Product.status == "published"
                        )
                        .limit(1)
                    )
                    if variant is None:
                        fixture_key = uuid4().hex
                        product = Product(
                            slug="verification-" + fixture_key,
                            name="Rollback verification product",
                            status="published",
                        )
                        session.add(product)
                        await session.flush()
                        variant = Variant(
                            product_id=product.id,
                            sku="VERIFY-" + fixture_key,
                            slug="verification",
                            name="Verification variant",
                            status="active",
                            price_minor=11800,
                            currency="INR",
                        )
                        session.add(variant)
                        await session.flush()
                    variant_id = variant.id
                    location = Location(name="Rollback verification " + str(uuid4()))
                    session.add(location)
                    await session.flush()
                    session.add(
                        InventoryItem(
                            variant_id=variant_id,
                            location_id=location.id,
                            on_hand=2,
                            reserved=0,
                            safety_stock=0,
                        )
                    )
                    await session.commit()
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://verification.local",
                ) as client:

                    async def checked(method, path, expected, **kwargs):
                        response = await client.request(method, path, **kwargs)
                        if response.status_code != expected:
                            raise RuntimeError(
                                f"{method} {path.split('?')[0]} returned {response.status_code}, expected {expected}"
                            )
                        checks.append(f"{method} {path.split('?')[0]}: {expected}")
                        return response.json()

                    await checked("GET", "/health/ready", 200)
                    await checked("GET", "/api/v1/customers/me", 200)
                    address = {
                        "full_name": "Verification buyer",
                        "street": "1 Verification Street",
                        "city": "Hyderabad",
                        "state": "Telangana",
                        "pin_code": "500001",
                        "country": "IN",
                    }
                    await checked(
                        "POST", "/api/v1/customers/me/addresses", 201, json=address
                    )
                    cart = await checked("POST", "/api/v1/carts", 201)
                    cart_headers = {"X-Cart-Token": cart["cart_token"]}
                    await checked(
                        "POST",
                        f"/api/v1/carts/{cart['id']}/items",
                        200,
                        headers=cart_headers,
                        json={"variant_id": str(variant_id), "quantity": 1},
                    )
                    payload = {
                        "cart_id": cart["id"],
                        "email": "verification@example.com",
                        "phone": "+919000000000",
                        "shipping_address": address,
                        "payment_method": "upi",
                    }
                    headers = {
                        **cart_headers,
                        "Idempotency-Key": "verification-" + str(uuid4()),
                    }
                    order = await checked(
                        "POST", "/api/v1/checkout", 201, headers=headers, json=payload
                    )
                    replay = await checked(
                        "POST", "/api/v1/checkout", 201, headers=headers, json=payload
                    )
                    if order != replay:
                        raise RuntimeError("Checkout replay did not match")
                    await checked(
                        "POST",
                        "/api/v1/webhooks/payments/sandbox",
                        200,
                        headers={"X-Sandbox-Secret": settings.sandbox_payment_secret},
                        json={
                            "event_id": "verification-" + str(uuid4()),
                            "provider_reference": order["payment"][
                                "provider_reference"
                            ],
                            "status": "captured",
                            "amount_minor": order["total_minor"],
                            "currency": order["currency"],
                        },
                    )
                    confirmed = await checked(
                        "GET",
                        f"/api/v1/orders/{order['id']}",
                        200,
                        headers={"X-Order-Token": order["order_token"]},
                    )
                    if confirmed["status"] != "confirmed":
                        raise RuntimeError("Sandbox payment did not confirm order")
            finally:
                await outer.rollback()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        await engine.dispose()
    print(f"Development flow checks passed: {len(checks)}")
    print(
        "Verified profile, address, cart, checkout replay, sandbox callback and confirmed order"
    )
    print(
        "All verification writes rolled back; no sample stock or orders were retained"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            f"Development flow verification failed ({type(exc).__name__}); all test writes rolled back"
        )
        raise SystemExit(1)
