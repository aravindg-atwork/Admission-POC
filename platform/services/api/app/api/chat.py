"""POST /api/chat - the route the frontend (src/api/chat.ts) already calls.
Defaults projectId to "bvsc" since that's the only programme ingested in
this vertical-slice checkpoint - accepts an explicit one too, for forward
compatibility once more programmes are ingested (see CLAUDE.md's phased
plan; this is NOT multi-programme-aware yet beyond accepting the field).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ..agent.answer import answer

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    uiLanguage: str = "en"
    projectId: str = "bvsc"


class ChatResponse(BaseModel):
    answer: str
    source: str
    model: str
    pages: list[int] = []


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = answer(req.projectId, req.question)
    return ChatResponse(**result)
