"""Prospectus PDF extraction and structure-aware chunking.

Uses pypdf (pure Python, no compiled deps) so it runs on the host. Every chunk
keeps the page it came from so answers can cite prospectus pages.

Extraction deliberately uses pypdf's "layout" mode and KEEPS the line structure
and column whitespace, rather than collapsing everything to single-spaced prose.
That whitespace is load-bearing: this prospectus carries its fee, refund and
hostel-charge data in tables, and a flattened table is actively dangerous - the
hostel table is a 3x3 grid (Nagpur/Mumbai/Shirwal-Parbhani-Udgir x 1st / 2nd&3rd
/ 4th year) whose column legend is only defined *after* the table. Collapsed to
one line it becomes a bare run of nine numbers with nothing tying each to its
college or year, and the model confidently pairs the wrong ones (observed: it
reported the 2nd/3rd-year total as the 1st-year figure). Preserving the grid
lets the model actually read down a column.

Two kinds of noise are stripped, both of which would otherwise land in every
chunk and pollute every embedding:
  - Repeated page furniture (site URL, running footer with page number). Detected
    by frequency across pages rather than hardcoded, so this still works when a
    different institution's prospectus is ingested into another project.
  - Mojibake: the source PDF renders a Marathi banner ("मतदार व्हा, मतदान करा")
    through a legacy non-Unicode font, so it extracts as Latin-1 garbage like
    "´ÖŸÖ¤üÖ¸ü ¾ÆüÖ". It is unreadable to the model and to a reader, and it
    appears on nearly every page.
"""

import re
from collections import Counter

from pypdf import PdfReader

from . import config

# Characters typical of legacy-font mojibake: Latin-1 supplement and Latin
# Extended-A symbol/accent range. Deliberately does NOT include Devanagari
# (U+0900-097F) or Tamil (U+0B80-0BFF), so genuine Indic text is never touched.
_MOJIBAKE_CHARS = re.compile(r"[ -ÿĀ-ſʰ-˿]")
_PAGE_FURNITURE_RATIO = 0.25


def _is_mojibake(token):
    """True for a token that is mostly legacy-encoding garbage.

    Requires 2+ suspicious characters AND a high density of them, so ordinary
    accented words (e.g. a name with an acute accent) survive - only sequences
    that are overwhelmingly symbol-soup get dropped.
    """
    hits = len(_MOJIBAKE_CHARS.findall(token))
    return hits >= 2 and hits / max(len(token), 1) >= 0.4


def _strip_mojibake(line):
    kept = [t for t in line.split(" ") if not _is_mojibake(t)]
    return " ".join(kept)


def _furniture_key(line):
    """Normalize a line so a running footer matches across pages.

    Page numbers are the only thing that varies in a running header/footer, so
    digits are dropped before comparing - otherwise "... 24 B.V.Sc. & A.H." and
    "... 25 B.V.Sc. & A.H." look like two distinct lines and neither is ever
    detected as repeated furniture.
    """
    return re.sub(r"\d+", "", line).strip().lower()


def _find_page_furniture(raw_pages):
    """Lines that recur on a large share of pages - headers, footers, site URL."""
    counts = Counter()
    for text in raw_pages:
        seen = {_furniture_key(l) for l in text.split("\n") if l.strip()}
        counts.update(k for k in seen if k)
    threshold = max(2, len(raw_pages) * _PAGE_FURNITURE_RATIO)
    return {key for key, n in counts.items() if n >= threshold}


def _clean_line(line):
    """Trim trailing space and cap runs of spaces used for column alignment.

    Long whitespace runs are what encode the table grid, so they are preserved -
    but capped, since pypdf's layout mode can emit 40+ spaces for a single gap
    and that burns chunk budget without adding meaning.
    """
    line = _strip_mojibake(line)
    line = re.sub(r" {12,}", "           ", line)
    return line.rstrip()


def extract_pages(pdf_path):
    """Extract per-page text with table layout preserved and furniture removed."""
    reader = PdfReader(str(pdf_path))
    raw_pages = [
        (page.extract_text(extraction_mode="layout") or "") for page in reader.pages
    ]
    furniture = _find_page_furniture(raw_pages)

    pages = []
    for i, raw in enumerate(raw_pages, start=1):
        lines = []
        for line in raw.split("\n"):
            if not line.strip():
                continue
            if _furniture_key(line) in furniture:
                continue
            cleaned = _clean_line(line)
            if cleaned.strip():
                lines.append(cleaned)
        text = "\n".join(lines)
        if text.strip():
            pages.append({"page": i, "text": text})
    return pages


