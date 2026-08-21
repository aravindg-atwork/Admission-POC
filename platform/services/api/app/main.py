"""Application entrypoint. Deliberately thin: this file wires the FastAPI
app together and mounts routers; it holds no business logic of its own,
matching the layering the existing POC's backend/http/app.py already
established (route modules own their own concern, this file just dispatches
to them) - same principle, cleaner mechanism (FastAPI's router include
instead of hand-rolled if/elif dispatch).

This is the vertical-slice checkpoint's entrypoint: it proves the process
boots, serves HTTP, and is reachable through the full Docker Compose stack.
The chat/agent routes land here once the ported RAG core exists - not yet,
by design (see the session's phased plan).
"""

import hashlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis

from .api.chat import router as chat_router
from .api.admin import router as admin_router
from .api.health import router as health_router
from .settings import get_settings
from .storage.database import init_db

settings = get_settings()

app = FastAPI(title=settings.service_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
    allow_credentials=False,
)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(admin_router)

_rate_store = Redis.from_url(
    settings.redis_url, decode_responses=True,
    socket_connect_timeout=settings.redis_operation_timeout_seconds,
    socket_timeout=settings.redis_operation_timeout_seconds,
)


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)

    if request.url.path == "/api/chat" and request.method == "POST":
        client_address = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
        client_key = hashlib.sha256(client_address.encode("utf-8")).hexdigest()[:24]
        minute = int(__import__("time").time() // 60)
        rate_key = f"rate:chat:{client_key}:{minute}"
        try:
            count = _rate_store.incr(rate_key)
            if count == 1:
                _rate_store.expire(rate_key, 90)
            if count > settings.chat_rate_limit_per_minute:
                return JSONResponse(
                    {"detail": "Too many questions. Please wait a moment and try again."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        except Exception as exc:
            print(f"[rate-limit] Redis unavailable; request allowed: {exc!r}")

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def root():
    return {"service": settings.service_name, "environment": settings.environment}
