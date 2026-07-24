"""Devanagari -> Hinglish (Roman-script Hindi) transliteration.

Asking the LLM to write Hindi directly in Roman script proved unreliable - even an
explicit, forceful instruction still came back in Devanagari (Sarvam appears to have
a strong trained-in preference for native script). So generation always stays in
Devanagari, which is 100% reliable, and Hinglish is produced as a deterministic
mechanical transliteration of that output - guaranteed correct every time instead of
depending on the model's mood.

Uses the Harvard-Kyoto scheme, lowercased for a casual-texting feel (HK's default
capitalizes long vowels, which nobody does when actually typing Hinglish). Latin
text the model already wrote as-is (English loanwords it didn't transliterate into
Devanagari) passes through untouched, since the underlying library only transforms
Devanagari characters.
"""

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate


def to_hinglish(devanagari_text):
    return transliterate(devanagari_text, sanscript.DEVANAGARI, sanscript.HK).lower()
