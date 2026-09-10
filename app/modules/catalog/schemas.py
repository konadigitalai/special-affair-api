from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CatalogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VariantRead(CatalogSchema):
    id: UUID
    sku: str
    slug: str
    name: str
    colour: str | None
    size: str | None = None
    material: str | None
    price_minor: int
    currency: str


class CategoryRead(CatalogSchema):
    id: UUID
    slug: str
    name: str


class CollectionRead(CatalogSchema):
    id: UUID
    slug: str
    name: str


class MediaRead(CatalogSchema):
    id: UUID
    media_type: str
    public_url: str | None
    alt_text: str | None
    position: int


class ProductSummary(CatalogSchema):
    id: UUID
    slug: str
    name: str
    description: str | None
    materials: str | None
    variants: list[VariantRead]
    media: list[MediaRead]


class ProductDetail(ProductSummary):
    care: str | None
    categories: list[CategoryRead]
    collections: list[CollectionRead]


class ProductList(BaseModel):
    items: list[ProductSummary]
    limit: int
    offset: int
