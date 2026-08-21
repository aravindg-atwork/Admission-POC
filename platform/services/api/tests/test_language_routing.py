from unittest.mock import patch

from app.agent import language
from app.agent.guards import language_preference_guard, multi_programme_eligibility_guard
from app.providers import llm


def test_english_text_ignores_stale_marathi_selector():
    ctx = language.prepare("What is the first-year tuition fee?", "mr")
    assert ctx.language == "en"
    assert ctx.retrieval_question == ctx.question
    assert "reply in English" in ctx.reply_hint


def test_explicit_english_request_for_hindi_overrides_latin_script():
    assert language.requested_language("Can you text me in Hindi?") == "hi"
    assert language.requested_language("Can you test me in with Hindi?") == "hi"
    ctx = language.prepare("Can you reply in Hindi?", "hi", force_selected=True)
    assert ctx.language == "hi"
    assert language.requests_repeat("Can you say this same in Marathi?") is True
    assert language.requests_repeat("Can you reply in Marathi?") is False


@patch("app.agent.language.llm.translate_to_english", return_value="What is the tuition fee?")
def test_devanagari_uses_compatible_explicit_marathi_choice(translate):
    ctx = language.prepare("शिक्षण शुल्क किती आहे?", "mr")
    assert ctx.language == "mr"
    assert ctx.script == "devanagari"
    assert ctx.retrieval_question == "What is the tuition fee?"
    assert "natural Marathi" in ctx.reply_hint
    translate.assert_called_once_with(ctx.question, "mr")


@patch("app.agent.language.llm.translate_to_english", return_value="What documents are required?")
def test_native_hindi_detected_when_selector_left_english(translate):
    ctx = language.prepare("मुझे कौन से दस्तावेज चाहिए?", "en")
    assert ctx.language == "hi"
    assert "natural Hindi" in ctx.reply_hint
    translate.assert_called_once_with(ctx.question, "hi")


@patch("app.agent.language.llm.translate_to_english", return_value="What is the fee?")
def test_romanized_marathi_is_not_misclassified_as_english(translate):
    ctx = language.prepare("mala fee kiti ahe?", "en")
    assert ctx.language == "mr"
    assert ctx.typed_romanized is True
    assert ctx.retrieval_question == "What is the fee?"


@patch("app.agent.language.llm.translate_to_english", return_value="Am I eligible?")
def test_romanized_marker_before_colon_is_detected(translate):
    ctx = language.prepare("mala he kalaycha ahe: Am I eligible?", "mr")
    assert ctx.language == "mr"
    assert ctx.typed_romanized is True


@patch("app.providers.llm.generate", side_effect=RuntimeError("provider unavailable"))
def test_translation_failure_returns_original_question(_generate):
    text = "मला फी किती आहे?"
    assert llm.translate_to_english(text, "mr") == text


@patch("app.providers.llm.generate", return_value=("मला फी किती आहे?", "test"))
def test_non_latin_translation_is_rejected(_generate):
    text = "मला फी किती आहे?"
    assert llm.translate_to_english(text, "mr") == text


@patch("app.providers.llm.generate", return_value=("शुल्क ₹27,500 आहे.", "test"))
def test_localized_fixed_answer_preserves_number(_generate):
    answer, model = llm.localize_answer("The fee is ₹27,500.", "mr")
    assert answer == "शुल्क ₹27,500 आहे."
    assert model == "test"


@patch("app.providers.llm.generate", return_value=("शुल्क आहे.", "test"))
def test_localized_fixed_answer_rejects_dropped_number(_generate):
    original = "The fee is ₹27,500."
    answer, model = llm.localize_answer(original, "mr")
    assert answer == original
    assert model == "translation-fallback"


def test_english_school_subject_does_not_trigger_language_switch():
    question = (
        "I got 49% in Physics, Chemistry, Biology and English in 12th. "
        "Which course am I eligible for?"
    )
    assert language.requested_language(question) is None
    assert language_preference_guard(question, {}) is None


def test_explicit_reply_in_english_still_switches_language():
    assert language.requested_language("Please reply in English") == "en"


def test_distant_use_does_not_turn_english_subject_into_language_command():
    question = (
        "I scored 43% in PCM and English. My NCL expired and farming is not "
        "our main income. Which reservation can I actually use?"
    )
    assert language.requested_language(question) is None


def test_three_programme_compound_eligibility_is_synthesized():
    question = (
        "I'm OBC from Maharashtra, I'm already 17, and I got 49% in Physics, "
        "Chemistry, Biology and English in 12th. I did not have Mathematics. "
        "I appeared for MHT-CET 2026 in PCB and I also appeared for NEET but "
        "I did not qualify. My father is a fisherman and I have the required "
        "certificate. Out of B.V.Sc., B.F.Sc. and B.Tech Dairy Technology, "
        "which courses am I actually eligible for?"
    )
    result = multi_programme_eligibility_guard(question, {})
    assert result is not None
    assert "B.F.Sc.: You meet the academic and entrance-exam requirements" in result["answer"]
    assert "B.V.Sc. & A.H.: No" in result["answer"]
    assert "B.Tech. (Dairy Technology): No" in result["answer"]
    assert "12 weightage points" in result["answer"]
    assert "maximum of 20" in result["answer"]
    assert "final B.F.Sc. eligibility still depends" in result["answer"]
