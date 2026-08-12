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
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from . import config
from .lang import detect_script

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
#   1 - முதல் (mudhal)                 3 - மூன்றாம் / மூன்றாவது (moonraam)
#   2 - இரண்டாம் / இரண்டாவது (irandaam)   4 - நான்காம் / நான்காவது (naankaam)
# Not yet exhaustive - added as real Tamil questions surface a gap, same as
# the Hindi/Marathi lists (see module comment above on how those were found).
_ORDINAL_FORMS = {
    "1": ["first", "1st", "one", "pehla", "pehle", "pehli", "pahila", "pahile",
          "pahilya", "pratham", "पहल", "पहिल", "प्रथम", "முதல்"],
    "2": ["second", "2nd", "two", "dusra", "dusre", "dusri", "dusrya", "dusara",
          "दूसर", "दुसर", "दुसऱ", "द्वितीय", "இரண்டாம்", "இரண்டாவ"],
    "3": ["third", "3rd", "three", "tisra", "tisre", "tisrya",
          "तीसर", "तिसर", "तिसऱ", "तृतीय", "மூன்றாம்", "மூன்றாவ"],
    "4": ["fourth", "4th", "four", "chautha", "chauthe", "chouth",
          "चौथ", "चतुर्थ", "நான்காம்", "நான்காவ"],
}
# Mutually exclusive alternatives within a topic. Grouped rather than kept as a
# flat list so that *omitting* a word is treated as vagueness, not disagreement:
# "fee for reserved category" should still match a cached "application fee for
# reserved category", while "admission fee ..." must not.
_CONTRAST_FORMS = {
    "feetype": {
        "application": ["application", "आवेदन", "अर्ज", "aavedan", "arj",
                         "விண்ணப்ப"],
        "admission": ["admission", "प्रवेश", "एडमिशन", "pravesh", "சேர்க்கை"],
        "tuition": ["tuition", "ट्यूशन", "शिक्षणशुल्क", "शिक्षणफी", "கல்விக்"],
        "mess": ["mess", "मेस", "भोजन", "जेवण", "மெஸ்", "உணவக"],
        "hostel": ["hostel", "हॉस्टेल", "वसतिगृह", "छात्रावास", "விடுதி"],
        "exam": ["exam", "examination", "परीक्षा", "pariksha", "தேர்வு"],
        "registration": ["registration", "नोंदणी", "पंजीकरण", "रजिस्ट्रेशन",
                          "பதிவு"],
        # Separate from "application": "अर्ज"/"आवेदन" is the generic word for
        # "form" in Hindi/Marathi and appears inside "grievance application"
        # too ("तक्रार अर्ज"), so a grievance-fee question shared the same
        # feetype as a plain application-fee one and was served Rs.1000
        # (application fee) for a Rs.200 (grievance fee) question - a genuine
        # collision found 2026-08-11. Naming "grievance" here makes a
        # grievance question's feetype set a strict superset of a plain
        # application one ({application, grievance} != {application}), which
        # the existing set-equality check in _compatible already separates.
        "grievance": ["grievance", "complaint", "शिकायत", "तक्रार"],
    },
    "when": {
        "before": ["before", "पहले", "आधी", "पूर्वी", "अगोदर", "முன்"],
        "after": ["after", "बाद", "नंतर", "பிறகு", "பின்"],
    },
    "category": {
        "reserved": ["reserved", "आरक्षित", "राखीव", "arakshit", "ஒதுக்கீட்"],
        "unreserved": ["unreserved", "open", "अनारक्षित", "खुल्या", "खुला",
                        "खुले", "பொது"],
        "nri": ["nri", "एनआरआय", "एनआरआई", "என்ஆர்ஐ"],
        "ews": ["ews", "ईडब्ल्यूएस", "ஈடபிள்யூஎஸ்"],
        "obc": ["obc", "ओबीसी", "ஓபிசி"],
    },
    "bound": {
        "minimum": ["minimum", "least", "न्यूनतम", "किमान", "குறைந்தபட்ச"],
        "maximum": ["maximum", "most", "अधिकतम", "कमाल", "அதிகபட்ச"],
    },
    # What KIND of figure is being asked for. Two questions about the same
    # reserved category can want completely different numbers - a rupee amount
    # or a seat percentage - and their embeddings sit close enough to collide:
    # "आर्थिक रूप से कमजोर वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?" (what % of seats
    # are EWS-reserved) was served the cached answer to "आरक्षित वर्ग के लिए प्रवेश
    # शुल्क कितना है?", i.e. "Rs. 26135". Both name a category, so the category
    # group agreed and nothing else separated them until this group existed.
    #
    # "percentage"/"प्रतिशत" is deliberately NOT listed under "seats" below: it
    # is equally the word for "what % marks are required" (an eligibility
    # question) as for "what % of seats are reserved", so it doesn't
    # discriminate between them on its own. Found 2026-08-11: "शारीरिक रूप से
    # विकलांग उम्मीदवारों के लिए कितने प्रतिशत सीटें आरक्षित हैं?" (what % of seats are
    # PH-reserved, 5%) was served the cached answer to "आरक्षित श्रेणी ...
    # न्यूनतम कितने प्रतिशत अंक चाहिए?" (what % marks are needed, 47.50%) - both
    # matched "प्रतिशत" and neither had a value in the other's absent group, so
    # the asymmetric "missing = no opinion" rule let them collide. Splitting
    # "marks" out and requiring an actual seat noun (सीट/जागा/seat) for "seats"
    # closes that gap the same way "grievance" closes the application one.
    "asks_about": {
        "money": ["fee", "fees", "cost", "amount", "शुल्क", "फीस", "फी",
                  "भुगतान", "रक्कम", "கட்டணம்", "தொகை"],
        "seats": ["seat", "seats", "quota", "सीट", "जागा", "quota",
                  "இடம்", "இடங்கள்"],
        "marks": ["marks", "mark", "score", "अंक", "गुण", "मार्क्स",
                  "மதிப்பெண்"],
        # Added 2026-08-12: reproduced directly - "What documents do I need
        # to submit for B.Tech. Dairy Technology?" matched a cached "What is
        # the eligibility for B.Tech. Dairy Technology?" entry and served
        # subject/percentage/age eligibility criteria for a documents
        # question, no overlap in actual topic at all. Same collision shape
        # as money/seats/marks above (high embedding similarity, zero shared
        # discriminating vocabulary previously) - "documents" and
        # "eligibility" hadn't been split out as their own asks_about
        # dimension yet.
        "documents": ["document", "documents", "certificate", "certificates",
                      "upload", "checklist", "दस्तावेज", "कागदपत्र", "प्रमाणपत्र"],
        "eligibility": ["eligibility", "eligible", "criteria", "पात्रता", "अर्हता"],
    },
    # "Is NEET mandatory" (a necessary-condition question - yes/no on whether
    # it's required at all) vs "does qualifying for NEET guarantee admission"
    # (a sufficient-condition question - yes/no on whether clearing it is
    # enough by itself) are near-opposite claims that share almost every
    # other word ("NEET", "admission", "B.V.Sc.", "MAFSU"), so their
    # embeddings sit close enough to collide - reproduced directly 2026-08-12:
    # the mandatory question's cached "Yes" was served for the guarantee
    # question, whose correct answer is "No" (merit-based selection among
    # NEET-qualified candidates, not automatic). Same collision shape as the
    # asks_about group above (near-identical wording, opposite intent), just
    # on necessity vs sufficiency instead of which figure is wanted.
    "necessity": {
        "required": ["mandatory", "compulsory", "required", "necessary",
                     "must", "अनिवार्य", "जरूरी", "आवश्यक", "கட்டாயம்"],
        "sufficient": ["guarantee", "guaranteed", "automatically",
                       "automatic", "enough", "sufficient", "गारंटी",
                       "पर्याप्त", "உறுதி"],
    },
}


