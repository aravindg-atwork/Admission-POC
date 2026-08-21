"""
Pure-Python demo harness for the AI Admission Assistant POC.

This dev machine has a Windows Application Control policy that blocks execution
of any freshly-compiled unsigned binary - .NET Framework included - so the real
C# pipeline (AdmissionAssistant.Core) can't be run live here, even though it
compiles correctly. This script has no compiled dependencies (stdlib + pypdf,
both pure Python), so it can actually run, and it calls the exact same two real
services the C# code calls: the Dockerized embedding-service and Ollama. It
mirrors TextChunker.cs / RagService.cs closely enough to prove the pipeline and
your real prospectus content work end-to-end.
"""

import json
import sys
import urllib.request
from pathlib import Path

from pypdf import PdfReader

EMBEDDING_URL = "http://localhost:8000/embed"
EMBEDDING_API_KEY = sys.argv[2] if len(sys.argv) > 2 else ""
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.1"
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
TOP_K = 5

SYSTEM_PROMPT = (
    "You are an admission assistant. Answer ONLY using the provided prospectus "
    "excerpts. If the answer is not contained in the excerpts, say you don't "
    "have that information in the prospectus. Always cite the page number(s) "
    "you used."
)


def post_json(url, payload, headers=None, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_pages(pdf_path):
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        if text:
            pages.append((i, text))
    return pages


def chunk_pages(pages):
    chunks = []
    for page_number, text in pages:
        start = 0
        while start < len(text):
            end = min(start + CHUNK_CHARS, len(text))
            chunks.append({"page": page_number, "text": text[start:end]})
            if end >= len(text):
                break
            start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


def embed(texts):
    headers = {"X-API-Key": EMBEDDING_API_KEY} if EMBEDDING_API_KEY else {}
    result = post_json(EMBEDDING_URL, {"texts": texts}, headers)
    return result["embeddings"]


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def ask_ollama(context, question):
    user_prompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    result = post_json(OLLAMA_URL, payload, timeout=280)
    return result["message"]["content"]


def main():
    pdf_path = sys.argv[1]
    store_path = Path(__file__).parent / "demo-vector-store.json"

    if store_path.exists() and "--reingest" not in sys.argv:
        print("--- Reusing cached vector store:", store_path, "---")
        store = json.loads(store_path.read_text())
        print("Chunks:", len(store))
    else:
        print("--- Extracting & chunking:", pdf_path, "---")
        pages = extract_pages(pdf_path)
        chunks = chunk_pages(pages)
        print("Pages with text:", len(pages))
        print("Chunks:", len(chunks))

        print("\n--- Embedding chunks (calling Dockerized embedding-service) ---")
        batch_size = 32
        vectors = []
        for i in range(0, len(chunks), batch_size):
            batch = [c["text"] for c in chunks[i:i + batch_size]]
            vectors.extend(embed(batch))
            print("  embedded", min(i + batch_size, len(chunks)), "/", len(chunks))

        store = [{"page": c["page"], "text": c["text"], "vector": v} for c, v in zip(chunks, vectors)]
        store_path.write_text(json.dumps(store))
        print("Saved vector store to", store_path)

    questions = [
        "What are the eligibility criteria for admission?",
        "When is the last date to apply?",
        "What documents are required at the time of admission?",
    ]

    for question in questions:
        print("\n=== Q:", question, "===")
        q_vector = embed([question])[0]
        scored = sorted(store, key=lambda e: cosine_similarity(q_vector, e["vector"]), reverse=True)
        top = scored[:TOP_K]
        context = "\n\n".join("[Page {}] {}".format(e["page"], e["text"]) for e in top)

        answer = ask_ollama(context, question)
        pages_cited = sorted(set(e["page"] for e in top))
        print("A:", answer)
        print("Pages retrieved:", pages_cited)


if __name__ == "__main__":
    main()
