from httpx import AsyncClient


async def test_liveness_does_not_require_database(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_fails_when_database_is_unreachable(
    client: AsyncClient,
) -> None:
    from app.main import app
    from app.db.session import get_session

    class UnavailableSession:
        async def execute(self, *_):
            raise ConnectionError("Test database unavailable")

    async def unavailable():
        yield UnavailableSession()

    app.dependency_overrides[get_session] = unavailable
    try:
        response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 503
    assert response.json()["failing_check"] == "database"


async def test_correlation_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get(
        "/health/live", headers={"X-Correlation-ID": "test-correlation-id"}
    )
    assert response.headers["X-Correlation-ID"] == "test-correlation-id"


async def test_frontend_origin_is_allowed_by_cors(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/products",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
