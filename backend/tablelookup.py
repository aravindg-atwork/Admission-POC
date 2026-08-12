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

# Bare "year"/"years" doesn't discriminate in THIS kind of table on its own:
# every row descriptor is either "for Nth Year" or "for Internship", so the
# word appears (or is implied) across virtually every candidate regardless of
# which one is meant - the actual signal is the ordinal ("4th", "first") or
# "internship" itself, both already handled by _SYNONYMS/direct match. Left
# in, it actively hurts: "What is the registration fee during the internship
# year?" scored the correct "Registration Fee for Internship" reading at 0.6
# but "...for 1st Year" and "...for 4th year" both scored 0.5 purely because
# they share the word "year" too - a 0.1 margin, under _MIN_MARGIN, so the
# correct match was discarded as "too close to call" despite the question
# being unambiguous to a human reader. Verified 2026-08-11 against a 10-case
# regression set spanning tuition/exam/hostel/NRI readings that no other case
# depends on "year" for its margin - it's redundant everywhere it currently
# resolves, since the ordinal alone already uniquely narrows the match.
_STOPWORDS |= {"year", "years"}

_MIN_SCORE = 0.34
_MIN_MARGIN = 0.15

# The source PDF renders ordinal suffixes inconsistently: "1st Year" but
# "2 nd year" / "3 rd year" / "4 th year" - a layout/kerning artifact of the
# original table, preserved as-is by pdf.py's extraction. Split apart, "4"
# alone is a single character and gets dropped below (len(w) > 1), leaving
# only the bare, non-discriminating "th" as that reading's term - so a clean
# query token "4th" (from _SYNONYMS mapping "fourth") never matches it.
# Verified: "What is the special fee for NRI candidates in the fourth year?"
# scored zero candidates for exactly this reason, on a reading that otherwise
# matches perfectly. Joining the split ordinal before tokenizing fixes the
# term at the source, for both the question and every reading alike.
_SPLIT_ORDINAL = re.compile(r"(\d+)\s+(st|nd|rd|th)\b", re.I)


def _terms(text):
    text = _SPLIT_ORDINAL.sub(r"\1\2", text)
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
        # Two or more cells fit the question about equally well - normally
        # that means picking one would be an arbitrary guess, the failure
        # this module exists to prevent. But if EVERY cell within margin of
        # the best score holds the same value, there is no actual ambiguity
        # in the answer, only in which row's label gets shown - a flat fee
        # that doesn't vary by year (e.g. "special fee for Goa State
        # candidates", same Rs.75,000 every year) ties 5-ways across the
        # year-1/2/3/4/internship readings when the question names no year,
        # and used to fall through to the model despite every tied reading
        # agreeing. Still declines the moment any tied reading disagrees.
        tied = [s for s in scored if best[0] - s[0] < _MIN_MARGIN]
        if any(s[2] != best[2] for s in tied):
            return None
    return {"descriptor": best[1], "value": best[2]}
