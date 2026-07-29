"""Catalogue matching: rank brochure/template files against a quotation's text.

Same primitive the prospectus RAG pipeline already uses - embed everything with
the one shared embedding service and rank by cosine similarity - just applied
to a different pair of things (a quotation's text vs. a Drive catalogue's file
names/descriptions instead of a question vs. prospectus chunks). The caller
(the browser extension) does the Drive listing/download; this only ranks.
"""

import hashlib
import json
import re
import threading
from collections import OrderedDict

from . import embeddings


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _LRUCache:
    """Bounded in-memory cache, process-lifetime only - fine at POC scale and
    avoids the complexity of a persisted, invalidatable store for data that's
    cheap to regenerate on a cold start.
    """

    def __init__(self, max_size):
        self._max_size = max_size
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key, value):
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            if len(self._data) > self._max_size:
                self._data.popitem(last=False)


# item id -> (content hash, vector). A catalogue's items (Drive file name/
# description/OCR text) almost never change between one Send click and the
# next, but match()/match_lines() used to re-embed the *entire* catalogue on
# every single call - fine for a handful of items, but latency that grows
# linearly with catalogue size for no reason once it has dozens. Keyed by
# content hash (not just id) so an edited item is transparently re-embedded
# instead of serving a stale vector.
_item_vector_cache = {}
_item_vector_lock = threading.Lock()

_match_cache = _LRUCache(200)
_note_cache = _LRUCache(200)


def _text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _items_signature(items):
    return tuple(sorted((item.get("id"), _text_hash(_item_text(item))) for item in items))


def _embed_with_items(query_texts, items):
    """Embed `query_texts` fresh and return each item's vector, reusing cached
    item vectors where the item's own text hasn't changed. Returns
    (query_vectors, {item_id: vector}). Always a single embed() call - any
    items that do need (re-)embedding are batched into the same request as
    the query texts rather than a separate round trip.
    """
    texts_by_id = {item["id"]: _item_text(item) for item in items}
    item_vectors = {}
    to_embed_ids = []
    with _item_vector_lock:
        for item_id, text in texts_by_id.items():
            cached = _item_vector_cache.get(item_id)
            text_hash = _text_hash(text)
            if cached and cached[0] == text_hash:
                item_vectors[item_id] = cached[1]
            else:
                to_embed_ids.append(item_id)

    combined = list(query_texts) + [texts_by_id[i] for i in to_embed_ids]
    all_vectors = embeddings.embed(combined) if combined else []
    query_vectors = all_vectors[:len(query_texts)]
    fresh_vectors = all_vectors[len(query_texts):]

    with _item_vector_lock:
        for item_id, vector in zip(to_embed_ids, fresh_vectors):
            _item_vector_cache[item_id] = (_text_hash(texts_by_id[item_id]), vector)
            item_vectors[item_id] = vector

    return query_vectors, item_vectors


def match(quotation_text, items, top_k=3):
    """Rank catalogue items against a quotation's text.

    `items`: [{id, name, description, ocr_text?}, ...] - description can be
    empty, name alone is still enough to embed. If `ocr_text` is present, it
    is included in the embedding text for much richer semantic matching against
    the actual brochure content. Returns the same items, each with a `score`
    (cosine similarity, 0-1) added, sorted best-first, top_k only.
    """
    if not items:
        return []
    cache_key = ("match", quotation_text, _items_signature(items), top_k)
    cached = _match_cache.get(cache_key)
    if cached is not None:
        return [dict(m) for m in cached]

    query_vectors, item_vectors = _embed_with_items([quotation_text], items)
    quotation_vector = query_vectors[0]
    scored = [
        {**item, "score": round(_cosine(quotation_vector, item_vectors[item["id"]]), 3),
         "matchType": "semantic"}
        for item in items
    ]
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    result = scored[:top_k]
    _match_cache.set(cache_key, result)
    return result


