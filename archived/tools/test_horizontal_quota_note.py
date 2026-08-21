"""Regression coverage for rag/guards.py's _threshold_facts PWD/horizontal-
quota clarification - punch-list soft gap found in a 2026-08-19
adversarial stress test: "I am OBC and also PWD and also from EWS. What
percentage do I need for B.V.Sc.?" got a technically-correct but shallow
answer (just the reserved-category percentage) that never explained PWD
is a SEPARATE 5%-of-intake seat quota (verified: "5% of total intake
capacity seats are reserved for Physically Handicapped candidate"), not
a different marks percentage.

Deliberately narrow to PWD only - EWS's own marks-threshold classification
(does it use the reserved 47.5% or unreserved 50% figure?) was
investigated and left UNRESOLVED on purpose: the corpus lists EWS
alongside SC/ST/OBC in the SEAT reservation table but that does not by
itself confirm it also shares their MARKS threshold, and this codebase's
standing rule is never to state a number the source does not explicitly
support. See CLAUDE.md's Open section for this as its own, separate,
not-yet-investigated finding.

Pure logic, no backend needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag import guards  # noqa: E402
from backend.core import eligibility  # noqa: E402

rows = eligibility.thresholds_for("what percentage do I need", "bvsc")

CASES = [
    ("I am OBC and also PWD and also from EWS. What percentage do I need "
     "for B.V.Sc.?", True),
    ("What percentage do I need for physically handicapped category?", True),
    ("What percentage do I need for reserved category B.V.Sc.?", False),
    ("What is the eligibility percentage for B.V.Sc.?", False),
]

results = []
for original, expect_note in CASES:
    facts = guards._threshold_facts(rows, original)
    has_note = "Physically Handicapped (PWD)" in facts
    ok = has_note == expect_note
    print(f"{'PASS' if ok else 'FAIL'}  {original!r}: expected_note={expect_note} got_note={has_note}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} HORIZONTAL-QUOTA NOTE CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
