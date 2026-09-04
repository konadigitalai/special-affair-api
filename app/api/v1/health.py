from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

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
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str] | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "failing_check": "database"})
    try:
        connection = await session.connection()
        current, heads = await connection.run_sync(_revision_state)
        if current is None or set([current]) != set(heads):
            return JSONResponse(status_code=503, content={"status": "unavailable", "failing_check": "alembic_revision"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "failing_check": "alembic_revision"})
    return {"status": "ok"}


