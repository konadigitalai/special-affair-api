from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.core.abuse import AbuseGuard
from app.core.logging import _redact


async def test_chunked_requests_are_bounded_and_rate_limited():
    app = FastAPI()
    app.add_middleware(AbuseGuard, requests_per_minute=2, max_body_bytes=4)

    @app.post("/test")
    async def endpoint():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def chunks():
            yield b"123"
            yield b"456"

        assert (await client.post("/test", content=chunks())).status_code == 413
        assert (await client.post("/test", content=b"1")).status_code == 200
        limited = await client.post("/test", content=b"1")
        assert limited.status_code == 429 and "retry-after" in limited.headers


def test_nested_logs_redact_personal_and_payment_fields():
    result = _redact(
        {
            "event": "checkout",
            "nested": {
                "email": "buyer@example.com",
                "provider_token": "sensitive",
                "api_key": "sensitive",
            },
        }
    )
    assert result == {
        "event": "checkout",
        "nested": {
            "email": "[REDACTED]",
            "provider_token": "[REDACTED]",
            "api_key": "[REDACTED]",
        },
    }
