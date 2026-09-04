from types import SimpleNamespace
from uuid import UUID

from httpx import AsyncClient
from pytest import MonkeyPatch

from app.modules.catalog import router as catalog_router

PRODUCT_ID = UUID("018f0f5d-83b7-7cc8-95d8-1ebdba28d001")
VARIANT_ID = UUID("018f0f5d-83b7-7cc8-95d8-1ebdba28d002")


def product_record() -> SimpleNamespace:
    return SimpleNamespace(
        id=PRODUCT_ID,
        slug="classic-bouquet",
        name="Classic Bouquet",
        description="Seasonal flowers",
        materials="Leather",
        care="Wipe clean",
        variants=[SimpleNamespace(id=VARIANT_ID, sku="BOUQUET-CLASSIC", slug="standard", name="Standard", colour="Ivory", material="Leather", price_minor=3550000, currency="INR")],
        media=[],
        categories=[],
        collections=[],
    )


async def test_list_products_returns_paginated_public_catalog(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_list(*_: object, **__: object) -> list[SimpleNamespace]:
        return [product_record()]

    monkeypatch.setattr(catalog_router, "list_published_products", fake_list)
    response = await client.get("/api/v1/products?limit=10&offset=0")

    assert response.status_code == 200
    assert response.json()["items"][0]["slug"] == "classic-bouquet"
    assert response.json()["limit"] == 10


async def test_get_product_returns_not_found_error(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_get(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(catalog_router, "get_published_product", fake_get)
    response = await client.get(f"/api/v1/products/{PRODUCT_ID}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "product_not_found"
    assert response.json()["error"]["correlation_id"]


async def test_get_product_uses_public_slug(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    async def fake_get(*_: object, **__: object) -> SimpleNamespace:
        return product_record()

    monkeypatch.setattr(catalog_router, "get_published_product", fake_get)
    response = await client.get("/api/v1/products/classic-bouquet")

    assert response.status_code == 200
    assert response.json()["slug"] == "classic-bouquet"
