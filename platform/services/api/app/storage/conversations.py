"""Privacy-conscious transcript logging for the admin review queue."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import ConversationMessage, ConversationSession, ReviewCase, ReviewAudit

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_SESSION = re.compile(r"^[a-f0-9]{32}$")


def redact(text: str) -> str:
    text = _EMAIL.sub("[email redacted]", text)
    text = _PHONE.sub("[phone redacted]", text)
    return _AADHAAR.sub("[identity number redacted]", text)


def log_exchange(session_id: str | None, project_id: str, language: str,
                 question: str, result: dict) -> tuple[str, int]:
    safe_session = session_id if session_id and _SESSION.fullmatch(session_id) else uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        session = db.get(ConversationSession, safe_session)
        if session is None:
            session = ConversationSession(
                id=safe_session, project_id=project_id, language=language,
                created_at=now, updated_at=now,
            )
            db.add(session)
            db.flush()
        else:
            session.project_id = project_id
            session.language = language
            session.updated_at = now
        db.add(ConversationMessage(
            session_id=safe_session, role="student", content=redact(question),
            project_id=project_id, language=language, created_at=now,
        ))
        assistant = ConversationMessage(
            session_id=safe_session, role="assistant",
            content=redact(str(result.get("answer", ""))), project_id=project_id,
            language=language, source=result.get("source"), pages=result.get("pages", []),
            created_at=now,
        )
        db.add(assistant)
        db.flush()
        if result.get("source") in {"validation-blocked", "provider-unavailable", "low-confidence"}:
            review = ReviewCase(
                message_id=assistant.id, reason="automatic-safety-flag",
                status="open", notes=f"Automatically flagged source: {result.get('source')}",
                created_at=now, updated_at=now,
            )
            db.add(review)
            db.flush()
            db.add(ReviewAudit(
                review_id=review.id, action="auto_flagged",
                details={"source": result.get("source")}, created_at=now,
            ))
        db.commit()
        db.refresh(assistant)
        return safe_session, assistant.id


def previous_student_message(db, assistant: ConversationMessage) -> ConversationMessage | None:
    return db.scalar(select(ConversationMessage).where(
        ConversationMessage.session_id == assistant.session_id,
        ConversationMessage.role == "student",
        ConversationMessage.id < assistant.id,
    ).order_by(ConversationMessage.id.desc()).limit(1))
