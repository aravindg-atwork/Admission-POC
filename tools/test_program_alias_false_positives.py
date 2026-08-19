"""Regression coverage for core/programs.py's _NON_PROGRAMME_PHRASES -
punch-list item "B.Tech-Dairy tangent hallucination on bvsc's own
single-answer path", reproduced live 2026-08-19.

The bug: "dairy" is a deliberately bare alias for btech-dairy
(_PROGRAM_ALIASES), which made "Is an Indian Dairy Diploma equivalent to
12th standard?" - asked on the B.V.Sc.-SCOPED widget, about a real prior
vocational qualification named in bvsc's OWN prospectus - detect_program()
as naming a DIFFERENT programme (btech-dairy). _program_redirect_guard
(rag/guards.py) fires on ANY project when that happens, not just the
general `default` widget, so the student's own bvsc-scoped question was
silently answered from B.Tech (Dairy Technology)'s admission requirements
instead - a real answer, to the wrong programme, with nothing marking it
as a redirect the student would notice.

Pure logic, no backend needed - this is testing core/programs.py's
alias-matching decision itself, the same level test_programme_typo_
tolerance.py operates at.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import programs  # noqa: E402

CASES = [
    # (text, expected detect_programs_multi result)
    ("Is an Indian Dairy Diploma equivalent to 12th standard?", []),  # the reported bug
    ("is a dairy diploma the same as 12th pass", []),
    ("I have a Dairy Diploma, can I still apply?", []),
    ("what is the fee for B.Tech Dairy Technology", ["btech-dairy"]),  # real mention, unaffected
    ("what is the dairy technology admission process", ["btech-dairy"]),
    ("what is the fee for dairy", ["btech-dairy"]),  # bare "dairy" alone still works
]

results = []
for text, expected in CASES:
    got = programs.detect_programs_multi(text)
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  {text!r}: expected={expected} got={got}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} ALIAS FALSE-POSITIVE CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
