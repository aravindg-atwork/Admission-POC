"""Shared helpers used by both the single-answer path (answer.py/guards.py)
and the multi-part orchestrator (orchestrator.py) - extracted 2026-08-13 to
break the rag.py<->orchestrator.py circular import (orchestrator.py needed
these back via function-local imports; this module is a true leaf that
never imports its own siblings, so both can import it at module level
instead). Also holds every per-project prompt-building helper
(_system_prompt/_greeting_prompt/_injection_refusal) so guards.py and
answer.py both get them from here rather than importing each other.
"""

import re

from ..core import vocabulary
from ..core import glossary, programs, transliterate
from ..prompts.canned import _INJECTION_REFUSAL_TEMPLATES
from ..prompts.system import GREETING_PROMPT_BASE, SYSTEM_PROMPT_BASE
from .. import config
from ..generation import llm


# this, the model's own self-description was still wrong for 5 of 6 - it
# would call itself the "B.V.Sc. & A.H." assistant even while correctly
# answering from, say, the M.V.Sc. prospectus. Built per-call now instead of
# once at import time, from programs.PROGRAM_NAMES.
# The fallback for a project id that names no specific programme - which,
# since the 2026-08-16 split, is exactly what "default" is: the general entry
# point, holding no corpus. It used to fall back to "B.V.Sc. & A.H.", so every
# prompt built on the general widget introduced itself as the veterinary
# assistant and answered as one. That default is the whole reason a PCM
# student was told to apply for B.V.Sc. and a question about NEET vs MHT-CET
# came back covering only the two MHT-CET programmes.
_GENERAL_PROGRAM_NAME = "MAFSU undergraduate admissions"


def _program_name(project_id):
    return programs.PROGRAM_NAMES.get(project_id, _GENERAL_PROGRAM_NAME)


def _system_prompt(project_id):
    return SYSTEM_PROMPT_BASE.format(program=_program_name(project_id)) + llm.LANGUAGE_RULE


def _assistant_scope(project_id):
    """What the assistant should say it covers, when describing ITSELF.

    Not the same question as _program_name, which answers "whose prospectus
    am I retrieving from". The default project does double duty: it is both
    the B.V.Sc. corpus AND the general entry point every student lands on
    when no programme has been chosen, so _program_name returns
    "B.V.Sc. & A.H." for it. Feeding that into a greeting made the general
    widget introduce itself as the B.V.Sc. assistant and keep steering
    there - reported directly: "why are you only mentioning bvsc?".

    Answers stay scoped to the retrieved corpus, which is correct. Only the
    self-description widens, because on the shared entry point the honest
    answer to "what are you" is all three programmes.
    """
    if project_id == config.DEFAULT_PROJECT_ID:
        names = list(programs.PROGRAM_NAMES.values())
        return ", ".join(names[:-1]) + " and " + names[-1]
    return _program_name(project_id)


def _greeting_prompt(project_id):
    return GREETING_PROMPT_BASE.format(program=_assistant_scope(project_id)) + llm.LANGUAGE_RULE


def _injection_refusal(project_id, ui_language):
    template = _INJECTION_REFUSAL_TEMPLATES.get(ui_language) or _INJECTION_REFUSAL_TEMPLATES["en"]
    return template.format(program=_program_name(project_id))


_UI_LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "en": "English"}


def _ui_language_matches(language, ui_language):
    """Whether the picked ui_language is actually a useful signal for this
    question's already-detected script, worth forwarding to the model - as
    opposed to a stale selector value that contradicts what the student just
    typed (picked English, then asked a question in Marathi). Devanagari is the
    one genuinely ambiguous case (Hindi and Marathi share the script); Latin and
    Tamil aren't, so a mismatched ui_language there would only tell the model to
    answer in the wrong language and gets dropped instead of forwarded - see
    _language_hint.
    """
    if language == "devanagari":
        return ui_language in ("hi", "mr")
    if language == "tamil":
        return ui_language == "ta"
    return ui_language == "en"


def _language_hint(ui_language):
    """Explicit disambiguation for the model, built from the language the student
    picked in the app's own selector - not inferred. Hindi and Marathi share
    Devanagari script, so detect_script (and the model, left to guess from wording
    alone) can't reliably tell them apart on short/ambiguous questions; this closes
    that gap for the case that actually matters. A no-op when the caller didn't
    pass a recognized ui_language (e.g. legacy callers, tests).
    """
    name = _UI_LANGUAGE_NAMES.get(ui_language)
    if not name:
        return ""
    confusable = " (not Hindi)" if name == "Marathi" else " (not Marathi)" if name == "Hindi" else ""
    return f"\n\n(The student selected {name} in the app - always reply in {name}{confusable}.)"


