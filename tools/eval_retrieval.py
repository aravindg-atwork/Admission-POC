"""Retrieval quality, measured on its own - before trusting any answer.

Why this is the first thing to build
------------------------------------
The 80-question evaluation on 2026-08-14 scored 55/80, and not one of the
failures was a retrieval failure: they were routing, verdict arithmetic, scope
collapse and latency. That is a claim about retrieval made entirely from the
outside, by reading answers - which is exactly the kind of claim that turns
out to be wrong later. Nothing here measured whether the right chunk was in
front of the model, only whether the sentence that came out was right.

Adding a reranker or a query rewriter without this number is guessing. If
recall@k is already ~1.0, a reranker cannot improve the answer and only adds
a model call to every question; if it is 0.6, reranking is the highest-value
work available. The point of this file is to find out which.

How the gold set is built (no hand labelling)
---------------------------------------------
Each case pairs a question with a string that is VERBATIM in the prospectus -
a threshold, a fee, a subject clause. Any chunk containing that string is gold
for that question. So the labels come from the corpus itself, not from
judgement and not from a previous answer of the assistant's.

That has a real limit worth stating: it measures whether retrieval finds the
chunk containing the ANSWER STRING, not whether a human would call the chunk
the best possible context. It cannot score questions whose answer is spread
across several chunks, or phrased differently from the source. Those are
listed as unscored rather than silently counted.

Metrics
-------
  recall@k   did any gold chunk make the top k the pipeline actually uses
  MRR        1/rank of the first gold chunk, 0 if absent - how close to the
             top it lands, which is what matters once a reranker exists
  rank       where the first gold chunk actually sat

Usage:
    .venv-backend/bin/python3 -u tools/eval_retrieval.py
    ... --k 12          override the top-k under test
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.generation import embeddings  # noqa: E402
from backend.rag.helpers import _build_retrieval_text  # noqa: E402
from backend.storage import projects, vectorstore  # noqa: E402

# (project, question, verbatim string from that project's prospectus)
# Every string below was read out of the PDF text, with the page noted where
# it was confirmed during the 2026-08-14/16 work.
CASES = [
    # --- eligibility thresholds (B.V.Sc. p4, B.F.Sc. p10, B.Tech p5)
    ("bvsc", "What percentage do I need in 12th to apply for B.V.Sc.?",
     "50% marks in Physics, Chemistry, Biology or Biotechnology and English"),
    ("bvsc", "What is the eligibility percentage for reserved candidates in B.V.Sc.?",
     "47.50% marks in case of Reserved category"),
    ("bvsc", "What percentage is required for SC/ST/OBC candidates?",
     "47.50% marks in case of Reserved category"),
    ("bfsc", "What is the minimum percentage required for B.F.Sc.?",
     "50% marks in Physics, Chemistry, Biology and English"),
    ("bfsc", "What do reserved category candidates need for B.F.Sc.?",
     "40% marks in case of Reserved category"),
    ("btech-dairy", "What is the eligibility for B.Tech. Dairy Technology?",
     "50% marks in Physics, Chemistry, Mathematics and English"),
    ("btech-dairy", "Is Mathematics compulsory for B.Tech. Dairy Technology?",
     "Physics, Chemistry, Mathematics and English"),

    # --- entrance exams
    ("bfsc", "What entrance exam is required for B.F.Sc.?", "MHT-C"),
    ("btech-dairy", "Which entrance exam is used for B.Tech. Dairy admission?", "MHT-C"),

    # --- the student-phrased forms of the same facts: this is where a
    #     query rewriter would earn its place, if anywhere
    ("bvsc", "I got 48% in PCB and English, am I eligible?",
     "47.50% marks in case of Reserved category"),
    ("bvsc", "how much marks do i need for vet course",
     "50% marks in Physics, Chemistry, Biology or Biotechnology and English"),
    ("btech-dairy", "can i do dairy tech with biology",
     "Physics, Chemistry, Mathematics and English"),

    # --- duration
    ("bfsc", "How long is the B.F.Sc. course?", "four-year course divided into eight semesters"),
    ("btech-dairy", "How long is the B.Tech. Dairy Technology course?", "4 years"),
]


def gold_indices(store, needle):
    """Every chunk whose text literally contains the verified string."""
    flat = needle.lower()
    return {i for i, entry in enumerate(store)
            if flat in (entry.get("text") or "").lower()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=config.TOP_K)
    args = ap.parse_args()

    stores = {}
    rows, unscored = [], []
    for project_id, question, needle in CASES:
        if project_id not in stores:
            stores[project_id] = vectorstore.load(projects.store_path(project_id))
        store = stores[project_id]
        gold = gold_indices(store, needle)
        if not gold:
            # The verified string is not present verbatim - almost always OCR
            # spacing or a line break inside it. Reported, never scored as a
            # miss: that would blame retrieval for the label being wrong.
            unscored.append((project_id, question, needle))
            continue

        # Mirror the pipeline exactly (see answer.py's retrieval block): the
        # vector comes from the question as typed, but the LEXICAL half gets
        # _build_retrieval_text, which appends formal-prospectus anchor words
        # for eligibility-style questions. The first version of this harness
        # passed the raw question as query_text and so measured a weaker
        # retrieval than the system actually performs - a measurement tool
        # that does not run the real path reports a number about nothing.
        vector = embeddings.embed([question])[0]
        retrieval_text = _build_retrieval_text(question, "latin", None, "en")
        hits = vectorstore.search(store, vector, top_k=args.k, query_text=retrieval_text)
        # Matched on CONTENT, not identity: search() deliberately returns
        # copies of the entries so a per-query score cannot leak into the
        # shared cached store, so `entry is hit` never matches and the first
        # version of this file reported a flat 0/14 - a harness bug that looked
        # exactly like catastrophic retrieval failure.
        flat = needle.lower()
        first = next((pos for pos, hit in enumerate(hits, start=1)
                      if flat in (hit.get("text") or "").lower()), 0)
        rows.append((project_id, question, len(gold), first))

    print(f"\n{'':4}{'project':13} {'rank':>5}  question")
    print("-" * 78)
    hit_count = 0
    mrr_total = 0.0
    for project_id, question, gold_n, first in rows:
        ok = first > 0
        hit_count += ok
        mrr_total += (1.0 / first) if ok else 0.0
        mark = f"#{first}" if ok else "MISS"
        print(f"  {'ok ' if ok else 'MISS'} {project_id:13} {mark:>5}  {question[:52]}")

    n = len(rows)
    if n:
        print("\n" + "=" * 78)
        print(f"recall@{args.k}: {hit_count}/{n} = {hit_count / n:.2f}     "
              f"MRR: {mrr_total / n:.3f}")
        print("\nHow to read this: recall near 1.00 means the answer chunk is already")
        print("being retrieved, so a reranker cannot improve correctness - it could")
        print("only reorder what is already there. A low MRR with high recall is the")
        print("case where reranking genuinely helps: right chunk found, buried.")
    if unscored:
        print(f"\nUNSCORED ({len(unscored)}) - verified string not found verbatim in any")
        print("chunk, so the label is wrong rather than retrieval being wrong:")
        for project_id, question, needle in unscored:
            print(f"  [{project_id}] {question[:46]}  needle={needle[:40]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
