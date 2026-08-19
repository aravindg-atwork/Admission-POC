"""Regression coverage for rag/comparison.py's compound-question retrieval
split (_split_compound_query/_retrieve_top_multi) - punch-list item #2
("compound/multi-part questions degrade through the comparison path"),
reported directly by the project owner and reproduced live 2026-08-19.

The bug: a compound question ("What is the B.V.Sc. fee, and also am I
eligible with 55% in PCM for B.F.Sc., and also is hostel compulsory?")
embedded as ONE blended query dilutes similarity for each sub-topic
individually - the B.V.Sc. fee chunk never surfaced at all under the
blended embedding, even though the identical fee question asked alone
retrieves it cleanly.

Fixed by splitting on the connective phrases a compound admission
question actually uses ("and also", "as well as"), embedding and
retrieving each sub-question separately, then merging round-robin so
every sub-topic gets representation rather than whichever one scores
highest overall crowding out the rest.

This file covers only the pure-logic split (_split_compound_query) - the
retrieval merge (_retrieve_top_multi) needs a real vector store and
embedding service and is exercised end-to-end via the live HTTP API
instead (see the deploy verification in git history around this file's
introduction).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.comparison import _split_compound_query  # noqa: E402

CASES = [
    # (text, expected number of parts)
    ("What is the B.V.Sc. fee, and also am I eligible with 55% in PCM for "
     "B.F.Sc., and also is hostel compulsory?", 3),
    ("What is the fee for B.V.Sc.?", 1),  # single question, unaffected
    ("compare B.V.Sc. and B.F.Sc. fees", 1),  # bare "and" must NOT split
    ("What documents are needed as well as what is the last date to apply?", 2),
    ("Which courses require NEET and which require MHT-CET?", 1),  # bare "and" again
]

results = []
for text, expected_count in CASES:
    parts = _split_compound_query(text)
    ok = len(parts) == expected_count
    print(f"{'PASS' if ok else 'FAIL'}  {text!r}: expected {expected_count} part(s), "
          f"got {len(parts)}: {parts}")
    results.append(ok)

print()
if all(results):
    print(f"ALL {len(results)} COMPOUND-QUERY SPLIT CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