def _english_reply_hint():
    """Recency reminder that an English question gets an English answer.

    _language_hint above only fires when the CALLER supplied a ui_language, so
    anything that doesn't send one - the admin Live tester, a direct API
    consumer, the tools/ test scripts - left an English question with no
    language instruction anywhere near the end of the prompt, only
    llm.LANGUAGE_RULE far away at the top of the system prompt. Reproduced
    directly on sarvam-105b: "compare all courses eligibility", plain
    English, came back entirely in Hinglish ("B.V.Sc. & A.H. program ke liye,
    aapko XII Std. ya equivalent examination pass karna hoga...").

    Same recency principle the rest of this codebase already leans on for
    exactly this failure mode - see providers.py's _SCRIPT_REMINDER and
    answer.py's page_reminder, both added because a rule stated only in the
    system prompt gets dropped on long generations while the same rule
    repeated at the end of the user turn holds. Longer answers drift first,
    which is why the cross-program comparison path (several programs, one
    paragraph each) surfaced this and short single-fact answers didn't.

    Worded as an observation about the question rather than reusing
    _language_hint's "the student selected English in the app", which would
    be a false claim when nothing was actually selected.
    """
    return "\n\n(The question above is written in English - reply in English.)"


def _romanized_input_hint(name):
    """The student typed in Roman script but the words are Hindi/Marathi, not
    English (see lang.detect_romanized_indic) - e.g. "mera fees kitna hai".
    Without this, the model reads Latin script and, despite LANGUAGE_RULE's
    general "match their language" instruction, tends to default to English -
    there's no native-script cue to anchor it. Tells it explicitly to generate in
    Devanagari anyway, reusing the same reliable native-generate-then-romanize
    pipeline as script_pref="auto" (see _apply_script_pref) rather than asking
    for direct Roman-script generation, which transliterate.py's docstring notes
    is unreliable.
    """
    return (
        f"\n\n(The student typed this question in Roman/Latin letters, but it's "
        f"{name} written phonetically (\"Hinglish\"/\"Marathinglish\"), not English - "
        f"e.g. \"mera fees kitna hai\" means \"what is my fee\" in Hindi. Generate "
        f"your answer in proper Devanagari script, matching {name} - it will be "
        f"automatically romanized back for display. Do NOT answer in English.)"
    )


def _apply_script_pref(text, language, script_pref, typed_romanized=False):
    """Romanized (Hinglish/Tanglish) is a display-time transformation, not a
    generation-time one - asking the model to write Roman-script Hindi/Tamil
    directly proved unreliable (see transliterate.py), so generation always stays
    native-script and this converts afterward, deterministically. Returns
    (display_text, speakable). No-op for anything without a native script (e.g.
    English) or under an explicit "native" request.

    "auto" mirrors the script the student actually typed in: someone who wrote
    the question in Devanagari reads Devanagari, so they get Devanagari back,
    while someone who typed "mera fees kitna hai" gets a romanized reply. It used
    to romanize every Indic answer regardless of input script, on the reasoning
    that most students read Roman day to day - true of how they *type*, but it
    meant a student who deliberately wrote in Devanagari got back mechanical
    Harvard-Kyoto ("प्रवेश आवश्यक" -> "praveza avazyaka", since HK maps श to z),
    which is markedly harder to read than the Devanagari they just typed. It also
    contradicted tools/test_matrix.py, which has always asserted that a
    Devanagari/Tamil question comes back in that same script.

    An explicit "native" still forces native script, so the app's script toggle
    keeps working for the romanized-input case it was built for - and that is
    also what makes an answer speakable, since the TTS voice can't pronounce
    romanized text.
    """
    if script_pref != "native" and typed_romanized and language in ("devanagari", "tamil"):
        return transliterate.to_romanized(text, language), False
    return text, True

# Exact-match greetings across the supported languages. Deliberately not length-based:
# a longer question in any script must never be mistaken for a greeting.
GREETINGS = {
    "hi", "hey", "hello", "yo", "hii", "hiya", "hey there",
    "thanks", "thank you", "thankyou", "ok", "okay", "bye", "goodbye",
    "namaste", "namaskar", "vanakkam", "vanakam",
    "வணக்கம்", "नमस्ते", "नमस्कार", "हाय", "हेलो",
}


def is_greeting(text):
    return text.lower().strip().strip("!.?,। ") in GREETINGS


_READING_HEADER = "Explicit readings of the table above:"
# Matches pdf.py's per-cell line shape exactly - either the two-level form
# "{caption} - {label} for {group} at {where}: {value}" (linearize_table) or
# the single-level form "{caption} - {label} for {column}: {value}"
# (_linearize_column_table). Both end in "for <group>: <value>", which is
# the seam this splits on.
_READING_LINE = re.compile(r"^(?P<desc>.+?):\s*(?P<value>[-–]|[0-9][0-9,./%-]*)\s*$")


