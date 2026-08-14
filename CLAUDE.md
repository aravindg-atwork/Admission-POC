# Working notes for Claude

Operational context for this repo. Read before changing anything in `backend/`.

## Running it

```bash
cd /Volumes/nyx/Admission-POC          # project lives on the nyx external drive
.venv-backend/bin/python3 run_backend.py
```

Serves on `:5050` — student widget at `/`, operator console at `/admin`.
Admin token is `ADMIN_TOKEN` in `.env` (currently `password`; `admin-token.txt`
is untracked and gitignored).

Always use `.venv-backend/bin/python3`, never bare `python3` — the system
interpreter has none of the dependencies.

After changing a prompt, **clear the FAQ cache** or you will keep testing the
old answer and conclude nothing changed:

```bash
curl -X POST localhost:5050/admin/projects/default/cache/clear -H "X-Admin-Token: password"
```

## Scope

Three undergraduate programmes, 2026-27 prospectuses. Postgraduate
programmes (M.V.Sc., Ph.D., M.Tech.) were retired 2026-08-14 — projects
deleted and aliases removed from `core/programs.py`.

| project id | programme |
|---|---|
| `default` | B.V.Sc. & A.H. |
| `bfsc` | B.F.Sc. |
| `btech-dairy` | B.Tech. (Dairy Technology) |

`default` does double duty: it is the B.V.Sc. corpus AND the general entry
point. `helpers._assistant_scope` exists because of that — self-description
on `default` must name all three programmes, while retrieval stays scoped to
its own corpus. Conflating them made the shared widget introduce itself as
the B.V.Sc. assistant.

Languages: **English, Hindi, Marathi**. Tamil is out of scope (aliases and
canned text still exist; harmless, do not invest further).

## Providers, and how each one fails

Every key is in `.env`, which is gitignored. Never commit one.

| role | provider | notes |
|---|---|---|
| answers | `mistral` (`mistral-small-latest`) | `mistral-medium` was tried and exceeded **300s** on some questions while answering others in 1.6s — unusable variance |
| routing, greetings | `nvidia-fast` (`llama-3.1-8b`) | ~0.6s |
| fallback | `nvidia` (`nemotron-super-49b`) | reasoning model, 20-130s, high variance |
| embeddings | selfhosted BGE-M3 | remote, occasionally 503s |
| OCR | `mistral-ocr-latest` | ingest only |
| STT | `voxtral-mini-latest` | English 0.5s, Hindi 1.2s |

Dead or exhausted, do not rely on:
- **Sarvam** — HTTP 402, no credits. Was `CHAT_PRIMARY` for most of this project's life.
- **Groq** — 100k tokens/**day** free ceiling, reached inside one test run.
- **Hetzner** — alive but 52-77s for a trivial prompt.
- **TTS** (`TTS_URL`, local Docker on :8001) — connection refused. Indic voice
  is therefore broken. Mistral TTS does NOT fix it: ten voices, all
  `en_us`/`en_gb`, zero Indic, and English already has a browser voice.

## Architecture

`backend/` is layered; nothing imports upward.

```
core/        pure logic (lang, programs, intent, tablelookup)
storage/     projects, apikeys, faq, vectorstore, stats
generation/  providers, llm, embeddings, speech
prompts/     system.py (LLM prompts), canned.py (fixed replies), registry.py
rag/         router → guards → answer/comparison/orchestrator → validate/provenance
http/        app.py dispatch + admin/chat/trace routes
trace/       live SSE observability
```

**Guard order matters** (`rag/guards.py`, `GUARDS` list). Runs before the FAQ
cache is reachable, which is deliberate: clarification can never be skipped
by a cache hit.

```
injection → greeting → dispute → meta_correction → off_topic →
program_list → percentage_clarify → comparison → program_redirect →
unknown_programme → program_clarify
```

`rag/router.py` classifies intent in one call. It returns `None` on **any**
failure and every guard falls back to deterministic keyword logic — the
router is an upgrade, never a dependency. `ROUTER_ENABLED=false` reverts
everything.

## Things that cost hours — do not rediscover

**Programme detection must use `ctx.original_question`, not `ctx.question`.**
The router is instructed to strip the programme name out of
`resolved_question` (it belongs in `target_programs`). `ctx.question` is that
rewrite. Detecting from it caused a Ph.D. question to be answered with
B.V.Sc.'s fee.

**Redirects require the programme in the student's own text.** The router
hallucinated `target_programs=['bfsc']` for a question naming no programme,
and a B.Tech-scoped widget answered from B.F.Sc. Corroborate with
`detect_program` before redirecting.

**Every prompt speaking in the assistant's voice must name the institution.**
Ungrounded, the model invents a *real* university — "Osmania", then "Tamil
Nadu Veterinary". Use `canned.INSTITUTION` / `IDENTITY_RULE`.

**`faq.clear()` preserves seeded entries.** It used to wipe them, and
repeated debugging clears silently deleted the curated "How to Register?"
answer. Answers degraded with nothing failing.

**Embedding service refuses a single input between 5,000 and 6,000 chars.**
Measured. OCR markdown tables cross it, and the largest chunk failed *alone*,
so batching and retrying could never clear it. `ingest.MAX_CHUNK_CHARS`
splits at 4,500 keeping the header row.

**pypdf loses table structure; OCR does not.** `pypdf` gave
`"For Maharashtra State 68860/- Total : Candidate 69410/- 47400/-"` — figures
detached from labels, the root of several wrong-number bugs. Mistral OCR
returns proper markdown tables. `OCR_ENABLED=true`.

**Trace cards need `final_answer` to close.** Guards emit it via
`run_guards`; without it the console shows "Thinking…" forever.

## Testing

```bash
ADMIN_TOKEN=password .venv-backend/bin/python3 tools/bench_answer_quality.py
```

The one suite that checks **figures**, not just which path answered. Ground
truth read from the PDFs. Each case has a `forbid` list holding another
programme's figure — that is what contamination looks like.

Other scripts (`test_matrix`, `test_clarification`, `test_projects`,
`test_hinglish`, `test_retrieval_hi_mr`) assert on `source` and language, not
correctness of figures. All passing as of 2026-08-14; `test_retrieval_hi_mr`
is quota-free.

Long runs: write output to the session scratchpad, not `/tmp` (it does not
persist). Never `pkill -f` a pattern matching your own command — it kills the
wrapper shell before the work starts.

## Open

- **Benchmark has no clean post-OCR number.** Last trustworthy result 13/14,
  measured before OCR. Runs kept dying (see above).
- **Latency unproven at target.** Goal is 1-3s. `mistral-small` spot-checks
  are sub-second; not yet measured across the suite.
- **`_assistant_scope` fix is uncommitted and unverified live.**
- **Indic TTS broken** — needs the Docker service running or another provider.
- Presentation/quality pass and `taste-skill` redesign of the Playground.
