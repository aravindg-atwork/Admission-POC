"""POST /api/chat - the route the frontend (src/api/chat.ts) already calls.
Defaults projectId to "bvsc" since that's the only programme ingested in
this vertical-slice checkpoint - accepts an explicit one too, for forward
compatibility once more programmes are ingested (see CLAUDE.md's phased
plan; this is NOT multi-programme-aware yet beyond accepting the field).
"""

from fastapi import APIRouter
import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..agent.answer import answer
from ..agent import safety
from ..core.routing import effective_project
from ..storage import conversations
from ..storage import telemetry

router = APIRouter()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1200)
    uiLanguage: Literal["en", "hi", "mr"] = "en"
    projectId: Literal["bvsc", "bfsc", "btech-dairy"] = "bvsc"
    conversationState: dict = Field(default_factory=dict)
    sessionId: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be blank")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("question contains unsupported control characters")
        return value

    @field_validator("conversationState")
    @classmethod
    def bound_conversation_state(cls, value: dict) -> dict:
        if len(value) > 32 or len(json.dumps(value, ensure_ascii=False)) > 8192:
            raise ValueError("conversationState is too large")
        return value


class ChatResponse(BaseModel):
    """What a student receives. Deliberately carries no retrieval or provider
    internals: no prospectus page list, no model id, no policy rule ids. All
    three are still produced, logged and reviewable server-side - see
    safety.student_response, which is what removes them here."""

    answer: str
    source: str
    interviewField: str | None = None
    interviewOptions: list[dict] = Field(default_factory=list)
    carryQuestion: str | None = None
    slotUpdate: dict = Field(default_factory=dict)
    language: str = "en"
    cacheHit: bool = False
    projectId: str = "bvsc"
    sessionId: str | None = None
    messageId: int | None = None
    admissionYear: str = "2026-27"
    decisionState: Literal["eligible_so_far", "not_eligible", "needs_clarification", "document_issue", "quota_specific", "cannot_confirm", "informational"] = "informational"
    sourceTrace: dict = Field(default_factory=dict)
    fallbackReason: str | None = None


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    started = time.monotonic()
    project_id = effective_project(req.question, req.projectId)
    # Programme-specific interview slots cannot safely cross an explicit
    # programme switch made in the student's new question.
    state = req.conversationState if project_id == req.projectId else {}
    state, corrections = safety.reconcile_state(req.question, state)
    if corrections and len(req.question.split()) <= 12:
        labels = {"reserved": "Reserved/OBC", "unreserved": "Unreserved/General", "yes": "exam completed/qualified", "not_qualified": "appeared but not qualified"}
        changed = ", ".join(f"{key}: {labels.get(str(value), value)}" for key, value in corrections.items())
        result = {"answer": f"Updated—{changed} now replaces the earlier detail. I will use the corrected fact for the rest of this eligibility check.", "source": "state-correction", "model": "state-machine", "pages": [], "slotUpdate": corrections, "language": req.uiLanguage}
    else:
        try:
            result = answer(project_id, req.question, state, req.uiLanguage)
        except Exception as exc:  # fail closed: never answer admission facts from model memory
            print(f"[chat-fail-closed] {project_id}: {exc!r}")
            result = {
                "answer": "I'm unable to verify admission information right now. Please try again shortly.",
                "source": "service-unavailable", "model": "none", "pages": [],
                "language": req.uiLanguage,
            }
    if corrections:
        result["slotUpdate"] = {**result.get("slotUpdate", {}), **corrections}
    explicit_facts = safety.turn_facts(req.question, project_id)
    if explicit_facts:
        result["slotUpdate"] = {**result.get("slotUpdate", {}), **explicit_facts}
    result = safety.finalize(req.question, project_id, result)
    result["projectId"] = project_id
    try:
        session_id, message_id = conversations.log_exchange(
            req.sessionId, project_id, result.get("language", req.uiLanguage),
            req.question, result,
        )
        result["sessionId"] = session_id
        result["messageId"] = message_id
    except Exception as exc:  # logging must not block a student's answer
        print(f"[conversation-log] write failed: {exc!r}")
    telemetry.record_chat(project_id, result, round((time.monotonic() - started) * 1000))
    return ChatResponse(**safety.student_response(result))