def _compact_readings(text):
    """Regroup pdf.py's one-line-per-cell table readings into one line per
    group (year/column) instead, combining every component's value for that
    group onto a single line rather than a long run of near-identical lines
    that differ only in the trailing number.

    Same underlying figures, same "row - group / column: value" data per
    cell (tablelookup.py still parses the ORIGINAL per-cell lines directly
    off `top`, completely unaffected by this - this only reshapes the
    separate string built for the LLM prompt, see _answer below). What
    changes is the shape handed to the model: pdf.py's hostel-fee table
    linearizes to 27 lines that are maximally uniform (same template, only
    the number changes) - reproduced directly as close to a worst-case
    trigger for a small model's repetition tendencies, and confirmed via a
    captured live payload to be ~88x longer than llama.cpp's default
    repeat_last_n=64 window. Grouping by column/year cuts the line count by
    roughly the column count (3-9x here) and, just as importantly, makes
    each line structurally different from its neighbours instead of a
    uniform repeating template.

    Deliberately conservative: any line that doesn't match the expected
    "... for <group>: <value>" shape leaves the WHOLE block untouched rather
    than risk silently dropping or mangling a figure - the original,
    already-working format is the safe fallback, not a guess at a fix-up.
    """
    if _READING_HEADER not in text:
        return text
    head, body = text.split(_READING_HEADER, 1)
    groups, order = {}, []
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _READING_LINE.match(line)
        if not m:
            return text
        desc, value = m.group("desc").strip(), m.group("value").strip()
        if " for " not in desc:
            return text
        left, group_key = desc.rsplit(" for ", 1)
        caption, label = left.split(" - ", 1) if " - " in left else ("", left)
        if group_key not in groups:
            groups[group_key] = (caption, [])
            order.append(group_key)
        groups[group_key][1].append((label.strip(), value))

    lines = []
    for key in order:
        caption, pairs = groups[key]
        prefix = f"{caption} — " if caption else ""
        values = "; ".join(f"{label}: {value}" for label, value in pairs)
        lines.append(f"{prefix}{key} — {values}")
    return head + _READING_HEADER + "\n" + "\n".join(lines)


# Deterministic guardrail against the LLM leaking an NRI/FN/PIO/OCI-scoped
# provision (an exemption, waiver, or special fee) into an answer for a
# question that never established the student is in that category - added
# 2026-08-12 after prompt-only fixes (a general rule, then a specific worked
# example in SYSTEM_PROMPT_BASE) failed to reliably stop it: reproduced live
# on mvsc, the retrieved chunk DID contain both the "NRI/FN/PIO/OCI
# CANDIDATES" heading and the exemption clause together, so the model had
# everything it needed and still stated the exemption as a general rule for
# "if your degree is from abroad" - a reasoning failure prompting alone
# couldn't close, matching this codebase's standing preference for a
# mechanical check over hoping the model behaves (see glossary.py,
# tablelookup.py, intent.py for the same philosophy elsewhere).
#
# Deliberately narrow, same reasoning as _english_eligibility_boost above:
# fires only when (a) the excerpts actually used contain NRI/FN/PIO/OCI-
# headed content, (b) the reply's own wording shows the shape of claim that
# has actually leaked (an exemption/waiver or a special fee), and (c) the
# student's own question doesn't already establish they're in that category
# - so it doesn't fire on the ~86% retrieval noise this app already carries
# (TOP_K=15's documented noise ratio) just because an unrelated NRI chunk
# rode along, only when the answer looks like it actually drew from one.
_NRI_HEADING_RE = re.compile(r"NRI\s*/\s*FN\s*/\s*PIO\s*/\s*OCI", re.IGNORECASE)
_NRI_SELF_ID_RE = re.compile(
    r"\bNRI\b|\bFN\b|\bPIO\b|\bOCI\b|foreign national|overseas citizen|"
    r"non[- ]resident indian|person of indian origin", re.IGNORECASE)
_NRI_LEAK_SIGNALS = ("exempt", "not required to appear", "special fee")
_NRI_SCOPE_CAVEAT = (
    " This specific provision is what the prospectus states for NRI/FN/PIO/OCI "
    "candidates - if that is not your admission category, confirm with MAFSU "
    "admissions whether it still applies to your situation."
)


def _add_nri_scope_caveat(question, chunks, reply):
    """Append _NRI_SCOPE_CAVEAT to `reply` when it looks like an NRI/FN/PIO/OCI-
    scoped fact leaked into a general answer - see the module comment above.
    `chunks` is whatever excerpts the reply was actually generated from (a
    single project's `top`, or several programs' combined excerpts for a
    comparison answer).
    """
    if _NRI_SELF_ID_RE.search(question):
        return reply
    nri_chunk_text = " ".join(c["text"] for c in chunks if _NRI_HEADING_RE.search(c["text"]))
    if not nri_chunk_text:
        return reply
    reply_lower = reply.lower()
    if not any(signal in reply_lower for signal in _NRI_LEAK_SIGNALS):
        return reply
    return reply + _NRI_SCOPE_CAVEAT


