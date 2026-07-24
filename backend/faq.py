"""FAQ cache: instant answers for questions we've seen (or seeded) before.

Sits in front of RAG. A new question is embedded once (that same vector is reused
for RAG retrieval), and if it is semantically close to a cached question we return
the stored answer immediately - no vector search, no LLM call, so it's instant.

Two ways entries get here:
  - seeded: an admin curates common Q&A up front (the "FAQ" proper)
  - auto-cached: a freshly generated answer is stored so the next similar ask is instant

Matching is language-aware by construction: the embedding of a Hindi question is
close to other Hindi phrasings, not to the English one, so cached answers stay in
the language they were created for.
"""

import json
import threading

from . import config

_lock = threading.Lock()


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load():
    if not config.FAQ_PATH.exists():
        return []
    return json.loads(config.FAQ_PATH.read_text(encoding="utf-8") or "[]")


def _save(entries):
    config.FAQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.FAQ_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def match(query_vector):
    """Return a cached entry {answer, pages, question} if one is close enough, else None."""
    best, best_score = None, 0.0
    for entry in _load():
        score = _cosine(query_vector, entry["vector"])
        if score > best_score:
            best, best_score = entry, score
    if best and best_score >= config.FAQ_THRESHOLD:
        return {"answer": best["answer"], "pages": best.get("pages", []),
                "question": best["question"], "score": round(best_score, 3)}
    return None


def add(question, answer, pages, vector):
    """Cache a generated answer for instant reuse next time."""
    with _lock:
        entries = _load()
        entries.append({"question": question, "answer": answer, "pages": pages, "vector": vector})
        _save(entries)


def list_entries():
    return [{k: v for k, v in e.items() if k != "vector"} for e in _load()]


def clear():
    with _lock:
        _save([])
