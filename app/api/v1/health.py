from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.core.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


def _revision_state(sync_connection: object) -> tuple[str | None, tuple[str, ...]]:
    context = MigrationContext.configure(sync_connection)  # type: ignore[arg-type]
    current = context.get_current_revision()
    config_path = Path(__file__).resolve().parents[3] / "alembic.ini"
    script = ScriptDirectory.from_config(Config(str(config_path)))
    return current, tuple(script.get_heads())


@router.get("/ready", response_model=None)
async def ready(
    session: AsyncSession = Depends(get_session),
) -> dict[str, str] | JSONResponse:
    settings = get_settings()
    if any(
        str(value).startswith("@Microsoft.KeyVault(")
        for value in (
            settings.database_url,
            settings.database_migration_url,
            settings.token_signing_secret,
        )
    ):
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "failing_check": "key_vault_reference"},
        )
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "failing_check": "database"},
        )
    try:
        connection = await session.connection()
        current, heads = await connection.run_sync(_revision_state)
        if current is None or set([current]) != set(heads):
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "failing_check": "alembic_revision"},
            )
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "failing_check": "alembic_revision"},
        )
    if settings.semantic_search_enabled:
        try:
            await session.execute(
                text("SELECT semantic_vector FROM product_embeddings LIMIT 0")
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "failing_check": "semantic_schema"},
            )
    return {"status": "ok"}
