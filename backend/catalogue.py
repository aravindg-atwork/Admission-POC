"""Catalogue matching: rank brochure/template files against a quotation's text.

Same primitive the prospectus RAG pipeline already uses - embed everything with
the one shared embedding service and rank by cosine similarity - just applied
to a different pair of things (a quotation's text vs. a Drive catalogue's file
names/descriptions instead of a question vs. prospectus chunks). The caller
(the browser extension) does the Drive listing/download; this only ranks.
"""

from . import embeddings


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def match(quotation_text, items, top_k=3):
    """Rank catalogue items against a quotation's text.

    `items`: [{id, name, description}, ...] - description can be empty, name
    alone is still enough to embed. Returns the same items, each with a
    `score` (cosine similarity, 0-1) added, sorted best-first, top_k only.
    """
    if not items:
        return []
    texts = [quotation_text] + [
        (item.get("name", "") + " " + item.get("description", "")).strip() for item in items
    ]
    vectors = embeddings.embed(texts)
    quotation_vector, item_vectors = vectors[0], vectors[1:]
    scored = [
        {**item, "score": round(_cosine(quotation_vector, vector), 3)}
        for item, vector in zip(items, item_vectors)
    ]
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored[:top_k]
