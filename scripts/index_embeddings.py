"""Index approved catalog text; provider calls run outside database transactions."""

import asyncio
from sqlalchemy import select, text
from app.ai.shopping_copilot.models import ProductEmbedding
from app.ai.shopping_copilot.semantic import embed, vector_literal
from app.core.config import get_settings
from app.core.domain import lock_key
from app.db.session import get_session_factory
from app.modules.catalog.models import Product


async def main():
    factory = get_session_factory()
    settings = get_settings()
    async with factory() as session:
        products = (
            await session.scalars(select(Product).where(Product.status == "published"))
        ).all()
        sources = [(p.id, p.name + "\n" + (p.description or "")) for p in products]
    indexed = 0
    for product_id, source in sources:
        values = await embed(source)
        async with factory() as session:
            await lock_key(session, "embedding", str(product_id))
            current = await session.get(Product, product_id)
            if (
                current is None
                or current.status != "published"
                or source != current.name + "\n" + (current.description or "")
            ):
                continue
            row = await session.scalar(
                select(ProductEmbedding).where(
                    ProductEmbedding.product_id == product_id
                )
            )
            if row is None:
                row = ProductEmbedding(
                    product_id=product_id,
                    source_text=source,
                    embedding=values,
                    embedding_model=settings.embedding_model,
                )
                session.add(row)
            else:
                row.source_text, row.embedding, row.embedding_model = (
                    source,
                    values,
                    settings.embedding_model,
                )
            await session.flush()
            await session.execute(
                text(
                    "UPDATE product_embeddings SET semantic_vector = CAST(:vector AS vector) WHERE product_id = :id"
                ),
                {
                    "vector": vector_literal(values, settings.embedding_dimensions),
                    "id": product_id,
                },
            )
            await session.commit()
            indexed += 1
    print(f"Indexed {indexed} approved products")


if __name__ == "__main__":
    asyncio.run(main())
