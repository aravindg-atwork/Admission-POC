"""Liveness/readiness endpoint - the direct replacement for backend/http/
health_routes.py's /healthz. Kept as a plain liveness check for now (process
is up, can respond); a readiness variant that actually pings Postgres/Redis/
Qdrant is a near-term follow-up once those clients exist in app/storage and
app/retrieval, not invented ahead of them.
"""

import time

from fastapi import APIRouter, Response
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import text

from ..settings import get_settings
from ..storage.database import engine

router = APIRouter()

_started_at = time.time()
_settings = get_settings()


@router.get("/healthz")
@router.get("/api/healthz")
def healthz():
    return {"status": "ok", "uptimeSeconds": round(time.time() - _started_at, 1)}


@router.get("/readyz")
@router.get("/api/readyz")
def readyz(response: Response):
    """Dependency readiness for load-balancer routing and recovery drills."""
    checks: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "unavailable"
    try:
        Redis.from_url(_settings.redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    try:
        QdrantClient(url=_settings.qdrant_url, timeout=2).get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "unavailable"
    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "degraded", "ready": ready,
            "checks": checks, "uptimeSeconds": round(time.time() - _started_at, 1)}