# Learned-discriminator overlay (added 2026-08-12, see selflearn.py) - a
# small, additive-only JSON file merged into _CONTRAST_FORMS at read time,
# never mutating the hand-authored constant above. Deliberately restricted
# to adding a SYNONYM WORD to an EXISTING group/canonical, never a new
# group or canonical: that's the one category of change this app treats as
# safe to apply without human sign-off first, because its error is provably
# one-directional - a new synonym can only turn a would-be cache HIT into a
# MISS (slower, still correct, falls through to fresh RAG), never the
# reverse. A new group/category could instead misroute a whole class of
# questions, which is a different and much higher-stakes kind of mistake -
# see selflearn.py's SAFE_TO_AUTOMATE bar for the full reasoning.
_overlay_cache = {"mtime": None, "data": None}


def _load_learned_overlay():
    """Raw overlay records: [{id, group, canonical, word, evidence, added_at}].
    A single GLOBAL file, not per-project - _CONTRAST_FORMS is itself
    module-level and shared across every project's FAQ cache, so a learned
    addition to it is global too.
    """
    from . import config
    path = config.LEARNED_DISCRIMINATORS_PATH
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8") or "[]")
    except ValueError:
        return []


def _effective_contrast_forms():
    """_CONTRAST_FORMS with the learned overlay's words merged in, additive
    only. Cached by the overlay file's mtime (same pattern as _load's
    vector-norm cache) so an admin's add/remove takes effect on the next
    call without a server restart.
    """
    from . import config
    path = config.LEARNED_DISCRIMINATORS_PATH
    mtime = path.stat().st_mtime if path.exists() else 0
    if _overlay_cache["mtime"] == mtime and _overlay_cache["data"] is not None:
        return _overlay_cache["data"]
    merged = {group: {canonical: list(forms) for canonical, forms in alternatives.items()}
              for group, alternatives in _CONTRAST_FORMS.items()}
    for entry in _load_learned_overlay():
        group, canonical, word = entry.get("group"), entry.get("canonical"), entry.get("word")
        if group in merged and canonical in merged[group] and word not in merged[group][canonical]:
            merged[group][canonical].append(word)
    _overlay_cache["mtime"] = mtime
    _overlay_cache["data"] = merged
    return merged


