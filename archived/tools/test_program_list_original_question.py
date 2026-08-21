"""Regression coverage for rag/guards.py's _program_list_guard using
ctx.original_question instead of ctx.question - found 2026-08-19 while
investigating the "leading/false-premise question gets a generic
programme list" soft gap flagged in an earlier adversarial stress test.

The bug: _program_list_guard read ctx.question (the router's paraphrase,
via route["resolved_question"]) instead of ctx.original_question (what
the student actually typed) - the exact class of bug this project's own
CLAUDE.md already documents ("Programme detection must use
ctx.original_question, not ctx.question"), just never audited for in
this specific guard. "Since I'm clearly not eligible for B.V.Sc., what
other programme should I consider?" got paraphrased by the router into
something like "what other programmes are available", which drops the
word "eligible" the guard's own _LIST_ATTRIBUTE_WORDS exclusion depends
on to defer eligibility-shaped questions elsewhere - so the guard fired
with a generic programme-list menu, confidently sidestepping the
student's actual (unverified) eligibility claim.

Fixed: check original_question throughout (trigger words, attribute-word
exclusion, detect_program). A genuine "what programmes do you offer?"
must still fire - verified below.

Needs a constructed ctx (via rag.answer._build_context) with a simulated
ctx.route, not just backend.core functions in isolation - the bug is in
which TEXT the guard reads, which only differs from the truth once a
route with a resolved_question is present.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.answer import _build_context  # noqa: E402
from backend.rag import guards  # noqa: E402

_ROUTE_BASE = {
    "confidence": "high", "target_programs": [], "intent": "admission_question",
    "is_comparison": False, "unknown_programme": False,
    "needs_program_clarification": False, "self_score_ambiguous": False,
}

CASES = [
    # (project, original question, router's resolved_question paraphrase, expect the guard to fire)
    ("bvsc", "Since I'm clearly not eligible for B.V.Sc., what other programme "
     "should I consider?", "what other programmes are available", False),  # the reported bug
    ("default", "what all programmes do you offer?", "what programmes do you offer",
     True),  # genuine list question, must still work
]

results = []
for project_id, original, resolved, expect_fires in CASES:
    ctx = _build_context(project_id, original, "auto", "en")
    ctx.route = {**_ROUTE_BASE, "resolved_question": resolved}
    ctx.question = resolved
    result = guards._program_list_guard(ctx)
    fired = result is not None
    ok = fired == expect_fires
    print(f"{'PASS' if ok else 'FAIL'}  {original[:55]!r}...: "
          f"expected_fires={expect_fires} got_fires={fired}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} PROGRAM-LIST ORIGINAL-QUESTION CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