def match_lines(quotation_lines, items, threshold=0.55, top_k=5):
    """Match several quotation lines against the catalogue independently.

    A quotation with multiple distinct products (e.g. "Widget A x2, Widget B
    x1") gets one best-matching catalogue item per line, instead of `match()`'s
    single item for the whole blended quotation text. If two lines land on the
    same catalogue item, only the higher-scoring occurrence is kept, so the
    same brochure is never offered twice. Returns items scoring >= threshold,
    sorted best-first, top_k only.
    """
    if not quotation_lines or not items:
        return []
    cache_key = ("match_lines", tuple(quotation_lines), _items_signature(items), threshold, top_k)
    cached = _match_cache.get(cache_key)
    if cached is not None:
        return [dict(m) for m in cached]

    line_vectors, item_vectors = _embed_with_items(quotation_lines, items)

    best_by_item = {}
    for line, line_vector in zip(quotation_lines, line_vectors):
        for item in items:
            score = round(_cosine(line_vector, item_vectors[item["id"]]), 3)
            existing = best_by_item.get(item["id"])
            if existing is None or score > existing["score"]:
                best_by_item[item["id"]] = {
                    **item, "score": score, "matchedLine": line, "matchType": "semantic",
                }

    matches = [m for m in best_by_item.values() if m["score"] >= threshold]
    matches.sort(key=lambda entry: entry["score"], reverse=True)
    result = matches[:top_k]
    _match_cache.set(cache_key, result)
    return result


def suggest_complementary(quotation_text, items, existing_ids, max_suggestions=2):
    """Suggest catalogue items commonly bundled with this order, even when
    they aren't semantically similar to it.

    Cosine similarity (match/match_lines above) finds items about the same
    topic as the quotation - it will never surface "water bottle" for an
    "employee award" order, because those aren't similar in meaning, they're
    just commonly given together in real corporate-gifting practice. That's
    a world-knowledge relationship, not a semantic one, so it needs an LLM
    call over the *other* catalogue items rather than another embedding
    comparison. Returns items tagged `matchType: "complementary"` with a
    synthetic score of 0.5 - not comparable to a real cosine score, callers
    should treat these as curated suggestions to always show, not ranked
    matches to threshold-filter.
    """
    from . import llm

    candidates = [item for item in items if item.get("id") not in existing_ids]
    if not quotation_text or not candidates:
        return []

    catalogue_lines = "\n".join(
        f"- {item['id']}: {item.get('name', '')} - {item.get('description', '')}".rstrip(" -")
        for item in candidates
    )
    system_prompt = (
        "You help a sales rep decide what else to attach to a quotation email. "
        "Given the order and a catalogue of other available items, suggest ONLY "
        "items that are commonly given or ordered TOGETHER WITH this order in "
        "real business practice (for example: an employee award often pairs "
        "with a water bottle, keychain, or mug as a corporate gift bundle) - "
        "NOT items that are simply similar to or alternatives for it. If "
        "nothing in the catalogue is a plausible real-world pairing, return "
        "an empty array. Reply with ONLY a JSON array of at most "
        f"{max_suggestions} catalogue item IDs, best fit first, e.g. "
        '["abc123"]. No other text, no markdown.'
    )
    user_prompt = f"Order: {quotation_text}\n\nOther catalogue items:\n{catalogue_lines}"

    try:
        # Local-only: a sales rep's Send click waits on this, and it's a nice-to-have
        # suggestion, not the quotation itself - not worth a paid Sarvam call (see
        # generate_note for the matching reasoning on the note-generation call).
        reply, _ = llm.generate(system_prompt, user_prompt, quotation_text, timeout=30,
                                 allow_cloud=False)
        match = re.search(r"\[.*?\]", reply, re.DOTALL)
        ids = json.loads(match.group(0)) if match else []
    except Exception:
        return []

    by_id = {item["id"]: item for item in candidates}
    suggestions = []
    for item_id in ids:
        item = by_id.get(item_id)
        if item and len(suggestions) < max_suggestions:
            suggestions.append({**item, "score": 0.5, "matchType": "complementary"})
    return suggestions


def _item_text(item):
    """Build a single embedding text from name, description, and OCR text.

    OCR text from the brochure PDF is included when available, weighted by
    taking the first ~2000 chars to stay within the embedding model's window
    while preserving the most relevant content. Name/description come first
    since they are the most discriminative signals.
    """
    parts = [
        item.get("name", ""),
        item.get("description", ""),
    ]
    ocr = item.get("ocr_text", "") or item.get("extractedText", "") or ""
    if ocr:
        # Truncate OCR to a generous window - the full brochure text could
        # be many pages; the first portion contains the most relevant content
        # (title, overview, key features).
        ocr = ocr[:2000]
        parts.append(ocr)
    return " ".join(p for p in parts if p).strip()


