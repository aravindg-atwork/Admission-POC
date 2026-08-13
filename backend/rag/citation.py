"""Exact source citation: the real page AND line in the prospectus PDF, with
the line quoted verbatim.

Used when a student pushes back on an answer (see guards.py's
_dispute_guard). Normal answers deliberately show no page references at all
any more - a row of "p. 5 p. 9 p. 13" under every reply reads as homework,
and the student is here precisely because reading the PDF did not work. A
citation earns its place at exactly one moment: when someone says "that's
wrong". Then it should be specific enough to settle the question outright.

Why this re-extracts rather than reading the vector store
--------------------------------------------------------
Chunks carry only {page, text} - no line offsets - so a line number cannot
come from the store, and adding one would mean re-ingesting (and re-paying
for) every project's embeddings. The source PDF is kept per project
(projects.prospectus_path), so the page's lines are recoverable on demand
instead. This path only runs when an answer is actually challenged, so a
one-off parse is affordable where it would not be per-request.

Why NOT pdf.extract_pages
-------------------------
That function drops blank lines AND running headers/footers before joining,
because both are noise for embedding. Counting lines in its output would
therefore produce a number that does not match what a person counts looking
at the same page - off by however much furniture sat above the line. A
citation that is confidently wrong about where to look is worse than no
citation, and would be the same "sounds authoritative, isn't" failure this
assistant keeps being corrected for. So this module does its own extraction
in raw layout mode and counts visible (non-blank) lines exactly as they
appear on the page, furniture included.
"""

import re
import threading

from ..core.textclean import clean_for_display  # noqa: F401  (kept for callers)
from ..storage import projects

# (path, mtime) -> {page_number: [line, ...]}. A prospectus is a few MB and
# parses in seconds; re-parsing per dispute would be pure waste, and keying
# on mtime means a re-uploaded prospectus invalidates itself with no explicit
# call, exactly like vectorstore.load's own cache.
_cache = {}
_cache_lock = threading.Lock()

_STOPWORDS = frozenset("""
a an the is are was were be been being of for to in on at by with from as and or
not no do does did what when where which who whom how why can could shall should
will would may might must i me my we our you your it its this that these those
if then than so such about into over under after before during per any all
""".split())


def _terms(text):
    out, word = set(), []
    for ch in (text or "").lower():
        if ch.isalnum() or ch in "/%.":
            word.append(ch)
        elif word:
            out.add("".join(word).strip("."))
            word = []
    if word:
        out.add("".join(word).strip("."))
    return {w for w in out if len(w) > 2 and w not in _STOPWORDS}


def _page_lines(pdf_path):
    """{page_number: [visible line, ...]} counted as a human would.

    Blank lines are skipped (nobody counts those), everything else is kept
    in document order including headers/footers, so line N here is the Nth
    line of text a person sees on that page.
    """
    if not pdf_path.exists():
        return {}
    key = (str(pdf_path), pdf_path.stat().st_mtime)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001 - a citation must never break a reply
            print(f"[citation] could not open {pdf_path}: {exc!r}")
            return {}
        pages = {}
        for number, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text(extraction_mode="layout") or ""
            except Exception:  # noqa: BLE001 - one bad page must not kill the rest
                continue
            lines = [ln.rstrip() for ln in raw.split("\n") if ln.strip()]
            if lines:
                pages[number] = lines
        _cache[key] = pages
        return pages


_NUMBER_RE = re.compile(r"\d")


def locate(project_id, claim, candidate_pages, limit=2):
    """Best page+line matches for `claim`, searched within `candidate_pages`.

    Returns [{"page": int, "line": int, "text": str}], most relevant first,
    or [] when nothing scores above a floor - an empty result means the
    caller must not cite anything rather than cite its best guess.
    """
    pages = _page_lines(projects.prospectus_path(project_id))
    if not pages:
        return []
    claim_terms = _terms(claim)
    if not claim_terms:
        return []
    claim_has_number = bool(_NUMBER_RE.search(claim or ""))

    scored = []
    for page_number in candidate_pages or pages.keys():
        for index, line in enumerate(pages.get(page_number, []), start=1):
            line_terms = _terms(line)
            if not line_terms:
                continue
            overlap = len(claim_terms & line_terms)
            if not overlap:
                continue
            # Overlap as a fraction of the LINE's own vocabulary, not the
            # claim's: a claim summarizing several lines would otherwise
            # score every one of them equally, while this favors the line
            # that is most specifically about what was claimed.
            score = overlap / (len(line_terms) ** 0.5)
            # A disputed fact is usually a number (a fee, a percentage, a
            # date). When the claim contains one, a candidate line that also
            # carries a number is far more likely to be the actual source.
            if claim_has_number and _NUMBER_RE.search(line):
                score *= 1.4
            scored.append((score, page_number, index, line))

    if not scored:
        return []
    scored.sort(key=lambda row: row[0], reverse=True)
    # Floor: below this the "match" is one or two incidental shared words,
    # which would produce an authoritative-looking pointer to an unrelated
    # line - the exact failure this module exists to avoid.
    best = scored[0][0]
    return [
        {"page": page_number, "line": index, "text": " ".join(line.split())}
        for score, page_number, index, line in scored[:limit]
        if score >= max(0.6, best * 0.55)
    ]