def add_learned_discriminator(group, canonical, word, evidence):
    """Append one additive overlay entry. Only ever targets an EXISTING
    group/canonical in the hand-authored _CONTRAST_FORMS above - raises
    ValueError for anything else, since a new group/category is explicitly
    NOT in the safe-to-automate category (see the module comment above).
    `evidence` should be a short, non-identifying description of what
    triggered this (e.g. which discriminator groups collided) - not raw
    question/answer text, same discipline as reviewlog.py.

    Returns the new entry's id.
    """
    import secrets as _secrets

    from . import config

    if group not in _CONTRAST_FORMS or canonical not in _CONTRAST_FORMS[group]:
        raise ValueError(f"{group!r}/{canonical!r} is not an existing discriminator - "
                          "learned entries may only add a synonym to one that already exists.")
    entries = _load_learned_overlay()
    entry_id = _secrets.token_hex(6)
    entries.append({
        "id": entry_id, "group": group, "canonical": canonical, "word": word,
        "evidence": evidence, "added_at": time.time(),
    })
    path = config.LEARNED_DISCRIMINATORS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry_id


def list_learned_discriminators():
    return _load_learned_overlay()


def remove_learned_discriminator(entry_id):
    """Human override, always available - removes one overlay entry (never
    touches _CONTRAST_FORMS itself, which this can't reach). Returns False
    if entry_id doesn't exist.
    """
    from . import config

    entries = _load_learned_overlay()
    kept = [e for e in entries if e.get("id") != entry_id]
    if len(kept) == len(entries):
        return False
    path = config.LEARNED_DISCRIMINATORS_PATH
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


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


def _is_tamil(word):
    return any(0x0B80 <= ord(ch) <= 0x0BFF for ch in word)


def _matches_form(word, form):
    """Whether `word` expresses `form`.

    Devanagari and Tamil forms are matched as STEMS, not whole tokens: Hindi,
    Marathi and Tamil all agglutinate case endings onto the noun, so the
    question "आरक्षित प्रवर्गासाठी प्रवेश शुल्क किती आहे?" contains
    "प्रवेशासाठी"/"प्रवर्गासाठी" as single tokens (exact membership would match
    neither) and a Tamil question names "கல்விக்கட்டணம்" (tuition-fee,
    suffixed onto the stem "கல்விக்") the same way - which is precisely why an
    exact-match-only rule scores zero discriminators for these scripts. Latin
    forms stay exact: English barely inflects, and prefix matching there would
    have "one" match "online" and "exam" match "example", inventing
    constraints out of ordinary words.
    """
    if word == form:
        return True
    return (_is_devanagari(form) or _is_tamil(form)) and len(form) >= 3 and word.startswith(form)


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
        # _effective_contrast_forms(), not the raw _CONTRAST_FORMS constant -
        # includes any learned overlay synonyms (see that function's
        # docstring) additively, with zero effect when the overlay is empty.
        for group, alternatives in _effective_contrast_forms().items():
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


