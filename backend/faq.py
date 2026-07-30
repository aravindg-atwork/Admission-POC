"""FAQ cache: instant answers for questions we've seen (or seeded) before.

Sits in front of RAG. A new question is embedded once (that same vector is reused
for RAG retrieval), and if it is semantically close to a cached question we return
the stored answer immediately - no vector search, no LLM call, so it's instant.

Two ways entries get here:
  - seeded: an admin curates common Q&A up front (the "FAQ" proper)
  - auto-cached: a freshly generated answer is stored so the next similar ask is instant

Matching is language-aware by construction across scripts: the embedding of a
Hindi/Marathi question is close to other Devanagari phrasings, not to the English
or Tamil one. Hindi and Marathi are the exception - they share Devanagari script
and a lot of overlapping vocabulary (especially for short admin-y phrasings like
fee/document questions), so their embeddings can land close enough to collide.
Same story one level up: a plain "what is the fee" question and a "my payment
failed" question are topically close enough to also collide, even though they
need completely different answers (a number vs. a triage response).

`tags` (e.g. {"ui_language": "hi", "intent": "payment_issue"}) is how rag.py
guards against both: stored per entry and checked on match. An entry carrying an
explicit value for a tag key is only eligible for a query carrying that same
value. An entry with no value for the key (older entries from before tagging, or
an axis that doesn't apply) stays eligible for anything, so this never requires a
tag that isn't there.

The asymmetry is deliberate, and it is the *entry's* tag that gates. Treating a
missing query-side tag as "no opinion, match anything" looked equivalent but
silently served wrong answers whenever a caller omitted the tag: a Marathi
question with no ui_language matched the Hindi-tagged entry for the same question
- identical topic, near-identical Devanagari embedding - and answered a Marathi
student in Hindi. Reproduced with tools/test_matrix.py, which doesn't send
uiLanguage. The same hole let an entry tagged intent="payment_issue" surface for
a plain "what is the fee" question, which is the collision tagging it was
introduced to prevent.

One cache per project - every function takes that project's own faq_path
(see projects.py) rather than a single global file.
"""

import atexit
import json
import threading
import time
import unicodedata
from pathlib import Path

from . import config

_lock = threading.Lock()
_dirty = set()
_last_flush = {}

# path -> (mtime, entries). This cache is on the hottest path in the system: at
# admission scale most questions are repeats, so match() runs for nearly every
# request. Re-reading and re-parsing the whole file each time (as this did)
# meant the busiest code path was also the most wasteful, and it is GIL-bound,
# so it queues rather than merely being slow. Keyed on mtime so an external edit
# or another process's write is still picked up.
_cache = {}


def _norm(vec):
    return sum(x * x for x in vec) ** 0.5


