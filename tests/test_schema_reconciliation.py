"""Regression tests for legacy column synchronization after migration 0008."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)


async def test_legacy_customer_address_dual_writes():
    url = os.environ["TEST_DATABASE_URL"]
    assert url.rsplit("/", 1)[-1].startswith("sf_test")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                legacy = await connection.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='customers' AND column_name='auth0_sub')"
                    )
                )
                if not legacy:
                    pytest.skip(
                        "Only legacy customer-layout databases require compatibility triggers"
                    )
                customer_id, address_id = uuid4(), uuid4()
                subject = "test|" + str(customer_id)
                await connection.execute(
                    text(
                        "INSERT INTO customers (id,auth_subject,display_name) VALUES (:id,:subject,'New name')"
                    ),
                    {"id": customer_id, "subject": subject},
                )
                row = (
                    await connection.execute(
                        text("SELECT auth0_sub,name FROM customers WHERE id=:id"),
                        {"id": customer_id},
                    )
                ).one()
                assert row == (subject, "New name")
                await connection.execute(
                    text("UPDATE customers SET name='Legacy update' WHERE id=:id"),
                    {"id": customer_id},
                )
                assert (
                    await connection.scalar(
                        text("SELECT display_name FROM customers WHERE id=:id"),
                        {"id": customer_id},
                    )
                    == "Legacy update"
                )
                await connection.execute(
                    text(
                        "INSERT INTO addresses(id,customer_id,details) VALUES (:id,:customer,CAST(:details AS jsonb))"
                    ),
                    {
                        "id": address_id,
                        "customer": customer_id,
                        "details": '{"full_name":"Test buyer","street":"1 Test Street","city":"Hyderabad","state":"Telangana","pin_code":"500001","country":"IN"}',
                    },
                )
                assert (
                    await connection.scalar(
                        text("SELECT city FROM addresses WHERE id=:id"),
                        {"id": address_id},
                    )
                    == "Hyderabad"
                )
                await connection.execute(
                    text("UPDATE addresses SET city='Legacy city' WHERE id=:id"),
                    {"id": address_id},
                )
                assert (
                    await connection.scalar(
                        text("SELECT details->>'city' FROM addresses WHERE id=:id"),
                        {"id": address_id},
                    )
                    == "Legacy city"
                )
                await connection.rollback()
    finally:
        await engine.dispose()
