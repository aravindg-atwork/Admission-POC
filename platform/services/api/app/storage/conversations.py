"""Privacy-conscious transcript logging for the admin review queue."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import ConversationMessage, ConversationSession, MachineReview, ReviewCase, ReviewAudit

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_OTP = re.compile(r"(?i)\b(?:otp|one[ -]?time password)\s*[:#-]?\s*\d{4,8}\b")
_BANK = re.compile(r"(?i)\b(?:account|a/c)\s*(?:number|no\.?|#)?\s*[:#-]?\s*\d{9,18}\b")
_EXAM_ID = re.compile(
    r"(?i)\b(?:(?:neet|cet|cuet)\s+(?:application|registration|roll)|"
    r"(?:application|registration|roll)\s+(?:id|no\.?|number))\s*[:#-]?\s*[A-Z0-9-]{7,}\b"
)
_SESSION = re.compile(r"^[a-f0-9]{32}$")


def redact(text: str) -> str:
    text = _EMAIL.sub("[email redacted]", text)
    text = _PHONE.sub("[phone redacted]", text)
    text = _OTP.sub("[one-time password redacted]", text)
    # _BANK before _AADHAAR, deliberately: _BANK requires a contextual cue
    # ("account"/"a/c") next to its digits, _AADHAAR matches a bare 12-digit
    # run with no cue at all. In the original order, a bank account number
    # (e.g. "account number 123456789012") was consumed by _AADHAAR first
    # (any 12 digits match it) before _BANK's own, more specific pattern
    # ever got a turn - the value was still redacted either way, just
    # mislabeled as an identity number instead of a bank account. Most-
    # specific-pattern-first fixes the label without changing what gets
    # removed. tools/test_privacy_retention.py.
    text = _BANK.sub("[bank account redacted]", text)
    text = _AADHAAR.sub("[identity number redacted]", text)
    return _EXAM_ID.sub("[exam identifier redacted]", text)


def _needs_machine_review(result: dict) -> bool:
    source = str(result.get("source", ""))
    if source in {"greeting", "identity", "language-control", "language-repeat", "malformed-input", "privacy-guard", "instruction-override", "prediction-boundary"}:
        return False
    answer = str(result.get("answer", "")).lower()
    high_risk = any(term in answer for term in (
        "eligible", "eligibility", "fee", "deadline", "quota", "reservation",
        "seat", "certificate", "document", "neet", "mht-cet", "cuet",
    ))
    return high_risk or result.get("decisionState") in {
        "eligible_so_far", "not_eligible", "document_issue", "quota_specific", "cannot_confirm",
    }


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
        if _needs_machine_review(result):
            db.add(MachineReview(
                message_id=assistant.id, status="pending", created_at=now, updated_at=now,
            ))
        if result.get("source") in {"validation-blocked", "provider-unavailable", "service-unavailable", "low-confidence"}:
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