# Words that flip a question's meaning while barely moving its embedding.
# "first year hostel fee" and "2nd year hostel fee" are near-identical vectors
# but different answers - and a cache that returns the wrong one states a wrong
# number with total confidence, which is worse than a slow correct answer.
#
# These lists were English-only, which silently disabled the entire safeguard for
# Hindi and Marathi: every Devanagari question produced an EMPTY discriminator
# set, so nothing was ever blocked and the 0.88 threshold ran unguarded in the
# lane it was never measured on. Verified by direct probe - "आरक्षित वर्ग के लिए
# प्रवेश शुल्क" (reserved category) was served the cached answer for "अनारक्षित"
# (UNreserved), i.e. Rs.62635 instead of Rs.26135, and an exam-fee question was
# answered with the tuition figure. Both are exactly the confident-wrong-number
# failure this mechanism exists to prevent, and both scored as a cache "hit".
#
# Surface forms are grouped under a canonical key so that Hindi and Marathi words
# for the same concept (अनारक्षित / खुल्या) compare equal instead of looking like
# two different constraints.
_ORDINAL_FORMS = {
    "1": ["first", "1st", "one", "pehla", "pehle", "pehli", "pahila", "pahile",
          "pahilya", "pratham", "पहल", "पहिल", "प्रथम"],
    "2": ["second", "2nd", "two", "dusra", "dusre", "dusri", "dusrya", "dusara",
          "दूसर", "दुसर", "दुसऱ", "द्वितीय"],
    "3": ["third", "3rd", "three", "tisra", "tisre", "tisrya",
          "तीसर", "तिसर", "तिसऱ", "तृतीय"],
    "4": ["fourth", "4th", "four", "chautha", "chauthe", "chouth",
          "चौथ", "चतुर्थ"],
}
# Mutually exclusive alternatives within a topic. Grouped rather than kept as a
# flat list so that *omitting* a word is treated as vagueness, not disagreement:
# "fee for reserved category" should still match a cached "application fee for
# reserved category", while "admission fee ..." must not.
_CONTRAST_FORMS = {
    "feetype": {
        "application": ["application", "आवेदन", "अर्ज", "aavedan", "arj"],
        "admission": ["admission", "प्रवेश", "एडमिशन", "pravesh"],
        "tuition": ["tuition", "ट्यूशन", "शिक्षणशुल्क", "शिक्षणफी"],
        "mess": ["mess", "मेस", "भोजन", "जेवण"],
        "hostel": ["hostel", "हॉस्टेल", "वसतिगृह", "छात्रावास"],
        "exam": ["exam", "examination", "परीक्षा", "pariksha"],
        "registration": ["registration", "नोंदणी", "पंजीकरण", "रजिस्ट्रेशन"],
    },
    "when": {
        "before": ["before", "पहले", "आधी", "पूर्वी", "अगोदर"],
        "after": ["after", "बाद", "नंतर"],
    },
    "category": {
        "reserved": ["reserved", "आरक्षित", "राखीव", "arakshit"],
        "unreserved": ["unreserved", "open", "अनारक्षित", "खुल्या", "खुला", "खुले"],
        "nri": ["nri", "एनआरआय", "एनआरआई"],
        "ews": ["ews", "ईडब्ल्यूएस"],
        "obc": ["obc", "ओबीसी"],
    },
    "bound": {
        "minimum": ["minimum", "least", "न्यूनतम", "किमान"],
        "maximum": ["maximum", "most", "अधिकतम", "कमाल"],
    },
    # What KIND of figure is being asked for. Two questions about the same
    # reserved category can want completely different numbers - a rupee amount
    # or a seat percentage - and their embeddings sit close enough to collide:
    # "आर्थिक रूप से कमजोर वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?" (what % of seats
    # are EWS-reserved) was served the cached answer to "आरक्षित वर्ग के लिए प्रवेश
    # शुल्क कितना है?", i.e. "Rs. 26135". Both name a category, so the category
    # group agreed and nothing else separated them until this group existed.
    "asks_about": {
        "money": ["fee", "fees", "cost", "amount", "शुल्क", "फीस", "फी",
                  "भुगतान", "रक्कम"],
        "seats": ["seat", "seats", "percentage", "percent", "quota",
                  "सीट", "जागा", "प्रतिशत", "टक्के", "टक्का"],
    },
}


# Devanagari digits: "१ लाख" and "1 लाख" are the same claim, and students type
# both. Normalized here so a number discriminator compares equal either way
# rather than looking like two different figures.
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _is_word_char(ch):
    """Whether this character continues a word.

    `isalnum()` alone is wrong for Indic scripts and was the deeper reason the
    Devanagari lane had no discriminators at all: vowel signs (matras), the
    virama and the nukta are Unicode combining marks, which are NOT alnum, so an
    alnum-only split shatters every word at its vowel signs - "आरक्षित" came out
    as ['आरक', 'ष', 'त'] and "दुसऱ्या" as ['द', 'सऱ', 'य']. No stem or member
    list can match fragments like that, so nothing downstream could ever fire.

    Tested by category rather than by codepoint range so this holds for Tamil and
    any other Indic script the project adds later, and so that the danda "।" - a
    sentence-ending punctuation mark that happens to sit inside the Devanagari
    block - still correctly splits words instead of gluing sentences together.
    """
    return ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc")


def _words(text):
    out, current = [], []
    for ch in text.lower().translate(_DEVA_DIGITS):
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def _is_devanagari(word):
    return any(0x0900 <= ord(ch) <= 0x097F for ch in word)


def _matches_form(word, form):
    """Whether `word` expresses `form`.

    Devanagari forms are matched as STEMS, not whole tokens: Hindi and Marathi
    agglutinate case endings onto the noun, so the question "आरक्षित प्रवर्गासाठी
    प्रवेश शुल्क किती आहे?" contains "प्रवेशासाठी"/"प्रवर्गासाठी" as single tokens and
    exact membership would match none of them - which is precisely why the
    Devanagari lane scored zero discriminators. Latin forms stay exact: English
    barely inflects, and prefix matching there would have "one" match "online"
    and "exam" match "example", inventing constraints out of ordinary words.
    """
    if word == form:
        return True
    return _is_devanagari(form) and len(form) >= 3 and word.startswith(form)


