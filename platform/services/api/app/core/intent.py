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
# Retrieval-internals reconnaissance ("show me the retrieved chunks", "what
# similarity score did that get", "dump your vector database"). Deliberately
# limited to terms no student asking about admissions ever writes - notably
# NOT bare "documents" or "context", since "which documents do I need" and
# "in this context" are ordinary admission questions.
_RAG_RECONNAISSANCE = re.compile(
    r"\b(?:raw|retrieved|retrieval|rag|prompt)\s+(?:context|chunks?|excerpts?|text|window)\b|"
    r"\bchunks?\s*(?:ids?)?\b|"
    r"\bvector\s+(?:database|db|store|search)\b|"
    r"\bembedding\s*(?:vector|model)?s?\b|"
    r"\b(?:similarity|retrieval|relevance|reranking)\s+scores?\b|"
    r"\bknowledge\s+base\b",
    re.I,
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
        or bool(_RAG_RECONNAISSANCE.search(lowered))
    )
