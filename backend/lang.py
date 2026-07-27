"""Language detection for model routing.

Script-based: fast, deterministic, no model needed. We only need to route between
an English lane and an Indic lane, so detecting the dominant script is enough for
Devanagari/Tamil input.

Hindi vs Marathi both use Devanagari and can't be told apart by script alone -
but they route to the same Indic model, so that ambiguity doesn't matter for
routing generation itself. For TTS voice selection and for actually disambiguating
Hindi vs Marathi generation (see rag._language_hint), the request carries the
user's explicit UI language choice instead of guessing.

Script alone is NOT enough to route romanized Hindi/Marathi ("Hinglish") - most
students day-to-day type "mera fees kitna hai" or "fee kiti ahe" rather than the
native script, and that's pure Latin/ASCII, indistinguishable from English by
Unicode block. detect_romanized_indic below is a deliberately simple word-list
heuristic (not a model call - keeps this fast, free, and predictable) to catch
that case; see its docstring for the tradeoffs.
"""

# Unicode block ranges for the scripts we care about.
_TAMIL = (0x0B80, 0x0BFF)
_DEVANAGARI = (0x0900, 0x097F)  # Hindi, Marathi


def _count_in(text, block):
    lo, hi = block
    return sum(1 for ch in text if lo <= ord(ch) <= hi)


def detect_script(text):
    """Return 'tamil', 'devanagari', or 'latin' for the dominant script."""
    tamil = _count_in(text, _TAMIL)
    deva = _count_in(text, _DEVANAGARI)

    if tamil and tamil >= deva:
        return "tamil"
    if deva:
        return "devanagari"
    return "latin"


def is_indic(text):
    """True when the text is written in an Indic script (route to Indic model)."""
    return detect_script(text) in ("tamil", "devanagari")


# Common romanized function/question words. Deliberately short, high-signal words
# that rarely appear in genuine English sentences (unlike, say, "hai" which could
# theoretically collide with an English word - it doesn't here, but a couple of
# proper-noun collisions like "Om" or "Ka" are excluded to keep false positives
# low). Not exhaustive; tune by adding words as real misses turn up.
_HINGLISH_MARKERS = {
    "hai", "hain", "kya", "kyun", "kaise", "kab", "kahan", "kaunsa", "kaunsi",
    "kitna", "kitne", "kitni", "mera", "meri", "mere", "tera", "teri", "tere",
    "tumhara", "tumhari", "hum", "humein", "mujhe", "tumhe", "aapko", "aapka",
    "karo", "karna", "chahiye", "milega", "milegi", "milenge", "hoga", "hogi",
    "honge", "nahi", "nahin", "haan", "abhi", "kripya", "bataiye", "batao",
    "batayein", "chahie", "lagega", "lagegi",
}
_MARATHINGLISH_MARKERS = {
    "ahe", "ahet", "kiti", "mala", "tumhala", "tyala", "amhala", "kay", "kadhi",
    "kuthe", "kasa", "kashi", "karaycha", "karayche", "pahije", "lagto", "lagtat",
    "aahe", "aahet", "mazi", "maza", "tujhi", "tuza", "tumchi", "tumcha", "hoy",
    "nako", "havi", "havet",
}
_ROMANIZED_INDIC_MIN_HITS = 2


def detect_romanized_indic(text):
    """Best-effort: 'hi', 'mr', or None for Latin-script text that reads as
    romanized Hindi/Marathi rather than English (e.g. "mera fees kitna hai").

    Word-list heuristic, not a classifier - requires >=2 marker hits (not 1) to
    cut down on false positives from a single ambiguous/borrowed word, and only
    even runs on text detect_script already called 'latin' (native-script input
    never needs this). Ties or a mix of both marker sets lean Hindi, since it's
    the more common default; callers that also have an explicit ui_language
    should prefer that for the hi/mr choice and only use this to decide whether
    romanized-Indic handling applies at all.
    """
    # Strip trailing/leading punctuation per word - "kya?" or "hai." otherwise
    # never matches "kya"/"hai" in the marker sets, silently undercounting hits
    # (seen in testing: a real 2-hit sentence measured as 1 because the second
    # marker word had a "?" stuck to it, missing the threshold entirely).
    words = {w.strip(".,?!\"'()") for w in text.lower().split()}
    hi_hits = len(words & _HINGLISH_MARKERS)
    mr_hits = len(words & _MARATHINGLISH_MARKERS)
    if mr_hits > hi_hits and mr_hits >= _ROMANIZED_INDIC_MIN_HITS:
        return "mr"
    if hi_hits >= _ROMANIZED_INDIC_MIN_HITS:
        return "hi"
    return None
