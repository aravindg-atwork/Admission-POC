"""Strip markdown/formatting noise the model leaves in despite being told not to.

The chat model is prompted to avoid markdown, but that's a request, not a
guarantee - a stray asterisk or bullet dash reads as literal noise either way:
spoken aloud as "star star" / "dash" by TTS, or just shown as raw "**bold**" /
"- " in the chat bubble. Both call sites are safety nets independent of prompt
compliance, not a substitute for it.
"""

import re

_MARKUP = re.compile(r"[*_`#]+")
_LEADING_BULLET = re.compile(r"^\s*[-•]\s+", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{2,}")
_WHITESPACE = re.compile(r"\s{2,}")
# rag.py labels each retrieved chunk "[Page N] ..." in the prompt so the model
# can ground its answer - despite being told those labels are for its reference
# only, it occasionally echoes them back verbatim instead of paraphrasing (seen
# in testing, gemma2:2b). Since we control this exact format ourselves, stripping
# it here is zero-risk - it can only ever remove text we generated, never a
# student's or the model's own words.
_PAGE_TAG = re.compile(r"\[Page \d+\]:?\s*", re.IGNORECASE)


def clean_for_display(text):
    """Strip markdown noise from model output before it reaches the chat bubble.
    Preserves paragraph breaks/newlines (unlike clean_for_speech) since this is
    read, not spoken.
    """
    text = _PAGE_TAG.sub("", text)
    text = _MARKUP.sub("", text)
    text = _LEADING_BULLET.sub("", text)
    return text.strip()


def clean_for_speech(text):
    text = _PAGE_TAG.sub("", text)
    text = _MARKUP.sub("", text)
    text = _LEADING_BULLET.sub("", text)
    text = _BLANK_LINES.sub(". ", text)
    text = text.replace("\n", " ")
    text = _WHITESPACE.sub(" ", text)
    return text.strip()
