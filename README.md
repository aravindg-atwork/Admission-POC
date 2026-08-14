# MAFSU Admission Assistant — POC

A RAG chat assistant that answers undergraduate admission questions from
MAFSU's own prospectuses, in English, Hindi and Marathi, with an operator
console that shows how each answer was reached.

Covers three programmes, 2026-27: **B.V.Sc. & A.H.**, **B.F.Sc.**, and
**B.Tech. (Dairy Technology)**.

## Running it

```bash
.venv-backend/bin/python3 run_backend.py
```

- `http://localhost:5050/` — student chat widget
- `http://localhost:5050/admin` — operator console (admin token from `.env`)

Configuration lives in `.env` (gitignored — it holds provider keys). Copy
`.env.example` to start.

## Why it is built this way

The deployment host runs a locked-down Windows machine whose Application
Control policy blocks freshly built native binaries, so the backend is
**pure Python standard library** — `http.server`, no FastAPI, no pydantic,
no compiled dependencies. Anything needing real ML (embeddings, OCR, speech)
is called over HTTP rather than loaded in-process.

That constraint shapes everything: the vector store is a JSON file searched
with exact cosine similarity (a few hundred chunks per programme, so an
approximate index would be slower *and* less accurate), and every model is a
plain HTTPS call behind a small provider class.

## How an answer is produced

```
question
  → intent router          one classification call; understands negation,
                           follow-ups, off-topic, corrections
  → guards                 eleven ordered checks; any may answer outright
  → FAQ cache              only reachable once every guard declines
  → retrieval              hybrid cosine + keyword, topic-aware
  → generation             answer written from the retrieved excerpts
  → validation             deterministic checks; provenance for comparisons
```

The guard stage runs **before** the cache by construction, so a question
needing clarification can never be short-circuited by a cached answer.

Retrieval is section-aware: chunks carry the prospectus section they came
from and a derived topic (fees, eligibility, quota, dates…), so a fee
question favours the fee section instead of competing with the table of
contents. Chunk topics can be overridden by content — the application fee is
printed under "Important Instructions", not under any fee heading.

Prospectuses are extracted with OCR into markdown tables, which keeps every
figure attached to its row label and column header. Whitespace-based PDF
extraction loses that association on fee grids, and did cause wrong figures
to be quoted.

## Operator console

- **Playground** — ask as a student would; each reply links to its own
  reasoning trace (answers carry a `traceId`), with a switch for watching all
  live traffic
- **Prompts** — the exact system prompts being sent, per programme
- **Dashboard / Cost** — volume, cache hit rate, provider mix, spend caps
- **Flagged / Review** — student dislikes, and answers the system flagged itself
- **API Keys** — one key per consumer, individually revocable

## Layout

```
backend/
  core/        pure logic — language, programmes, intent, table lookup
  storage/     projects, API keys, FAQ cache, vector store, stats
  generation/  provider classes, LLM policy, embeddings, speech
  prompts/     system prompts, canned replies, prompt registry
  rag/         router, guards, answer pipeline, comparison, validation
  http/        request dispatch and route modules
  trace/       live reasoning trace (Server-Sent Events)
  static/      student widget and operator console (React via CDN, no build)
tools/         test and benchmark scripts
data/projects/ per-programme prospectus, vector store, FAQ cache, stats
```

Each programme is a fully isolated project: its own prospectus, embeddings,
cache and keys. Nothing is shared, which is what stops one programme's
figures being served under another's name.

## Testing

```bash
ADMIN_TOKEN=... .venv-backend/bin/python3 tools/bench_answer_quality.py
```

Checks answers against figures verified in the PDFs, and fails a case if
another programme's figure appears — the shape cross-contamination actually
takes. Other scripts under `tools/` cover routing, clarification, project
isolation and Hindi/Marathi retrieval.

## Status

Working: multilingual answers with citations on challenge, section-aware
retrieval, OCR ingest, voice input, live tracing, per-programme isolation.

Known gaps: Indic text-to-speech depends on a local service that is
currently down, and end-to-end latency is not yet at its 1-3s target.

See `CLAUDE.md` for operational notes, provider behaviour and the failure
modes worth knowing before changing anything.