def _discriminators(question):
    """(numbers, {group: alternatives}) - what must agree for two questions to mean
    the same thing. Everything else may vary freely; that is the paraphrasing the
    cache exists to absorb.
    """
    numbers, groups = set(), {}
    for w in _words(question):
        if w.isdigit():
            numbers.add(w.lstrip("0") or "0")
            continue
        matched_ordinal = False
        for value, forms in _ORDINAL_FORMS.items():
            if any(_matches_form(w, f) for f in forms):
                numbers.add(value)
                matched_ordinal = True
                break
        if matched_ordinal:
            continue
        for group, alternatives in _CONTRAST_FORMS.items():
            for canonical, forms in alternatives.items():
                if any(_matches_form(w, f) for f in forms):
                    groups.setdefault(group, set()).add(canonical)
                    break
    return numbers, groups


def _compatible(a, b):
    """True when two questions agree on every dimension both of them specify.

    Groups are compared as whole sets, so a question naming two members of one
    group ("reserved EWS seats" -> category {reserved, ews}) will not match one
    naming a single member ("reserved seats" -> {reserved}) even when they mean
    the same thing. That is a deliberate asymmetry: the cost is a cache miss and
    a slower correct answer, whereas loosening it to a subset test would let a
    genuinely narrower question be answered from a broader cached one - a
    confidently wrong number, which is the failure this whole module prevents.
    """
    a_nums, a_groups = a
    b_nums, b_groups = b
    if a_nums != b_nums:
        return False  # "1st year" vs "2nd year", "20 days" vs "30 days"
    for group in set(a_groups) & set(b_groups):
        if a_groups[group] != b_groups[group]:
            return False  # both name a fee type / direction, but different ones
    return True


def compatible_questions(a, b):
    """Whether two texts agree on every discriminating dimension both specify.

    Public wrapper over the same check the cache uses internally. Exposed
    because rag.py needs it for a different purpose - vetoing a table reading
    whose descriptor contradicts the student's question - and that vocabulary
    (fee types, ordinals, categories, in three languages) should have exactly
    one definition rather than a second copy that drifts.
    """
    return _compatible(_discriminators(a), _discriminators(b))


def _load(faq_path):
    """Parsed entries, reused while the file is unchanged. Treat as read-only."""
    if not faq_path.exists():
        return []
    key = str(faq_path)
    mtime = faq_path.stat().st_mtime
    cached = _cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    entries = json.loads(faq_path.read_text(encoding="utf-8") or "[]")
    # Precompute each stored vector's norm once rather than per comparison.
    for entry in entries:
        if "_norm" not in entry:
            entry["_norm"] = _norm(entry["vector"])
    _cache[key] = (mtime, entries)
    return entries


def _save(faq_path, entries):
    faq_path.parent.mkdir(parents=True, exist_ok=True)
    # "_norm" is a runtime aid, not part of the on-disk format - strip it so the
    # file stays readable and doesn't drift if the vectors are ever regenerated.
    payload = [{k: v for k, v in e.items() if k != "_norm"} for e in entries]
    faq_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep serving from memory rather than forcing the next match() to re-read
    # what we just wrote, and re-key on the new mtime.
    _cache[str(faq_path)] = (faq_path.stat().st_mtime, entries)
    _dirty.discard(str(faq_path))
    _last_flush[str(faq_path)] = time.time()


def _stage(faq_path, entries):
    """Publish new entries to readers immediately; persist them on a schedule.

    A full rewrite of this file is O(everything) - at the 1000-entry cap that is
    roughly 15MB of JSON serialized under the write lock, on every cache MISS,
    which is precisely when the system is already doing expensive work. Since
    this is a cache and every entry is reproducible by re-answering the
    question, trading a few seconds of durability for not stalling every writer
    is the right way round. Readers never see stale data because the in-memory
    copy is updated synchronously; only the disk write is deferred.
    """
    key = str(faq_path)
    _cache[key] = (_cache.get(key, (0, None))[0], entries)
    _dirty.add(key)
    if time.time() - _last_flush.get(key, 0.0) >= config.FAQ_FLUSH_SECONDS:
        _save(faq_path, entries)


def flush(faq_path=None):
    """Write any deferred entries to disk. Called on shutdown and by admin ops."""
    with _lock:
        targets = [faq_path] if faq_path else [Path(p) for p in list(_dirty)]
        for path in targets:
            if str(path) in _dirty and _cache.get(str(path)):
                _save(path, _cache[str(path)][1])