def answer_addresses_question(question, reply):
    """Whether a full-sentence ANSWER stays on-topic for the question that
    prompted it - a different comparison than compatible_questions above,
    which assumes BOTH sides are question-shaped. Added 2026-08-12 for
    validate.py's topic_mismatch check; reproduced directly why
    compatible_questions itself can't be reused as-is: "What is the
    first-year tuition fee?" (numbers {'1'}) vs its own genuinely correct
    answer "The first-year tuition fee is Rs. 27,500." (numbers
    {'1','27','500'}) failed compatible_questions's exact-set-equality rule,
    because a correct answer legitimately contains NEW numbers (the result
    figure) the question never had - that's not the same failure shape as
    two DIFFERENT questions disagreeing on "1st year" vs "2nd year".

    So numbers use SUBSET semantics here (every number/ordinal the question
    named must still appear somewhere in the reply - an answer that drops
    the year/ordinal it was asked about IS a real mismatch - but the reply
    is free to add more), while groups (fee type, category, bound) keep
    compatible_questions's exact intersection-equality: a reply naming a
    DIFFERENT fee type or category than the question asked about is exactly
    the kind of topic drift this check exists to catch, and nothing about
    "the answer contains new numbers" excuses that.
    """
    q_nums, q_groups = _discriminators(question)
    r_nums, r_groups = _discriminators(reply)
    if not q_nums <= r_nums:
        return False
    for group in set(q_groups) & set(r_groups):
        if q_groups[group] != r_groups[group]:
            return False
    return True


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
    needs_id = False
    for entry in entries:
        # Precompute each stored vector's norm once rather than per comparison.
        if "_norm" not in entry:
            entry["_norm"] = _norm(entry["vector"])
        # Backfill for entries that predate feedback support (see
        # apply_feedback) - a stable id is what match()'s result and the
        # /api/feedback endpoint use to target a specific entry, so an old
        # entry without one would otherwise never be feedback-able.
        if "id" not in entry:
            entry["id"] = secrets.token_hex(6)
            needs_id = True
    _cache[key] = (mtime, entries)
    if needs_id:
        # Written back immediately, not staged - this only runs once per
        # entry (every entry has an id from here on), and match() needs the
        # id to be real right away, not after the next flush interval.
        with _lock:
            _save(faq_path, entries)
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
    """Keep the cache bounded, never dropping curated (seeded) or user-trusted
    entries.

    Every unseen question adds an entry carrying a 768-float vector, so an
    admission rush with thousands of distinct phrasings would grow this file
    without limit - slowing every match and every write. Seeded answers are
    curated and permanent; a `trusted` entry (see apply_feedback) has earned
    the same permanence by a real student marking it correct, so it's kept on
    the same footing rather than aging out like an ordinary auto-cached guess
    nobody has vouched for yet. Everything else is disposable, oldest first.
    """
    limit = config.FAQ_MAX_ENTRIES
    if limit <= 0 or len(entries) <= limit:
        return entries
    permanent = [e for e in entries if e.get("seeded") or e.get("trusted")]
    auto = [e for e in entries if not (e.get("seeded") or e.get("trusted"))]
    auto.sort(key=lambda e: e.get("created_at", 0))
    keep_auto = max(0, limit - len(permanent))
    return permanent + auto[len(auto) - keep_auto:] if keep_auto else permanent


