import httpx
from app.core.config import get_settings
from app.main import create_app


async def test_preflight_does_not_consume_limit_and_errors_include_cors():
    settings = get_settings()
    previous = settings.requests_per_minute
    settings.requests_per_minute = 1
    try:
        application = create_app()
        origin = settings.allowed_frontend_origins[0]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            for _ in range(3):
                preflight = await client.options("/docs", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
                assert preflight.status_code == 200
            first = await client.get("/docs", headers={"Origin": origin})
            assert first.status_code == 200
            limited = await client.get("/docs", headers={"Origin": origin})
            assert limited.status_code == 429
            assert limited.headers["access-control-allow-origin"] == origin
            assert limited.json()["error"]["message"]
            assert limited.headers["retry-after"]
    finally:
        settings.requests_per_minute = previous
