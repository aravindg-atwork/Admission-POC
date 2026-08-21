"""Regression coverage for core/eligibility.py's raw-marks-fraction
conversion ("300 out of 500", "300/500") - found in an adversarial stress
test 2026-08-19: "I scored 300 out of 500 in Physics, Chemistry, Biology
and English combined, unreserved category. Am I eligible for B.V.Sc.?"
was answered by asking "have you appeared for NEET-UG-2026?" - extract()
found no percentage at all (there wasn't one stated as a percentage - only
a raw fraction), so the guard fell into the guided interview instead of
recognising 300/500 = 60% and giving a real verdict.

_MARKS_OUT_OF_RE converts a stated fraction into the same value space
_PERCENT_RE already produces, then runs through the IDENTICAL subject/
overall cue-scoping - protected against false positives (dates, unrelated
fractions like document counts) by that same existing cue requirement: a
fraction with no subject/overall word nearby stays correctly unassigned,
exactly like a bare unscoped percentage already does.

Pure logic, no backend needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import eligibility  # noqa: E402

CASES = [
    # (text, key, expected value)
    ("I scored 300 out of 500 in Physics, Chemistry, Biology and English combined.",
     "subject_percent", 60.0),  # the reported bug
    ("I scored 250/500 in PCB and English", "subject_percent", 50.0),  # slash form
    ("I got 51% overall but only 45% in PCB and English", "overall_percent", 51.0),  # Q25 regression
    ("I got 51% overall but only 45% in PCB and English", "subject_percent", 45.0),  # same case, other key
    # false-positive guards: no subject/overall cue nearby -> must stay unassigned
    ("What is the deadline, is it 15/08/2026?", "subject_percent", None),
    ("I have 2 out of 3 required documents ready, what percentage do I need?",
     "subject_percent", None),
    ("my DOB is 01/04/2010, am I eligible age-wise?", "subject_percent", None),
]

results = []
for text, key, expected in CASES:
    got = eligibility.extract(text)[key]
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  extract({text!r})[{key!r}]: expected={expected} got={got}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} RAW-MARKS CONVERSION CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