def match(faq_path, query_vector, tags=None, question=""):
    """Return a cached entry {answer, pages, question} if one is close enough, else None.

    Cached answers are always native-script (generation never varies by script
    preference - see rag.py); Hinglish/Tanglish is a display-time transliteration
    applied uniformly to both fresh and cached answers - that part genuinely
    has nothing script-specific to match on. But the QUESTION's own script is
    still a real signal the embedding alone doesn't reliably enforce: found
    live 2026-08-12, a Marathi (Devanagari) question matched an English-typed
    cached entry and served its English answer to a Devanagari-script
    question, purely on embedding proximity plus a `ui_language` tag that
    happened to align (the tag mechanism protects against a Hindi/English
    *selector* mismatch, not against the question's own script). See
    module docstring for what `tags` does; this is a separate, cheaper check
    the tag system was never meant to cover on its own.
    """
    tags = tags or {}
    qnorm = _norm(query_vector)
    if qnorm == 0:
        return None
    q_disc = _discriminators(question) if question else None
    # None (not "latin") when question is blank, so callers that don't pass
    # one (there are a couple of internal/legacy call sites) get the old,
    # script-agnostic behavior rather than being silently filtered to zero
    # results by a script("") default.
    q_script = detect_script(question) if question else None
    best, best_score = None, 0.0
    for entry in _load(faq_path):
        entry_tags = entry.get("tags") or {}
        if any(entry_tags.get(k) and entry_tags[k] != v for k, v in tags.items()):
            continue
        if q_script is not None and detect_script(entry["question"]) != q_script:
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
        # `verified` must ride along here, not just live on the stored entry -
        # rag.py's cache-verification-gate reads it off this returned dict to
        # decide whether to re-check a numeric hit against a fresh table
        # lookup before serving it. Omitting it silently defeated that gate
        # entirely: every hit looked like it had no verified provenance, so
        # every numeric cache collision (Mumbai served Nagpur's hostel fee,
        # etc.) kept being served exactly as before the gate was added,
        # despite the entries on disk carrying the correct `verified` field.
        return {"answer": best["answer"], "pages": best.get("pages", []),
                "question": best["question"], "score": round(best_score, 3),
                "verified": best.get("verified"), "id": best.get("id")}
    return None


def add(faq_path, question, answer, pages, vector, tags=None, seeded=False, verified=None):
    """Cache an answer for instant reuse next time.

    `seeded=True` marks a curated entry, which is exempt from pruning.

    `verified={"descriptor", "value"}` records that this answer's number came
    from tablelookup's deterministic table lookup, not the model's own
    reading. rag.py re-checks it against a fresh lookup before ever serving
    this entry again (embedding similarity alone cannot tell "Nagpur hostel
    fee" from "Mumbai hostel fee" apart - see rag.py's cache-check comment for
    the failures this caught), so it's kept out of the stored entry only when
    there was no verified figure to begin with (open-ended answers), not
    silently defaulted to something that would look like a confirmed value.
    """
    with _lock:
        entries = list(_load(faq_path))
        entry = {"id": secrets.token_hex(6), "question": question, "answer": answer,
                 "pages": pages, "vector": vector, "tags": tags or {},
                 "seeded": bool(seeded), "created_at": time.time()}
        if verified:
            entry["verified"] = {"descriptor": verified["descriptor"], "value": verified["value"]}
        entry["_norm"] = _norm(vector)
        entries.append(entry)
        _stage(faq_path, _prune(entries))
        return entry["id"]


def get_by_id(faq_path, entry_id):
    """The raw stored entry (not the trimmed shape match() returns), or None."""
    if not entry_id:
        return None
    for entry in _load(faq_path):
        if entry.get("id") == entry_id:
            return entry
    return None


