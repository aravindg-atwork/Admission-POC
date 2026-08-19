"""Regression coverage for core/eligibility.py's missing_entrance_exam
double-negation handling - found in an adversarial stress test 2026-08-19:
"It is not true that I haven't passed NEET" (a double negative - the
student HAS passed) matched _NOT_APPEARED_RE on "haven't passed NEET" and
told the student the exact opposite of the truth: "you did not appear for
NEET-UG-2026", which fed straight into a wrong "not eligible" verdict.

Genuine double-negation parsing is not something a regex can do reliably.
_DOUBLE_NEGATION_FRAME_RE does not attempt to flip the match back to a
positive claim (asserting "the student HAS passed" from a double negative
is exactly as risky a guess as the bug being fixed) - it recognises the
common outer-negation framings that flip an inner negation's meaning and
treats the exam status as UNKNOWN rather than confidently asserting either
way, the same "don't guess when ambiguous" discipline the rest of the
eligibility engine already follows.

Pure logic, no backend needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import eligibility  # noqa: E402

CASES = [
    # (project_id, text, expected missing_entrance_exam result)
    ("bvsc", "It is not true that I haven't passed NEET. Am I eligible for B.V.Sc. with 55%?",
     None),  # the reported bug: double negation must not assert "missing"
    ("bvsc", "It's false that I haven't passed NEET, so am I eligible?",
     None),  # a second outer-negation framing (subordinating "that")
    ("bvsc", "I haven't passed NEET, am I eligible for B.V.Sc.?",
     "NEET-UG-2026"),  # genuine single negation - must still work
    ("bfsc", "I did not appear for MHT-CET, can I still get into B.F.Sc.?",
     "MHT-CET 2026"),  # genuine single negation, different exam/programme
    ("bvsc", "Is there an exemption if I haven't passed NEET?",
     None),  # pre-existing exemption exclusion, must not regress
]

results = []
for pid, text, expected in CASES:
    got = eligibility.missing_entrance_exam(pid, text)
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  missing_entrance_exam({pid!r}, {text!r}): "
          f"expected={expected!r} got={got!r}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} DOUBLE-NEGATION CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
