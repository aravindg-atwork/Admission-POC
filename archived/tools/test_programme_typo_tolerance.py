"""Regression coverage for core/programs.py's single-edit typo tolerance on
the three core programme abbreviations (bvsc/bfsc/btech) - added 2026-08-18,
punch-list item deferred earlier in the same session over a real risk:
"bvsc" and "bfsc" are mutually edit-distance-1 of EACH OTHER, so a naive
per-abbreviation fuzzy match would let a typo of one programme's name
"correct" into a DIFFERENT, wrong programme. See
core/programs.py's _typo_matched_projects docstring for the fix (require a
UNIQUE nearest abbreviation) and _TYPO_EXCLUDED_WORDS for the other real
failure mode found while building this (the common word "tech" sits
edit-distance-1 from "btech").

Pure logic, no backend needed - unlike this project's other test_*.py
scripts, which all exercise the live HTTP API. Fast to run and the right
level: this is testing core/programs.py's matching decision itself, not
how a guard consumes it (test_conversation_flows.py already covers the
eligibility-interview round trip end to end).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import programs  # noqa: E402

CASES = [
    # (text, expected detect_programs_multi result)
    ("am i eligible for bfsv", ["bfsc"]),                       # substitution typo
    ("am i eligible for bvcs", ["bvsc"]),                        # adjacent transposition
    ("what is the btch fee", ["btech-dairy"]),                   # deletion typo
    ("what is the fee for bfsc", ["bfsc"]),                      # exact match still works
    ("is bvsc or bfsc better", ["bvsc", "bfsc"]),                # exact, both, unaffected
    ("fee for bfsc and bvsx", ["bfsc", "bvsc"]),                 # one exact + one typo, mixed
    ("what is the eligibility for b.tech. dairy technology", ["btech-dairy"]),  # "tech" must not misfire
    ("what is the daily fee schedule", []),                      # "daily" must not fuzz-match "dairy"
    ("what is the fee", []),                                     # no programme named at all
    ("does bfsc need neet", ["bfsc"]),                           # unrelated short words nearby don't leak in
]

results = []
for text, expected in CASES:
    got = programs.detect_programs_multi(text)
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  {text!r}: expected={expected} got={got}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} TYPO-TOLERANCE CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
