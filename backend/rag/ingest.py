"""PDF ingest pipeline entry point - extract, chunk, embed, store. Moved
unchanged from rag.py during the 2026-08-13 re-architecture; kept as its
own module since ingest is a distinct concern (building the corpus) from
answer.py/guards.py/comparison.py/orchestrator.py (answering from it).
"""

import hashlib
import json
import time
from datetime import datetime, timezone

from .. import ocr, pdf
from ..generation import embeddings
from ..storage import projects, vectorstore

# Bump whenever extraction or chunking changes in a way that makes an existing
# index stale (see ingest). Mixed into the content hash so already-ingested
# projects rebuild instead of silently keeping data built by the old pipeline.
#   2 - layout-preserving extraction, page-furniture/mojibake stripping,
#       line-boundary chunking, tables kept whole
#   3 - explicit linearized readings appended to table pages
#   4 - table detection widened to 2-column tables (schedule/date grids)
#  11 - single-level year-column fee tables linearized too (Annexure III-A/III-C),
#       which previously produced no readings at all
#  12 - prose beside a table kept as its own caption-prefixed chunk, and
#       chunk `kind` (table/prose) stored so retrieval can budget per kind
#  13 - chunks tagged with their prospectus SECTION and a derived topic
#       (fees/quota/eligibility/seats/dates/documents/process/academics),
#       so retrieval can favour the right part of the document
#  14 - chunk topic can be overridden by its CONTENT, so a fact stated far
#       from its heading (the application fee, under "important
#       instructions") is tagged for what it says, not where it sits
#  15 - extraction may come from Mistral OCR (markdown tables that keep
#       each figure attached to its row label and column header) instead
#       of pypdf layout reconstruction
PIPELINE_VERSION = "15"


# Roughly a third of the observed failure threshold, leaving headroom for a
# single oversized chunk to travel alone rather than push a batch over.
# The embedding service refuses a single input somewhere between 5,000 and
# 6,000 characters - measured directly, not guessed: 5,000 embeds, 6,000
# returns 503. Markdown tables from OCR are dense enough to cross that on one
# chunk (the B.V.Sc. fee grid is 8,559 chars), and it failed ALONE, so no
# amount of batching or retrying could have cleared it. 4,500 leaves headroom
# for a chunk that is heavier per character than the one measured.
MAX_CHUNK_CHARS = 4500


def _split_oversized(chunks):
    """Split any chunk too large for the embedding service, on line
    boundaries, repeating the first line into each part.

    That first line is the table's header row for an OCR markdown table, and
    the caption for everything else - the piece that makes a fragment
    interpretable on its own. Splitting a fee grid without it would recreate
    the exact failure OCR was adopted to fix: figures with nothing naming
    their columns.
    """
    out = []
    for chunk in chunks:
        text = chunk["text"]
        if len(text) <= MAX_CHUNK_CHARS:
            out.append(chunk)
            continue
        lines = text.split("\n")
        header = lines[0] if lines else ""
        current, size = [], 0
        for line in lines:
            if current and size + len(line) + 1 > MAX_CHUNK_CHARS:
                out.append({**chunk, "text": "\n".join(current)})
                current = [header] if header and current[0] != header else []
                size = sum(len(l) + 1 for l in current)
            current.append(line)
            size += len(line) + 1
        if current:
            out.append({**chunk, "text": "\n".join(current)})
    return out


EMBED_BATCH_CHARS = 6000
EMBED_BATCH_MAX = 8


def _batches(texts):
    """Group texts so no single request is large enough to be refused."""
    current, size = [], 0
    for text in texts:
        # An oversized chunk goes on its own rather than joining anything.
        if current and (size + len(text) > EMBED_BATCH_CHARS
                        or len(current) >= EMBED_BATCH_MAX):
            yield current
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        yield current


