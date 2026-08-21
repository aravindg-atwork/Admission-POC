"""Conservative semantic cache for previously validated open-ended answers."""

import re
import uuid

from qdrant_client.http import models as qmodels
from sqlalchemy import func, select

from ..retrieval import store
from ..settings import get_settings
from .database import SessionLocal
from .models import FaqCache

_settings = get_settings()
_COLLECTION = "semantic-faq"
_MARKERS = (
    "general", "unreserved", "obc", "sc", "st", "ews", "ncl", "nri", "pio", "oci",
    "management", "icar", "vci", "regional", "state quota", "female", "pwd",
    "neet", "mht-cet", "cuet", "pcb", "pcm", "biology", "mathematics",
)


def _signature(text: str) -> dict:
    low = " ".join(text.casefold().split())
    return {
        "numbers": sorted(set(re.findall(r"\b\d+(?:\.\d+)?%?\b", low))),
        "markers": [marker for marker in _MARKERS if marker in low],
        "topic": store.query_topic(low) or "general",
    }


def lookup(project_id: str, language: str, question: str,
           vector: list[float]) -> dict | None:
    if not _settings.semantic_faq_enabled:
        return None
    client = store.get_client()
    if not client.collection_exists(_COLLECTION):
        return None
    signature = _signature(question)
    points = client.query_points(
        _COLLECTION, query=vector, limit=5, with_payload=True,
        query_filter=qmodels.Filter(must=[
            qmodels.FieldCondition(key="project_id", match=qmodels.MatchValue(value=project_id)),
            qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=language)),
        ]),
    ).points
    for point in points:
        if point.score < _settings.semantic_faq_threshold:
            continue
        payload = point.payload or {}
        if payload.get("signature") != signature:
            continue
        with SessionLocal() as db:
            row = db.get(FaqCache, str(point.id).replace("-", ""))
            if row is None or row.tags.get("revision") != _settings.faq_cache_revision:
                continue
            return {
                "answer": row.answer, "source": "semantic-cache", "model": "cache",
                "pages": row.pages or [], "language": language, "cacheHit": True,
            }
    return None


def put(project_id: str, language: str, question: str, result: dict,
        vector: list[float]) -> bool:
    if not _settings.semantic_faq_enabled or result.get("source") != "rag":
        return False
    signature = _signature(question)
    entry_id = uuid.uuid4().hex
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(FaqCache).where(
            FaqCache.project_id == project_id)) or 0
        if count >= _settings.semantic_faq_max_entries_per_project:
            return False
        row = FaqCache(
            id=entry_id, project_id=project_id, question=question,
            answer=result["answer"], pages=result.get("pages") or [],
            tags={"ui_language": language, "signature": signature,
                  "revision": _settings.faq_cache_revision},
        )
        db.add(row)
        db.commit()
    try:
        store.ensure_collection(_COLLECTION)
        store.get_client().upsert(_COLLECTION, points=[qmodels.PointStruct(
            id=str(uuid.UUID(entry_id)), vector=vector,
            payload={"project_id": project_id, "language": language,
                     "signature": signature},
        )])
        return True
    except Exception:
        with SessionLocal() as db:
            row = db.get(FaqCache, entry_id)
            if row:
                db.delete(row); db.commit()
        return False
