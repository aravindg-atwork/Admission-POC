"""Regression coverage for rag/comparison.py's provenance-retry acceptance
check (_flagged_problems, used by _answer_comparison) - punch-list item
deferred earlier in the same session: a retry that objectively fixed the
reported problem was being rejected.

The bug: offenders/label_offenders are {pid: [numbers]} - the OLD code
compared `len(offenders)`, which counts programmes with at least one
problem, not the number of actual flagged figures. A programme with 3
unsourced numbers reduced to 1 by the retry read as "1" before and "1"
after ("no improvement"), so a genuinely-fixed provenance problem was
thrown away and the honest-fallback path fired instead of serving the
corrected answer.

Fixed by flattening to the actual SET of (kind, pid, number) problems and
requiring the after-set be a strict subset of the before-set. Pure logic,
no backend needed - this is the same reasoning tools/test_programme_typo_
tolerance.py uses for its own pure-function target.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.comparison import _flagged_problems  # noqa: E402

CASES = [
    # (label, before_offenders, before_labels, after_offenders, after_labels, expect_accept)
    ("the reported bug: 3 unsourced numbers in one programme reduced to 1",
     {"A": ["10", "20", "30"]}, {}, {"A": ["30"]}, {}, True),
    ("fully resolved, nothing left",
     {"A": ["10", "20"]}, {"B": ["5"]}, {}, {}, True),
    ("lateral trade: fixes A, introduces a new problem in B - must stay rejected",
     {"A": ["10"]}, {}, {"B": ["99"]}, {}, False),
    ("no change at all - must stay rejected",
     {"A": ["10"]}, {}, {"A": ["10"]}, {}, False),
    ("partial fix but a new unrelated problem also appears - must stay rejected",
     {"A": ["10", "20"]}, {}, {"A": ["20"], "C": ["77"]}, {}, False),
    ("mislabel-only problem resolved",
     {}, {"A": ["10"]}, {}, {}, True),
    ("fixes a borrowed figure by mislabelling a real one - not an improvement",
     {"A": ["10"]}, {}, {}, {"A": ["10"]}, False),
]

results = []
for label, before_o, before_l, after_o, after_l, expect in CASES:
    before = _flagged_problems(before_o, before_l)
    after = _flagged_problems(after_o, after_l)
    accepted = after < before
    ok = accepted == expect
    print(f"{'PASS' if ok else 'FAIL'}  {label}: expected accept={expect} got={accepted}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} COMPARISON-RETRY CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
