"""Engine/session wiring. `init_db()` uses `Base.metadata.create_all` for
now, not Alembic migrations - deliberate for this phase: the schema is
still settling as domain logic gets ported in, and a migration history
against a schema that's still moving is churn, not safety. Alembic is a
near-term follow-up once app/storage/models.py stabilizes, not an
oversight - don't reach for `create_all` once real migrations exist,
and don't add Alembic before the schema has a reason to need one.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..settings import get_settings
from .models import Base

settings = get_settings()
engine = create_engine(settings.postgres_dsn)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency - `Depends(get_session)` in a route gets a
    session that's always closed after the request, success or failure.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
