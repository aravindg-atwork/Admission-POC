"""Devanagari/Tamil -> romanized (Hinglish/Tanglish) transliteration.

Asking the LLM to write Hindi/Tamil directly in Roman script proved unreliable - even
an explicit, forceful instruction still came back in native script (Sarvam appears to
have a strong trained-in preference for native script). So generation always stays in
native script, which is 100% reliable, and the romanized form is produced as a
deterministic mechanical transliteration of that output - guaranteed correct every
time instead of depending on the model's mood.

Uses the Harvard-Kyoto scheme, lowercased for a casual-texting feel (HK's default
capitalizes long vowels, which nobody does when actually typing Hinglish/Tanglish).
Latin text the model already wrote as-is (English loanwords it didn't transliterate
into native script) passes through untouched, since the underlying library only
transforms Devanagari/Tamil characters.

Two known-rough edges, both handled below rather than left for the model to fix
(same reasoning as the rest of this file - deterministic beats hoping):
  1. Despite being told to keep English loanwords in Latin script, the model
     regularly writes them phonetically in Devanagari instead (सर्टिफिकेट for
     "certificate", कॉलेज for "college") - HK then transliterates the *sound*,
     not the original word, producing garbage ("sartiphiketa"). _LOANWORD_FIXUPS
     catches the common admissions-domain ones before transliteration runs.
  2. HK has no clean single-letter mapping for several nuqta consonants (ज़, ड़,
     ढ़, ग़ - Persian/Urdu-influenced sounds outside classical Sanskrit), so it
     falls back to digit-suffixed forms (ज़रूरी -> "z2aruri") that nobody
     actually types that way. _NUQTA_CLEANUP normalizes those post-transliteration
     to how people actually romanize them.
"""

import re

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

_SCRIPT_BY_LANGUAGE = {
    "devanagari": sanscript.DEVANAGARI,
    "tamil": sanscript.TAMIL,
}

# Devanagari phonetic spelling -> the actual English word. Word-boundary matched
# and applied before transliteration runs, so the real spelling survives instead
# of being mechanically transliterated into gibberish. Not exhaustive - extend as
# new garbled terms turn up in practice (same approach as lang.py's marker sets).
_LOANWORD_FIXUPS = {
    "कॉलेज": "college", "डॉक्यूमेंट": "document", "डॉक्यूमेंट्स": "documents",
    "सर्टिफिकेट": "certificate", "सर्टिफिकेट्स": "certificates",
    "फॉर्मेट": "format", "फॉर्म": "form", "एडमिशन": "admission",
    "एप्लीकेशन": "application", "ऑनलाइन": "online", "रजिस्ट्रेशन": "registration",
    "अपलोड": "upload",
}
_LOANWORD_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(_LOANWORD_FIXUPS, key=len, reverse=True))
)

# HK digit-suffix -> how people actually type it. Ordered longest-first so "r3h"
# (ढ़) is replaced before the shorter "r3" (ड़) can partially match inside it.
# The danda/double-danda sentence-enders (।/॥) transliterate to "|"/"||" under
# HK's Sanskrit convention - correct for that convention, but nobody texting in
# Hinglish writes a pipe character for a full stop, so these fold to ".": "||"
# first, so "hai||" becomes "hai." not "hai.|".
_NUQTA_CLEANUP = [
    ("z2", "z"), ("r3h", "rh"), ("r3", "r"), ("g2", "g"), ("||", "."), ("|", "."),
]

# Safety net: strip any native-script character the scheme didn't map (e.g. the
# "ॉ"/"ऑ" candra-O signs used for English "o" sounds, which HK has no mapping
# for at all and otherwise leaks through raw mid-word, e.g. "kaॉleja"). Losing an
# unmapped character is a smaller problem than a jarring mixed-script artifact.
_UNMAPPED_NATIVE = re.compile("[ऀ-ॿ஀-௿]")


def _fix_loanwords(native_text):
    return _LOANWORD_PATTERN.sub(lambda m: _LOANWORD_FIXUPS[m.group(0)], native_text)


def to_romanized(native_text, language):
    """Romanize Devanagari (Hindi/Marathi -> Hinglish) or Tamil (-> Tanglish) text.

    `language` is the value returned by lang.detect_script - anything without a
    known native-script mapping (e.g. "latin") is returned unchanged.
    """
    script = _SCRIPT_BY_LANGUAGE.get(language)
    if not script:
        return native_text
    cleaned = _fix_loanwords(native_text) if language == "devanagari" else native_text
    romanized = transliterate(cleaned, script, sanscript.HK).lower()
    for digit_form, plain_form in _NUQTA_CLEANUP:
        romanized = romanized.replace(digit_form, plain_form)
    return _UNMAPPED_NATIVE.sub("", romanized)


def to_hinglish(devanagari_text):
    """Back-compat alias for the Hindi/Marathi-only case."""
    return to_romanized(devanagari_text, "devanagari")
