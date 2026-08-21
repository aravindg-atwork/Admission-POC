"""Deterministic post-generation safeguards for the B.V.Sc. slice."""

import re

from ..core import programs

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*%?")
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)


def _extract_numbers(text: str) -> set[str]:
    return {
        number.replace(",", "").rstrip("%").strip()
        for number in _NUMBER_RE.findall(text)
        if len(number.replace(",", "").rstrip("%").strip()) >= 2
    }


def deterministic_checks(question: str, context: str, reply: str,
                         own_project_id: str = "bvsc") -> list[str]:
    reasons = []
    unsupported = _extract_numbers(reply) - _extract_numbers(context)
    if unsupported:
        reasons.append(f"unsupported_number: {', '.join(sorted(unsupported))}")
    reply_programmes = set(programs.detect_programs_multi(reply))
    question_programmes = set(programs.detect_programs_multi(question))
    foreign = reply_programmes - {own_project_id} - question_programmes
    if foreign:
        reasons.append(f"foreign_programme_mention: {', '.join(sorted(foreign))}")
    return reasons


def autofix(reply: str) -> str:
    return _NUMBERED_LIST_RE.sub("", reply)
