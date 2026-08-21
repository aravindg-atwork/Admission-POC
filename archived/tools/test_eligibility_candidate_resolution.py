"""Regression coverage for rag/guards.py's _eligibility_guard candidate
resolution on the `default` project - specifically the router-fallback
path, which has its OWN version of the "silently pick one programme when
several are named" bug already fixed once for the purely-deterministic
path (see detect_programs_multi's docstring in core/programs.py).

Found live 2026-08-19 testing the compound-question retrieval fix: "What
is the B.V.Sc. fee, and also am I eligible with 55% in PCM for B.F.Sc.,
and also is hostel compulsory?" names BOTH B.V.Sc. and B.F.Sc. explicitly
- detect_programs_multi correctly returns both, so the deterministic
`named` variable is correctly None - but the router classified
target_programs as the single-item ['bvsc'] anyway, and the OLD
`named or (routed[0] if len(routed) == 1 else None)` trusted that single
router guess unconditionally. The answer was a confident B.V.Sc. verdict
to a question that also asked about B.F.Sc., with B.F.Sc. dropped
entirely and never mentioned - the exact failure shape the original fix
was built to prevent, just reached via the router path instead of
detect_program's own first-match bias.

Fixed by only trusting a single-target router classification when the
student's OWN text names ZERO programmes (genuine ambiguity, the router
is the only signal) - not when it names two or more (a real multi-
programme question, which must fall through to _percentage_clarify_guard/
_comparison_guard exactly like the fully-deterministic case does).

Needs a constructed ctx (via rag.answer._build_context) with a simulated
ctx.route, not just backend.core functions in isolation - the bug is in
HOW guards.py combines the router's opinion with the deterministic
check, not in either building block by itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.answer import _build_context  # noqa: E402
from backend.rag import guards  # noqa: E402

CASES = [
    # (question, simulated router target_programs, expect the guard to fire)
    ("What is the B.V.Sc. fee, and also am I eligible with 55% in PCM for "
     "B.F.Sc., and also is hostel compulsory?", ["bvsc"], False),  # the reported bug
    ("Am I eligible for veterinary with 55% in PCB, unreserved, and I "
     "cleared NEET?", ["bvsc"], True),  # legitimate single-target fallback, must still work
]

results = []
for question, routed_targets, expect_fires in CASES:
    ctx = _build_context("default", question, "auto", "en")
    ctx.route = {"confidence": "high", "target_programs": routed_targets,
                 "intent": "admission_question"}
    result = guards._eligibility_guard(ctx)
    fired = result is not None
    ok = fired == expect_fires
    print(f"{'PASS' if ok else 'FAIL'}  {question[:60]!r}...: "
          f"routed={routed_targets} expected_fires={expect_fires} got_fires={fired}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} CANDIDATE-RESOLUTION CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
