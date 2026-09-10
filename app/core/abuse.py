"""Bounded per-process guard; production ingress must enforce shared limits too."""

from collections import OrderedDict
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class AbuseGuard(BaseHTTPMiddleware):
    def __init__(
        self, app, requests_per_minute: int = 120, max_body_bytes: int = 1000000
    ):
        super().__init__(app)
        self.limit = requests_per_minute
        self.max_body_bytes = max_body_bytes
        self.windows: OrderedDict[str, tuple[float, int]] = OrderedDict()

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/health/"):
            return await call_next(request)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > self.max_body_bytes):
            return JSONResponse(
                {"error": {"code": "request_too_large"}}, status_code=413
            )
        # Never trust arbitrary forwarded headers to choose the rate-limit identity.
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        since, count = self.windows.get(key, (now, 0))
        if now - since >= 60:
            since, count = now, 0
        self.windows[key] = (since, count + 1)
        self.windows.move_to_end(key)
        if len(self.windows) > 10000:
            self.windows.popitem(last=False)
        if count >= self.limit:
            return JSONResponse(
                {"error": {"code": "rate_limit_exceeded", "message": "Too many requests. Please wait a moment and try again."}},
                status_code=429,
                headers={"Retry-After": str(max(1, int(60 - (now - since))))},
            )
        chunks = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > self.max_body_bytes:
                return JSONResponse(
                    {"error": {"code": "request_too_large"}}, status_code=413
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        if request.url.path.startswith(
            (
                "/api/v1/admin",
                "/api/v1/customers",
                "/api/v1/orders",
                "/api/v1/carts",
                "/api/v1/wishlists",
                "/api/v1/checkout",
                "/api/v1/support",
                "/api/v1/operations",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
