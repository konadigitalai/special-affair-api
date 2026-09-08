"""Opt-in extension provisioning with migration identity; run before enabling search.

Azure PostgreSQL must allow-list the vector extension first. Keep this separate
from core commerce migrations so commerce does not depend on an AI provider.
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings


async def main():
    settings = get_settings()
    database = settings.migration_database
    engine = create_async_engine(database.url, connect_args=database.connect_args)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(
            text(
                f"ALTER TABLE product_embeddings ADD COLUMN IF NOT EXISTS semantic_vector vector({settings.embedding_dimensions})"
            )
        )
    await engine.dispose()
    print(
        "Native vector column is ready; index approved products before enabling semantic search"
    )


if __name__ == "__main__":
    asyncio.run(main())
