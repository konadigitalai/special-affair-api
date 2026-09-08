"""Apply least-privilege grants with the migration identity; never print secrets."""

import asyncio
import re
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings


async def main(role: str):
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError("Expected a simple PostgreSQL role identifier")
    database = get_settings().migration_database
    engine = create_async_engine(database.url, connect_args=database.connect_args)
    async with engine.begin() as connection:
        await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        await connection.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
        )
        await connection.execute(text(f'REVOKE ALL ON alembic_version FROM "{role}"'))
        await connection.execute(text(f'GRANT SELECT ON alembic_version TO "{role}"'))
        for table in (
            "audit_ledger",
            "consent_records",
            "stock_movements",
            "order_status_history",
            "order_items",
            "payment_transactions",
        ):
            await connection.execute(
                text(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM "{role}"')
            )
    await engine.dispose()
    print(f"Applied runtime grants to {role}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
