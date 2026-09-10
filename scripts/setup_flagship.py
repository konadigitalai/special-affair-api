"""Back up and enable the approved client-review wishlist and apparel catalogue."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
from scripts.setup_development import row_counts, run_step


async def grant_new_tables():
    settings = get_settings()
    database = settings.migration_database
    engine = create_async_engine(database.url, connect_args=database.connect_args)
    try:
        async with engine.begin() as connection:
            quote = connection.dialect.identifier_preparer.quote
            role = make_url(settings.database_url).username
            if not role:
                raise RuntimeError("Application role is required")
            for table in ["wishlists", "wishlist_items"]:
                await connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {quote(table)} TO {quote(role)}"))
    finally:
        await engine.dispose()


def main():
    settings = get_settings()
    application, migration = make_url(settings.database_url), make_url(settings.database_migration_url)
    if settings.environment != "dev" or (application.host, application.port, application.database) != (migration.host, migration.port, migration.database):
        raise RuntimeError("Both identities must target the same development database")
    directory = Path(".test-artifacts") / ("flagship-setup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir(parents=True, exist_ok=False)
    before = asyncio.run(row_counts())
    (directory / "before-counts.json").write_text(json.dumps(before, indent=2))
    binary = Path(r"C:\Program Files\PostgreSQL\18\bin")
    env = os.environ.copy()
    env["PGPASSWORD"] = migration.password or ""
    env["PGSSLMODE"] = "require" if settings.migration_database.connect_args.get("ssl") else "prefer"
    env["PGCONNECT_TIMEOUT"] = "15"
    dump = directory / "before-migration.dump"
    run_step("backup", [str(binary / "pg_dump.exe"), "--format=custom", "--no-owner", "--no-acl", "--host", migration.host or "localhost", "--port", str(migration.port or 5432), "--username", migration.username or "", "--dbname", migration.database or "", "--file", str(dump)], directory, env)
    run_step("backup-validation", [str(binary / "pg_restore.exe"), "--list", str(dump)], directory)
    run_step("migration", [sys.executable, "-m", "alembic", "upgrade", "0010"], directory)
    after = asyncio.run(row_counts())
    if any(after.get(table) != count for table, count in before.items()):
        raise RuntimeError("Existing row counts changed; inspect before proceeding")
    print("Existing records preserved", flush=True)
    asyncio.run(grant_new_tables())
    print("Wishlist runtime grants applied", flush=True)
    run_step("sample-catalogue", [sys.executable, "-m", "scripts.seed_flagship"], directory)
    print("Client-review database ready; backup: " + str(dump), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Setup stopped: " + type(exc).__name__ + "; inspect ignored setup logs", file=sys.stderr)
        raise SystemExit(1)
