from httpx import AsyncClient


async def test_liveness_does_not_require_database(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_fails_when_database_is_unreachable(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["failing_check"] == "database"


async def test_correlation_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Correlation-ID": "test-correlation-id"})
    assert response.headers["X-Correlation-ID"] == "test-correlation-id"
