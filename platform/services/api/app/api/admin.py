"""Authenticated P0 conversation review and exact-correction promotion API."""

from datetime import datetime, timezone
from hmac import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..settings import get_settings
from ..agent import validate
from ..retrieval import store
from ..storage import answer_cache, telemetry
from ..storage.conversations import previous_student_message
from ..storage.curated import question_hash
from ..storage.database import get_session
from ..storage.models import (
    ConversationMessage, ConversationSession, CorrectionVersion, CuratedOverride,
    MachineReview, ReviewAudit, ReviewCase,
)

router = APIRouter(prefix="/api/admin", tags=["admin-review"])
settings = get_settings()


def require_admin(x_admin_key: str = Header(default=""),
                  x_admin_actor: str = Header(default="primary-admin")) -> str:
    configured = settings.admin_api_key
    if not configured:
        raise HTTPException(status_code=503, detail="Admin review is not configured")
    if not compare_digest(x_admin_key, configured):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    actor = x_admin_actor.strip().lower()
    if not actor or len(actor) > 255:
        raise HTTPException(status_code=400, detail="Invalid admin actor")
    return actor


class FlagRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=64)
    notes: str = Field(default="", max_length=4000)
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low)$")


class ReviewUpdate(BaseModel):
    correctedAnswer: str = Field(min_length=1, max_length=12000)
    evidencePages: list[int] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=4000)
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    admissionYear: str = Field(default="2026-27", pattern=r"^20\d{2}-\d{2}$")


def _now():
    return datetime.now(timezone.utc)


def _review_payload(db: Session, review: ReviewCase) -> dict:
    answer = db.get(ConversationMessage, review.message_id)
    question = previous_student_message(db, answer) if answer else None
    machine = db.scalar(select(MachineReview).where(MachineReview.message_id == review.message_id))
    versions = db.scalars(select(CorrectionVersion).where(
        CorrectionVersion.review_id == review.id
    ).order_by(CorrectionVersion.version)).all()
    return {
        "id": review.id, "status": review.status, "reason": review.reason,
        "notes": review.notes, "correctedAnswer": review.corrected_answer,
        "evidencePages": review.evidence_pages, "createdAt": review.created_at,
        "messageId": review.message_id,
        "question": question.content if question else "",
        "answer": answer.content if answer else "",
        "projectId": answer.project_id if answer else "",
        "language": answer.language if answer else "en",
        "source": answer.source if answer else None,
        "pages": answer.pages if answer else [],
        "sessionId": answer.session_id if answer else None,
        "machineReview": _machine_payload(machine) if machine else None,
        "versions": [{
            "id": item.id, "version": item.version, "severity": item.severity,
            "admissionYear": item.admission_year, "answer": item.answer,
            "evidencePages": item.evidence_pages, "notes": item.notes,
            "status": item.status, "proposedBy": item.proposed_by,
            "approvedBy": item.approved_by, "createdAt": item.created_at,
            "approvedAt": item.approved_at,
        } for item in versions],
    }


def _latest_version(db: Session, review_id: int) -> CorrectionVersion | None:
    return db.scalar(select(CorrectionVersion).where(
        CorrectionVersion.review_id == review_id
    ).order_by(desc(CorrectionVersion.version)).limit(1))


def _machine_payload(item: MachineReview) -> dict:
    return {"id": item.id, "messageId": item.message_id, "status": item.status,
            "verdict": item.verdict, "severity": item.severity, "issues": item.issues,
            "explanation": item.explanation, "suggestedCorrection": item.suggested_correction,
            "evidencePages": item.evidence_pages, "model": item.model_name,
            "attempts": item.attempts, "createdAt": item.created_at, "updatedAt": item.updated_at}


@router.get("/summary", dependencies=[Depends(require_admin)])
def summary(db: Session = Depends(get_session)) -> dict:
    return {
        "sessions": db.scalar(select(func.count()).select_from(ConversationSession)) or 0,
        "messages": db.scalar(select(func.count()).select_from(ConversationMessage)) or 0,
        "openReviews": db.scalar(select(func.count()).select_from(ReviewCase).where(
            ReviewCase.status.in_(["open", "draft", "tested"]))) or 0,
        "published": db.scalar(select(func.count()).select_from(CuratedOverride).where(
            CuratedOverride.active.is_(True))) or 0,
        "machineReviewPending": db.scalar(select(func.count()).select_from(MachineReview).where(
            MachineReview.status == "pending")) or 0,
        "machineReviewCritical": db.scalar(select(func.count()).select_from(MachineReview).where(
            MachineReview.verdict == "critical")) or 0,
    }


@router.get("/operations", dependencies=[Depends(require_admin)])
def operations() -> dict:
    metrics = telemetry.snapshot()
    alerts = []
    if metrics["providerRateLimits"]:
        alerts.append("A model provider returned a rate limit today")
    if metrics["providerFailures"] >= 5:
        alerts.append("Provider failures are elevated")
    if metrics["providerBudgetUsed"] >= 0.8:
        alerts.append("Configured daily provider-call budget is at least 80% used")
    if metrics["slowRequests"] >= 5:
        alerts.append("Multiple responses exceeded 10 seconds")
    if metrics["requests"] >= 20 and metrics["cacheHitRate"] < 0.15:
        alerts.append("Cache hit rate is below 15%")
    return {**metrics, "alerts": alerts}


