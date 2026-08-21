"""In-memory JSON vector store with cosine similarity search.

At POC scale (one prospectus, a few hundred chunks) this fits comfortably in
memory and needs no dedicated vector database. One store per project - the
caller passes the project's own store_path (see projects.py).
"""

import json
import threading

from . import atomic
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



# How much a topic match may add. Smaller than _KEYWORD_WEIGHT on purpose: a
# chunk from the right SECTION is a hint, not proof, and must never outrank a
# chunk that genuinely matches the question's words. Tuned to lift the right
# section's chunks past incidental noise (a table of contents, an unrelated
# Government Resolution) without letting a weakly-related fee paragraph beat a
# strongly-matching one from elsewhere.
_TOPIC_WEIGHT = 0.12

# Question words -> the chunk topic they imply. The mirror image of pdf.py's
# _TOPIC_RULES, which tags chunks from their section HEADING; this reads the
# student's question instead. Deliberately deterministic and free - the intent
# router already costs a call, and this must work when it is unavailable.
_QUERY_TOPICS = (
    # Checked before the general fee rule: "application fee" must not boost
    # the admission-fee tables, which is what happened when both shared one
    # topic (see pdf.py's _CONTENT_TOPIC_RULES).
    ("application_fee", ("application",)),
    ("fees", ("fee", "fees", "cost", "costs", "payment", "payments", "refund",
               "deposit", "charges", "tuition", "hostel",
               "शुल्क", "फी", "फीस")),
    ("quota", ("quota", "quotas", "reservation", "reservations", "reserved",
                "category", "categories", "ews", "obc",
                "आरक्षण", "कोटा")),
    # Subject/stream words belong here: "which subjects do I need in 12th" is
    # an eligibility question in every sense except vocabulary, and without
    # them it got no topic boost at all. Measured on B.Tech (Dairy): the
    # authoritative eligibility sentence sat at rank 6, below NRI
    # instructions and the syllabus, and the answer came back "Physics,
    # Chemistry, Biology and English" - B.V.Sc.'s subject list. B.Tech
    # requires MATHEMATICS. A student could have sat the wrong subjects.
    ("eligibility", ("eligibility", "eligible", "criteria", "qualify",
                      "qualifying", "percentage", "marks", "cutoff",
                      "subject", "subjects", "stream", "physics", "chemistry",
                      "biology", "mathematics", "maths", "pcb", "pcm",
                      "12th", "xii", "hsc", "minimum", "aggregate", "score",
                      "पात्रता", "गुण", "विषय")),
    ("seats", ("seat", "seats", "intake", "capacity", "vacancy", "vacancies",
                "जागा")),
    ("dates", ("date", "dates", "deadline", "last", "schedule", "when",
                "तारीख", "तारखा")),
    ("documents", ("document", "documents", "certificate", "certificates",
                    "affidavit", "proof", "कागदपत्रे", "दस्तावेज")),
)


def query_topic(text):
    """The section topic a question is asking about, or None when unclear.

    Scored by how many markers each topic matches, not first-match-wins.
    Ordering alone was too crude: "what is the minimum percentage needed for
    unreserved CATEGORY" matched quota on the single word "category" and
    stopped there, so a question about the eligibility threshold boosted the
    RESERVATION OF SEATS section and the answer came back "the prospectus
    does not specify" - about a figure printed on page 5. Counting matches
    lets the more specific reading win, and ties still fall back to
    declaration order.

    None is common and fine - it simply means no boost is applied and
    retrieval behaves exactly as it did before topics existed.
    """
    words = _terms(text or "")
    if not words:
        return None
    best, best_score = None, 0
    for topic, markers in _QUERY_TOPICS:
        score = len(words & set(markers))
        if score > best_score:
            best, best_score = topic, score
    return best


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
    # Atomic: this file holds the whole corpus's embeddings, produced by paid
    # calls over every prospectus. A truncated write during a re-ingest loses
    # them with no cheap way back (see HANDOFF: the vector stores are the one
    # thing that must be copied by hand between machines).
    atomic.write_json(store_path, entries)
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
    topic = query_topic(query_text)

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
        total = cosine + _KEYWORD_WEIGHT * _keyword_score(query_terms, entry_terms)
        # Section affinity: a fee question should not be competing with the
        # table of contents and an unrelated Government Resolution for slots.
        # Measured before this existed - "what is the application fee" shipped
        # ~29,700 chars to the model, most of it from sections with nothing to
        # do with fees.
        if topic and entry.get("topic") == topic:
            total += _TOPIC_WEIGHT
        return total

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
    # Budgeted per (page, kind), not per page. A fee page yields BOTH grid
    # slices and the prose rule that states the answer in words, and those
    # answer different questions. Under a flat per-page cap the three
    # near-identical grid slices - which score within 0.02 of each other
    # because they share the same header and legend - took every slot on
    # their page and pushed the prose chunk into overflow. Measured on the
    # Ph.D. fee page: the sentence giving the actual admission fee was
    # unreachable for a multi-program query for exactly this reason, and the
    # model answered from the grid instead, misreading a reservation fee as
    # the unreserved one. Splitting the budget lets the page contribute its
    # grid AND its prose without either crowding the other out, and without
    # raising the overall per-page allowance that stops one table dominating
    # the whole result set. `kind` is absent from stores ingested before this
    # existed; those all fall into one bucket and behave exactly as before.
    picked, overflow, seen = [], [], {}
    for entry in ranked:
        if len(picked) >= top_k:
            break
        bucket = (entry.get("page"), entry.get("kind", ""))
        if seen.get(bucket, 0) >= _MAX_CHUNKS_PER_PAGE:
            overflow.append(entry)
            continue
        seen[bucket] = seen.get(bucket, 0) + 1
        picked.append(entry)
    return [{**entry, "score": score_by_id[id(entry)]} for entry in (picked + overflow)[:top_k]]