_NUMERIC_FIELD = re.compile(r"^[-–]$|^[0-9][0-9,./%-]*$|^Rs\.?[0-9]")


def _numeric_column_count(line):
    return sum(1 for f in _fields(line) if _NUMERIC_FIELD.match(f))


def is_table_page(text):
    """True when a page carries real tabular data (fees, refund tiers, schedule).

    Counts lines holding 2+ *numeric* whitespace-separated columns, and requires
    several of them. Counting bare multi-space runs is not enough - this PDF is
    fully justified, so ordinary prose is full of wide gaps too and a looser
    test flagged 41 of 59 pages.

    The 2-column threshold matters: an earlier 3-column rule missed the
    admission-programme schedule (Annexure XIV), whose rows are just
    "<n> <description> <date>". That page then chunked as prose and the model
    answered the application deadline with the CVC deadline instead - two
    different rows of the same table. Requiring 4+ such rows keeps stray prose
    lines that happen to end in a number from dragging a page in.
    """
    rows = sum(1 for l in text.split("\n") if _numeric_column_count(l) >= 2)
    return rows >= 4


# Short uppercase column codes like "N", "M", "S/P/U" - the per-column keys in
# a fee grid, as opposed to the row-label header ("Particulars of Fees").
_COLUMN_CODE = re.compile(r"^[A-Z][A-Za-z]{0,2}(?:/[A-Z][A-Za-z]{0,2})*$")


# A markdown table row, as produced by OCR: "| 2 | Tuition Fee | 27500 | ... |".
# The separator row "|---|---|" is structure, not data.
_MD_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _fields(line):
    """Cells of a row, from either extractor.

    pypdf reconstructs columns with runs of spaces; OCR emits real markdown
    pipes. Splitting only on whitespace scored every markdown row as zero
    columns, so an OCR'd fee grid was not recognised as a table at all and
    chunked as prose - which would have split it away from its header row and
    thrown away the whole benefit of OCR.
    """
    stripped = line.strip()
    if _MD_ROW.match(stripped) and not _MD_SEPARATOR.match(stripped):
        return [f.strip() for f in stripped.strip("|").split("|") if f.strip()]
    return [f for f in re.split(r" {2,}", stripped) if f]


# Column headings of a single-level fee grid: "1st Year", "2 nd year",
# "Internship (1 year)", "Total". Deliberately narrow - this decides whether a
# line is a header row at all, and a loose pattern matched ordinary justified
# prose ("covered from 1st to 4th") on a page that holds no such table.
_YEAR_COLUMN = re.compile(r"^(?:\d\s*(?:st|nd|rd|th)|internship|total)\b|\byear\b", re.I)
_MAX_COLUMN_HEADING = 22


def _row_cells(fields):
    """(fields, values) with a leading serial number dropped.

    The college fee rows start with the "Sr. No." column ("2  Tuition Fee  27500
    ..."), which is numeric and would otherwise be counted as a data value -
    making a 5-column row look like 6 and knocking the column count off by one
    for the entire table.
    """
    values = [f for f in fields if _NUMERIC_FIELD.match(f)]
    if values and re.fullmatch(r"[0-9]{1,3}", fields[0]) and fields[0] == values[0]:
        return fields[1:], values[1:]
    return fields, values


