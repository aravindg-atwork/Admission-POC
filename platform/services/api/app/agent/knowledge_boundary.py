"""Student-facing uncertainty policy; never blame the University or expose RAG internals."""

import re

_BLAME_OR_INTERNAL = re.compile(
    r"(?:the prospectus|the university|mafsu)\s+(?:does not|doesn't|has not|hasn't|did not|didn't)\s+"
    r"(?:specify|state|mention|provide|include)|"
    r"\b(?:retrieval|retrieved (?:excerpts?|context)|chunks?|vector database|knowledge base|rag|retrieval confidence)\b",
    re.I,
)

SAFE_UNCERTAINTY = (
    "I don't have enough verified information to confirm that. I can explain any applicable admission rule I can verify, "
    "but for an individual or current administrative decision, please confirm with the appropriate MAFSU admission authority."
)


def apply(answer: str) -> str:
    return SAFE_UNCERTAINTY if _BLAME_OR_INTERNAL.search(answer or "") else answer
