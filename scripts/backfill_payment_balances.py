"""Run after migration 0006 and before enabling refund APIs on legacy data."""

import asyncio
from sqlalchemy import text
from app.db.session import get_session_factory


async def main():
    total = 0
    while True:
        async with get_session_factory()() as session:
            result = await session.execute(
                text("""
                WITH batch AS (
                    SELECT id FROM payment_attempts
                    WHERE status = 'captured' AND captured_amount_minor = 0 AND amount_minor > 0
                    ORDER BY id LIMIT 500 FOR UPDATE SKIP LOCKED
                )
                UPDATE payment_attempts p SET captured_amount_minor = amount_minor
                FROM batch WHERE p.id = batch.id RETURNING p.id
            """)
            )
            count = len(result.all())
            await session.commit()
        total += count
        if not count:
            break
    print(f"Backfilled {total} legacy captured balances")


if __name__ == "__main__":
    asyncio.run(main())
