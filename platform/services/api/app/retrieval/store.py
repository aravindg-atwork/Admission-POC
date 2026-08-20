"""Qdrant-backed retrieval - the direct replacement for backend/storage/
vectorstore.py's in-memory JSON scan (see the platform architecture doc's
retrieval section for why: a JSON file loaded into one process's memory
caps this system at exactly one instance).

The hybrid cosine + keyword + topic scoring algorithm itself is PORTED,
not re-derived - `terms`, `_keyword_score`, `_QUERY_TOPICS`, `query_topic`,
and the per-page contribution cap are copied from the original almost
verbatim, because that algorithm is real, measured domain knowledge (see
each constant's own comment for the specific retrieval failure it fixes),
not incidental plumbing. What changes is WHERE the cosine half runs:
Qdrant does it server-side over its own ANN index and returns a generous
candidate set; the keyword/topic rescoring and per-page cap still happen
here, in Python, exactly as before, then the candidates are re-ranked by
the combined score.
"""

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from ..settings import get_settings

_settings = get_settings()
_client: QdrantClient | None = None

VECTOR_SIZE = 1024  # BGE-M3's own dimensionality


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=_settings.qdrant_url)
    return _client


def ensure_collection(name: str) -> None:
    client = get_client()
    if not client.collection_exists(name):
        client.create_collection(
            name,
            vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
        )


# --- ported scoring (see backend/storage/vectorstore.py) -------------------

_STOPWORDS = frozenset("""
a an the is are was were be been being of for to in on at by with from as and or
not no do does did what when where which who whom how why can could shall should
will would may might must i me my we our you your it its this that these those
if then than so such about into over under after before during per as any all
""".split())


def terms(text: str) -> set[str]:
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


def _keyword_score(query_terms: set[str], entry_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & entry_terms) / len(query_terms)


_KEYWORD_WEIGHT = 0.25
_TOPIC_WEIGHT = 0.12
_MAX_CHUNKS_PER_PAGE = 3
# How many candidates to pull from Qdrant's own ANN search before the
# keyword/topic rescoring narrows them to top_k. Generous on purpose - the
# keyword half can promote a chunk that ranked outside Qdrant's raw cosine
# top-K back into contention, the same rescue backend/storage/vectorstore.py's
# own docstring documents (a 25-row schedule table beating loosely-related
# prose only because of lexical overlap, not vector similarity alone).
_CANDIDATE_MULTIPLIER = 4

_QUERY_TOPICS = (
    ("application_fee", ("application",)),
    ("fees", ("fee", "fees", "cost", "costs", "payment", "payments", "refund",
               "deposit", "charges", "tuition", "hostel",
               "शुल्क", "फी", "फीस")),
    ("quota", ("quota", "quotas", "reservation", "reservations", "reserved",
                "category", "categories", "ews", "obc",
                "आरक्षण", "कोटा")),
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


def query_topic(text: str) -> str | None:
    words = terms(text or "")
    if not words:
        return None
    best, best_score = None, 0
    for topic, markers in _QUERY_TOPICS:
        score = len(words & set(markers))
        if score > best_score:
            best, best_score = topic, score
    return best


def search(collection: str, query_vector: list[float], top_k: int, query_text: str = "") -> list[dict]:
    """Top-k chunks by the same hybrid cosine+keyword+topic score the
    original system uses. Each returned dict carries {page, text, kind,
    topic, section, score}.
    """
    client = get_client()
    if not client.collection_exists(collection):
        return []

    query_terms = terms(query_text) if query_text else set()
    topic = query_topic(query_text)

    raw = client.query_points(
        collection,
        query=query_vector,
        limit=max(top_k * _CANDIDATE_MULTIPLIER, top_k),
        with_payload=True,
    ).points

    scored = []
    for point in raw:
        payload = point.payload or {}
        cosine = point.score  # Qdrant's COSINE distance metric returns similarity directly
        total = cosine
        if query_terms:
            entry_terms = set(payload.get("terms") or [])
            total += _KEYWORD_WEIGHT * _keyword_score(query_terms, entry_terms)
        if topic and payload.get("topic") == topic:
            total += _TOPIC_WEIGHT
        scored.append((total, payload))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    picked, overflow, seen = [], [], {}
    for score, payload in scored:
        if len(picked) >= top_k:
            break
        bucket = (payload.get("page"), payload.get("kind", ""))
        if seen.get(bucket, 0) >= _MAX_CHUNKS_PER_PAGE:
            overflow.append((score, payload))
            continue
        seen[bucket] = seen.get(bucket, 0) + 1
        picked.append((score, payload))

    final = (picked + overflow)[:top_k]
    return [
        {
            "page": payload.get("page"),
            "text": payload.get("text", ""),
            "kind": payload.get("kind", ""),
            "topic": payload.get("topic", "general"),
            "section": payload.get("section", ""),
            "score": score,
        }
        for score, payload in final
    ]
