"""Strip markdown/formatting noise before text goes to a speech synthesizer.

The chat model is prompted to avoid markdown, but that's a request, not a
guarantee - a stray asterisk or bullet dash gets read aloud as literal noise
("star star", "dash") if it reaches TTS unfiltered. This is a safety net
independent of prompt compliance.
"""

import re

_MARKUP = re.compile(r"[*_`#]+")
_LEADING_BULLET = re.compile(r"^\s*[-•]\s+", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{2,}")
_WHITESPACE = re.compile(r"\s{2,}")


def clean_for_speech(text):
    text = _MARKUP.sub("", text)
    text = _LEADING_BULLET.sub("", text)
    text = _BLANK_LINES.sub(". ", text)
    text = text.replace("\n", " ")
    text = _WHITESPACE.sub(" ", text)
    return text.strip()