def _linearize_column_table(text):
    """Readings for a fee grid with ONE header row of year columns.

    linearize_table's two-level path keys off short column CODES (N, M, S/P/U)
    under a group header, which is the hostel table's shape (Annexure III-B).
    The college fee table (III-A) and the NRI table (III-C) are laid out
    differently - a single header row naming the years directly - so that path
    never fired for them and they produced no readings at all. That left the
    single most-asked figures in the prospectus (tuition, registration,
    examination and internship fees) with no verified reading, so tablelookup
    returned None and the model was back to eyeballing the grid. Measured
    consequence: the Marathi answer to "what is the first year tuition fee"
    quoted Rs.62635, the total admission fee, and a plain internship-fee
    question was answered Rs.34400 - the NRI row - because nothing labelled
    which table that number came from.

    Same conservatism as the two-level path: the column count is taken as the
    modal count across candidate rows, the header must sit above the first data
    row and actually read like year columns, and any row whose value count
    disagrees is skipped rather than guessed at.
    """
    lines = text.split("\n")
    candidates = []
    for i, line in enumerate(lines):
        fields, values = _row_cells(_fields(line))
        if len(values) >= 3 and len(fields) > len(values):
            candidates.append((i, fields, values))
    if not candidates:
        return []

    width = Counter(len(v) for _, _, v in candidates).most_common(1)[0][0]

    header = None
    for i in range(candidates[0][0] - 1, -1, -1):
        fields = _fields(lines[i])
        if len(fields) < width:
            continue
        columns = fields[-width:]
        if all(len(c) <= _MAX_COLUMN_HEADING for c in columns) and \
                sum(bool(_YEAR_COLUMN.search(c)) for c in columns) >= max(2, width // 2):
            header = (i, columns)
            break
    if not header:
        return []
    header_idx, columns = header

    # Start the body at the first real data row. The header wraps across several
    # lines in the source ("2nd" on the header line, "year" and "(1 1/2 year)"
    # below it), and those remnants are label-only lines, so _label_context
    # happily glued them onto the first row - producing "year) Registration Fee".
    body = lines[header_idx + 1:]
    first_data = next((n for n, l in enumerate(body)
                       if len(_row_cells(_fields(l))[1]) == width), None)
    if first_data is None:
        return []
    body = body[first_data:]

    caption = _find_caption(lines[:header_idx])
    readings = []
    for n, line in enumerate(body):
        fields, values = _row_cells(_fields(line))
        if len(values) != width or len(fields) == len(values):
            continue
        own = " ".join(f for f in fields if not _NUMERIC_FIELD.match(f))
        label = " ".join(_label_context(body, n) + [own]).strip(" :*#")
        label = _dedupe_tokens(re.sub(r"\s+", " ", label))
        if not label:
            continue
        for column, value in zip(columns, values):
            reading = (f"{caption} - " if caption else "") + f"{label} for {column}: {value}"
            readings.append(re.sub(r"\s{2,}", " ", reading))
    return readings


def _dedupe_tokens(label):
    """Collapse runs of the same token: a currency unit repeated once per column
    ("Special Fees U.S. U.S. U.S. U.S. U.S.") is an artifact of the row's text
    cells, and the repetition dilutes tablelookup's term-overlap scoring.
    """
    out = []
    for token in label.split():
        if not out or out[-1].lower() != token.lower():
            out.append(token)
    return " ".join(out)


def linearize_table(text):
    """Append an explicit, unambiguous reading of each numeric table row.

    Preserving the visual grid was necessary but NOT sufficient: asked for the
    2nd/3rd-year Nagpur hostel total the model returned the 1st-year Mumbai
    figure, having drifted one column group while eyeballing nine numbers under
    a two-level header (year-group over college). Expecting a language model to
    index reliably into a 2-D grid rendered in spaces is a bad bet.

    So the grid is kept for context AND each data row is restated as flat
    "row - group / column: value" lines, where alignment is done here in code
    rather than left to the model. Deliberately conservative: it only fires when
    the sub-header count divides evenly into the group count (so each group
    spans an equal, inferable span) and the row's value count matches the
    sub-header count. Anything it can't map confidently is left alone rather
    than guessed at - a wrong explicit label would be worse than none.
    """
    lines = text.split("\n")
    sub_idx = next(
        (i for i, l in enumerate(lines)
         if len(_fields(l)) >= 4 and _looks_like_subheader(_fields(l))),
        None,
    )
    if sub_idx is None:
        return _append_readings(text, _linearize_column_table(text))

    # Only true column codes (N, M, S/P/U) - not the row-label header ("Sr.",
    # "No.", "Particulars of Fees"), which names the label column, not a data one.
    subs = [s for s in _fields(lines[sub_idx]) if _COLUMN_CODE.match(s)]
    groups = _find_group_header(lines[:sub_idx])
    if not subs or not groups or len(subs) % len(groups):
        return _append_readings(text, _linearize_column_table(text))
    span = len(subs) // len(groups)

    # A row's label is often wrapped across lines in the source ("a)Hostel" on
    # the row itself, "Maintenance" on the next), so a label taken from the data
    # line alone reads as "a)Hostel" - ambiguous enough that the model picked
    # that component row when asked for the "total hostel fee". Stitching the
    # neighbouring label-only lines back on restores "Hostel Charges a)Hostel
    # Maintenance", which is distinguishable from "Total".
    body = lines[sub_idx + 1:]
    legend_map = _parse_legend(lines)
    caption = _find_caption(lines[:sub_idx])
    readings = []
    for n, line in enumerate(body):
        fields = _fields(line)
        values = [f for f in fields if _NUMERIC_FIELD.match(f)]
        if len(values) != len(subs) or len(fields) == len(values):
            continue  # no row label, or column count doesn't line up - skip
        own = " ".join(f for f in fields if not _NUMERIC_FIELD.match(f))
        label = " ".join(_label_context(body, n) + [own]).strip(" :*#")
        label = re.sub(r"\s+", " ", label)
        for i, (sub, val) in enumerate(zip(subs, values)):
            group = groups[i // span] if groups else ""
            where = legend_map.get(sub, sub)
            group = re.sub(r"\s*\(Rs\.?\)\s*", "", group).strip()
            # Phrased as a natural sentence rather than "label - group / code".
            # Terse codes ("N") share almost no surface form with how a student
            # asks ("at Nagpur"), so an expanded, readable line is far easier for
            # the model to match to the question - and to quote without mixing up
            # which row it came from.
            # Caption prefix ("Hostel Fees - Total for 1st Year at Nagpur")
            # matters: without it the Total line contained no subject noun, so
            # a question about the "hostel total" matched a component row that
            # did contain "Hostel" and the model quoted maintenance instead.
            line = f"{caption} - {label} for {group} at {where}: {val}" if caption \
                else f"{label} for {group} at {where}: {val}"
            readings.append(re.sub(r"\s{2,}", " ", line))

    return _append_readings(text, readings)


def _append_readings(text, readings):
    """Attach the linearized readings block, or return the text untouched."""
    if not readings:
        return text
    return text + "\n\nExplicit readings of the table above:\n" + "\n".join(readings)


def _find_caption(lines_above):
    """The table's own title, e.g. "HOSTEL FEES" from "[B]  HOSTEL FEES:".

    Searched bottom-up so the nearest heading above the table wins.
    """
    for line in reversed(lines_above):
        raw = re.sub(r"^\s*\[[A-Z]\]\s*", "", line.strip()).strip(" :")
        if 3 <= len(raw) <= 60 and raw.upper() == raw and re.search(r"[A-Z]{3}", raw):
            return raw.title()
    return ""


def _parse_legend(lines):
    """Map short column codes to their full names from an abbreviations line.

    "Abbreviations: N=Nagpur; M=Mumbai; S=Shirwal; P=Parbhani; U=Udgir" becomes
    {"N": "Nagpur", ...}, and a composite code like "S/P/U" expands to
    "Shirwal/Parbhani/Udgir" so the reading names the actual colleges.
    """
    pairs = {}
    for line in lines:
        if "=" not in line:
            continue
        for m in re.finditer(r"\b([A-Z])\s*=\s*([A-Za-z][A-Za-z .-]*)", line):
            pairs[m.group(1)] = m.group(2).strip(" .;-")
    if not pairs:
        return {}

    expanded = dict(pairs)
    for code in set(re.findall(r"[A-Z](?:/[A-Z])+", " ".join(lines))):
        parts = [pairs.get(c, c) for c in code.split("/")]
        expanded[code] = "/".join(parts)
    return expanded


def _label_context(body, n):
    """Label-only lines wrapping a data row - the line just before and just after.

    Only lines with no numeric fields qualify, so a neighbouring data row is
    never mistaken for label text.
    """
    out = []
    for j in (n - 1, n + 1):
        if not (0 <= j < len(body)):
            continue
        raw = body[j].strip()
        # Drop a leading serial number ("2  Maintenance") before judging whether
        # this is a label-only line - otherwise the row number makes a pure text
        # continuation look numeric and the wrapped label is lost, which is how
        # "Hostel Maintenance" degraded to the meaningless "a)Hostel".
        fields = _fields(body[j])
        if fields and re.fullmatch(r"\d{1,2}", fields[0]):
            fields = fields[1:]
        if not fields or any(_NUMERIC_FIELD.match(f) for f in fields):
            continue
        # Legend and footnote lines sit directly under the last data row, so the
        # "Total" row would otherwise absorb "Abbreviations: N=Nagpur; ..." into
        # its label. They describe the table, not the row.
        if len(raw) > 60 or "=" in raw or re.match(r"^(abbrev|note|\*|#)", raw, re.I):
            continue
        out.append(" ".join(fields))
    return out


def _looks_like_subheader(fields):
    """A row of short column labels (N, M, S/P/U ...) rather than data or prose."""
    short = [f for f in fields if len(f) <= 6 and not _NUMERIC_FIELD.match(f)]
    return len(short) >= 4 and len(short) >= len(fields) - 2


def _find_group_header(lines_above):
    """The nearest line above the sub-header holding the spanning group labels.

    Keeps only fields naming a real span (e.g. "1st Year (Rs.)"); layout mode
    sometimes splits a trailing unit into its own field, and a bare "(Rs.)"
    counted as a group would throw the whole column-to-group division off.
    """
    for line in reversed(lines_above):
        groups = [f for f in _fields(line) if re.search(r"year", f, re.I)]
        if len(groups) >= 2:
            return groups
    return []



# --- Section / topic tagging -------------------------------------------
#
# A prospectus is not a flat bag of pages: it is a numbered document with
# stable sections ("6. RESERVATION OF SEATS", "ANNEXURE - III FEE
# STRUCTURE"), and every one of the six prospectuses carries 19-26 of them.
# Tagging each chunk with the section it came from lets retrieval aim at the
# right part of the book instead of searching the whole thing.
#
# Why it matters, measured on "what is the application fee for bvsc": the
# top-15 shipped ~29,700 chars to the model, of which the genuinely
# fee-related chunks were a minority - the rest was the table of contents, a
# reservation Government Resolution, portal signup steps and a paragraph
# about the Director of Instruction. That noise costs generation time and is
# precisely how a figure from the wrong part of the document gets quoted.
#
# Deterministic, no model call: the headings are already in the text.
_SECTION_RE = re.compile(
    r"^(ANNEXURE\s*[-–—]?\s*[IVXLC0-9]+|\d{1,2}[.)]\s+[A-Z][A-Z /&,()'-]{4,})")

# Heading keywords -> topic. First match wins, so the more specific
# entries come first. "general" is the deliberate catch-all: a chunk whose
# section says nothing useful must stay retrievable rather than be filtered
# into a corner.
_TOPIC_RULES = (
    ("fees", ("FEE", "FEES", "PAYMENT", "REFUND")),
    ("quota", ("RESERVATION", "QUOTA")),
    ("eligibility", ("ELIGIBILITY", "SELECTION CRITERIA", "QUALIFYING")),
    ("seats", ("AVAILABILITY OF SEATS", "INTAKE", "SEATS")),
    ("dates", ("SCHEDULE", "PROGRAMME OF", "TIME TABLE", "IMPORTANT DATES")),
    ("documents", ("CERTIFICATE", "DOCUMENT", "AFFIDAVIT", "UNDERTAKING")),
    ("process", ("INSTRUCTION", "ADMISSION PROCEDURE", "CAP", "ALLOTMENT",
                  "CANCELLATION", "GRIEVANCE", "REGISTRATION")),
    ("academics", ("SYSTEM OF EDUCATION", "DISCIPLINE", "CURRICULUM",
                    "ACADEMIC", "ATTENDANCE", "EXAMINATION")),
)


def _topic_for(heading):
    upper = (heading or "").upper()
    for topic, keywords in _TOPIC_RULES:
        if any(k in upper for k in keywords):
            return topic
    return "general"



# Content beats section. A chunk's SECTION is a good default, but some facts
# live nowhere near the heading that describes them: the application fee is
# stated under "7. IMPORTANT INSTRUCTIONS TO CANDIDATES", so section-tagging
# filed it as "process" while a question about it boosted "fees" - actively
# ranking the ANNEXURE-III admission-fee tables ABOVE the one chunk holding
# the answer. Observed: a comparison answered "the application fee is not
# explicitly mentioned for B.V.Sc." one message after quoting it correctly.
#
# Application and admission fees are separated deliberately. They are
# different amounts for different things (Rs. 1,000 to apply; Rs. 62,635 to
# join) and share the word "fee", which is exactly how they get confused.
_CONTENT_TOPIC_RULES = (
    ("application_fee", ("application fee", "application fees")),
    ("fees", ("admission fee", "admission fees", "college fees", "fee structure",
               "hostel fees", "tuition fee")),
)


def _content_topic(text):
    lowered = " ".join((text or "").split()).lower()
    for topic, phrases in _CONTENT_TOPIC_RULES:
        if any(ph in lowered for ph in phrases):
            return topic
    return None


def _page_sections(pages):
    """{page_number: (heading, topic)} with the heading carried FORWARD.

    A section starts at its heading and runs until the next one, so most
    pages carry no heading of their own and inherit the one above them -
    page 40's fee table has no "FEE STRUCTURE" line on it, that sits on page
    39. Without carrying it forward the pages that actually hold the numbers
    would be the ones left untagged.
    """
    out, current = {}, ("", "general")
    for page in pages:
        # Scan the WHOLE page, not just the top. A section does not have to
        # begin on a fresh page - "4. THE ELIGIBILITY / SELECTION CRITERIA
        # FOR ADMISSION" starts on line 13 of its page, and an 8-line window
        # missed it, leaving the entire eligibility section tagged with
        # whatever section preceded it (2 chunks tagged eligibility across
        # the whole prospectus, for one of its most-asked-about topics).
        #
        # The FIRST heading on a page decides that page's tag and the LAST
        # one carries forward, which is right when a page ends one section
        # and starts the next: the bulk of that page still belongs to the
        # section it opened under.
        lines = [" ".join(l.split()) for l in page["text"].split("\n")]
        lines = [l for l in lines if l]
        first_heading = None
        for i, text in enumerate(lines):
            if len(text) >= 70 or not _SECTION_RE.match(text):
                continue
            # "ANNEXURE - III" alone says nothing about what is in it; the
            # words that do ("FEE STRUCTURE") sit on the following line, and
            # these headings wrap narrowly. Pull the next couple of short
            # lines into the heading before deciding the topic - without
            # this every ANNEXURE, including the entire fee structure,
            # classified as "general".
            heading = " ".join([text] + [l for l in lines[i + 1:i + 3] if len(l) < 60])
            resolved = (heading[:120], _topic_for(heading))
            if first_heading is None:
                first_heading = resolved
            current = resolved
        out[page["page"]] = first_heading or current
    return out


def chunk_pages(pages):
    """Split each page into chunks on line boundaries, never mid-line.

    The previous version sliced at a fixed character count regardless of
    content, which routinely cut a table row - or a numbered refund tier - in
    half, so a percentage could land in one chunk and the condition it applies
    to in another. Accumulating whole lines keeps each row intact.

    Table pages are never split at all. A table's meaning lives in its header
    row and its legend, which sit at the top and bottom of the grid - split the
    page and a middle chunk becomes a naked run of numbers with nothing to align
    them to, which is exactly how the wrong figure gets quoted with confidence
    (observed before this change: the hostel table's 2nd/3rd-year total was
    reported as the 1st-year fee). These pages top out around 4KB, well inside
    the embedding model's window, so keeping them whole costs nothing.
    """
    sections = _page_sections(pages)
    chunks = []
    for entry in pages:
        page, text = entry["page"], entry["text"]
        if is_table_page(text):
            chunks.extend(_chunk_table_page(page, text))
            continue
        lines = text.split("\n")
        current, size = [], 0
        for line in lines:
            # +1 for the newline that rejoins them.
            if current and size + len(line) + 1 > config.CHUNK_CHARS:
                chunks.append({"page": page, "text": "\n".join(current)})
                current = _overlap_tail(current)
                size = sum(len(l) + 1 for l in current)
            current.append(line)
            size += len(line) + 1
        if current:
            chunks.append({"page": page, "text": "\n".join(current)})

    # Applied once at the end so every branch above - prose pages, table
    # pages, row slices - gets tagged without each having to remember to.
    for chunk in chunks:
        heading, topic = sections.get(chunk["page"], ("", "general"))
        chunk.setdefault("kind", "")
        chunk["section"] = heading
        chunk["topic"] = _content_topic(chunk["text"]) or topic
    return chunks


def _row_chunks(page, text):
    """One chunk per row, for simple "label -> single value" tables only.

    Requires most data rows to carry exactly one numeric field: that is what
    distinguishes a schedule or checklist (each row stands alone) from a fee
    grid (where a row without its column headers is worse than useless). Each
    chunk repeats the table caption so the row still has context on its own.
    """
    def payload(line):
        """Fields with any leading serial number dropped - "2  Foo  12/07/2025"
        is a one-value row, but the row number makes it look like two."""
        fields = _fields(line)
        if fields and re.fullmatch(r"\d{1,2}", fields[0]):
            fields = fields[1:]
        return fields

    lines = [l for l in text.split("\n") if l.strip()]
    rows, single = [], []
    for line in lines:
        values = [f for f in payload(line) if _NUMERIC_FIELD.match(f)]
        if values:
            rows.append(line)
            if len(values) == 1:
                single.append(line)
    if len(rows) < 4 or len(single) < len(rows) * 0.7:
        return []

    caption = _find_caption(lines) or ""
    out = []
    for line in single:
        fields = payload(line)
        value = next((f for f in fields if _NUMERIC_FIELD.match(f)), "")
        label = " ".join(f for f in fields if not _NUMERIC_FIELD.match(f)).strip(" :.-")
        # Drop bare serial-number rows - "12" alone names nothing worth indexing.
        if len(label) < 8:
            continue
        out.append({"page": page,
                    "text": f"{caption} - {label}: {value}".strip(" -")})
    return out


_TABLE_CHUNK_CHARS = 1800
# Every table page in this prospectus linearizes to under 5KB, and the embedding
# model's window is roughly 8KB, so all of them stay whole. This is not just
# tidiness: at 3600 the fee page split into 9 near-identical slices which then
# occupied ALL of the top-8 retrieval slots between them, crowding out the pages
# holding the application fee and the admission schedule entirely. Splitting a
# table is a last resort, not a default.
_TABLE_WHOLE_MAX = 5000


_PROSE_MIN_WORDS = 6
_PROSE_MIN_BLOCK_CHARS = 100
_WORDISH_RE = re.compile(r"[A-Za-z]{2,}")


def _prose_chunks(page, text):
    """Sentence-prose on a table page, kept as its own chunk.

    Table pages in these prospectuses are not pure grids: nearly every one
    ends with a paragraph or two of the actual RULES ("The admission fees for
    unreserved category Rs. 68860/-, for reservation category Rs. 30310/-...",
    the 10% revision clause, the EBC concession terms). Both table-chunking
    branches below discard those lines - _row_chunks keeps only lines it
    recognizes as data rows, and the row-slice branch folds them into a
    `legend` that is only reached when _row_chunks returns nothing.

    Measured across the six ingested prospectuses: the authoritative
    "admission fees for unreserved category" sentence was present in 0 chunks
    for M.V.Sc., Ph.D. and M.Tech. Every program whose sentence DID survive
    chunking answered the fee question correctly; the Ph.D. answer, with no
    sentence to read, reconstructed figures from the mangled grid and
    reported its reservation fee as its unreserved fee (Rs. 30,310 against a
    real Rs. 68,860). The text was never the problem - extract_pages produces
    that sentence perfectly - it simply never reached the index.

    Emitted IN ADDITION to the table chunks, deliberately, rather than
    replacing them: the grid and the prose answer different questions, and a
    short prose-only chunk embeds far more sharply for "what is the admission
    fee" than a 4KB slab of fee grid ever could.
    """
    blocks, current = [], []
    for line in text.split("\n"):
        stripped = line.strip()
        # A data row carries several aligned columns; prose runs as words. The
        # word count is what separates "3. The admission fees for unreserved
        # category Rs. 68860/-" (prose that happens to contain figures) from
        # "1 Registration Fee 2750 2750 2750" (a row that happens to contain
        # words).
        # numeric_column_count <= 2, not < 2: layout-mode padding puts wide
        # gaps inside ordinary sentences, so "3. The admission fees for
        # unreserved category Rs. 68860/-, for reservation category" reads as
        # two numeric columns and a stricter test excluded the single most
        # important line on the page. Genuine grid rows carry three or more.
        is_prose = (len(_WORDISH_RE.findall(stripped)) >= _PROSE_MIN_WORDS
                    and _numeric_column_count(line) <= 2)
        if is_prose:
            current.append(stripped)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    # Prefix the table's caption, exactly as _row_chunks does for rows and for
    # the same reason: a bare paragraph loses the page's identity. Measured on
    # the Ph.D. fee page against the live store - the plain block scored 0.6156
    # and never surfaced, while the same text behind "ANNEXURE-IV. FEES
    # STRUCTURE COLLEGE FEES : Ph.D." scored 0.8827 and took rank 1 ahead of
    # the fee-grid slices that used to monopolise retrieval.
    # Four lines, not two: these headings wrap narrowly ("ANNEXURE-IV." /
    # "FEES STRUCTURE" / "[A] COLLEGE FEES :" / "Ph.D."), and stopping at two
    # drops the two parts that actually discriminate - which fee table this
    # is, and which programme it belongs to. Measured: the two-line caption
    # left the chunk unretrievable, the four-line one put it at rank 1.
    caption = " ".join(
        " ".join(l.split()) for l in text.split("\n")[:4] if l.strip()
    )[:160]

    chunks = []
    for block in blocks:
        joined = " ".join(block)
        if len(joined) < _PROSE_MIN_BLOCK_CHARS:
            continue
        body = joined
        # Don't double the caption when the block already opens with it (a
        # short page whose first prose line IS the heading).
        if caption and not body.startswith(caption[:40]):
            body = f"{caption} {body}"
        chunks.append({"page": page, "text": body, "kind": "prose"})
    return chunks


def _chunk_table_page(page, text):
    """Chunk a table page into self-describing slices of rows.

    Emitting the whole table as one chunk keeps it readable but wrecks
    retrieval: the 25-row admission schedule became a single 4KB chunk whose
    embedding averaged every date on the page, so it matched no specific date
    question at all and simply never surfaced - the model then answered the
    application deadline from an unrelated page that happened to mention a
    different deadline. Splitting blindly is worse still, since a bare row loses
    the header that gives its columns meaning.

    So rows are grouped into modest slices and every slice repeats the table's
    caption/header lines and its trailing legend/notes. Each chunk is therefore
    independently interpretable AND narrow enough to embed sharply, and the
    per-slice linearized readings stay correct because the header travels with
    the rows they describe.
    """
    # A table that already fits stays whole - splitting it would only produce
    # near-duplicate chunks (each repeating the same header and legend), which
    # wastes index space and blunts retrieval by making several chunks compete
    # with nearly identical embeddings.
    whole = linearize_table(text)
    chunks = ([{"page": page, "text": whole, "kind": "table"}]
              if len(whole) <= _TABLE_WHOLE_MAX else [])
    # A schedule-style table is a list of independent facts, not one structure,
    # so each row is also indexed on its own. As a single chunk the 31-row
    # admission programme averaged out to a vague "dates" vector and lost to
    # prose pages that merely discussed the topic - asked for the grievance
    # deadline, retrieval returned pages about grievances and never the row
    # holding the date. One row per chunk embeds sharply enough to win. The fee
    # grids are excluded because a row there is meaningless without its header.
    chunks.extend(_row_chunks(page, text))
    # Always, in every branch - the rules stated in prose beside a table are
    # the part a student actually asks about, and both branches below drop
    # them otherwise. See _prose_chunks for the fee-sentence loss this fixes.
    prose = _prose_chunks(page, text)
    if chunks:
        return chunks + prose

    lines = text.split("\n")
    data_idx = [i for i, l in enumerate(lines) if _numeric_column_count(l) >= 2]
    if not data_idx:
        return chunks + [{"page": page, "text": text, "kind": "table"}]
    chunks.extend(prose)

    header = lines[:data_idx[0]]
    legend = lines[data_idx[-1] + 1:]
    body = lines[data_idx[0]:data_idx[-1] + 1]
    fixed = sum(len(l) + 1 for l in header + legend)

    slices, current, size = [], [], 0
    for line in body:
        if current and fixed + size + len(line) + 1 > _TABLE_CHUNK_CHARS:
            slices.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        slices.append(current)

    return chunks + [
        {"page": page, "text": linearize_table("\n".join(header + s + legend)),
         "kind": "table"}
        for s in slices
    ]


def _overlap_tail(lines):
    """Trailing whole lines to repeat into the next chunk, within the overlap budget."""
    tail, size = [], 0
    for line in reversed(lines):
        if size + len(line) + 1 > config.CHUNK_OVERLAP:
            break
        tail.insert(0, line)
        size += len(line) + 1
    return tail
