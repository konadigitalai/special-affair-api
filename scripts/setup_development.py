"""Back up and initialize the configured development database without seed data."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def row_counts():
    database = get_settings().migration_database
    engine = create_async_engine(database.url, connect_args=database.connect_args)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            tables = list(
                (
                    await connection.execute(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version' ORDER BY tablename"
                        )
                    )
                ).scalars()
            )
            quote = connection.dialect.identifier_preparer.quote
            return {
                table: await connection.scalar(
                    text(f"SELECT count(*) FROM public.{quote(table)}")
                )
                for table in tables
            }
    finally:
        await engine.dispose()


def run_step(label, args, log_directory, env=None):
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    # Diagnostic output stays in ignored local artifacts; never display credentials.
    (log_directory / (label + ".log")).write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    if result.returncode:
        raise RuntimeError(f"{label} failed; see its local diagnostic log")
    print(f"{label}: passed", flush=True)


def main():
    settings = get_settings()
    if settings.environment != "dev":
        raise RuntimeError("This setup command is development-only")
    app_url, migration_url = (
        make_url(settings.database_url),
        make_url(settings.database_migration_url),
    )
    if (app_url.host, app_url.port, app_url.database) != (
        migration_url.host,
        migration_url.port,
        migration_url.database,
    ):
        raise RuntimeError(
            "Application and migration URLs must target the same database"
        )
    if app_url.username == migration_url.username:
        raise RuntimeError("Use separate application and migration identities")
    dump = shutil.which("pg_dump")
    if dump is None:
        raise RuntimeError(
            "Install PostgreSQL client tools so setup can create a backup"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(".test-artifacts") / ("database-setup-" + stamp)
    directory.mkdir(parents=True, exist_ok=False)
    before = asyncio.run(row_counts())
    (directory / "before-counts.json").write_text(json.dumps(before, indent=2) + "\n")
    env = os.environ.copy()
    env["PGPASSWORD"] = migration_url.password or ""
    env["PGSSLMODE"] = (
        "require" if settings.migration_database.connect_args.get("ssl") else "prefer"
    )
    run_step(
        "backup",
        [
            dump,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--host",
            migration_url.host or "localhost",
            "--port",
            str(migration_url.port or 5432),
            "--username",
            migration_url.username or "",
            "--dbname",
            migration_url.database or "",
            "--file",
            str(directory / "before-migration.dump"),
        ],
        directory,
        env,
    )
    run_step("migrate", [sys.executable, "-m", "alembic", "upgrade", "head"], directory)
    run_step(
        "runtime-grants",
        [sys.executable, "-m", "scripts.grant_runtime", app_url.username or ""],
        directory,
    )
    run_step(
        "payment-backfill",
        [sys.executable, "-m", "scripts.backfill_payment_balances"],
        directory,
    )
    after = asyncio.run(row_counts())
    (directory / "after-counts.json").write_text(json.dumps(after, indent=2) + "\n")
    if any(after.get(table) != count for table, count in before.items()):
        raise RuntimeError(
            "Existing row counts changed; inspect setup diagnostics before continuing"
        )
    print("Setup completed; all existing table row counts preserved", flush=True)
    print("Backup and diagnostics: " + str(directory), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exception text from external libraries can contain a database URL.
        print(
            f"Development setup stopped ({type(exc).__name__}); inspect ignored setup logs",
            file=sys.stderr,
        )
        raise SystemExit(1)
