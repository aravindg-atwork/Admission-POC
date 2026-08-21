"""Student vocabulary to prospectus vocabulary for lexical retrieval.

Ported from backend/core/vocabulary.py. Expansion is additive and is never
embedded; it only closes measured register gaps in keyword scoring and exact
table lookup.
"""

import re

_TERM_MAP = (
    (r"\b(sc|st|obc|vj|dt|nt|sbc|sebc|ews|scheduled caste|scheduled tribe|"
     r"other backward|nomadic|backward class|caste|reservation|reserved|"
     r"quota)\b", "Reserved category candidate reservation"),
    (r"\b(open|general|unreserved|ur)\s+(category|candidate|student)?\b",
     "Unreserved category"),
    (r"\b(vet|veterinary|bvsc|b\.?v\.?sc)\b",
     "Veterinary Science and Animal Husbandry"),
    (r"\b(dairy\s*tech\w*|btech\s*dairy|b\.?tech)\b", "Dairy Technology"),
    (r"\b(fishery|fisheries|fish|bfsc|b\.?f\.?sc)\b", "Fishery Science"),
    (r"\b(12th|12 th|twelfth|xii|hsc|plus two|\+2|10\+2|higher secondary)\b",
     "XII Std 10+2 qualifying examination"),
    (r"\b(marks?|score|percentage|percent|cut ?off|aggregate)\b",
     "minimum marks percentage"),
    (r"\b(cet|mht ?cet|mhtcet|entrance|entrance exam)\b",
     "MHT-CET Common Entrance Test"),
    (r"\bneet\b", "NEET-UG"),
    (r"\b(hostel|accommodation|room|mess)\b", "hostel accommodation"),
    (r"\b(fees?|cost|charges?|payment|amount)\b", "fee structure"),
    (r"\b(documents?|certificates?|papers?)\b", "documents certificate required"),
    (r"\b(seats?|intake|vacanc\w+)\b", "availability of seats intake"),
    (r"\b(domicile|resident|residence|maharashtra state)\b",
     "domicile residence certificate Maharashtra State"),
    (r"\b(subjects?|stream|pcb|pcm)\b", "Physics Chemistry subjects"),
)

_COMPILED = tuple((re.compile(pattern, re.IGNORECASE), addition)
                  for pattern, addition in _TERM_MAP)


def expansion_terms(text: str) -> list[str]:
    if not text:
        return []
    found = []
    for pattern, addition in _COMPILED:
        if pattern.search(text) and addition not in found:
            found.append(addition)
    return found


def expand(text: str) -> str:
    terms = expansion_terms(text)
    return f"{text} {' '.join(terms)}" if terms else text
