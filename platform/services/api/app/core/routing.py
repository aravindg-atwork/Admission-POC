"""Deterministic programme routing at the API boundary."""

import re

SUPPORTED_PROJECTS = frozenset({"bvsc", "bfsc", "btech-dairy"})

_EXPLICIT_PATTERNS = {
    "bvsc": re.compile(
        r"\b(?:b\s*\.?\s*v\s*\.?\s*sc|bvsc|veterinary(?:\s+science)?|animal\s+husbandry|vet)\b",
        re.I,
    ),
    "bfsc": re.compile(
        r"\b(?:b\s*\.?\s*f\s*\.?\s*sc|bfsc|fishery\s+science|fisheries\s+science)\b",
        re.I,
    ),
    "btech-dairy": re.compile(
        r"\b(?:b\s*\.?\s*tech(?:nology)?|btech|dairy\s+technology)\b",
        re.I,
    ),
}


def explicitly_named_projects(question: str) -> list[str]:
    """Return only unambiguous, word-bounded programme mentions.

    The broader intent matcher deliberately accepts aliases such as ``vet`` as
    substrings. That is useful for search, but unsafe for routing: normalized
    phrases such as "have to" contain ``vet`` and previously switched a B.F.Sc.
    fee question to B.V.Sc. This boundary uses stricter explicit mentions.
    """
    return [project for project, pattern in _EXPLICIT_PATTERNS.items() if pattern.search(question)]


def effective_project(question: str, requested_project: str) -> str:
    """An explicit single programme mention overrides stale UI selection.

    Multi-programme questions deliberately retain the requested project until
    comparison fan-out is implemented; silently choosing one named course would
    be worse than preserving the existing context.
    """
    named = explicitly_named_projects(question)
    if len(named) == 1:
        return named[0]
    return requested_project if requested_project in SUPPORTED_PROJECTS else "bvsc"
