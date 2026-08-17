# Handoff — moving this project to another machine

Everything needed to get running, plus what is left to do and why.
Written 2026-08-17.

---

## 1. Git is not enough — two things must be copied by hand

`git clone` gives you the code and nothing else. These are gitignored and
**must be transferred separately** (USB, zip, cloud drive — anything):

| What | Size | Why it matters |
|---|---|---|
| `.env` | tiny | every API key, the admin token, the port |
| `data/` | **48 MB** | the prospectus PDFs, the **vector stores**, API keys, FAQ caches |

**Do not skip `data/`.** The vector stores in `data/projects/*/vector-store.json`
were built by paid embedding calls over the whole corpus. Losing them means
re-ingesting three prospectuses — money, time, and a real chance of a different
result. Zip the whole `data/` directory as-is.

```bash
# on the old machine
zip -r admission-data.zip data .env
```

Then on the new machine, unzip both into the repo root so you have
`./.env` and `./data/projects/...`.

`.env` values are NOT in this file on purpose: deleting a file from git later
does not remove it from git history, so anything committed here stays
recoverable in every clone forever. Get the values from the old machine's
`.env`, or ask whoever set it up.

---

## 2. Setup on Windows

Python 3.9+ (3.9.6 is what it was developed on).

```bat
python -m venv .venv-backend
.venv-backend\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` is deliberately two pure-Python packages (`pypdf`,
`indic-transliteration`). **Keep it that way.** The deployment host is a
locked-down Windows box whose Application Control policy blocks freshly built
native binaries, which is why there is no FastAPI, no pydantic, and no
compiled dependency anywhere in the backend. Anything needing real ML
(embeddings, OCR, speech) is called over HTTP instead of imported.

### Run it

```bat
.venv-backend\Scripts\python.exe run_backend.py
```

- `http://localhost:5050/` — student widget
- `http://localhost:5050/admin` — operator console (token = `ADMIN_TOKEN` in `.env`)

Use `-u` when redirecting output to a file, or Python block-buffers and the
log looks empty/hung for minutes.

### Verify it actually works

```bat
:: retrieval quality — no backend needed, pure measurement
.venv-backend\Scripts\python.exe -u tools\eval_retrieval.py
:: expect: recall@15 0.93, MRR ~0.65

:: full answer suite — backend must be running
set ADMIN_TOKEN=<your token>
.venv-backend\Scripts\python.exe -u tools\eval_admissions.py
:: expect: ~71/75 graded, 5 manual

:: one section only
.venv-backend\Scripts\python.exe -u tools\eval_admissions.py --section C
```

If those two numbers come out roughly right, the move worked.

---

## 3. What the `.env` keys are for

Names only. Values come from the old machine.

| Key | Role | Notes |
|---|---|---|
| `EMBEDDING_API_KEY`, `SELFHOSTED_*` | embeddings (BGE-M3) | remote; needed for retrieval AND ingest |
| `MISTRAL_API_KEY` | **answer model** + OCR | `CHAT_PRIMARY=mistral`, `mistral-small-latest` |
| `NVIDIA_API_KEY` | router + greetings | `nvidia-fast` = llama-3.1-8b, ~0.6s |
| `GROQ_API_KEY` | fast lane | **100k tokens/day** ceiling, hits it fast |
| `SARVAM_API_KEY` | was primary | **dead — HTTP 402, no credits** |
| `HETZNER_*` | fallback | alive but **52–77s**, effectively unusable |
| `ADMIN_TOKEN` | console auth | currently `password` |
| `PORT` | 5050 | |
| `OCR_ENABLED` | true | Mistral OCR for ingest; do not turn off (see §6) |

---

## 4. Where things live

```
backend/
  core/        pure logic — lang, programs, intent, eligibility, vocabulary
  storage/     projects, apikeys, faq cache, vectorstore, stats
  generation/  provider classes, llm, embeddings, speech
  prompts/     system prompts, canned replies
  rag/         router → guards → answer/comparison → validate/provenance
  http/        dispatch + route modules
  trace/       live SSE observability
  static/      student widget + operator console (React via CDN, no build)
tools/         eval_admissions.py, eval_retrieval.py, bench_answer_quality.py
data/projects/ per-programme corpus, vector store, FAQ cache  ← COPY THIS
```

**Projects** (`data/projects/<id>/`):

| id | what |
|---|---|
| `default` | general entry point — **no corpus**, routes only |
| `bvsc` | B.V.Sc. & A.H. |
| `bfsc` | B.F.Sc. |
| `btech-dairy` | B.Tech. (Dairy Technology) |

`default` used to hold the B.V.Sc. corpus as well. That double duty caused 7 of
the 80 evaluation failures — every question that named no programme answered
confidently from B.V.Sc. Split 2026-08-16. Do not put a corpus back on
`default`.

---

## 5. Current state

Measured 2026-08-17, all caches cleared, every section:

| Section | Baseline | Now |
|---|---|---|
| A. Basic eligibility | 11/12 | 10/11 |
| B. Student-style | 8/12 | 11/12 |
| C. RAG reasoning | 4/10 | **9/9** |
| D. Application process | 9/14 | **12/12** |
| E. Reservation | 7/9 | 8/9 |
| F. Fees/colleges/seats | 8/11 | 9/10 |
| G. Retired PG traps | 8/12 | **12/12** |
| **total** | **55/80** | **71/75 graded** (5 manual) |

