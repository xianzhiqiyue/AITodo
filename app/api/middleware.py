import time
from collections import defaultdict, deque

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.errors import AppError, ErrorCode

logger = structlog.get_logger()

RATE_LIMIT = 100
WINDOW_SECONDS = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else "anonymous"

        now = time.time()
        window = self._requests[key]

        while window and window[0] < now - WINDOW_SECONDS:
            window.popleft()

        if len(window) >= RATE_LIMIT:
            raise AppError(ErrorCode.RATE_LIMITED, "Too many requests. Please slow down.")

        window.append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "http_request",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
