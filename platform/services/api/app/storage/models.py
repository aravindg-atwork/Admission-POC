"""SQLAlchemy models - the durable, transactional half of the storage
layer. The other half (every embedding - both corpus chunks for retrieval
AND cached questions for FAQ matching) lives in Qdrant, never here; see
app/retrieval/ once it exists.

FaqCache.id doubles as the id of that entry's question-embedding point in
Qdrant's FAQ collection - one shared id instead of a separate mapping
table, so a cache row and its vector can never drift apart or point at each
other's wrong entry.

Minimal on purpose, matching this phase's own scope (see ../../../CLAUDE.md
- "port, don't build ahead of what's proven necessary"). admin_users has a
single flat `role` string, not a real RBAC model with permissions - that's
a stated later-phase item, not an oversight here.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A programme/tenant. Replaces backend/core/programs.py's hardcoded
    PROGRAM_NAMES dict with real rows - onboarding a new programme becomes
    a database insert, not a code change (see the platform architecture
    doc's multi-tenancy section). This phase seeds exactly one row (bvsc);
    the schema supports more from day one because retrofitting a
    single-tenant assumption later is expensive, adding rows isn't.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "bvsc"
    name: Mapped[str] = mapped_column(String(255))  # e.g. "B.V.Sc. & A.H."
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    faq_entries: Mapped[list["FaqCache"]] = relationship(back_populates="project")
    review_log_entries: Mapped[list["ReviewLog"]] = relationship(back_populates="project")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project")


class FaqCache(Base):
    """A cached answer. `id` is shared with its question-embedding's point
    id in Qdrant (see this module's docstring) - deliberately not an
    auto-increment integer, so the two stores can never silently diverge.

    `verified` mirrors backend/storage/faq.py's own field: {"descriptor":
    ..., "value": ...} when this answer came from a deterministic table
    lookup, None for an open-ended answer - carried over so a future hit
    can be re-checked against a fresh lookup before being served, exactly
    like the ported behaviour this replaces (see backend/rag/answer.py's
    verified-provenance re-check, and its own hard-won UnboundLocalError
    fix from the same session this rebuild started in).
    """

    __tablename__ = "faq_cache"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSON, default=list)
    verified: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)  # {"ui_language": ..., "intent": ...}
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False)  # curated entries are never pruned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="faq_entries")


class ReviewLog(Base):
    """A flagged/regenerated/self-detected-near-miss event - same shape as
    backend/storage/reviewlog.py's append-only log, just a real table
    instead of a flat JSON file (no hand-rolled RLock needed - see
    backend/CLAUDE.md's own documented deadlock incident from that
    pattern, which a real transactional store structurally can't repeat).
    """

    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(64))  # "validation_flag" | "validation_regenerated" | ...
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="review_log_entries")


class ApiKey(Base):
    """A per-project API key. `key_hash`, never the raw key - a real
    improvement over backend/data/api-keys.json, which stores every key
    in plaintext on disk. The raw key is shown to the admin exactly once,
    at creation time, and never again.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    key_hash: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="api_keys")


class AdminUser(Base):
    """A single admin identity - replaces backend's one shared static
    ADMIN_TOKEN with per-person accounts (see the platform architecture
    doc's security section). This phase seeds exactly one admin; real
    role-based permissions beyond the flat `role` string are a stated
    later-phase item.
    """

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(64), default="bvsc")
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("conversation_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    project_id: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(8), default="en")
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewCase(Base):
    __tablename__ = "review_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("conversation_messages.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    reason: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    corrected_answer: Mapped[str] = mapped_column(Text, default="")
    evidence_pages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CuratedOverride(Base):
    __tablename__ = "curated_overrides"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_cases.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    question_hash: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewAudit(Base):
    __tablename__ = "review_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
