"""Provider boundary. No database sessions cross this interface."""

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.exceptions import AppError


@dataclass(frozen=True)
class PaymentSession:
    reference: str
    client_secret: str | None
    redirect_url: str | None


class PaymentProvider(Protocol):
    async def create_session(
        self,
        attempt_id: UUID,
        amount_minor: int,
        currency: str,
        method: str,
        idempotency_key: str,
    ) -> PaymentSession: ...
    async def refund(
        self, reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> str: ...


class SandboxProvider:
    def __init__(self, return_url: str) -> None:
        self.return_url = return_url

    async def create_session(
        self,
        attempt_id: UUID,
        amount_minor: int,
        currency: str,
        method: str,
        idempotency_key: str,
    ) -> PaymentSession:
        reference = f"sandbox_{attempt_id.hex}"
        return PaymentSession(
            reference,
            reference if method == "card" else None,
            f"{self.return_url}?reference={reference}" if method == "upi" else None,
        )

    async def refund(
        self, reference: str, amount_minor: int, currency: str, idempotency_key: str
    ) -> str:
        return (
            "sandbox_refund_"
            + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        )


def payment_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider != "sandbox" or settings.environment == "prod":
        raise AppError(
            503,
            "payment_provider_unconfigured",
            "A production payment provider must be configured",
        )
    return SandboxProvider(settings.payment_return_url)
