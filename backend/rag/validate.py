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

from ..prompts.system import _VALIDATE_SYSTEM
from ..storage import faq

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


def deterministic_checks(question, context_text, reply, own_project_id=None):
    """Zero-LLM-call checks. Returns a list of failure-reason strings (empty
    if the reply looks clean). `context_text` is whatever excerpts the
    reply was actually generated from - the same `context`/pooled section
    text already built in rag.py, not re-fetched here.

    `own_project_id`, if given, enables one more check: a single-programme
    answer that names a DIFFERENT programme the student never asked about.
    Optional (defaults to skipping that check) because comparison.py's
    multi-programme answers are SUPPOSED to name several programmes - this
    only makes sense on the single-project path, which is the only caller
    that passes it.
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

    # Found live 2026-08-17, right before a demo: "What is the eligibility
    # for B.V.Sc.?" asked directly on bvsc's own project reproducibly (4/4)
    # answered with a bizarre "this is not a B.Tech degree" tangent - "B.Tech"
    # appears NOWHERE in the retrieved context or the question, confirmed
    # directly, so this is the model spontaneously inventing a comparison,
    # not a retrieval leak. Reuses programs.detect_programs_multi (the same
    # alias matching every other programme-identity check in this codebase
    # already trusts) rather than a new keyword list.
    #
    # detect_programs_multi, not detect_program: the single-best-match
    # version returned "bvsc" here and only "bvsc" - the reply legitimately
    # names its OWN programme too ("You do not qualify for B.V.Sc. & A.H.
    # with a B.Tech degree"), which outranked the stray "B.Tech" mention and
    # hid it entirely. The multi-detector catches both names in the same
    # reply, which is exactly the signal: a reply is allowed to name its own
    # programme, but a SECOND, different one that the student's own question
    # never mentioned is never legitimate on this single-project path.
    if own_project_id:
        from ..core import programs
        reply_programmes = set(programs.detect_programs_multi(reply))
        question_programmes = set(programs.detect_programs_multi(question))
        # Excludes own_project_id (a reply is always allowed to name its own
        # programme) AND anything the question itself named (a student who
        # asks "how does bvsc compare to btech" invited that mention) -
        # first cut wrongly required the QUESTION to name zero programmes at
        # all, which broke on the very case this exists for: "What is the
        # eligibility for B.V.Sc.?" legitimately names bvsc in the question.
        foreign = reply_programmes - {own_project_id} - question_programmes
        if foreign:
            reasons.append(f"foreign_programme_mention: {', '.join(sorted(foreign))}")

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
    from .. import config
    from ..generation import llm

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
                          postprocess=None, own_project_id=None):
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

    `own_project_id` - see deterministic_checks's own docstring; forwarded
    through unchanged.
    """
    from .. import config
    from ..generation import llm

    reasons = deterministic_checks(question, context_text, reply, own_project_id)
    if not reasons:
        return reply, model, [], False

    # topic_mismatch alone does NOT buy an LLM call any more. Measured from
    # the review logs on 2026-08-14: it was the flag on 37 of 40 escalations
    # for `default`, 26 of 28 for bfsc, 16 of 17 for btech-dairy - and across
    # all three projects the escalation it paid for produced exactly one
    # regeneration each. So it was spending an LLM round trip on ~93% of
    # answers to confirm they were fine, which is where 40-390s response
    # times were going.
    #
    # It is a keyword-overlap heuristic (faq.answer_addresses_question) built
    # for matching cached questions, not for grading answers. A direct answer
    # shares FEWER words with its question than a padded one, so the work
    # making answers direct ("lead with the fact, no restating the question")
    # pushed this check's false-positive rate up rather than down.
    #
    # Still recorded in `reasons` so the review log keeps seeing it - it is
    # weak evidence, not no evidence, and it costs nothing to log.
    if all(r.startswith("topic_mismatch") for r in reasons):
        return reply, model, reasons, False

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