def _prune(entries):
    """Keep the cache bounded, never dropping curated (seeded) entries.

    Every unseen question adds an entry carrying a 768-float vector, so an
    admission rush with thousands of distinct phrasings would grow this file
    without limit - slowing every match and every write. Seeded answers are
    curated and permanent; auto-cached ones are disposable, so the oldest of
    those go first.
    """
    limit = config.FAQ_MAX_ENTRIES
    if limit <= 0 or len(entries) <= limit:
        return entries
    seeded = [e for e in entries if e.get("seeded")]
    auto = [e for e in entries if not e.get("seeded")]
    auto.sort(key=lambda e: e.get("created_at", 0))
    keep_auto = max(0, limit - len(seeded))
    return seeded + auto[len(auto) - keep_auto:] if keep_auto else seeded


def match(faq_path, query_vector, tags=None, question=""):
    """Return a cached entry {answer, pages, question} if one is close enough, else None.

    Cached answers are always native-script (generation never varies by script
    preference - see rag.py); Hinglish/Tanglish is a display-time transliteration
    applied uniformly to both fresh and cached answers, so there's nothing
    script-specific to match on here. See module docstring for what `tags` does.
    """
    tags = tags or {}
    qnorm = _norm(query_vector)
    if qnorm == 0:
        return None
    q_disc = _discriminators(question) if question else None
    best, best_score = None, 0.0
    for entry in _load(faq_path):
        entry_tags = entry.get("tags") or {}
        if any(entry_tags.get(k) and entry_tags[k] != v for k, v in tags.items()):
            continue
        # Embedding similarity alone cannot separate "1st year" from "2nd year"
        # or "before" from "after" - measured: with a 0.88 threshold the cache
        # answered a 2nd-year fee question with the 1st-year figure, and a
        # "20 days before" refund question with the "20 days after" answer.
        # Requiring these tokens to agree is what makes a lower threshold (and
        # so a much better hit rate on genuine paraphrases) safe.
        if q_disc is not None and not _compatible(q_disc, _discriminators(entry["question"])):
            continue
        enorm = entry.get("_norm") or _norm(entry["vector"])
        if enorm == 0:
            continue
        score = sum(x * y for x, y in zip(query_vector, entry["vector"])) / (qnorm * enorm)
        if score > best_score:
            best, best_score = entry, score
    if best and best_score >= config.FAQ_THRESHOLD:
        return {"answer": best["answer"], "pages": best.get("pages", []),
                "question": best["question"], "score": round(best_score, 3)}
    return None


def add(faq_path, question, answer, pages, vector, tags=None, seeded=False):
    """Cache an answer for instant reuse next time.

    `seeded=True` marks a curated entry, which is exempt from pruning.
    """
    with _lock:
        entries = list(_load(faq_path))
        entry = {"question": question, "answer": answer, "pages": pages,
                 "vector": vector, "tags": tags or {},
                 "seeded": bool(seeded), "created_at": time.time()}
        entry["_norm"] = _norm(vector)
        entries.append(entry)
        _stage(faq_path, _prune(entries))


def seed(faq_path, items, embed):
    """Bulk-load curated question/answer pairs, embedding them in one batch.

    Worth doing before an admission window opens: the cache is only fast for
    questions it has already seen, so without seeding the first students to ask
    each common question all pay full RAG-plus-LLM latency, at exactly the
    busiest moment. `items` is [{question, answer, pages?, tags?}]; `embed` is
    injected so this module stays independent of the embedding client.

    Re-seeding the same question replaces it rather than piling up duplicates,
    so this is safe to re-run after editing the curated answers.
    """
    items = [i for i in items if i.get("question") and i.get("answer")]
    if not items:
        return 0
    vectors = embed([i["question"] for i in items])
    with _lock:
        entries = [e for e in _load(faq_path)
                   if e["question"] not in {i["question"] for i in items}]
        for item, vector in zip(items, vectors):
            entries.append({
                "question": item["question"], "answer": item["answer"],
                "pages": item.get("pages", []), "vector": vector,
                "tags": item.get("tags") or {}, "seeded": True,
                "created_at": time.time(),
            })
        _save(faq_path, _prune(entries))
    return len(items)


def list_entries(faq_path):
    return [{k: v for k, v in e.items() if k not in ("vector", "_norm")}
            for e in _load(faq_path)]


def clear(faq_path):
    with _lock:
        _save(faq_path, [])


# Curated seeds and explicit clears are administrative actions, not hot-path
# writes, so they persist immediately (via _save) rather than being deferred.
# This only catches auto-cached entries still staged in memory at shutdown.
atexit.register(flush)
