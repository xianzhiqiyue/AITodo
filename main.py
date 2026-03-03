from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.api.routes import health_router, router
from app.errors import AppError
from app.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield


app = FastAPI(
    title="AI 任务调度中心",
    description="AI-first task scheduling center with semantic search and MCP support.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(router)
app.include_router(health_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code.value, "message": exc.message}},
    )
