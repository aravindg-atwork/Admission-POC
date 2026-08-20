"""The answer pipeline - a pragmatic first pass, not the full guard system
yet. Scoped deliberately for this vertical-slice checkpoint (see
../../../CLAUDE.md): retrieval -> confidence gate -> verified table lookup
-> a narrow eligibility-verdict check -> general RAG generation. What's
explicitly NOT here yet, and shouldn't be assumed to exist: the full 16-
guard pipeline (injection/greeting/dispute/comparison/clarification/etc.),
the guided multi-turn eligibility interview, and any Hindi/Marathi handling
(script detection, romanization, translate-to-English for retrieval) - this
checkpoint is English-only by scope, not by oversight. See CLAUDE.md for
what's next.

Every piece actually wired in here is ported logic, not new judgment calls:
the confidence floor, the eligibility/table-lookup precedence, and the
system prompts are all carried over from the proven system, just called
from a simpler pipeline shape.
"""

from ..core import eligibility, tablelookup
from ..providers import embeddings, llm
from ..retrieval import store
from ..settings import get_settings
from . import prompts

_settings = get_settings()

_ELIGIBILITY_HINT_WORDS = {"eligible", "eligibility", "qualify", "qualified", "admit", "admission"}

# Reproduced live, same failure the original project already documented
# (backend/rag/helpers.py's _english_reply_hint): LANGUAGE_RULE alone
# ("match the student's language") is not enough - a plain English
# question came back in Hindi with no other hint present. This checkpoint
# is English-only by scope (no script detection/romanization ported yet),
# so the hint is appended unconditionally rather than conditionally like
# the original does, matching this phase's own scope, not a shortcut.
_ENGLISH_REPLY_HINT = "\n\n(The question above is written in English - reply in English.)"


def _retrieval_is_confident(top: list[dict]) -> bool:
    """Ported from this project's own session-added confidence gate (see
    backend/rag/helpers.py's retrieval_is_confident) - the #1-ranked chunk's
    score must clear the floor before a free-form answer is generated from
    it, so an out-of-corpus or garbled question gets an honest "not
    confident" reply instead of a fluent answer built on noise.
    """
    return bool(top) and top[0].get("score", 0) >= _settings.retrieval_confidence_floor


def _looks_like_eligibility_question(question: str) -> bool:
    """Narrow, deliberately simpler than backend/rag/guards.py's
    _looks_like_eligibility_question - no guided-interview follow-up yet,
    so this only needs to decide whether to ATTEMPT a verdict, not manage a
    multi-turn slot-filling conversation. Requires first-person language
    (the same describes_self signal the original uses) so a general "what
    is the eligibility criteria" question still falls through to RAG
    instead of being answered as a personal verdict with insufficient
    information.
    """
    low = question.lower()
    return eligibility.describes_self(question) and any(w in low for w in _ELIGIBILITY_HINT_WORDS)


def answer(project_id: str, question: str) -> dict:
    query_vector = embeddings.embed_query(question)
    top = store.search(project_id, query_vector, _settings.top_k, question)

    if not top:
        return {
            "answer": "There's no prospectus loaded for this programme yet, so I can't "
                      "answer specific questions until it is.",
            "source": "no-context", "model": "none", "pages": [],
        }

    if not _retrieval_is_confident(top):
        reply, model = llm.generate(
            prompts.SYSTEM_PROMPT_BASE.format(program=project_id) + llm.LANGUAGE_RULE,
            "The retrieved excerpts don't clearly cover what's being asked. State "
            "honestly and briefly that you're not confident you have the right "
            "information for this specific question, and suggest rephrasing or "
            "contacting admissions directly. Do not guess or invent a figure.\n\n"
            f"Question: {question}" + _ENGLISH_REPLY_HINT,
            question,
        )
        return {"answer": reply, "source": "low-confidence", "model": model, "pages": []}

    pages = sorted({e["page"] for e in top})

    # Eligibility verdict - checked before table lookup, same precedence as
    # the original (a personal verdict question should never fall through
    # to a generic table figure). Only acts on a determinable verdict;
    # "insufficient" falls through to general RAG rather than attempting
    # the guided interview this checkpoint doesn't have yet.
    if _looks_like_eligibility_question(question):
        result = eligibility.evaluate(project_id, question)
        if result["verdict"] in ("eligible", "not_eligible"):
            facts = _eligibility_facts_text(result) + _ENGLISH_REPLY_HINT
            reply, model = llm.generate(prompts.ELIGIBILITY_SYSTEM_PROMPT, facts, question)
            return {"answer": reply, "source": "eligibility", "model": model,
                    "pages": [result["page"]] if result.get("page") else pages}

    # Verified table lookup - code picks the number, the model only phrases it.
    verified = tablelookup.lookup(question, top)
    if verified:
        fact_prompt = (
            f"Verified fact (this is the complete answer - nothing else is in "
            f"scope): {verified['descriptor']}: {verified['value']}\n\n"
            f"Student's question (for tone only): {question}" + _ENGLISH_REPLY_HINT
        )
        reply, model = llm.generate(prompts.VERIFIED_FACT_SYSTEM, fact_prompt, question)
        if verified["value"] not in reply:
            reply = f"{verified['descriptor']}: {verified['value']}"
        return {"answer": reply, "source": "verified-fact", "model": model, "pages": pages}

    # General RAG.
    context = "\n\n".join(e["text"] for e in top)
    system_prompt = prompts.SYSTEM_PROMPT_BASE.format(program=project_id) + llm.LANGUAGE_RULE
    user_prompt = (
        f"Prospectus excerpts:\n{context}\n\nQuestion: {question}\n\n"
        "(Answer this fully yourself using the excerpts above - do not tell the "
        "student to go check a page number themselves.)" + _ENGLISH_REPLY_HINT
    )
    reply, model = llm.generate(system_prompt, user_prompt, question)
    return {"answer": reply, "source": "rag", "model": model, "pages": pages}


def _eligibility_facts_text(result: dict) -> str:
    """Facts written out for the model to phrase - same "verdict already
    decided, state it" shape as backend/rag/guards.py's _eligibility_facts,
    scoped down to the percentage-verdict case only (no entrance-exam or
    subjects reasons yet - those require the fuller guard logic this
    checkpoint hasn't ported).
    """
    verdict = "MEETS THE MARKS REQUIREMENT for" if result["verdict"] == "eligible" else "is NOT eligible for"
    lines = [
        f"VERDICT (already decided, state exactly this): the student {verdict} "
        f"{result['programme']} on the marks they gave.",
        f"Their stated marks in {result['required_subjects']}: {result['stated']}%.",
        f"The requirement for the {result['category']} category: {result['required']}%.",
    ]
    if result.get("category_assumed"):
        lines.append("They did not state a category, so this used the Unreserved requirement.")
    if result["verdict"] == "eligible" and result.get("entrance"):
        lines.append(f"Meeting the marks requirement is NOT the same as being admitted - "
                     f"they must also clear (not just appear for) {result['entrance']}.")
    if result["verdict"] == "eligible" and result.get("age_requirement"):
        lines.append(f"They must also meet the age requirement: {result['age_requirement']}.")
    lines.append("Lead with the verdict in the first sentence.")
    return "\n".join(lines)
