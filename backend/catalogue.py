"""Catalogue matching: rank brochure/template files against a quotation's text.

Same primitive the prospectus RAG pipeline already uses - embed everything with
the one shared embedding service and rank by cosine similarity - just applied
to a different pair of things (a quotation's text vs. a Drive catalogue's file
names/descriptions instead of a question vs. prospectus chunks). The caller
(the browser extension) does the Drive listing/download; this only ranks.
"""

import json
import re

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

    `items`: [{id, name, description, ocr_text?}, ...] - description can be
    empty, name alone is still enough to embed. If `ocr_text` is present, it
    is included in the embedding text for much richer semantic matching against
    the actual brochure content. Returns the same items, each with a `score`
    (cosine similarity, 0-1) added, sorted best-first, top_k only.
    """
    if not items:
        return []
    texts = [quotation_text] + [
        _item_text(item) for item in items
    ]
    vectors = embeddings.embed(texts)
    quotation_vector, item_vectors = vectors[0], vectors[1:]
    scored = [
        {**item, "score": round(_cosine(quotation_vector, vector), 3), "matchType": "semantic"}
        for item, vector in zip(items, item_vectors)
    ]
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored[:top_k]


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
    texts = list(quotation_lines) + [_item_text(item) for item in items]
    vectors = embeddings.embed(texts)
    line_vectors = vectors[: len(quotation_lines)]
    item_vectors = vectors[len(quotation_lines):]

    best_by_item = {}
    for line, line_vector in zip(quotation_lines, line_vectors):
        for item, item_vector in zip(items, item_vectors):
            score = round(_cosine(line_vector, item_vector), 3)
            existing = best_by_item.get(item["id"])
            if existing is None or score > existing["score"]:
                best_by_item[item["id"]] = {
                    **item, "score": score, "matchedLine": line, "matchType": "semantic",
                }

    matches = [m for m in best_by_item.values() if m["score"] >= threshold]
    matches.sort(key=lambda entry: entry["score"], reverse=True)
    return matches[:top_k]


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
        reply, _ = llm.generate(system_prompt, user_prompt, quotation_text, timeout=30)
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
    names = [item.get("name", "our product catalogue") for item in matched_items]
    items_block = "\n".join(
        f"- {item.get('name', '')}: {item.get('description', '')}".rstrip(": ")
        for item in matched_items
    )
    plural = len(matched_items) != 1

    system_prompt = (
        "You are a sales assistant helping write a short email note. "
        f"Write concise, natural sentences informing the recipient that "
        f"{'brochures have' if plural else 'a brochure has'} been attached - "
        "roughly two sentences for each attached item, combined into one "
        "natural note rather than a mechanical list. Mention each attached "
        "item by name naturally. Do NOT use markdown, asterisks, bullet "
        "points, or any formatting. Do NOT include a subject line or "
        "greeting. Just plain text, as if continuing the email body."
    )

    user_prompt = (
        f"Attached items:\n{items_block}\n\n"
        f"Quotation context: {quotation_text[:500]}\n\n"
        f"Write the note now, mentioning that {', '.join(names)} "
        f"{'have' if plural else 'has'} been attached and why each might be "
        f"relevant."
    )

    try:
        reply, model = llm.generate(system_prompt, user_prompt, quotation_text, timeout=30)
        # Clean up any markdown or formatting the model might add despite instructions
        reply = reply.replace("*", "").replace("#", "").replace("_", "").strip()
        # Roughly two sentences' worth of length per attached item
        max_len = 500 * len(matched_items)
        if len(reply) > max_len:
            reply = reply[:max_len]
        return reply, model
    except Exception as exc:
        # Fallback: generate a simple static note if the LLM fails
        joined = ", ".join(names)
        return (
            f"We have attached our catalogue ({joined}) that we believe may "
            f"be of interest to you. Please take a moment to review the "
            f"enclosed documents."
        ), "static-fallback"
