"""POST /api/chat - the route the frontend (src/api/chat.ts) already calls.
Defaults projectId to "bvsc" since that's the only programme ingested in
this vertical-slice checkpoint - accepts an explicit one too, for forward
compatibility once more programmes are ingested (see CLAUDE.md's phased
plan; this is NOT multi-programme-aware yet beyond accepting the field).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ..agent.answer import answer
from ..core.routing import effective_project
from ..storage import conversations

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    uiLanguage: str = "en"
    projectId: str = "bvsc"
    conversationState: dict = {}
    sessionId: str | None = None


class ChatResponse(BaseModel):
    answer: str
    source: str
    model: str
    pages: list[int] = []
    interviewField: str | None = None
    interviewOptions: list[dict] = []
    carryQuestion: str | None = None
    slotUpdate: dict = {}
    policyDecisions: list[dict] = []
    language: str = "en"
    cacheHit: bool = False
    projectId: str = "bvsc"
    sessionId: str | None = None
    messageId: int | None = None


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    project_id = effective_project(req.question, req.projectId)
    # Programme-specific interview slots cannot safely cross an explicit
    # programme switch made in the student's new question.
    state = req.conversationState if project_id == req.projectId else {}
    result = answer(project_id, req.question, state, req.uiLanguage)
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
    return ChatResponse(**result)
