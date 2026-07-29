"""Compare fixed-K retrieval against a relevance-threshold ("nucleus") cutoff.

Fixed K always returns exactly K chunks, whatever their quality. That is wasteful
in both directions: an easy question whose answer sits in one chunk still drags 9
irrelevant ones into the prompt, and a hard question spread across several pages
is capped at K even when the 11th chunk was clearly relevant. The analogue of
nucleus sampling is to keep chunks while they remain close to the best match, and
stop when quality falls off - a variable number per question.

Measured here rather than argued, because the trade is real: a threshold that is
too tight starves hard questions (the failure mode is a false "the prospectus
doesn't specify"), and one too loose reintroduces the prompt noise that fixed K
was capping.

Two metrics, because recall alone would trivially favour "return everything":
  RECALL   did the gold page make the cut (higher is better)
  CHUNKS   mean chunks sent to the model (lower is better - less prompt noise,
           fewer reasoning tokens burned before the answer starts, and Sarvam's
           4096 budget is a reasoning budget, not an answer budget)

Translations are computed ONCE and reused across every configuration, so the
comparison isolates the retrieval policy instead of also measuring the local
translator's run-to-run drift. Costs no cloud calls.

Usage:
  python tools/sweep_retrieval_topk.py
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from backend import config, embeddings, glossary, llm, projects, vectorstore  # noqa: E402
from test_retrieval_hi_mr import PROBES  # noqa: E402

# Relative to the best-scoring chunk: keep everything scoring at least this
# fraction of the top hit. Relative rather than absolute because raw cosine
# varies a lot between question types - an absolute cutoff tuned on fee
# questions starves date questions, whose whole-table chunks score lower across
# the board.
RATIOS = [0.80, 0.85, 0.90, 0.95]
FIXED_K = [6, 8, 10, 12]
HARD_CAP = 14  # never send more than this, whatever the threshold allows


def scored(store, query_vector, query_text):
    """Every chunk with its hybrid score, best first - the ranking search() uses
    internally, exposed so a threshold can be applied to the scores themselves.
    """
    qnorm = vectorstore._norm(query_vector)
    terms = vectorstore._terms(query_text) if query_text else set()
    out = []
    for entry in store:
        enorm = entry.get("_norm") or vectorstore._norm(entry["vector"])
        if not enorm or not qnorm:
            continue
        cosine = sum(x * y for x, y in zip(query_vector, entry["vector"])) / (qnorm * enorm)
        score = cosine
        if terms:
            score += vectorstore._KEYWORD_WEIGHT * vectorstore._keyword_score(
                terms, entry.get("_terms") or vectorstore._terms(entry.get("text", "")))
        out.append((score, entry))
    out.sort(key=lambda s: s[0], reverse=True)
    return out


def by_threshold(ranked, ratio):
    if not ranked:
        return []
    floor = ranked[0][0] * ratio
    kept = [e for s, e in ranked if s >= floor]
    return kept[:HARD_CAP]


def main():
    store = vectorstore.load(projects.store_path(config.DEFAULT_PROJECT_ID))
    if not store:
        print("FATAL: no vector store - ingest a prospectus first.")
        return 1

    print(f"preparing {len(PROBES)} probes (translating once, reused for every config)...")
    prepared = []
    for pid, lang, question, gold, _expected in PROBES:
        english = llm.translate_to_english(question, lang)
        text = " ".join(filter(None, [english, glossary.english_terms(question)]))
        prepared.append((lang, gold, embeddings.embed([english])[0], text))

    print()
    print(f"{'config':<16}{'hi recall':>12}{'mr recall':>12}{'ALL recall':>12}{'mean chunks':>14}")
    print("-" * 66)

    def report(label, picker):
        hits = {"hi": [0, 0], "mr": [0, 0]}
        total_chunks = 0
        for lang, gold, vector, text in prepared:
            ranked = scored(store, vector, text)
            kept = picker(ranked)
            total_chunks += len(kept)
            pages = {e["page"] for e in kept}
            hits[lang][0] += bool(gold & pages)
            hits[lang][1] += 1
        h, m = hits["hi"], hits["mr"]
        allh, alln = h[0] + m[0], h[1] + m[1]
        print(f"{label:<16}{100*h[0]/h[1]:>11.1f}%{100*m[0]/m[1]:>11.1f}%"
              f"{100*allh/alln:>11.1f}%{total_chunks/len(prepared):>14.1f}")

    for k in FIXED_K:
        report(f"fixed K={k}", lambda r, k=k: [e for _, e in r[:k]])
    for ratio in RATIOS:
        report(f"threshold {ratio:.2f}", lambda r, ratio=ratio: by_threshold(r, ratio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
