"""Read-only connection checks; never print credentials, URLs or exception bodies."""

import asyncio
import json
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from pydantic import ValidationError

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base


async def database_check(database, application=False):
    result = {}
    engine = None
    try:
        engine = create_async_engine(
            database.url,
            connect_args={
                **database.connect_args,
                "timeout": 10,
                "command_timeout": 10,
            },
            pool_pre_ping=True,
        )
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(text("SELECT 1"))
                result["connection"] = "passed"
                result["server_major_version"] = (
                    int(await connection.scalar(text("SHOW server_version_num")))
                    // 10000
                )
                tables = set(
                    (
                        await connection.execute(
                            text(
                                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                            )
                        )
                    ).scalars()
                )
                result["missing_tables"] = sorted(set(Base.metadata.tables) - tables)
                columns = {}
                for table_name, column_name in await connection.execute(
                    text(
                        "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'"
                    )
                ):
                    columns.setdefault(table_name, set()).add(column_name)
                result["missing_columns"] = {
                    table.name: sorted(
                        set(table.columns.keys()) - columns.get(table.name, set())
                    )
                    for table in Base.metadata.sorted_tables
                    if table.name in tables
                    and set(table.columns.keys()) - columns.get(table.name, set())
                }
                if "alembic_version" in tables:
                    result["database_revisions"] = list(
                        (
                            await connection.execute(
                                text("SELECT version_num FROM alembic_version")
                            )
                        ).scalars()
                    )
                else:
                    result["database_revisions"] = []
                result["expected_revisions"] = ScriptDirectory.from_config(
                    Config("alembic.ini")
                ).get_heads()
                result["schema_matches"] = (
                    not result["missing_tables"]
                    and not result["missing_columns"]
                    and set(result["database_revisions"])
                    == set(result["expected_revisions"])
                )
                if application:
                    result["runtime_superuser"] = await connection.scalar(
                        text(
                            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
                        )
                    )
                    result["missing_select_permissions"] = []
                    result["missing_write_permissions"] = []
                    immutable = {
                        "audit_ledger",
                        "consent_records",
                        "stock_movements",
                        "order_status_history",
                        "order_items",
                        "payment_transactions",
                    }
                    result["mutable_history_grants"] = []
                    for table in sorted(set(Base.metadata.tables) & tables):
                        if not await connection.scalar(
                            text(
                                "SELECT has_table_privilege(current_user, :table, 'SELECT')"
                            ),
                            {"table": table},
                        ):
                            result["missing_select_permissions"].append(table)
                        permissions = (
                            ["INSERT"]
                            if table in immutable
                            else ["INSERT", "UPDATE", "DELETE"]
                        )
                        for permission in permissions:
                            if not await connection.scalar(
                                text(
                                    "SELECT has_table_privilege(current_user, :table, :permission)"
                                ),
                                {"table": table, "permission": permission},
                            ):
                                result["missing_write_permissions"].append(
                                    f"{table}:{permission}"
                                )
                        if table in immutable and await connection.scalar(
                            text(
                                "SELECT has_table_privilege(current_user, :table, 'UPDATE,DELETE')"
                            ),
                            {"table": table},
                        ):
                            result["mutable_history_grants"].append(table)
                    if {"variants", "inventory_items"} <= tables:
                        result[
                            "active_variants_without_inventory"
                        ] = await connection.scalar(
                            text(
                                "SELECT count(*) FROM variants v WHERE v.status='active' AND NOT EXISTS (SELECT 1 FROM inventory_items i WHERE i.variant_id=v.id)"
                            )
                        )
    except Exception as exc:
        result.setdefault("connection", "failed")
        result["checks_completed"] = False
        result["error_class"] = type(exc).__name__
        cause = getattr(exc, "orig", exc)
        result["sqlstate"] = getattr(cause, "sqlstate", None)
    finally:
        if engine is not None:
            await engine.dispose()
    return result


async def identity_check(settings):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://{settings.auth0_domain}/.well-known/openid-configuration"
            )
            if response.status_code != 200:
                return {"discovery": "failed", "http_status": response.status_code}
            metadata = response.json()
            issuer_ok = metadata.get("issuer") == f"https://{settings.auth0_domain}/"
            response = await client.get(
                f"https://{settings.auth0_domain}/.well-known/jwks.json"
            )
            keys = (
                response.json().get("keys", []) if response.status_code == 200 else []
            )
            return {
                "discovery": "passed",
                "issuer_matches": issuer_ok,
                "jwks_http_status": response.status_code,
                "rsa_signing_keys": sum(
                    key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                    for key in keys
                ),
                "audience_registration": "requires_valid_access_token",
            }
    except Exception as exc:
        return {"discovery": "failed", "error_class": type(exc).__name__}


async def main():
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(
            json.dumps(
                {
                    "configuration": "invalid",
                    "errors": [
                        {"field": e["loc"], "type": e["type"]}
                        for e in exc.errors(include_input=False)
                    ],
                }
            )
        )
        return 1
    app_db, migration_db, identity = await asyncio.gather(
        database_check(settings.application_database, application=True),
        database_check(settings.migration_database),
        identity_check(settings),
    )
    result = {
        "application_database": app_db,
        "migration_database": migration_db,
        "auth0": identity,
        "checks_are_read_only": True,
    }
    target = Path(".test-artifacts/configuration-verification.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return (
        0
        if (
            app_db.get("schema_matches")
            and migration_db.get("schema_matches")
            and not app_db.get("missing_select_permissions")
            and not app_db.get("missing_write_permissions")
            and not app_db.get("mutable_history_grants")
            and not app_db.get("runtime_superuser")
            and "error_class" not in app_db
            and "error_class" not in migration_db
            and identity.get("issuer_matches")
            and identity.get("rsa_signing_keys", 0) > 0
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
