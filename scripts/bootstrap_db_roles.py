"""One-off, idempotent bootstrap for SpecialAffair database roles."""

import asyncio
import os
import secrets
import string
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import normalize_asyncpg_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
ROLES = ("sa_migrate", "sa_app", "sa_read")
PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(32))


def assert_env_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Refusing to write .env because Git does not ignore it")


def replace_env_lines(application_url: str, migration_url: str) -> None:
    assert_env_is_ignored()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacements = {
        "DATABASE_URL": application_url,
        "DATABASE_MIGRATION_URL": migration_url,
    }
    found: set[str] = set()
    updated: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in replacements:
            updated.append(f"{key}={replacements[key]}")
            found.add(key)
        else:
            updated.append(line)
    for key in replacements.keys() - found:
        updated.append(f"{key}={replacements[key]}")
    ENV_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")


async def bootstrap() -> None:
    load_dotenv(ENV_PATH)
    admin_url = os.getenv("ADMIN_DATABASE_URL")
    if not admin_url:
        raise RuntimeError("ADMIN_DATABASE_URL is required")

    passwords = {role: generate_password() for role in ROLES}
    database = normalize_asyncpg_url(admin_url)
    engine = create_async_engine(database.url, connect_args=database.connect_args)

    try:
        async with engine.begin() as connection:
            for role in ROLES:
                exists = await connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"
                    ),
                    {"role": role},
                )
                password = passwords[role]
                if exists:
                    await connection.exec_driver_sql(
                        f"ALTER ROLE {role} LOGIN PASSWORD '{password}'"
                    )
                else:
                    await connection.exec_driver_sql(
                        f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"
                    )

            await connection.exec_driver_sql("GRANT sa_migrate TO CURRENT_USER")
            await connection.exec_driver_sql(
                "GRANT CONNECT ON DATABASE special_affair_dev TO sa_migrate, sa_app, sa_read"
            )
            await connection.exec_driver_sql("GRANT ALL ON SCHEMA public TO sa_migrate")
            await connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO sa_app")
            await connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO sa_read")
            await connection.exec_driver_sql(
                "REVOKE CREATE ON SCHEMA public FROM PUBLIC"
            )
            await connection.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES FOR ROLE sa_migrate IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sa_app"
            )
            await connection.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES FOR ROLE sa_migrate IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO sa_app"
            )
            await connection.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES FOR ROLE sa_migrate IN SCHEMA public "
                "GRANT SELECT ON TABLES TO sa_read"
            )
    finally:
        await engine.dispose()

    parsed = urlsplit(database.url)
    host = parsed.hostname
    if not host:
        raise RuntimeError("ADMIN_DATABASE_URL has no hostname")
    port = parsed.port or 5432
    app_url = (
        f"postgresql+asyncpg://sa_app:{passwords['sa_app']}@{host}:{port}"
        "/special_affair_dev?sslmode=require"
    )
    migration_url = (
        f"postgresql+asyncpg://sa_migrate:{passwords['sa_migrate']}@{host}:{port}"
        "/special_affair_dev?sslmode=require"
    )
    replace_env_lines(app_url, migration_url)

    print(
        "Database roles configured; application and migration credentials saved to ignored .env"
    )


if __name__ == "__main__":
    asyncio.run(bootstrap())
