from contextvars import ContextVar, Token
from uuid import uuid4
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = b"x-correlation-id"
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next(
            (
                value.decode("utf-8", errors="replace")
                for key, value in scope["headers"]
                if key.lower() == CORRELATION_HEADER
            ),
            None,
        )
        correlation_id = (
            incoming
            if incoming and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", incoming)
            else str(uuid4())
        )
        token: Token[str | None] = correlation_id_var.set(correlation_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((CORRELATION_HEADER, correlation_id.encode("utf-8")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_var.reset(token)
