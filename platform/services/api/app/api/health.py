"""Liveness/readiness endpoint - the direct replacement for backend/http/
health_routes.py's /healthz. Kept as a plain liveness check for now (process
is up, can respond); a readiness variant that actually pings Postgres/Redis/
Qdrant is a near-term follow-up once those clients exist in app/storage and
app/retrieval, not invented ahead of them.
"""

import time

from fastapi import APIRouter

router = APIRouter()

_started_at = time.time()


@router.get("/healthz")
@router.get("/api/healthz")
def healthz():
    return {"status": "ok", "uptimeSeconds": round(time.time() - _started_at, 1)}
