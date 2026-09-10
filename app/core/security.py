import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings


class TokenPayload(BaseModel):
    sub: str
    permissions: list[str] = Field(default_factory=list)


class JWKSCache:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl_seconds = ttl_seconds
        self._expires_at = 0.0
        self._keys: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get_key(self, domain: str, kid: str) -> Any:
        async with self._lock:
            if time.monotonic() >= self._expires_at:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"https://{domain}/.well-known/jwks.json")
                    response.raise_for_status()
                self._keys = {item["kid"]: PyJWK.from_dict(item).key for item in response.json().get("keys", [])}
                self._expires_at = time.monotonic() + self.ttl_seconds
            key = self._keys.get(kid)
            if key is None:
                self._expires_at = 0.0
                raise KeyError("Signing key not found")
            return key


_bearer = HTTPBearer(auto_error=False)
_jwks = JWKSCache()


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenPayload:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise ValueError("Token has no key identifier")
        key = await _jwks.get_key(settings.auth0_domain, kid)
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
            options={"require": ["exp", "sub"]},
        )
        return TokenPayload.model_validate(claims)
    except (jwt.PyJWTError, httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc


async def optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenPayload | None:
    return await verify_token(credentials, settings) if credentials else None


def require_permissions(*perms: str) -> Callable[..., Coroutine[Any, Any, TokenPayload]]:
    """Require token permissions; resource-specific business authorization belongs in the domain layer."""
    async def dependency(token: TokenPayload = Depends(verify_token)) -> TokenPayload:
        missing = set(perms) - set(token.permissions)
        if missing:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return token

    return dependency
