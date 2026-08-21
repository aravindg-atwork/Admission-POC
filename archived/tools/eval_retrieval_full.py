"""Phase 4/5 of the RAG audit: a structured golden retrieval dataset built
from tools/eval_admissions.py's 75 questions, and Recall@1/3/5/10 + MRR +
Hit Rate measured against it. Retrieval only - no LLM calls, no cost.

Companion to eval_retrieval.py, not a replacement: that file's 14 cases pair
a question with one hand-verified verbatim phrase, which is the highest-
confidence gold label this project has. This file scales the SAME idea to
every question eval_admissions.py already has ground-truthed figures for,
by automating gold-chunk derivation instead of hand-picking a phrase per
question - the tradeoff is weaker precision per label (see _gold_indices),
which is why every case is written to the report as either SCORED or
EXCLUDED with a stated reason, never guessed.

How gold is derived automatically
----------------------------------
A case's `expect` list is figures/keywords already verified against the PDFs
by eval_admissions.py's own author (see that file's docstring: "Ground truth
comes from the prospectus PDFs, with page numbers"). A chunk is gold for a
question if it contains EVERY expect term - AND, not OR, because a single
short term ("50", "NEET") appears in dozens of unrelated chunks, but the
conjunction of two or more narrows to the chunk that actually states the
fact. Cases with fewer than 2 usable expect terms, or with expect=[] (only
`answered=True`/`refuse=True` behavioural cases), cannot be scored this way
and are excluded, not guessed at.

What's excluded, and why that's honest rather than lazy
---------------------------------------------------------
- refuse=True (Section G, retired PG programmes): correct behaviour is
  refusing to search at all, not retrieving a chunk - there is no gold
  chunk to find, by design.
- Questions naming no programme and not resolvable via
  programs.detect_program (general/comparison questions, e.g. "what is the
  difference between B.V.Sc. and B.F.Sc. admission"): these route to
  MULTIPLE stores or the comparison path in production, not one project's
  single-store retrieval, so scoring them against one store would not
  measure what actually happens.
- expect=[] or fewer than 2 usable terms: no reliable AND-conjunction gold
  label available.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.core import programs  # noqa: E402
from backend.generation import embeddings  # noqa: E402
from backend.rag.helpers import _build_retrieval_text  # noqa: E402
from backend.storage import projects, vectorstore  # noqa: E402

from eval_admissions import CASES  # noqa: E402

_MIN_TERM_LEN = 2


def _usable_terms(expect):
    return [t for t in expect if len(t.strip()) >= _MIN_TERM_LEN]


def _gold_indices(store, terms):
    lowered = [t.lower() for t in terms]
    gold = set()
    for i, entry in enumerate(store):
        text = (entry.get("text") or "").lower()
        if all(t in text for t in lowered):
            gold.add(i)
    return gold


def _resolve_project(case):
    if case.get("refuse"):
        return None, "refuse=True - retired programme, no gold chunk to retrieve"
    pid = programs.detect_program(case["q"])
    if pid is None or pid not in programs.PROGRAM_NAMES:
        return None, "no single programme named/detected - routes to multi-store/comparison path"
    return pid, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10, help="max k to report (also computes 1/3/5)")
    args = ap.parse_args()

    stores = {}
    scored, excluded = [], []

    for case in CASES:
        terms = _usable_terms(case.get("expect") or [])
        pid, why = _resolve_project(case)
        if pid is None:
            excluded.append((case, why))
            continue
        if len(terms) < 2:
            excluded.append((case, f"only {len(terms)} usable expect term(s) - "
                                    "not enough to AND-conjunct a reliable gold label"))
            continue

        if pid not in stores:
            stores[pid] = vectorstore.load(projects.store_path(pid))
        store = stores[pid]
        gold = _gold_indices(store, terms)
        if not gold:
            excluded.append((case, f"expect terms {terms} never co-occur in one chunk of "
                                    f"{pid}'s corpus - label unverifiable, not a retrieval miss"))
            continue

        vector = embeddings.embed([case["q"]])[0]
        retrieval_text = _build_retrieval_text(case["q"], "latin", None, "en")
        hits = vectorstore.search(store, vector, top_k=max(args.k, 10), query_text=retrieval_text)
        lowered = [t.lower() for t in terms]
        first = next((pos for pos, hit in enumerate(hits, start=1)
                      if all(t in (hit.get("text") or "").lower() for t in lowered)), 0)
        scored.append({"section": case["section"], "n": case["n"], "q": case["q"],
                        "project": pid, "terms": terms, "gold_n": len(gold), "rank": first})

    n = len(scored)
    print(f"Golden retrieval set: {n} scored, {len(excluded)} excluded (see below)\n")

    ks = sorted({1, 3, 5, min(args.k, 10)})
    print(f"{'':4}{'#':<5}{'project':13}{'rank':>6}  question")
    print("-" * 82)
    for row in scored:
        mark = f"#{row['rank']}" if row["rank"] else "MISS"
        ok = row["rank"] > 0
        print(f"  {'ok ' if ok else 'MISS'} Q{row['n']:<4}{row['project']:13}{mark:>6}  {row['q'][:48]}")

    print("\n" + "=" * 82)
    print(f"RETRIEVAL METRICS (n={n})")
    for k in ks:
        hits_at_k = sum(1 for r in scored if 0 < r["rank"] <= k)
        print(f"  Recall@{k:<2} = Hit Rate@{k:<2} : {hits_at_k}/{n} = {hits_at_k / n:.3f}" if n else "n/a")
    mrr = sum((1.0 / r["rank"]) for r in scored if r["rank"] > 0) / n if n else 0.0
    print(f"  MRR              : {mrr:.3f}")

    if excluded:
        print(f"\nEXCLUDED ({len(excluded)}) - not scored, reason stated (never guessed):")
        for case, why in excluded:
            print(f"  [{case['section']}] Q{case['n']:<3} {case['q'][:46]:48} {why}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
