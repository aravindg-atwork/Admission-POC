"""Durable single-worker loop for advisory Qwen shadow reviews."""

from datetime import datetime, timezone
import time

from sqlalchemy import select

from ..retrieval.store import page_context
from ..settings import get_settings
from ..storage.conversations import previous_student_message
from ..storage.database import SessionLocal, init_db
from ..storage.models import ConversationMessage, MachineReview, ReviewAudit, ReviewCase
from .reviewer import review

settings = get_settings()


def _now():
    return datetime.now(timezone.utc)


def process_one() -> bool:
    with SessionLocal() as db:
        job = db.scalar(select(MachineReview).where(MachineReview.status == "pending").order_by(MachineReview.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return False
        job.status, job.attempts, job.updated_at = "processing", job.attempts + 1, _now()
        db.commit()
        message = db.get(ConversationMessage, job.message_id)
        question = previous_student_message(db, message) if message else None
        if not message or not question:
            job.status, job.explanation, job.updated_at = "failed", "Conversation pair is unavailable", _now()
            db.commit(); return True
        project, pages = message.project_id, list(message.pages or [])
        evidence = page_context(project, pages) if pages else ""
        message_id = message.id
        inputs = (question.content, message.content, project, message.language, message.source or "", pages, evidence)
    try:
        result = review(*inputs)
    except Exception as exc:
        with SessionLocal() as db:
            job = db.scalar(select(MachineReview).where(MachineReview.message_id == message_id))
            job.status = "pending" if job.attempts < 3 else "failed"
            job.explanation, job.updated_at = f"Reviewer unavailable: {type(exc).__name__}"[:4000], _now()
            db.commit()
        return True
    with SessionLocal() as db:
        job = db.scalar(select(MachineReview).where(MachineReview.message_id == message_id))
        job.status, job.verdict, job.severity = "completed", result["verdict"], result["severity"]
        job.issues, job.explanation = result["issues"], result["explanation"]
        job.suggested_correction, job.evidence_pages = result["suggestedCorrection"], result["evidencePages"]
        job.model_name, job.updated_at = settings.qwen_review_model, _now()
        if job.verdict in {"review", "critical"}:
            existing = db.scalar(select(ReviewCase).where(ReviewCase.message_id == message_id))
            if existing is None:
                case = ReviewCase(message_id=message_id, reason="qwen-shadow-review", status="open",
                                  notes=f"Qwen {job.verdict}/{job.severity}: {job.explanation}",
                                  evidence_pages=job.evidence_pages, created_at=_now(), updated_at=_now())
                db.add(case); db.flush()
                db.add(ReviewAudit(review_id=case.id, action="machine_flagged",
                                   details={"severity": job.severity, "issues": job.issues,
                                            "machineReviewId": job.id}, created_at=_now()))
        db.commit()
    return True


def main():
    init_db()
    while True:
        if not settings.qwen_review_enabled:
            time.sleep(max(settings.qwen_review_poll_seconds, 5)); continue
        if not process_one():
            time.sleep(max(settings.qwen_review_poll_seconds, 1))


if __name__ == "__main__":
    main()
