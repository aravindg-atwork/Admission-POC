from app.agent import answer as answer_module
from app.api import chat as chat_module


def test_chat_fails_closed_when_answer_pipeline_crashes(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise ConnectionError("qdrant unavailable")

    monkeypatch.setattr(chat_module, "answer", unavailable)
    monkeypatch.setattr(chat_module.conversations, "log_exchange", lambda *_args: ("a" * 32, 1))
    monkeypatch.setattr(chat_module.telemetry, "record_chat", lambda *_args: None)
    response = chat_module.chat(chat_module.ChatRequest(
        question="I am OBC with 48%. Am I eligible for B.V.Sc.?",
        projectId="bvsc",
    ))
    assert response.source == "service-unavailable"
    assert response.decisionState == "cannot_confirm"
    assert "eligible" not in response.answer.lower()
    assert response.pages == []


def test_embedding_failure_never_calls_retrieval(monkeypatch):
    monkeypatch.setattr(answer_module.embeddings, "embed_query", lambda *_args: (_ for _ in ()).throw(ConnectionError()))
    monkeypatch.setattr(answer_module.store, "search", lambda *_args: (_ for _ in ()).throw(AssertionError("must not retrieve")))
    context = answer_module.language.prepare("What are the fees?", "en")
    result = answer_module._answer_uncached("bvsc", "What are the fees?", {}, context)
    assert result["source"] == "provider-unavailable"
    assert result["pages"] == []
