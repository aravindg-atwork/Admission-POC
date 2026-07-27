"""Deterministic lookup of a figure from a table's linearized readings.

pdf.linearize_table already emits one unambiguous line per cell, e.g.
"Hostel Fees - Total for 1st Year at Nagpur: 27300", aligned mechanically at
ingest time. Those values are correct by construction. What proved unreliable
was asking the model to pick the right line out of ~45 near-identical ones: it
returned the maintenance row for a question about the total, drifted a column
group, and gave different answers to the same question on different runs. A 3B
local model got 0/4 on these; even a 30B cloud model was inconsistent.

Selecting the line is a matching problem, not a reasoning problem, so it is done
here in code. The model still writes the sentence (which keeps multilingual
phrasing working) but is handed the figure rather than choosing it.

Deliberately conservative: a confidently wrong number is worse than no shortcut
at all, so anything ambiguous returns None and the normal RAG path handles it.
"""

import re

_READING = re.compile(r"^(?P<desc>.+?):\s*(?P<value>[-–]|[0-9][0-9,./%-]*)\s*$")
_READING_HEADER = "Explicit readings of the table above:"

# "first year" and "1st Year" must compare equal, likewise for the row label
# wording students actually use versus the prospectus's own column headings.
_SYNONYMS = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th",
    "one": "1st", "two": "2nd", "three": "3rd", "four": "4th",
    "fees": "fee", "charges": "charge", "totals": "total",
}
_STOPWORDS = frozenset("""
a an the is are was were be for to in on at by with from of and or what when
how much cost costs many i my me we our you your it its that this there do does
did can could will would should shall please tell about
""".split())

_MIN_SCORE = 0.34
_MIN_MARGIN = 0.15


def _terms(text):
    words, current = [], []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    out = set()
    for w in words:
        w = _SYNONYMS.get(w, w)
        if len(w) > 1 and w not in _STOPWORDS:
            out.add(w)
    return out


def _parse_readings(chunk_text):
    """Pull (descriptor, value, terms) for each linearized reading in a chunk."""
    if _READING_HEADER not in chunk_text:
        return []
    body = chunk_text.split(_READING_HEADER, 1)[1]
    out = []
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _READING.match(line)
        if not m:
            continue
        desc, value = m.group("desc").strip(), m.group("value").strip()
        if value in {"-", "–"}:
            continue  # an empty cell, not a figure
        out.append((desc, value, _terms(desc)))
    return out


def lookup(question, chunks):
    """Return {"descriptor", "value"} when one reading clearly answers the
    question, else None.

    Two guards make this safe to trust:

    1. Discriminating terms must match. Terms that appear in some candidate
       descriptors but not all (the year, the college) are what separate one
       cell from another; if the question names one, the winner must contain
       it. This is derived from the candidates themselves rather than a
       hardcoded list of years and cities, so it holds for any table.
    2. The winner must beat the runner-up by a clear margin, so a question that
       does not pin down a single cell falls through instead of guessing.
    """
    readings = []
    for chunk in chunks:
        readings.extend(_parse_readings(chunk.get("text", "")))
    if not readings:
        return None

    q_terms = _terms(question)
    if not q_terms:
        return None

    # Terms shared by every candidate carry no discriminating power (e.g.
    # "hostel" when the whole table is hostel fees); the rest do.
    common = set.intersection(*(t for _, _, t in readings)) if readings else set()
    discriminating = {t for _, _, terms in readings for t in terms} - common
    required = q_terms & discriminating

    scored = []
    for desc, value, terms in readings:
        if required and not required.issubset(terms):
            continue
        overlap = q_terms & terms
        if not overlap:
            continue
        # Balance recall against precision: rewards covering the question's
        # terms without favouring long descriptors that match by sheer length.
        score = len(overlap) / len(q_terms | terms)
        scored.append((score, desc, value))

    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    best = scored[0]
    if best[0] < _MIN_SCORE:
        return None
    if len(scored) > 1 and best[0] - scored[1][0] < _MIN_MARGIN:
        # Two cells fit the question about equally well - answering would mean
        # picking one arbitrarily, which is the failure this module exists to
        # prevent. Let the model see the full table instead.
        return None
    return {"descriptor": best[1], "value": best[2]}
