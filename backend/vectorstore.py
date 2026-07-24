"""In-memory JSON vector store with cosine similarity search.

At POC scale (one prospectus, a few hundred chunks) this fits comfortably in
memory and needs no dedicated vector database.
"""

import json

from . import config


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load():
    if not config.STORE_PATH.exists():
        return []
    return json.loads(config.STORE_PATH.read_text(encoding="utf-8"))


def save(entries):
    config.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.STORE_PATH.write_text(json.dumps(entries), encoding="utf-8")


def search(store, query_vector, top_k=None):
    top_k = top_k or config.TOP_K
    scored = sorted(store, key=lambda e: _cosine(query_vector, e["vector"]), reverse=True)
    return scored[:top_k]
