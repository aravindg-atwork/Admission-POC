"""Post-generation review of a draft answer - deterministic checks first
(free, always run), a bounded LLM check second (rare, Hetzner-only, at most
one call), and at most one regeneration retry. Never a loop - see rag.py's
call sites and config.VALIDATION_MAX_ROUNDS's own comment for why an
unbounded "validate until perfect" loop was deliberately rejected.

Leaf module: imports only config, llm, faq, textclean - never rag or
orchestrator, so the import graph stays acyclic (rag.py imports this, not
the reverse).

Every check here reuses a mechanism that already exists elsewhere in this
codebase for a related reason, rather than inventing new logic:
unsupported_number leans on the same "a number in the answer must be
grounded in the excerpts" bar tablelookup.py and the NRI-scope guardrail
already enforce; topic_mismatch reuses faq.answer_addresses_question, which
shares its discriminator vocabulary with faq.compatible_questions (the same
one already guarding the FAQ cache and the table-lookup veto) but compares
a question against an ANSWER rather than another question - see that
function's docstring for why compatible_questions itself isn't reusable
as-is here (a correct answer legitimately contains new numbers, the result
figure, that compatible_questions's exact-equality rule would wrongly flag).
"""

import re

from . import faq

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*%?")
# Numbers under 2 digits are mostly ordinals/counts ("3 rounds", "1st year")
# that recur naturally in phrasing without being drawn from a specific
# excerpt figure - only longer numbers (fee amounts, percentages, dates)
# are worth grounding-checking; a 1-2 digit number false-positiving here
# would flag almost every answer.
_MIN_NUMBER_LEN = 2

# clean_for_display (textclean.py) already strips *_`# markup and leading
# -/bullet dashes before a reply ever reaches this module - this catches
# the one common leak it doesn't: a numbered list ("1. ", "2) ") at a line
# start, which reads fine as text but violates SYSTEM_PROMPT_BASE's "never
# use markdown, weave items into a natural sentence" rule just as much.
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)


def _extract_numbers(text):
    return {n.replace(",", "").rstrip("%").strip() for n in _NUMBER_RE.findall(text)
            if len(n.replace(",", "").rstrip("%").strip()) >= _MIN_NUMBER_LEN}


def deterministic_checks(question, context_text, reply):
    """Zero-LLM-call checks. Returns a list of failure-reason strings (empty
    if the reply looks clean). `context_text` is whatever excerpts the
    reply was actually generated from - the same `context`/pooled section
    text already built in rag.py, not re-fetched here.
    """
    reasons = []

    reply_numbers = _extract_numbers(reply)
    context_numbers = _extract_numbers(context_text)
    unsupported = reply_numbers - context_numbers
    if unsupported:
        # Sorted for a stable, readable reason string - this feeds
        # reviewlog entries and (if escalated) the LLM check's prompt.
        reasons.append(f"unsupported_number: {', '.join(sorted(unsupported))}")

    if not faq.answer_addresses_question(question, reply):
        reasons.append("topic_mismatch")

    return reasons


def autofix(reply):
    """Mechanically strips a numbered-list pattern the model may have used
    despite the system prompt's "no markdown, weave into a sentence" rule.
    A fix, not a regenerate-worthy failure - matches this codebase's
    standing preference (see rag._compact_readings, textclean.py) for a
    deterministic repair over spending a call when the fix is unambiguous.
    Never escalates markdown_leak to the LLM check.
    """
    return _NUMBERED_LIST_RE.sub("", reply)


_VALIDATE_SYSTEM = (
    "You are checking a draft answer against the prospectus excerpts it was "
    "generated from, for a university admissions chatbot. You are NOT "
    "answering the question yourself - only judging the draft.\n\n"
    "Reply with exactly one line: either the single word PASS, or FAIL "
    "followed by a colon and a short reason (under 15 words).\n\n"
    "FAIL only for a real problem: a number, date, or requirement stated in "
    "the draft that is NOT actually supported by the excerpts, or the draft "
    "answering a different question than the one asked (e.g. a different "
    "year/category/program than what was asked about). Do NOT fail the "
    "draft for tone, phrasing, brevity, or anything already correct - a "
    "correct answer written differently than you would have written it is "
    "still PASS."
)


def llm_check(question, context_text, reply):
    """ONE bounded llm.generate_scoped(config.ORCHESTRATOR_PROVIDER, ...)
    call. Returns (passed: bool, reason: str|None). ANY failure of the call
    itself (unconfigured, timeout, unparseable output) returns (True, None)
    - a broken validator degrades to "serve the draft as before", never to
    withholding or delaying a good-faith answer.

    Imports llm/config lazily (function-local) to avoid a module-level
    circular import risk, since llm.py itself is imported by many other
    leaf modules already - keeps this file safe to import from anywhere.
    """
    from . import config, llm

    if not config.VALIDATION_LLM_CHECK_ENABLED:
        return True, None

    prompt = (
        f"Prospectus excerpts:\n{context_text}\n\n"
        f"Question: {question}\n\n"
        f"Draft answer: {reply}"
    )
    result = llm.generate_scoped(config.ORCHESTRATOR_PROVIDER, _VALIDATE_SYSTEM, prompt,
                                  question, timeout=config.VALIDATION_TIMEOUT)
    if result is None:
        return True, None
    text, _ = result
    text = text.strip()
    if text.upper().startswith("PASS"):
        return True, None
    if text.upper().startswith("FAIL"):
        reason = text.split(":", 1)[1].strip() if ":" in text else "unspecified"
        return False, reason
    # Unparseable output (neither PASS nor FAIL) - same safe-degrade rule
    # as a call failure: don't block a good-faith answer over a validator
    # that didn't follow its own instructions.
    return True, None


def check_and_regenerate(question, context_text, reply, model, system_prompt, user_prompt,
                          postprocess=None):
    """The full bounded pipeline in one call, so rag.py's hook stays a
    one-liner: deterministic checks -> (only if flagged) one LLM check ->
    (only if that fails) one regeneration attempt. Never a loop - see the
    module docstring.

    Returns (final_reply, final_model, flagged_reasons, regenerated: bool).
    `flagged_reasons` is always the ORIGINAL draft's deterministic-check
    result, even when a regeneration happened - callers use it to decide
    what to log, independent of whether serving actually changed.

    `postprocess`, if given, is applied to a regenerated reply the same way
    the caller already applied it to the first draft (e.g. rag.py's
    _add_nri_scope_caveat) - keeps a regenerated reply held to the exact
    same safety nets as the original, without this leaf module needing to
    import rag.py's private helpers.
    """
    from . import config, llm

    reasons = deterministic_checks(question, context_text, reply)
    if not reasons:
        return reply, model, [], False

    passed, why = llm_check(question, context_text, reply)
    if passed:
        return reply, model, reasons, False

    retry_prompt = user_prompt + (
        f"\n\n(A previous draft failed review: {why}. Fix specifically that "
        "problem; change nothing else.)"
    )
    retry_result = llm.generate_scoped(config.ORCHESTRATOR_PROVIDER, system_prompt, retry_prompt,
                                        question, timeout=config.VALIDATION_TIMEOUT)
    if retry_result is None:
        return reply, model, reasons, False

    new_reply, new_model = retry_result
    new_reply = autofix(new_reply)
    if postprocess:
        new_reply = postprocess(new_reply)
    return new_reply, new_model, reasons, True