_ELIGIBILITY_BOOST_TERMS = "eligibility criteria minimum marks XIIth Std 10+2 pattern qualifying examination"


def _english_eligibility_boost(text):
    """A handful of formal-prospectus anchor words appended to an eligibility-
    style question in English - mirrors what glossary.english_terms does for
    Devanagari/Tamil input, but for a same-language REGISTER gap instead of a
    cross-lingual one: a real student writes "I scored 49% in 12th, am I
    eligible?", while the prospectus says "minimum 50% marks... XIIth Std...
    10+2 pattern...". That divergence is large enough that the real
    eligibility page sometimes ranks just outside TOP_K - confirmed directly
    on a live benchmark miss (rank 25 of 219 chunks for a B.F.Sc. probe via
    vectorstore.search), which is what let the model reach for a less-
    relevant excerpt instead (in that case, wrongly applying an NRI-specific
    clause to an ordinary question - see SYSTEM_PROMPT_BASE's NRI-clause
    rule, added the same day for the same root incident).

    Deliberately narrow - only fires when the text both asks about
    eligibility/marks AND references a class-12 qualifying exam, so it adds
    no noise to unrelated English questions (a fee or hostel question is
    untouched).
    """
    lower = text.lower()
    asks_eligibility = any(w in lower for w in ("eligible", "eligibility", "qualify", "qualified")) or "%" in text
    names_twelfth = "12th" in lower or "xii" in lower or "10+2" in lower
    return _ELIGIBILITY_BOOST_TERMS if (asks_eligibility and names_twelfth) else ""


def _build_retrieval_text(question, language, hint_language, ui_language):
    """English text for the LEXICAL half of retrieval and for table lookup,
    as opposed to `question` (what the student actually typed). These
    diverge for Indic input and keeping them separate is the point: both of
    those mechanisms compare against an English prospectus, so handing them
    Devanagari guarantees zero matches. (The VECTOR half of retrieval uses
    the native-script question directly instead - see retrieval_vector in
    _answer - so this function's output never gets embedded, only used for
    keyword overlap and tablelookup.)

    Extracted 2026-08-12 from _answer so _answer_comparison can build the
    same retrieval_text once and reuse it across several projects' vector
    stores, instead of re-deriving (and re-calling translate_to_english for)
    each one.
    """
    if language == "latin":
        boost = _english_eligibility_boost(question)
        base = f"{question} {boost}" if boost else question
        # Bridge the student's words to the prospectus's own wording before
        # the lexical half of retrieval ever runs. Measured gap: "what
        # percentage is required for SC/ST/OBC candidates?" never retrieved
        # the chunk holding "47.50% marks in case of Reserved category",
        # because the document does not contain SC, ST or OBC - which is the
        # retrieval half of the Q50 wrong answer. Additive, so a question that
        # already retrieved correctly keeps every signal it had.
        return vocabulary.expand(base)
    # llm.translate_to_english's own docstring/history documents that naming
    # the source language measurably improves translation accuracy - but that
    # only fires when the passed language resolves to hi/mr/ta (see
    # llm._translate_system); raw `ui_language` stays "en" whenever the
    # student left the default UI selector, even for a plainly Devanagari or
    # Tamil question, silently falling back to the unanchored generic prompt
    # exactly the naming fix exists to avoid. Reproduced directly: a Marathi
    # "how do I file a complaint" question, ui_language="en", translated to
    # "Where is the fee charged? grievance" - not just imprecise, a different
    # question entirely, which poisoned retrieval before scoring ever ran.
    # `hint_language` (computed by the caller for the generation-side prompt)
    # already resolves Devanagari's hi/mr ambiguity from the question text
    # itself when ui_language doesn't; Tamil script is unambiguous on its own
    # once detected, so it never needed a word-list guess. Reusing both
    # closes this the same way, for the same root cause, without a second
    # detector.
    translate_language = hint_language or ("ta" if language == "tamil" else ui_language)
    translated = llm.translate_to_english(question, translate_language)
    if translated and translated != question:
        # Used only for the lexical half of retrieval and the table lookup -
        # never shown to the student, and never embedded, so a mistranslation
        # costs ranking noise at worst instead of aiming the whole vector
        # search at the wrong topic.
        # Domain terms appended deterministically rather than relying on the
        # translation alone - the translator drops or inverts exactly the
        # domain nouns that decide which part of the prospectus is relevant
        # (a reservation-percentage question came back as a question about
        # fees, and duly retrieved the fee tables), so the terms it must not
        # lose are added mechanically.
        return " ".join(filter(None, [translated, glossary.english_terms(question),
                                       _english_eligibility_boost(translated)]))
    return question

