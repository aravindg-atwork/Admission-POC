"""Complexity detection and question decomposition for genuinely multi-part
questions - "I'm reserved category, want to know the fee, the hostel
availability, and the document checklist" - where a single retrieval pass
and one narrow answer tend to under-serve at least one part.

Same philosophy as programs.py/intent.py: keyword/regex triggers, no LLM
call to decide WHETHER to orchestrate (that decision must be free and
instant, or it isn't worth having). `rag.py`'s `_answer_comparison` (built
2026-08-12, earlier the same day as this module) is the working precedent
this generalizes from: fan out retrieval across several scoped contexts,
then ONE combined generation call over clearly-labeled sections - not one
LLM call per branch, and not a multi-agent framework (explicitly rejected
earlier this session).

Phase A only (deterministic split + retrieval fanout + one generation
call) - Phase B (true per-sub-question LLM dispatch) is deliberately
deferred, per the 2026-08-12 orchestration plan, until a captured live
failure shows Phase A insufficient. Nothing in this module calls an LLM.
"""

import re

from .. import config
from ..core import programs
from ..prompts.system import _ORCHESTRATOR_SYSTEM_PROMPT
from ..storage.faq import _discriminators, _words
from .helpers import (_add_nri_scope_caveat, _apply_script_pref, _build_retrieval_text,
                       _compact_readings, _program_name)

# Reuses programs._PROGRAM_SPECIFIC_MARKERS (the same vocabulary that
# already decides whether a question needs program-level clarification)
# rather than a second hand-maintained list, bucketed into named topics so
# "3+ distinct topics in one question" can be measured at all - a raw count
# of matched marker words would treat "fee" and "fees" as two topics
# instead of one.
_TOPIC_BUCKETS = {
    "fee": {"fee", "fees", "tuition", "refund", "शुल्क", "फी", "फीस"},
    "eligibility": {"eligibility", "eligible", "criteria", "marks", "neet",
                     "aieea", "cgpa", "cutoff", "merit", "पात्रता"},
    "documents": {"documents", "document", "certificate", "certificates"},
    "seats": {"seat", "seats", "quota", "reservation", "reserved", "unreserved",
               "vacancy", "vacancies", "intake", "जागा"},
    "hostel": {"hostel", "वसतिगृह"},
    "dates": {"deadline"},
    "process": {"admission", "grievance", "internship", "duration",
                 "syllabus", "curriculum", "प्रवेश"},
}

_CLAUSE_CONNECTOR_RE = re.compile(r"\b(and|also|as well as)\b|;", re.IGNORECASE)


def _topic_buckets_hit(question):
    words = set(_words(question))  # faq._words returns a list (order matters for
    # discriminator matching there); this call site only needs set membership.
    return {bucket for bucket, markers in _TOPIC_BUCKETS.items() if words & markers}


def _clause_signal(question):
    return question.count("?") >= 2 or len(_CLAUSE_CONNECTOR_RE.findall(question)) >= 2


def is_complex(question):
    """True only when 2+ INDEPENDENT signals agree - never one alone, since
    raw length is common in an ordinary wordy single-fact question and must
    not trigger this by itself (see config.ORCHESTRATOR_MIN_WORDS's own
    reasoning).
    """
    signals = 0
    has_clause_signal = _clause_signal(question)
    if has_clause_signal:
        signals += 1
    if len(_topic_buckets_hit(question)) >= 3:
        signals += 1
    _, groups = _discriminators(question)
    if len(groups.get("category", set())) >= 2:
        signals += 1
    if has_clause_signal and len(_words(question)) >= config.ORCHESTRATOR_MIN_WORDS:
        signals += 1
    return signals >= 2


