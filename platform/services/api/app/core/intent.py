"""Deterministic intent checks ported from backend/core/intent.py."""

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
)


def is_prompt_injection(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return any(phrase in lowered for phrase in _INJECTION_PHRASES)
