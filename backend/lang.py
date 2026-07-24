"""Language detection for model routing.

Script-based: fast, deterministic, no model needed. We only need to route between
an English lane and an Indic lane, so detecting the dominant script is enough.

Hindi vs Marathi both use Devanagari and can't be told apart by script alone -
but they route to the same Indic model, so that ambiguity doesn't matter for
routing. For TTS voice selection (which does differ by language) the request
carries the user's explicit UI language choice instead of guessing.
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
