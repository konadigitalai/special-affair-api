from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConnection(BaseModel):
    url: str
    connect_args: dict[str, bool]


def normalize_asyncpg_url(url: str) -> DatabaseConnection:
    """Remove libpq-only sslmode and translate `require` to asyncpg's ssl flag."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return DatabaseConnection(url=normalized, connect_args={"ssl": True} if sslmode == "require" else {})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["dev", "qa", "prod"]
    database_url: str
    database_migration_url: str
    auth0_domain: str
    auth0_audience: str
    frontend_urls: str = "http://localhost:3000,http://127.0.0.1:3000"
    sandbox_payment_secret: str = "local-sandbox-secret"
    token_signing_secret: str = "change-this-local-token-secret"
    log_level: str = "INFO"

    @property
    def allowed_frontend_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.frontend_urls.split(",") if origin.strip()]

    @property
    def application_database(self) -> DatabaseConnection:
        return normalize_asyncpg_url(self.database_url)

    @property
    def migration_database(self) -> DatabaseConnection:
        return normalize_asyncpg_url(self.database_migration_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()