@router.get("/conversations", dependencies=[Depends(require_admin)])
def conversations(limit: int = Query(50, ge=1, le=200),
                  project: str | None = None,
                  db: Session = Depends(get_session)) -> list[dict]:
    stmt = select(ConversationSession).order_by(desc(ConversationSession.updated_at)).limit(limit)
    if project:
        stmt = stmt.where(ConversationSession.project_id == project)
    rows = db.scalars(stmt).all()
    result = []
    for session in rows:
        messages = db.scalars(select(ConversationMessage).where(
            ConversationMessage.session_id == session.id
        ).order_by(ConversationMessage.id)).all()
        review_count = 0
        message_ids = [m.id for m in messages if m.role == "assistant"]
        if message_ids:
            review_count = db.scalar(select(func.count()).select_from(ReviewCase).where(
                ReviewCase.message_id.in_(message_ids))) or 0
        result.append({
            "id": session.id, "projectId": session.project_id,
            "language": session.language, "createdAt": session.created_at,
            "updatedAt": session.updated_at, "messageCount": len(messages),
            "flagCount": review_count,
            "preview": messages[0].content[:160] if messages else "",
        })
    return result


@router.get("/conversations/{session_id}", dependencies=[Depends(require_admin)])
def conversation(session_id: str, db: Session = Depends(get_session)) -> dict:
    session = db.get(ConversationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.scalars(select(ConversationMessage).where(
        ConversationMessage.session_id == session_id
    ).order_by(ConversationMessage.id)).all()
    reviews = {r.message_id: r for r in db.scalars(select(ReviewCase).where(
        ReviewCase.message_id.in_([m.id for m in messages] or [-1]))).all()}
    machines = {r.message_id: r for r in db.scalars(select(MachineReview).where(
        MachineReview.message_id.in_([m.id for m in messages] or [-1]))).all()}
    return {
        "id": session.id, "projectId": session.project_id, "language": session.language,
        "messages": [{
            "id": m.id, "role": m.role, "content": m.content,
            "source": m.source, "pages": m.pages, "createdAt": m.created_at,
            "review": _review_payload(db, reviews[m.id]) if m.id in reviews else None,
            "machineReview": _machine_payload(machines[m.id]) if m.id in machines else None,
        } for m in messages],
    }


@router.get("/machine-reviews", dependencies=[Depends(require_admin)])
def machine_reviews(status: str | None = None, verdict: str | None = None,
                    db: Session = Depends(get_session)) -> list[dict]:
    stmt = select(MachineReview).order_by(desc(MachineReview.updated_at))
    if status:
        stmt = stmt.where(MachineReview.status == status)
    if verdict:
        stmt = stmt.where(MachineReview.verdict == verdict)
    return [_machine_payload(item) for item in db.scalars(stmt.limit(200)).all()]


@router.get("/reviews", dependencies=[Depends(require_admin)])
def reviews(status: str | None = None, db: Session = Depends(get_session)) -> list[dict]:
    stmt = select(ReviewCase).order_by(desc(ReviewCase.updated_at))
    if status:
        stmt = stmt.where(ReviewCase.status == status)
    return [_review_payload(db, item) for item in db.scalars(stmt.limit(200)).all()]


@router.get("/reviews/{review_id}", dependencies=[Depends(require_admin)])
def review_detail(review_id: int, db: Session = Depends(get_session)) -> dict:
    review = db.get(ReviewCase, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return _review_payload(db, review)


@router.post("/messages/{message_id}/flag")
def flag_message(message_id: int, body: FlagRequest,
                 actor: str = Depends(require_admin),
                 db: Session = Depends(get_session)) -> dict:
    message = db.get(ConversationMessage, message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status_code=404, detail="Assistant message not found")
    existing = db.scalar(select(ReviewCase).where(ReviewCase.message_id == message_id))
    if existing:
        return _review_payload(db, existing)
    review = ReviewCase(message_id=message_id, reason=body.reason, notes=body.notes,
                        status="open", created_at=_now(), updated_at=_now())
    db.add(review); db.flush()
    db.add(ReviewAudit(review_id=review.id, action="flagged",
                       details={"reason": body.reason, "severity": body.severity,
                                "actor": actor}, created_at=_now()))
    db.commit(); db.refresh(review)
    return _review_payload(db, review)


@router.patch("/reviews/{review_id}")
def update_review(review_id: int, body: ReviewUpdate,
                  actor: str = Depends(require_admin),
                  db: Session = Depends(get_session)) -> dict:
    review = db.get(ReviewCase, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review.corrected_answer = body.correctedAnswer.strip()
    review.evidence_pages = sorted(set(body.evidencePages))
    review.notes = body.notes
    review.status = "draft"
    review.updated_at = _now()
    previous = _latest_version(db, review.id)
    version = CorrectionVersion(
        review_id=review.id, version=(previous.version + 1) if previous else 1,
        severity=body.severity, admission_year=body.admissionYear,
        answer=review.corrected_answer, evidence_pages=review.evidence_pages,
        notes=review.notes, status="draft", proposed_by=actor, created_at=_now(),
    )
    db.add(version)
    db.add(ReviewAudit(review_id=review.id, action="edited",
                       details={"actor": actor, "version": version.version,
                                "severity": body.severity,
                                "admissionYear": body.admissionYear}, created_at=_now()))
    db.commit(); db.refresh(review)
    return _review_payload(db, review)


@router.post("/reviews/{review_id}/test")
def test_review(review_id: int, actor: str = Depends(require_admin),
                db: Session = Depends(get_session)) -> dict:
    review = db.get(ReviewCase, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    failures = []
    if len(review.corrected_answer.strip()) < 20:
        failures.append("Corrected answer is too short")
    if not review.evidence_pages:
        failures.append("At least one prospectus page is required")
    if any(page < 1 for page in review.evidence_pages):
        failures.append("Evidence pages must be positive numbers")
    answer = db.get(ConversationMessage, review.message_id)
    question = previous_student_message(db, answer) if answer else None
    if answer and question and review.evidence_pages:
        context = store.page_context(answer.project_id, review.evidence_pages)
        if not context:
            failures.append("No indexed prospectus content was found on the selected pages")
        else:
            failures.extend(validate.deterministic_checks(
                question.content, context, review.corrected_answer, answer.project_id
            ))
    review.status = "draft" if failures else "tested"
    review.updated_at = _now()
    version = _latest_version(db, review.id)
    if version:
        version.status = "draft" if failures else "tested"
    db.add(ReviewAudit(review_id=review.id, action="test_failed" if failures else "tested",
                       details={"failures": failures, "actor": actor,
                                "version": version.version if version else None}, created_at=_now()))
    db.commit()
    return {"passed": not failures, "failures": failures, "review": _review_payload(db, review)}


@router.post("/reviews/{review_id}/publish")
def publish(review_id: int, actor: str = Depends(require_admin),
            db: Session = Depends(get_session)) -> dict:
    review = db.get(ReviewCase, review_id)
    if review is None or review.status != "tested":
        raise HTTPException(status_code=409, detail="Review must pass testing before publication")
    version = _latest_version(db, review_id)
    if version is None or version.status != "tested":
        raise HTTPException(status_code=409, detail="The latest correction version must pass testing")
    if (settings.admin_require_two_person_high_risk
            and version.severity in {"critical", "high"}
            and version.proposed_by == actor):
        raise HTTPException(status_code=409, detail="High-risk corrections require a second approver")
    answer = db.get(ConversationMessage, review.message_id)
    question = previous_student_message(db, answer) if answer else None
    if answer is None or question is None:
        raise HTTPException(status_code=409, detail="Original exchange is incomplete")
    digest = question_hash(question.content)
    existing = db.scalars(select(CuratedOverride).where(
        CuratedOverride.project_id == answer.project_id,
        CuratedOverride.language == answer.language,
        CuratedOverride.question_hash == digest,
        CuratedOverride.active.is_(True),
    )).all()
    for item in existing:
        item.active = False; item.retired_at = _now()
    override = CuratedOverride(
        review_id=review.id, project_id=answer.project_id, language=answer.language,
        question_hash=digest, question=question.content,
        answer=review.corrected_answer, pages=review.evidence_pages,
        active=True, created_at=_now(),
    )
    db.add(override)
    review.status = "published"; review.updated_at = _now()
    version.status = "published"; version.approved_by = actor; version.approved_at = _now()
    db.add(ReviewAudit(review_id=review.id, action="published",
                       details={"overrideId": override.id, "actor": actor,
                                "version": version.version}, created_at=_now()))
    db.commit()
    answer_cache.invalidate(answer.project_id, question.content, answer.language)
    return {"published": True, "overrideId": override.id}


@router.post("/reviews/{review_id}/rollback")
def rollback(review_id: int, actor: str = Depends(require_admin),
             db: Session = Depends(get_session)) -> dict:
    review = db.get(ReviewCase, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    items = db.scalars(select(CuratedOverride).where(
        CuratedOverride.review_id == review_id, CuratedOverride.active.is_(True))).all()
    for item in items:
        item.active = False; item.retired_at = _now()
        answer_cache.invalidate(item.project_id, item.question, item.language)
    review.status = "rolled_back"; review.updated_at = _now()
    version = _latest_version(db, review_id)
    if version:
        version.status = "rolled_back"
    db.add(ReviewAudit(review_id=review.id, action="rolled_back",
                       details={"actor": actor, "version": version.version if version else None},
                       created_at=_now()))
    db.commit()
    return {"rolledBack": True, "count": len(items)}
