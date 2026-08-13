"""In-memory JSON vector store with cosine similarity search.

At POC scale (one prospectus, a few hundred chunks) this fits comfortably in
memory and needs no dedicated vector database. One store per project - the
caller passes the project's own store_path (see projects.py).
"""

import json
import threading

from .. import config

# path -> (mtime, entries). The store was being re-read and JSON-parsed on every
# single chat request - measured at 42ms of pure waste per question on a 2.5MB
# store, single-threaded and GIL-bound, which turns into a queue rather than a
# delay once several students ask at once. Keyed on mtime so a re-ingest is
# picked up automatically without needing a restart or an explicit invalidation
# call from the ingest path.
_cache = {}
_cache_lock = threading.Lock()

# Most chunks any single page may contribute to one result set (see search).
_MAX_CHUNKS_PER_PAGE = 3

# How much lexical overlap can add on top of cosine (which spans roughly 0-1).
_KEYWORD_WEIGHT = 0.25

# A relevance floor relative to each query's own top score was tried here and
# reverted: the actual bug behind a "is hostel available" question retrieving
# the hostel FEE table (see pdf.py's table-reading block) turned out to be
# glossary.py mapping "वसतिगृह"/hostel to the retrieval terms "hostel fees"
# unconditionally, inflating the fee table's keyword score regardless of
# what was actually asked - fixed there instead. Measured directly on this
# corpus: the fee table scored 0.6062 against a top score of 0.6335, a ~4%
# gap that no reasonably lenient relative threshold would have caught anyway,
# so the threshold wasn't even solving the case it was written for. Left out
# rather than kept as unvalidated, unproven-necessary complexity.


def _norm(vec):
    return sum(x * x for x in vec) ** 0.5


# Words too common in this corpus to signal anything about which chunk is meant.
_STOPWORDS = frozenset("""
a an the is are was were be been being of for to in on at by with from as and or
not no do does did what when where which who whom how why can could shall should
will would may might must i me my we our you your it its this that these those
if then than so such about into over under after before during per as any all
""".split())


def _terms(text):
    out, word = set(), []
    for ch in text.lower():
        if ch.isalnum() or ch == "/":
            word.append(ch)
        elif word:
            out.add("".join(word))
            word = []
    if word:
        out.add("".join(word))
    return {w for w in out if len(w) > 2 and w not in _STOPWORDS}


def _keyword_score(query_terms, entry_terms):
    """Fraction of the question's content words that appear in this chunk.

    Pure vector search averages a whole chunk into one point, so a table of 25
    dated rows ends up equidistant from every date question and ranks below
    loosely-related prose - the admission schedule was never retrieved for "last
    date to submit the online application form" despite containing that exact
    row. Lexical overlap is what rescues those cases, and it costs nothing.
    """
    if not query_terms:
        return 0.0
    return len(query_terms & entry_terms) / len(query_terms)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load(store_path):
    """Return the project's chunks, reusing the parsed copy when unchanged.

    Callers must treat the result as read-only - it is shared between requests.
    """
    if not store_path.exists():
        return []
    key = str(store_path)
    mtime = store_path.stat().st_mtime
    cached = _cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        entries = json.loads(store_path.read_text(encoding="utf-8"))
        # Precompute each chunk's vector norm once. search() previously
        # recomputed both the stored norm AND the query norm for every entry, so
        # a single question walked all 768 dimensions three times per chunk
        # instead of once. The norm is stored alongside rather than assuming
        # unit vectors: the embedding service does normalize today, but a future
        # provider might not, and a silently wrong ranking is far worse than the
        # one multiply this costs.
        for entry in entries:
            entry["_norm"] = _norm(entry["vector"])
            # Same reasoning as the norm: tokenizing every chunk's text on every
            # query is per-request work that never changes between requests.
            entry["_terms"] = _terms(entry.get("text", ""))
        _cache[key] = (mtime, entries)
        return entries


def save(store_path, entries):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(entries), encoding="utf-8")
    with _cache_lock:
        _cache.pop(str(store_path), None)


def search(store, query_vector, top_k=None, query_text=""):
    """Top-k chunks by a hybrid of cosine similarity and keyword overlap.

    The query norm is a constant across the whole scan, so it is computed once
    here rather than per entry, and each chunk's norm comes precomputed from
    load(). That leaves a single dot product per chunk as the only real work.

    `query_text` enables the lexical half of the score (see _keyword_score); it
    is optional so existing callers keep working as pure vector search.
    """
    top_k = top_k or config.TOP_K
    qnorm = _norm(query_vector)
    if qnorm == 0:
        return []
    query_terms = _terms(query_text) if query_text else set()

    def score(entry):
        enorm = entry.get("_norm") or _norm(entry["vector"])
        if enorm == 0:
            return 0.0
        cosine = sum(x * y for x, y in zip(query_vector, entry["vector"])) / (qnorm * enorm)
        if not query_terms:
            return cosine
        # Cosine stays the primary signal; keyword overlap is a bounded nudge,
        # enough to lift an exact-phrase match out of the pack without letting a
        # keyword-stuffed but semantically irrelevant chunk win outright.
        entry_terms = entry.get("_terms")
        if entry_terms is None:
            entry_terms = _terms(entry.get("text", ""))
        return cosine + _KEYWORD_WEIGHT * _keyword_score(query_terms, entry_terms)

    # Scored once here and kept keyed by id() rather than sorting on score()
    # directly - store's entries are the SAME cached dict objects load()
    # returns to every caller (see its own docstring: "shared between
    # requests"), so mutating them with a per-query score would leak this
    # query's score into the next, unrelated one. Attached back onto a copy
    # of each picked entry below instead. Was previously computed only for
    # ranking and thrown away - the trace's "score" field (see rag/answer.py)
    # has been silently None on every retrieval event since it was added.
    scored = [(score(entry), entry) for entry in store]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    score_by_id = {id(entry): s for s, entry in scored}
    ranked = [entry for _, entry in scored]

    # Cap how many chunks one page may contribute. When a long page splits into
    # several similar chunks they score almost identically, so without this a
    # single page can take every slot - a fee table once filled all 8, leaving
    # no room for the pages that actually held the answer. Lower-ranked pages
    # backfill the remaining slots; if there genuinely aren't enough distinct
    # pages, the overflow is added back rather than returning short.
    picked, overflow, seen = [], [], {}
    for entry in ranked:
        if len(picked) >= top_k:
            break
        page = entry.get("page")
        if seen.get(page, 0) >= _MAX_CHUNKS_PER_PAGE:
            overflow.append(entry)
            continue
        seen[page] = seen.get(page, 0) + 1
        picked.append(entry)
    return [{**entry, "score": score_by_id[id(entry)]} for entry in (picked + overflow)[:top_k]]
