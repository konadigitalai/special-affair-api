from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConnection(BaseModel):
    url: str
    connect_args: dict[str, bool]


def normalize_asyncpg_url(url: str) -> DatabaseConnection:
    """Remove libpq-only sslmode and translate `require` to asyncpg's ssl flag."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    normalized = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return DatabaseConnection(
        url=normalized, connect_args={"ssl": True} if sslmode == "require" else {}
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["dev", "qa", "prod"]
    database_url: str
    database_migration_url: str
    auth0_domain: str
    auth0_audience: str
    frontend_urls: str = "http://localhost:3000,http://127.0.0.1:3000"
    sandbox_payment_secret: str = "local-sandbox-secret"
    token_signing_secret: str = "change-this-local-token-secret"
    log_level: str = "INFO"
    requests_per_minute: int = Field(default=120, ge=1)
    payment_provider: str = "sandbox"
    sandbox_browser_payments_enabled: bool = False
    payment_return_url: str = "http://localhost:3000/payment/upi-return"
    reservation_ttl_minutes: int = Field(default=15, ge=1, le=60)
    worker_poll_seconds: float = Field(default=1, gt=0)
    worker_lease_seconds: int = Field(default=120, ge=30)
    refund_approval_threshold_minor: int = Field(default=100000, ge=0)
    return_window_days: int = Field(default=30, ge=1)
    tax_rate_percent: int = Field(default=18, ge=0, le=100)
    shipping_fee_minor: int = Field(default=0, ge=0)
    applicationinsights_connection_string: str = ""
    azure_key_vault_url: str = ""
    azure_storage_account_url: str = ""
    azure_storage_container: str = "product-media"
    semantic_search_enabled: bool = False
    embedding_api_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=1536, ge=1, le=2000)

    @model_validator(mode="after")
    def production_secrets(self) -> "Settings":
        if self.environment == "prod" and (
            len(self.token_signing_secret) < 32
            or self.token_signing_secret.startswith("change-")
        ):
            raise ValueError(
                "TOKEN_SIGNING_SECRET must be a randomly generated secret of at least 32 characters"
            )
        if self.semantic_search_enabled and (
            not self.embedding_api_url.startswith("https://")
            or not self.embedding_api_key
            or not self.embedding_model
        ):
            raise ValueError(
                "Semantic search requires an HTTPS embedding endpoint, model and key"
            )
        return self

    @property
    def allowed_frontend_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_urls.split(",")
            if origin.strip()
        ]

    @property
    def application_database(self) -> DatabaseConnection:
        return normalize_asyncpg_url(self.database_url)

    @property
    def migration_database(self) -> DatabaseConnection:
        return normalize_asyncpg_url(self.database_migration_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
