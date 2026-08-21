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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.chat import router as chat_router
from .api.admin import router as admin_router
from .api.health import router as health_router
from .settings import get_settings
from .storage.database import init_db

settings = get_settings()

app = FastAPI(title=settings.service_name)
# Wildcard for this vertical-slice checkpoint, matching the existing POC's
# own current posture (see backend/http/app.py) - scoping this to known
# origins is a stated later-phase item (platform architecture doc,
# security section), not settled here.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(admin_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def root():
    return {"service": settings.service_name, "environment": settings.environment}