def _split_subtopics(question):
    """Deterministic split into up to config.ORCHESTRATOR_MAX_SUBTASKS
    sub-questions - regex only, no LLM call. Returns None (not a list of
    one) when no real split point was found, so the caller falls straight
    back to the normal single-pass path - decomposition is an optimization,
    never a requirement to produce an answer.
    """
    if question.count("?") >= 2:
        parts = [p.strip() + "?" for p in question.split("?") if p.strip()]
    else:
        parts = [p.strip() for p in _CLAUSE_CONNECTOR_RE.split(question) if p and p.strip()]
        # re.split with a capturing-less alternation still leaves the
        # separators out (the connector group isn't captured), but the ";"
        # branch in the same pattern IS a literal in the alternation, not a
        # group, so nothing extra to filter here.
    parts = [p for p in parts if len(_words(p)) >= 2]  # drop degenerate fragments
    if len(parts) < 2:
        return None
    if len(parts) > config.ORCHESTRATOR_MAX_SUBTASKS:
        # Merge the overflow into the last kept part rather than silently
        # dropping content the student actually asked about.
        head, tail = parts[:config.ORCHESTRATOR_MAX_SUBTASKS - 1], parts[config.ORCHESTRATOR_MAX_SUBTASKS - 1:]
        parts = head + [" ".join(tail)]
    return parts


def _system_prompt(project_id):
    return _ORCHESTRATOR_SYSTEM_PROMPT.format(program=_program_name(project_id))


def answer_complex(project_id, question, script_pref, ui_language, language,
                    hint_language, hint, typed_romanized, cloud_ok, trace=None):
    """Top-level entry called from rag._answer() once is_complex(question)
    is already True. Returns None (not a dict) if decomposition didn't find
    a real split or if retrieval came back empty for every sub-topic - the
    caller falls back to the normal single-pass _answer flow in either
    case, same "optimization, not a requirement" rule as _split_subtopics.
    """
    from .. import config
    from ..core import tablelookup, textclean
    from ..generation import embeddings, llm
    from ..storage import projects, reviewlog, vectorstore
    from . import validate

    trace = trace or (lambda *a, **k: None)  # optional: callers outside the guard-stage need no trace

    subtopics = _split_subtopics(question)
    if not subtopics:
        return None

    query_vector = embeddings.embed_query(question)
    store = vectorstore.load(projects.store_path(project_id))
    if not store:
        return None

    sections, all_chunks = [], []
    for subtopic in subtopics:
        retrieval_text = _build_retrieval_text(subtopic, language, hint_language, ui_language)
        top = vectorstore.search(store, query_vector, config.ORCHESTRATOR_TOP_K_PER_SUBTASK, retrieval_text)
        if not top:
            continue
        all_chunks.extend(top)
        excerpt_text = "\n\n".join(_compact_readings(e["text"]) for e in top)
        sections.append(f"=== Part: {subtopic} ===\n{excerpt_text}")

    trace("retrieval", topK=config.ORCHESTRATOR_TOP_K_PER_SUBTASK, subtopics=subtopics,
          chunks=[{"page": e.get("page"), "score": e.get("score"), "snippet": e["text"][:160]}
                  for e in all_chunks])

    if not sections:
        return None

    context = "\n\n".join(sections)
    page_reminder = (
        "\n\n(Reminder: answer this fully yourself using the excerpts above for "
        "each part - do NOT tell the student to go check a page number "
        "themselves, and do not mention page numbers at all.)"
    )
    system_prompt = _system_prompt(project_id)
    user_prompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question + hint + page_reminder
    reply, model = llm.generate(system_prompt, user_prompt, question, allow_cloud=cloud_ok)
    trace("generation", model=model, promptId="orchestrator_system_prompt")
    reply = textclean.clean_for_display(reply)
    reply = validate.autofix(reply)
    reply = _add_nri_scope_caveat(question, all_chunks, reply)

    if config.VALIDATION_ENABLED:
        if language == "latin" and not typed_romanized:
            nri_postprocess = lambda r: _add_nri_scope_caveat(question, all_chunks, r)  # noqa: E731
            reply, model, reasons, regenerated = validate.check_and_regenerate(
                question, context, reply, model, system_prompt, user_prompt,
                postprocess=nri_postprocess)
        else:
            reasons = validate.deterministic_checks(question, context, reply)
            regenerated = False
        trace("validation", reasons=reasons, regenerated=regenerated)
        if reasons:
            reviewlog.append(projects.review_log_path(project_id), {
                "kind": "validation_regenerated" if regenerated else "validation_flag",
                "reasons": reasons, "source": "orchestrated",
            })

    display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
    pages = sorted({e["page"] for e in all_chunks})
    return {"answer": display, "pages": pages, "model": model, "language": language,
            "source": "orchestrated", "speakable": speakable, "subtopics": subtopics}
