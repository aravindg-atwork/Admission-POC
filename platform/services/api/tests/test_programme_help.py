from app.agent.guards import (
    greeting_guard,
    identity_guard,
    language_preference_guard,
    programme_clarify_guard,
    programme_help_confirmation_guard,
    programme_help_guard,
)


def test_greeting_is_brief_and_does_not_dump_capabilities():
    result = greeting_guard("hi", {})
    assert result is not None
    assert result["answer"] == "Hi! I'm MAFSU MITRA. How can I help with your admission today?"
    assert len(result["answer"]) < 80


def test_broad_help_is_a_short_topic_menu():
    result = programme_help_guard("Can you help me with B.Tech?", {}, "btech-dairy")
    assert result is not None
    assert result["source"] == "topic-menu"
    assert result["pages"] == []
    assert "What would you like to know" in result["answer"]
    assert programme_help_guard("help mw with bfsc", {}, "bfsc")["source"] == "topic-menu"


def test_short_confirmation_reuses_help_context():
    result = programme_help_confirmation_guard(
        "sure?", {"intent": "programme_help_menu"}, "bfsc"
    )
    assert result is not None
    assert "B.F.Sc." in result["answer"]


def test_specific_question_is_not_intercepted():
    assert programme_help_guard(
        "Can you help me with B.Tech eligibility and fees?", {}, "btech-dairy"
    ) is None


def test_identity_introduction_covers_all_programmes_and_help_topics():
    result = identity_guard("Who are you and what can you do?", {})
    assert result is not None
    assert result["source"] == "identity"
    assert "MAFSU MITRA" in result["answer"]
    assert "Beta" in result["answer"]
    assert "B.V.Sc." in result["answer"]
    assert "B.F.Sc." in result["answer"]
    assert "B.Tech." in result["answer"]


def test_ambiguous_fee_question_requires_programme_choice():
    result = programme_clarify_guard("What are the fees?", {})
    assert result is not None
    assert result["source"] == "programme-clarify"
    assert result["interviewField"] == "projectId"
    assert [option["value"] for option in result["interviewOptions"]] == [
        "bvsc", "bfsc", "btech-dairy",
    ]
    assert result["carryQuestion"] == "What are the fees?"


def test_programme_clarification_skips_explicit_or_established_course():
    assert programme_clarify_guard("What are the B.F.Sc. fees?", {}) is None
    assert programme_clarify_guard("What are the fees?", {"programme": "bfsc"}) is None


def test_chat_language_request_is_a_control_not_off_topic():
    result = language_preference_guard("Can you text me in Hindi?", {})
    assert result is not None
    assert result["source"] == "language-preference"
    assert result["slotUpdate"]["preferredLanguage"] == "hi"
    assert "हिंदी" in result["answer"]
