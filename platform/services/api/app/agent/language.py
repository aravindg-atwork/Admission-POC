"""Language routing for the admissions answer pipeline.

The prospectuses are English, while students may ask in Hindi or Marathi.
This module keeps three concerns separate:

* ``question`` is always the student's original text and is used for answer
  language/tone and the multilingual vector embedding.
* ``retrieval_question`` is an English translation used only by lexical
  retrieval and deterministic English-domain matchers.
* ``reply_hint`` tells generation which language to use.  Hindi and Marathi
  share Devanagari, so an explicit, compatible UI choice wins; otherwise a
  conservative lexical detector is used.

Translation is best-effort.  A failed or suspicious translation never blocks
the request and never replaces the student's original question in the answer.
"""

from dataclasses import dataclass
import re

from ..core import lang
from ..providers import llm

SUPPORTED_UI_LANGUAGES = {"en", "hi", "mr"}
_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
_LANGUAGE_NAMES = {
    "hi": re.compile(r"\b(?:hindi|हिंदी|हिन्दी)\b", re.I),
    "mr": re.compile(r"\b(?:marathi|मराठी)\b", re.I),
    "en": re.compile(r"\b(?:english|अंग्रेजी|इंग्रजी)\b", re.I),
}
_LANGUAGE_CONTROL = re.compile(
    r"\b(?:speak|talk|reply|respond|answer|text|chat|write|communicate|language|"
    r"use|switch|change|test|say|translate)\b",
    re.I,
)


@dataclass(frozen=True)
class LanguageContext:
    question: str
    script: str
    language: str
    typed_romanized: bool
    retrieval_question: str

    @property
    def generation_question(self) -> str:
        """Question used only for the provider's script reminder.

        Romanized Hindi/Marathi has Latin script, so passing it directly would
        incorrectly suppress the Devanagari reminder even though routing has
        already established the intended reply language.
        """
        if self.language in ("hi", "mr") and self.script != "devanagari":
            return "अ"
        return self.question

    @property
    def reply_hint(self) -> str:
        name = _NAMES[self.language]
        if self.language == "en":
            return "\n\n(The question above is written in English - reply in English.)"
        other = "Marathi" if self.language == "hi" else "Hindi"
        return (
            f"\n\n(The student's question is in {name}. Reply in natural {name}, "
            f"not {other}, using Devanagari script. Preserve official English "
            "names and exact numbers from the source.)"
        )


def _normalise_ui_language(ui_language: str | None) -> str | None:
    value = (ui_language or "").strip().lower()
    return value if value in SUPPORTED_UI_LANGUAGES else None


def requested_language(question: str) -> str | None:
    """Return a language explicitly requested in the student's message."""
    if not _LANGUAGE_CONTROL.search(question):
        return None
    matches = [code for code, pattern in _LANGUAGE_NAMES.items() if pattern.search(question)]
    return matches[0] if len(matches) == 1 else None


def requests_repeat(question: str) -> bool:
    """Whether a language command asks to repeat the previous answer."""
    low = " ".join(question.lower().split())
    return requested_language(question) is not None and any(
        phrase in low for phrase in (
            "say this", "same in", "repeat", "say it again", "translate this",
            "previous answer", "last answer", "again in",
        )
    )


def _resolve_language(question: str, script: str, ui_language: str | None,
                      force_selected: bool = False) -> tuple[str, bool]:
    selected = _normalise_ui_language(ui_language)
    if force_selected and selected:
        return selected, script == "latin" and selected in ("hi", "mr")
    if script == "devanagari":
        # The selector is authoritative only where it is script-compatible.
        if selected in ("hi", "mr"):
            return selected, False
        return lang.detect_devanagari_hi_mr(question) or "hi", False

    romanized = lang.detect_romanized_indic(question) if script == "latin" else None
    if romanized:
        # Text evidence beats a stale English selector. A compatible hi/mr
        # selector disambiguates short mixed romanized questions.
        return (selected if selected in ("hi", "mr") else romanized), True
    return "en", False


def prepare(question: str, ui_language: str | None = None,
            force_selected: bool = False) -> LanguageContext:
    script = lang.detect_script(question)
    language, typed_romanized = _resolve_language(
        question, script, ui_language, force_selected=force_selected
    )
    retrieval_question = question
    if language in ("hi", "mr"):
        retrieval_question = llm.translate_to_english(question, language)
    return LanguageContext(
        question=question,
        script=script,
        language=language,
        typed_romanized=typed_romanized,
        retrieval_question=retrieval_question,
    )
