from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from app.core.config import get_settings
from app.core.telemetry import configure_telemetry

configure_telemetry(get_settings())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="SpecialAffair API",
        lifespan=lifespan,
        docs_url=None if settings.environment == "prod" else "/docs",
        redoc_url=None if settings.environment == "prod" else "/redoc",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Cart-Token",
            "X-Order-Token",
            "X-Correlation-ID",
        ],
    )
    from app.core.abuse import AbuseGuard

    application.add_middleware(
        AbuseGuard, requests_per_minute=settings.requests_per_minute
    )
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(health_router)
    application.include_router(api_v1_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()
