"""Optional provider-configured embeddings and native pgvector retrieval."""

import math
import httpx
from sqlalchemy import select, text
from app.core.config import get_settings
from app.modules.catalog.models import Product, Variant


def vector_literal(values: list[float], dimensions: int) -> str:
    if len(values) != dimensions or any(not math.isfinite(x) for x in values):
        raise ValueError("Embedding dimensions or values are invalid")
    if not any(values):
        raise ValueError("A zero embedding cannot be cosine-ranked")
    return "[" + ",".join(str(float(x)) for x in values) + "]"


async def embed(content: str) -> list[float]:
    settings = get_settings()
    if (
        not settings.embedding_api_url.startswith("https://")
        or not settings.embedding_model
        or not settings.embedding_api_key
    ):
        raise RuntimeError(
            "Configure the embedding endpoint, model and key before enabling semantic search"
        )
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.embedding_api_url,
            headers={"Authorization": "Bearer " + settings.embedding_api_key},
            json={"model": settings.embedding_model, "input": content},
        )
        response.raise_for_status()
        values = [float(x) for x in response.json()["data"][0]["embedding"]]
    vector_literal(values, settings.embedding_dimensions)
    return values


async def semantic_products(session, message: str, limit: int):
    settings = get_settings()
    query_vector = vector_literal(await embed(message), settings.embedding_dimensions)
    # Product lifecycle is checked in the same database query; vectors never determine sellability.
    rows = await session.execute(
        text("""
        SELECT e.product_id FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE p.status = 'published' AND e.embedding_model = :model
          AND e.semantic_vector IS NOT NULL
        ORDER BY e.semantic_vector <=> CAST(:query AS vector)
        LIMIT :limit
    """),
        {"model": settings.embedding_model, "query": query_vector, "limit": limit},
    )
    ids = [row[0] for row in rows]
    if not ids:
        return []
    pairs = (
        await session.execute(
            select(Product, Variant)
            .join(Variant)
            .where(
                Product.id.in_(ids),
                Product.status == "published",
                Variant.status == "active",
            )
        )
    ).all()
    rank = {product_id: index for index, product_id in enumerate(ids)}
    return sorted(
        [(p, v) for p, v in pairs],
        key=lambda pair: (rank[pair[0].id], pair[1].price_minor),
    )[:limit]