Retrieval: recall@15 **0.86 → 0.93**, MRR 0.649.

The 5 manual cases are unscored on purpose — their ground truth (B.V.Sc. course
length, seat totals, full-course cost) is not stated in the PDFs, and asserting
a number the assistant produced would only prove it is self-consistent.

---

## 6. Remaining work, in the order I would do it

### P0 — cold-start latency
**The biggest open problem.** Section B averages **85s** and F **43s** with
caches cold, which is what a real student hits on any question nobody has asked
before. Every earlier latency figure in this project was partly measuring cache
hits.

Where the time goes, measured: retrieval finishes ~1.5s, generation ~3.2s,
and the rest is downstream. The deterministic paths (eligibility verdicts,
retired-programme refusals) answer in ~1s precisely because they skip the LLM
round trips — that is the shape of the fix.

### P1 — Q19, the contradiction
"I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?" still
answers "Yes, you can still get admission… you must also appear for MHT-CET."
It goes through the RAG path with nothing deterministic constraining it. It was
once reported fixed on a single lucky sample; it is not.

### P1 — `topic_mismatch` replacement (task #40)
Currently **disabled, not replaced**. It fired on ~93% of answers (37/40, 26/28,
16/17 in the review logs) and produced one regeneration per project, costing an
LLM round trip each time. It reuses `faq.answer_addresses_question`, a
keyword-overlap heuristic built for cache matching — and direct answers share
fewer words with their question, so making answers better made it worse. Needs
a real check, not just the escalation removed.

### P2 — smaller known bugs
- **Q1** intermittently answers a B.V.Sc. question about B.Tech. Router is
  6/6 stable and correct on it, so the cause is downstream — not yet found.
- **Q62** lists "College of Veterinary & Animal Sciences, Akola" twice (six
  colleges reported as seven).
- **Q66** ("how many seats for B.V.Sc.") occasionally fails outright; once hung
  18 minutes without the client timeout firing.

### P2 — from the requested list, not started
- **Tool/step scoping + graph view** — the guard pipeline is already an ordered
  graph with SSE tracing; this is making it explicit in the console. Keep it
  stdlib (LangGraph needs pydantic — see §2).
- **Least-to-most prompting** for multi-part answers, where the pipeline
  currently truncates or rambles.

### Deferred on evidence — reranking
Recall is 0.93 with 8 of 12 hits already at rank 1–2, so a reranker would add a
model call to every question to reorder what is already there. It also cannot
fix the one remaining miss ("can i do dairy tech with biology"), because that
chunk never enters the candidate set — that is a **query rewriting** case.
Revisit only if recall drops or the gold set grows and shows ordering problems.

---

## 7. Things that will cost you hours if you don't know them

**Clear EVERY project's cache when testing, not just `default`.** A question
asked on the general widget is answered by whichever programme it routes to and
cached *there*. Clearing `default` alone leaves the real answers in place and
you measure the cache instead of the pipeline. `tools/eval_admissions.py` now
does this automatically; anything you write by hand must too. This produced
days of apparent "nondeterminism" that was nothing of the kind.

**A flagged answer is never cached** (`rag/answer.py`). Before that rule, one
wrong answer produced in one slow moment was written to the cache and served
forever after — fast, confident, and wrong, looking exactly like a regression.

**`faq.clear()` preserves seeded entries.** Curated portal answers survive a
cache clear on purpose.

**`storage/faq.py:_lock` must stay an `RLock`.** Every writer holds it across a
read-modify-write and reads via `_load()`, which takes the same lock. As a
plain `Lock` that is a permanent self-deadlock that wedges FAQ writes for every
project at once.

**Programme detection must use `ctx.original_question`.** The router strips the
programme name out of `resolved_question`; detecting from the rewrite answered a
Ph.D. question with B.V.Sc.'s fee.

**Never let a deterministic path take the router's opinion as a veto.** The
eligibility verdict was gated on the router's `unknown_programme` flag and
became intermittent — 1.8s and right on one run, 140.8s and wrong on the next.
Consult the router to gain intelligence, never to lose determinism.

**The clarification guard punishes clever ideas.** Three attempts were measured
and two reverted: `deterministic OR router` (section D 6/12), self-consistency
sampling (the fee question came back as three redactions instead of a
clarification), and deterministic-only (E 9/9 → 5/9, F 8/11 → 6/10). A word
list cannot tell "what is the reservation *policy*?" from "what percentage do
*reserved* candidates need?". Measure section scores before and after.

**Embedding service refuses a single input of 5,000–6,000+ chars.** Measured.
`ingest.MAX_CHUNK_CHARS` splits at 4,500.

**pypdf loses table structure; OCR does not.** `OCR_ENABLED=true`. Whitespace
extraction detached figures from their row labels and caused several
wrong-number bugs.

**Use `python -u` for long runs**, or output buffers and the run looks hung.

**Never `pkill -f` a pattern that matches your own command** — it kills the
wrapper shell before the work starts.
