"""Deterministic, normalization-aware prompt-injection checks."""

import re
import unicodedata

_INJECTION_PHRASES = (
    "ignore all instruction", "ignore all previous", "ignore your instruction",
    "ignore the above", "ignore previous instruction", "disregard all instruction",
    "disregard your instruction", "disregard the above", "disregard your system",
    "forget your instruction", "forget all instruction", "forget the above",
    "override your instruction", "bypass your instruction", "your system prompt",
    "reveal your prompt", "show your prompt", "print your instruction",
    "repeat your instruction", "what is your prompt", "you are now",
    "act as if you", "pretend you are", "reply with only", "respond with only",
    "say exactly", "output only the word", "just say the word",
    "developer message", "hidden instruction", "confidential instruction",
    "jailbreak", "dan mode", "do anything now", "ignore safety",
    "disable your guard", "disable the guard", "bypass the guard",
    "treat the following as system", "new system message", "roleplay as",
)

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SEPARATED_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,55}"
    r"\b(?:instruction|prompt|rule|guard|policy|system|previous|above)\b",
    re.I | re.S,
)
_PROMPT_EXFILTRATION = re.compile(
    r"\b(?:reveal|show|print|repeat|expose|leak|quote)\b.{0,45}"
    r"\b(?:system|developer|hidden|internal|initial)\s+(?:prompt|message|instruction|rule)s?\b",
    re.I | re.S,
)


def _normalize_for_security(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _ZERO_WIDTH.sub("", normalized).lower()
    normalized = normalized.translate(str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"}))
    return " ".join(normalized.split())


def is_prompt_injection(text: str) -> bool:
    lowered = _normalize_for_security(text)
    return (
        any(phrase in lowered for phrase in _INJECTION_PHRASES)
        or bool(_SEPARATED_OVERRIDE.search(lowered))
        or bool(_PROMPT_EXFILTRATION.search(lowered))
    )