def ingest(project_id, pdf_path):
    """Extract, chunk, embed and store a prospectus PDF for a project.

    Skips re-embedding entirely when the PDF is byte-identical to what's
    already indexed for this project AND the extraction pipeline hasn't changed
    since (both tracked via a hash in manifest.json) - re-uploading the same
    prospectus, or restarting against unchanged data, costs nothing. Returns
    counts plus `skipped: True` when the skip path was taken.

    The pipeline version is part of that hash on purpose. Hashing only the PDF
    bytes meant a change to extraction or chunking left every project silently
    serving an index built by the old, worse code - the file hadn't changed, so
    the skip path fired and the fix never reached the data. Bumping
    PIPELINE_VERSION forces a rebuild everywhere on next ingest.
    """
    pdf_bytes = pdf_path.read_bytes()
    content_hash = hashlib.sha256(
        pdf_bytes + PIPELINE_VERSION.encode("utf-8")
    ).hexdigest()

    manifest_path = projects.manifest_path(project_id)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("hash") == content_hash:
            return {"pagesProcessed": manifest["pagesProcessed"],
                     "chunksIndexed": manifest["chunksIndexed"], "skipped": True}

    # OCR first when enabled - it keeps table rows intact, which pypdf's
    # whitespace reconstruction does not (see ocr.py). Returns None for any
    # failure, so a missing key or a bad response degrades extraction
    # quality instead of blocking the ingest.
    pages = ocr.extract_pages(pdf_path) or pdf.extract_pages(pdf_path)
    chunks = _split_oversized(pdf.chunk_pages(pages))

    vectors = []
    # Modest batches keep any single request well inside the HTTP timeout.
    # (A round of ingest timeouts here looked like batch size being too large,
    # but the real cause was a wedged embedding-service process - after a
    # restart the same 3KB table chunks embed in well under a second.)
    # Batched by CHARACTER BUDGET, not by a fixed count. Eight chunks was
    # safe while pypdf produced modest text blocks, but OCR emits whole
    # markdown tables - one B.V.Sc. fee chunk alone is 8,559 chars - and a
    # batch of eight such chunks reached 17,438 characters, which the
    # embedding service rejects with a 503. It failed on the same batch
    # every attempt, so retrying could never clear it; only a smaller
    # request can. Still capped by count as well, since many tiny chunks in
    # one request is its own kind of unreasonable.
    for batch_no, texts in enumerate(_batches([c["text"] for c in chunks]), start=1):
        # Retry each batch. A prospectus is ~25-30 batches, so a single
        # transient 503 anywhere in the sequence used to abort the whole
        # ingest and discard every embedding already paid for - which is
        # exactly what happened re-ingesting the B.V.Sc. prospectus twice in
        # a row while the same service answered a one-off probe instantly.
        # The embedding service is remote and occasionally busy; that is
        # normal, and an ingest costing real calls should not be one blip
        # away from starting over.
        for attempt in range(1, 4):
            try:
                vectors.extend(embeddings.embed(texts))
                break
            except Exception as exc:  # noqa: BLE001 - retry, then give up loudly
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                print(f"[ingest] embed batch {batch_no} "
                      f"({len(texts)} chunks, {sum(len(t) for t in texts)} chars) "
                      f"failed ({exc!r}); retry {attempt}/2 in {wait}s")
                time.sleep(wait)

    # `kind` is carried through, not dropped: vectorstore.search budgets its
    # per-page slots per (page, kind), so one page can contribute both its
    # table slices and the prose rule that states the answer in words.
    # Dropping the field here silently collapsed every chunk into a single
    # bucket and reinstated the exact crowding the split was built to fix -
    # the near-identical grid slices taking every slot on the page while the
    # prose chunk, which actually answers the question, never surfaced.
    store = [{"page": c["page"], "text": c["text"], "kind": c.get("kind", ""),
              "topic": c.get("topic", "general"), "section": c.get("section", ""),
              "vector": v}
             for c, v in zip(chunks, vectors)]
    vectorstore.save(projects.store_path(project_id), store)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "hash": content_hash, "pagesProcessed": len(pages), "chunksIndexed": len(chunks),
        "embeddedAt": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")

    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks), "skipped": False}
