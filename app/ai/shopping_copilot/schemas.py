from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: UUID | None = None


class ProductEvidence(BaseModel):
    slug: str
    name: str
    description: str | None
    variant_id: UUID
    variant: str
    colour: str | None
    material: str | None
    price_minor: int
    currency: str


class ProposedAction(BaseModel):
    command: str
    payload: dict[str, object]
    requires_confirmation: bool = True


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    intent: str
    products: list[ProductEvidence] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    disclaimer: str | None = None

