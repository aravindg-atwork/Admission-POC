"""Prospectus PDF extraction and page-aware chunking.

Uses pypdf (pure Python, no compiled deps) so it runs on the host. Every chunk
keeps the page it came from so answers can cite prospectus pages.
"""

from pypdf import PdfReader

from . import config


def extract_pages(pdf_path):
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        if text:
            pages.append({"page": i, "text": text})
    return pages


def chunk_pages(pages):
    chunks = []
    for entry in pages:
        text, page = entry["text"], entry["page"]
        start = 0
        while start < len(text):
            end = min(start + config.CHUNK_CHARS, len(text))
            chunks.append({"page": page, "text": text[start:end]})
            if end >= len(text):
                break
            start += config.CHUNK_CHARS - config.CHUNK_OVERLAP
    return chunks
