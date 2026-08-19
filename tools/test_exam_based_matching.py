"""Regression coverage for core/eligibility.py's exam-based "which
programme am I eligible for" matching - reported live 2026-08-19: "if i
have passed [exam] exam what course im eligiblie for?" named no subjects
and no programme, so it fell all the way through the eligibility guard to
clarify-program asking "which programme are you asking about?" - a strange
question when the student had just told us their entrance exam, the one
thing that actually narrows it.

Mirrors the existing subjects-based "which courses can I apply for"
feature (eligibility.eligible_programmes/is_which_programmes_question) on
a different axis: NEET admits to bvsc only, CET/MHT-CET admits to bfsc and
btech-dairy.

Deliberately NOT typo-tolerant on the exam name itself (see
eligibility._EXAM_NAME_RE's docstring) - "neet"/"cet" are short enough
that their edit-distance-1 neighbours are common real words ("meet",
"feet", "get", "vet"...), so a garbled name like the literal reported
"quet" stays unrecognised on purpose and falls back to the pre-existing
clarify-program behaviour, unchanged.

Pure logic, no backend needed - the same level test_programme_typo_
tolerance.py operates at.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import eligibility  # noqa: E402

CASES = [
    # (text, expect is_which_programmes_by_exam_question, expected programme matches)
    ("I passed NEET, which course am I eligible for?", True, ["bvsc"]),
    ("I have cleared MHT-CET, which programmes can I apply to?", True, ["bfsc", "btech-dairy"]),
    ("I appeared for CET, what courses am I eligible for?", True, ["bfsc", "btech-dairy"]),
    # the literal reported phrasing - exam unrecognised, no match, but the
    # QUESTION SHAPE itself is still detected (falls through cleanly rather
    # than crashing or mis-triggering something else)
    ("if i have passed quet exam what course im eligiblie for?", True, []),
    # must not fire on a general rule question, not a personal claim
    ("do I need to appear for MHT-CET?", False, []),
    ("what is the eligibility criteria for B.V.Sc.?", False, []),
    # must not fire without the "which course/programme" question shape
    ("I passed NEET last year.", False, []),
]

results = []
for text, expect_is_q, expect_matches in CASES:
    is_q = eligibility.is_which_programmes_by_exam_question(text)
    ok = is_q == expect_is_q
    print(f"{'PASS' if ok else 'FAIL'}  is_which_programmes_by_exam_question({text!r}): "
          f"expected={expect_is_q} got={is_q}")
    results.append(ok)
    if is_q:
        keys = eligibility.named_entrance_keys(text)
        matches = sorted({pid for k in keys for pid in eligibility.eligible_programmes_by_exam(k)})
        ok2 = matches == expect_matches
        print(f"{'PASS' if ok2 else 'FAIL'}    -> matches: expected={expect_matches} got={matches}")
        results.append(ok2)

print()
if all(results):
    print(f"ALL {len(results)} EXAM-BASED MATCHING CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
