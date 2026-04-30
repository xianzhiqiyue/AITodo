import time
from collections import deque

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.errors import AppError, ErrorCode

logger = structlog.get_logger()

RATE_LIMIT = 100
WINDOW_SECONDS = 60
MAX_TRACKED_KEYS = 10_000
CLEANUP_INTERVAL = 300


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, deque[float]] = {}
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else "anonymous"

        now = time.time()

        if now - self._last_cleanup > CLEANUP_INTERVAL:
            self._cleanup_stale_keys(now)
            self._last_cleanup = now

        if key not in self._requests:
            if len(self._requests) >= MAX_TRACKED_KEYS:
                self._cleanup_stale_keys(now)
                if len(self._requests) >= MAX_TRACKED_KEYS:
                    raise AppError(ErrorCode.RATE_LIMITED, "Too many requests. Please slow down.")
            self._requests[key] = deque()

        window = self._requests[key]

        while window and window[0] < now - WINDOW_SECONDS:
            window.popleft()

        if len(window) >= RATE_LIMIT:
            raise AppError(ErrorCode.RATE_LIMITED, "Too many requests. Please slow down.")

        window.append(now)
        return await call_next(request)

    def _cleanup_stale_keys(self, now: float) -> None:
        stale_keys = [
            k for k, v in self._requests.items()
            if not v or v[-1] < now - WINDOW_SECONDS
        ]
        for k in stale_keys:
            del self._requests[k]


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