def generate_note(quotation_text, matched_items):
    """Generate an email note referencing one or more matched catalogue items.

    `matched_items` is a list of {name, description}; a single dict is also
    accepted for backward compatibility. Length scales with the number of
    attachments - roughly two sentences per item, combined into one natural
    note rather than a mechanical per-item list - since a quotation with
    several distinct products can now get several attachments at once
    (see `match_lines`), and each deserves its own mention.

    Uses the existing LLM pipeline (Sarvam primary, Ollama fallback).
    """
    from . import llm

    if isinstance(matched_items, dict):
        matched_items = [matched_items]

    cache_key = ("note", quotation_text,
                 tuple((i.get("name", ""), i.get("description", "")) for i in matched_items))
    cached = _note_cache.get(cache_key)
    if cached is not None:
        note, model = cached
        return note, f"cached:{model}"

    names = [item.get("name", "our product catalogue") for item in matched_items]
    items_block = "\n".join(
        f"- {item.get('name', '')}: {item.get('description', '')}".rstrip(": ")
        for item in matched_items
    )
    plural = len(matched_items) != 1

    system_prompt = (
        "You are a sales assistant helping write a short email note. The "
        "actual quotation is separate, sent elsewhere in this same email. "
        f"The {'items' if plural else 'item'} below are extra catalogue "
        "attachments included alongside it, the way a cross-sell or "
        "complementary suggestion would be - things the recipient might "
        "also be interested in, picked by a similarity match to the "
        "quotation. They are NOT guaranteed to be documentation of the "
        "exact product(s) being quoted, and may well be a different, "
        "related item. Introduce each attachment only by its own name/"
        "description below - never claim or imply it 'covers', 'outlines "
        "the specs of', or 'is the brochure for' whatever product is in "
        "the quotation unless the item's own name/description explicitly "
        "says so. Frame it the way you'd mention an added suggestion: "
        "attached, might also interest you, here's why. Roughly two "
        "sentences for each attached item, combined into one natural note "
        "rather than a mechanical list. Do NOT use markdown, asterisks, "
        "bullet points, or any formatting. Do NOT include a subject line or "
        "greeting. Just plain text, as if continuing the email body."
    )

    user_prompt = (
        f"Attached items (each is its own product/document - introduce it "
        f"by its own name only, do not claim it documents the quoted "
        f"product):\n{items_block}\n\n"
        f"Quotation (for context only, e.g. to judge why this might "
        f"interest the recipient - not what the attachment(s) are 'the "
        f"brochure for'): {quotation_text[:500]}\n\n"
        f"Write the note now, mentioning that {', '.join(names)} "
        f"{'have' if plural else 'has'} been attached as something the "
        f"recipient might also be interested in alongside the quotation."
    )

    try:
        # Local-only (gemma2:2b via Ollama), never Sarvam: this is a short,
        # low-stakes cross-sell blurb attached alongside a real quotation, not
        # the kind of answer quality difference worth a paid cloud call for.
        # Keeps the whole OrderAssist extension flow at $0 - only the RAG
        # chat pipeline (backend/rag.py) is worth spending Sarvam calls on.
        reply, model = llm.generate(system_prompt, user_prompt, quotation_text, timeout=30,
                                     allow_cloud=False)
        # Clean up any markdown or formatting the model might add despite instructions
        reply = reply.replace("*", "").replace("#", "").replace("_", "").strip()
        # Roughly two sentences' worth of length per attached item
        max_len = 500 * len(matched_items)
        if len(reply) > max_len:
            reply = reply[:max_len]
        _note_cache.set(cache_key, (reply, model))
        return reply, model
    except Exception as exc:
        # Fallback: generate a simple static note if the LLM fails. Not
        # cached - a real generation should replace it the moment the LLM
        # pipeline is back up, not get stuck serving this degraded text.
        joined = ", ".join(names)
        return (
            f"For your reference, we've also attached some additional "
            f"product information ({joined}) alongside the quotation, in "
            f"case it's useful."
        ), "static-fallback"
