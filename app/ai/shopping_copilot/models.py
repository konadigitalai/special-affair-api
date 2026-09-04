from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class CopilotSession(TimestampMixin, Base):
    __tablename__ = "copilot_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    customer_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)


class CopilotMessage(TimestampMixin, Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role_allowed"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("copilot_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)


class ProductEmbedding(TimestampMixin, Base):
    __tablename__ = "product_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False, default=list)
    embedding_model: Mapped[str] = mapped_column(String(150), nullable=False)

