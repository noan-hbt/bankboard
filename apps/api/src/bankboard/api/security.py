"""CSRF defence: mutating requests must come from an allowed Origin (cookies are SameSite=Lax)."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, allowed_origins: list[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.allowed = {o.rstrip("/") for o in allowed_origins}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is None and (ref := request.headers.get("referer")):
                p = urlparse(ref)
                origin = f"{p.scheme}://{p.netloc}"
            if origin is not None and origin.rstrip("/") not in self.allowed:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response
