"""Automatic transcript minimisation after the configured retention period."""

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..settings import get_settings
from .database import SessionLocal, init_db
from .models import ConversationMessage, ConversationSession

settings = get_settings()
_EXPIRED = "[conversation content removed by retention policy]"


def anonymize_expired(now: datetime | None = None) -> dict[str, int]:
    """Remove message bodies while retaining non-identifying operational totals.

    Review/audit rows remain referentially valid. Published curated answers are
    separate approved records and are not student transcript content.
    """
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=max(1, settings.conversation_retention_days))
    with SessionLocal() as db:
        messages = db.scalars(select(ConversationMessage).where(
            ConversationMessage.created_at < cutoff,
            ConversationMessage.content != _EXPIRED,
        )).all()
        session_ids = {item.session_id for item in messages}
        for item in messages:
            item.content = _EXPIRED
            item.pages = []
        sessions = []
        if session_ids:
            sessions = db.scalars(select(ConversationSession).where(
                ConversationSession.id.in_(session_ids)
            )).all()
            for session in sessions:
                session.language = "redacted"
        db.commit()
        return {"messagesAnonymized": len(messages), "sessionsMinimized": len(sessions)}


def run_forever() -> None:
    init_db()
    while True:
        try:
            result = anonymize_expired()
            print(f"[retention] {result}", flush=True)
        except Exception as exc:  # keep the next scheduled cleanup alive
            print(f"[retention] cleanup failed: {exc!r}", flush=True)
        time.sleep(max(1, settings.retention_poll_hours) * 3600)


if __name__ == "__main__":
    run_forever()
