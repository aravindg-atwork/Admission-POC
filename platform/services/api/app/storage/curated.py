"""Exact, reviewed answer overrides promoted through the admin workflow."""

from hashlib import sha256
import re

from sqlalchemy import select

from .database import SessionLocal
from .models import CuratedOverride

_SPACE = re.compile(r"\s+")


def question_hash(question: str) -> str:
    normalized = _SPACE.sub(" ", question.strip()).casefold()
    return sha256(normalized.encode("utf-8")).hexdigest()


def get(project_id: str, language: str, question: str) -> dict | None:
    with SessionLocal() as db:
        item = db.scalar(select(CuratedOverride).where(
            CuratedOverride.project_id == project_id,
            CuratedOverride.language == language,
            CuratedOverride.question_hash == question_hash(question),
            CuratedOverride.active.is_(True),
        ).order_by(CuratedOverride.created_at.desc()).limit(1))
        if item is None:
            return None
        return {
            "answer": item.answer, "source": "curated-override",
            "model": "admin-reviewed", "pages": item.pages,
            "cacheHit": False,
        }
