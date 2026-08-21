"""B.V.Sc. retrieval checkpoint using the legacy suite's verified needles."""

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "services" / "api"
sys.path.insert(0, str(API_ROOT))

from app.providers.embeddings import embed  # noqa: E402
from app.agent.answer import _retrieval_text  # noqa: E402
from app.retrieval import store  # noqa: E402
from app.settings import get_settings  # noqa: E402


# Exact B.V.Sc. subset of ../../tools/eval_retrieval.py.
CASES = [
    ("What percentage do I need in 12th to apply for B.V.Sc.?", "50% marks in Physics, Chemistry, Biology or Biotechnology and English"),
    ("What is the eligibility percentage for reserved candidates in B.V.Sc.?", "47.50% marks in case of Reserved category"),
    ("What percentage is required for SC/ST/OBC candidates?", "47.50% marks in case of Reserved category"),
    ("I got 48% in PCB and English, am I eligible?", "47.50% marks in case of Reserved category"),
    ("how much marks do i need for vet course", "50% marks in Physics, Chemistry, Biology or Biotechnology and English"),
    ("What is the application fee for B.V.Sc. unreserved candidates?", "for Unreserved candidate is Rs.1000/- and for Reserved candidate is Rs.700/-"),
    ("What is the grievance application fee for B.V.Sc.?", "grievance application fees"),
    ("Is the B.V.Sc. NRI quota special fee refundable?", "special fee paid by the candidate shall not be refunded in any case"),
    ("If I cancel my B.V.Sc. admission more than 30 days after the last date, do I get a refund?", "More than 30 days"),
    ("What documents are needed to claim caste reservation for B.V.Sc.?", "Caste Validity Certificate (CVC)"),
    ("What is the domicile certificate requirement for B.V.Sc.?", "minimum 3 years stay in preceding 10 years in Maharashtra State"),
    ("Is hostel accommodation guaranteed for B.V.Sc. students?", "Hostel accommodation for a limited number of stu"),
    ("What percentage of seats does SC reservation get for B.V.Sc.?", "13.0"),
]


def _all_payloads() -> list[dict]:
    client = store.get_client()
    payloads, offset = [], None
    while True:
        points, offset = client.scroll("bvsc", limit=256, offset=offset, with_payload=True, with_vectors=False)
        payloads.extend(point.payload or {} for point in points)
        if offset is None:
            return payloads


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=get_settings().top_k)
    parser.add_argument("--candidate-multiplier", type=int)
    args = parser.parse_args()
    if args.candidate_multiplier:
        store._CANDIDATE_MULTIPLIER = args.candidate_multiplier
    corpus = _all_payloads()
    rows, unscored = [], []
    for question, needle in CASES:
        if not any(needle.lower() in (item.get("text") or "").lower() for item in corpus):
            unscored.append((question, needle))
            continue
        vector = embed([question])[0]
        hits = store.search("bvsc", vector, args.k, query_text=_retrieval_text(question))
        first = next(
            (rank for rank, hit in enumerate(hits, 1) if needle.lower() in (hit.get("text") or "").lower()), 0
        )
        rows.append((question, first))

    hits = sum(first > 0 for _, first in rows)
    mrr = sum(1 / first for _, first in rows if first) / max(len(rows), 1)
    for question, first in rows:
        print(f"  {'ok  ' if first else 'MISS'} {('#' + str(first)) if first else 'MISS':>5}  {question[:60]}")
    print("\n" + "=" * 78)
    print(f"recall@{args.k}: {hits}/{len(rows)} = {hits / max(len(rows), 1):.2f}     MRR: {mrr:.3f}")
    if unscored:
        print(f"\nUNSCORED ({len(unscored)}) - needle absent from the freshly ingested corpus:")
        for question, needle in unscored:
            print(f"  {question[:52]}  needle={needle[:42]!r}")
    return 1 if hits != len(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