def apply_feedback(faq_path, flagged_path, entry_id, liked):
    """Record a student's thumbs up/down on a specific served answer.

    Liking an entry promotes it to `trusted` - the same permanence pruning
    already gives seeded (admin-curated) entries (see _prune), earned this
    time by a real student marking the actual served answer as correct
    rather than an admin curating it up front. Cheap and immediate: a single
    like is enough, no threshold, matching how directly a "yes this was
    right" signal should count.

    Disliking removes the entry from the cache outright UNLESS it's seeded,
    already trusted, OR carries a `verified` figure from tablelookup's
    deterministic table-cell resolution (see rag.py) - a plain auto-cached
    guess with none of those gets pulled immediately, rather than risk
    serving a wrong answer to the next student who asks something similar
    (this app's standing rule: a confidently wrong cached answer is worse
    than a cache miss). The `verified` exemption is deliberate self-
    awareness, not an oversight: a single click is a noisy, unvalidated
    signal on its own - a real student might dislike a correct answer for
    being too short, too long, or just because they're testing the bot, and
    that noise must not be able to overrule a fact the system already
    confirmed against the source table by its own separate, deterministic
    mechanism. A dislike still means something even here (maybe the PHRASING
    was bad, or the underlying table cell was misidentified despite the
    figure looking plausible), so it's never silently dropped - it's always
    logged for a human to weigh, exactly because raw feedback alone isn't
    trustworthy enough to act on unilaterally. Seeded/trusted entries get
    the same protection for the same reason: each already carries a
    stronger validation signal (an admin's curation, or an earlier
    independent like) than one new click can outweigh on its own.

    Every dislike is appended to `flagged_path` regardless of whether the
    entry was removed, so there's always a reviewable trail - the caller
    (an admin) is the one who can tell "wrong" from "just needed more
    detail" or "someone was testing the bot", not this function.

    Returns False if entry_id doesn't exist (nothing to apply feedback to,
    e.g. a stale id from a since-pruned entry), True otherwise.
    """
    with _lock:
        entries = list(_load(faq_path))
        entry = next((e for e in entries if e.get("id") == entry_id), None)
        if entry is None:
            return False

        if liked:
            entry["likes"] = entry.get("likes", 0) + 1
            entry["trusted"] = True
            _stage(faq_path, entries)
            return True

        entry["dislikes"] = entry.get("dislikes", 0) + 1
        protected = bool(entry.get("seeded") or entry.get("trusted") or entry.get("verified"))

        flagged_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            flagged = json.loads(flagged_path.read_text(encoding="utf-8") or "[]")
        except (FileNotFoundError, ValueError):
            flagged = []
        flagged.append({
            # flag_id (added 2026-08-12) is the same entry's cache "id" that
            # dislikes it multiple times over its life, "id" alone can't
            # target one specific dislike event for resolve_flag below.
            "flag_id": secrets.token_hex(6),
            "id": entry["id"], "question": entry["question"], "answer": entry["answer"],
            "pages": entry.get("pages", []), "tags": entry.get("tags") or {},
            "was_seeded": bool(entry.get("seeded")), "was_trusted": bool(entry.get("trusted")),
            "was_verified": bool(entry.get("verified")), "verified_figure": entry.get("verified"),
            "removed_from_cache": not protected, "flagged_at": time.time(),
            # resolution workflow (added 2026-08-12) - see resolve_flag below.
            "resolution": "open", "resolution_note": "", "resolved_at": None,
        })
        flagged_path.write_text(json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")

        if protected:
            _stage(faq_path, entries)
        else:
            entries = [e for e in entries if e.get("id") != entry_id]
            _stage(faq_path, entries)
        return True


_FLAG_RESOLUTIONS = {"open", "dismissed", "corrected", "rule-changed"}


def resolve_flag(flagged_path, flag_id, resolution, note=""):
    """Close the loop on one flagged dislike - added 2026-08-12, the flagged
    queue was read-only before this (apply_feedback above only ever
    appends). `resolution` in _FLAG_RESOLUTIONS: "dismissed" (looked into
    it, the served answer was fine), "corrected" (a real problem, fixed -
    re-seed/re-ingest/etc, whatever the admin actually did), "rule-changed"
    (fixed at the mechanism level - a new discriminator, a prompt rule,
    matching the shape of fix this whole session's real bugs got). Purely a
    workflow marker on the flagged record itself - never re-adds, edits, or
    removes anything in the live FAQ cache; that stays apply_feedback's job.

    Returns False if flag_id doesn't exist or resolution is invalid,
    True otherwise.
    """
    if resolution not in _FLAG_RESOLUTIONS:
        return False
    with _lock:
        flagged = load_flagged(flagged_path)
        entry = next((e for e in flagged if e.get("flag_id") == flag_id), None)
        if entry is None:
            return False
        entry["resolution"] = resolution
        entry["resolution_note"] = note
        entry["resolved_at"] = time.time() if resolution != "open" else None
        flagged_path.write_text(json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


def load_flagged(flagged_path):
    """Flagged entries with flag_id/resolution backfilled for anything that
    predates the resolve_flag workflow (added 2026-08-12) - same reasoning
    as _load's own "id" backfill above: resolve_flag targets a flag_id, so
    an old entry without one would otherwise never be resolvable. server.py
    uses this for both the GET .../flagged listing and the review-summary
    aggregate, instead of reading the raw JSON directly, so both stay
    consistent and neither has to duplicate this backfill.
    """
    if not flagged_path.exists():
        return []
    try:
        flagged = json.loads(flagged_path.read_text(encoding="utf-8") or "[]")
    except ValueError:
        return []
    changed = False
    for entry in flagged:
        if "flag_id" not in entry:
            entry["flag_id"] = secrets.token_hex(6)
            entry.setdefault("resolution", "open")
            entry.setdefault("resolution_note", "")
            entry.setdefault("resolved_at", None)
            changed = True
    if changed:
        flagged_path.write_text(json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")
    return flagged


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
