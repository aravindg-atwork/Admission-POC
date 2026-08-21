"""Ingestion CLI: extract, chunk, embed, and store one prospectus PDF.

Ported from backend/rag/ingest.py's ingest() - same extraction-then-OCR-
fallback order, same oversized-chunk splitting, same batching-by-character-
budget-not-fixed-count (both are real, measured constraints: the embedding
service refuses a single input between 5,000 and 6,000 chars, and a batch
of large OCR table chunks can independently cross ITS OWN limit even when
each chunk alone is fine - see MAX_CHUNK_CHARS/EMBED_BATCH_CHARS below).
What's different is the destination: Qdrant + Postgres instead of a JSON
file, and this actually RUNS the extraction/chunking/embedding fresh
against the real PDF, rather than reusing already-computed output from the
original system - the whole point of this phase's ingestion work is to
prove this new pipeline's OWN code, not to skip past it.

Usage: python -m app.ingestion.run <project_id> <path-to-pdf>
"""

import sys
import time
from pathlib import Path

from qdrant_client.http import models as qmodels
from sqlalchemy.orm import Session

from . import ocr, pdf
from ..providers import embeddings
from ..retrieval.store import ensure_collection, get_client, terms as compute_terms
from ..storage.database import SessionLocal, init_db
from ..storage.models import Project

# Roughly a third of the observed failure threshold - see backend/rag/
# ingest.py's own comment: measured directly (5,000 chars embeds, 6,000
# returns 503), not guessed. Left headroom for a chunk heavier per
# character than the one measured.
MAX_CHUNK_CHARS = 4500
EMBED_BATCH_CHARS = 6000
EMBED_BATCH_MAX = 8


def _split_oversized(chunks: list[dict]) -> list[dict]:
    """Split any chunk too large for the embedding service, on line
    boundaries, repeating the first line (a table's header row, or a
    caption) into each part so a fragment stays interpretable on its own.
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


def _batches(texts: list[str]):
    current, size = [], 0
    for text in texts:
        if current and (size + len(text) > EMBED_BATCH_CHARS or len(current) >= EMBED_BATCH_MAX):
            yield current
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        yield current


def ingest(project_id: str, project_name: str, pdf_path: Path) -> dict:
    print(f"[ingest] {project_id}: extracting {pdf_path.name}")
    # OCR first, exactly like the original - pypdf loses table structure
    # (see ingestion/ocr.py's own docstring), so a genuine attempt at OCR
    # always wins when it's available and returns something usable.
    pages = ocr.extract_pages(pdf_path)
    if pages:
        print(f"[ingest] OCR succeeded: {len(pages)} pages")
    else:
        print("[ingest] OCR unavailable or failed - falling back to pypdf")
        pages = pdf.extract_pages(pdf_path)
        print(f"[ingest] pypdf extracted {len(pages)} pages")

    chunks = _split_oversized(pdf.chunk_pages(pages))
    print(f"[ingest] chunked into {len(chunks)} pieces")

    vectors = []
    for batch_no, texts in enumerate(_batches([c["text"] for c in chunks]), start=1):
        for attempt in range(1, 4):
            try:
                vectors.extend(embeddings.embed(texts))
                print(f"[ingest] embedded batch {batch_no} ({len(texts)} chunks)")
                break
            except Exception as exc:  # noqa: BLE001 - retry, then give up loudly
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                print(f"[ingest] embed batch {batch_no} failed ({exc!r}); retry {attempt}/2 in {wait}s")
                time.sleep(wait)

    ensure_collection(project_id)
    client = get_client()
    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        payload = {
            "page": chunk["page"],
            "text": chunk["text"],
            "kind": chunk.get("kind", ""),
            "topic": chunk.get("topic", "general"),
            "section": chunk.get("section", ""),
            # Precomputed once at ingest time, not per-query - see
            # retrieval/store.py's search(), which reads this directly
            # instead of re-tokenizing every candidate on every request.
            "terms": list(compute_terms(chunk["text"])),
        }
        points.append(qmodels.PointStruct(id=i, vector=vector, payload=payload))
    client.upsert(project_id, points=points)
    print(f"[ingest] wrote {len(points)} points into Qdrant collection {project_id!r}")

    session: Session = SessionLocal()
    try:
        session.merge(Project(id=project_id, name=project_name))
        session.commit()
    finally:
        session.close()
    print(f"[ingest] upserted project row {project_id!r}")

    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks)}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python -m app.ingestion.run <project_id> <project_name> <pdf_path>")
        sys.exit(1)
    init_db()
    result = ingest(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
    print(f"[ingest] done: {result}")
