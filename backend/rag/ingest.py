"""PDF ingest pipeline entry point - extract, chunk, embed, store. Moved
unchanged from rag.py during the 2026-08-13 re-architecture; kept as its
own module since ingest is a distinct concern (building the corpus) from
answer.py/guards.py/comparison.py/orchestrator.py (answering from it).
"""

import hashlib
import json
from datetime import datetime, timezone

from .. import pdf
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
PIPELINE_VERSION = "11"


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

    pages = pdf.extract_pages(pdf_path)
    chunks = pdf.chunk_pages(pages)

    vectors = []
    # Modest batches keep any single request well inside the HTTP timeout.
    # (A round of ingest timeouts here looked like batch size being too large,
    # but the real cause was a wedged embedding-service process - after a
    # restart the same 3KB table chunks embed in well under a second.)
    batch = 8
    for i in range(0, len(chunks), batch):
        vectors.extend(embeddings.embed([c["text"] for c in chunks[i:i + batch]]))

    store = [{"page": c["page"], "text": c["text"], "vector": v} for c, v in zip(chunks, vectors)]
    vectorstore.save(projects.store_path(project_id), store)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "hash": content_hash, "pagesProcessed": len(pages), "chunksIndexed": len(chunks),
        "embeddedAt": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")

    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks), "skipped": False}
