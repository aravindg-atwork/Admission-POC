"""Regression coverage for rag/guards.py's _subjective_comparison_guard -
soft gap found in a 2026-08-19 adversarial stress test: "Which programme
is easier to get into, B.V.Sc. or B.F.Sc.?" lost the question's intent
entirely and fell back to _program_list_guard's generic "we offer 3
programmes" menu (both guards share the same trigger words: a programme
noun + a question word, and _program_list_guard's own attribute-word
exclusion has no notion of "easier"/"better"/"harder").

Answered directly and deterministically (no LLM call, so no risk of
inventing a difficulty ranking the source can't support) rather than
deferred to _comparison_guard - _COMPARISON_SYSTEM_PROMPT's "give a
direct, complete verdict per program" instruction is written for
eligibility verdicts and has no safeguard against a subjective question
pulling it toward fabricating an opinion instead.

Needs a constructed ctx (via rag.answer._build_context), since the guard
reads ctx.original_question and programs.detect_programs_multi.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.answer import _build_context  # noqa: E402
from backend.rag import guards  # noqa: E402

CASES = [
    # (project, question, expect this guard to fire)
    ("default", "Which programme is easier to get into, B.V.Sc. or B.F.Sc.?", True),
    ("default", "which course is the best?", True),  # superlative + course noun
    ("default", "what all programmes do you offer?", False),  # genuine list question, unaffected
    ("bvsc", "Is 55% better than 50% for eligibility?", False),  # 'better' with no programme context
    ("bvsc", "What is the fee for B.V.Sc.?", False),  # ordinary question, unaffected
]

results = []
for project_id, question, expect_fires in CASES:
    ctx = _build_context(project_id, question, "auto", "en")
    result = guards._subjective_comparison_guard(ctx)
    fired = result is not None
    ok = fired == expect_fires
    print(f"{'PASS' if ok else 'FAIL'}  {question!r}: expected_fires={expect_fires} got_fires={fired}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} SUBJECTIVE-COMPARISON GUARD CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
