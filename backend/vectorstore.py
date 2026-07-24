"""In-memory JSON vector store with cosine similarity search.

At POC scale (one prospectus, a few hundred chunks) this fits comfortably in
memory and needs no dedicated vector database. One store per project - the
caller passes the project's own store_path (see projects.py).
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


def load(store_path):
    if not store_path.exists():
        return []
    return json.loads(store_path.read_text(encoding="utf-8"))


def save(store_path, entries):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(entries), encoding="utf-8")


def search(store, query_vector, top_k=None):
    top_k = top_k or config.TOP_K
    scored = sorted(store, key=lambda e: _cosine(query_vector, e["vector"]), reverse=True)
    return scored[:top_k]
