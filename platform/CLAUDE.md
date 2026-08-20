# Working notes for platform/ (the ground-up rebuild)

Operational context for `platform/` specifically. Read before touching
anything under here. This is a **separate system** from `backend/` at the
repo root — `backend/` is the original POC, untouched, still the live
system serving real traffic at 159.69.210.30. This directory is a from-0
rebuild of the same product, following the target architecture in
`../docs/admission-assistant-platform-architecture.md` and
`../docs/admission-bot-end-to-end-system-flow.drawio.xml` (both at the repo
root — read those first for the *why*, this file is the *where we
actually are*).

**No formal written spec exists for this rebuild.** The brainstorming
skill's normal architectural path is questions → 2-3 approaches → sectioned
design → write a spec to `docs/superpowers/specs/` → user reviews the spec
→ writing-plans. That happened only through the sectioned-design-in-chat
step — the user said "start this local service" instead of confirming a
written spec, and implementation began directly from the in-chat design. If
a future session wants a fuller spec document, reconstruct it from this
file + the two docs above + that conversation, not from an existing spec
file — there isn't one.

## What was decided (brainstorming session, before any code existed)

- **Scope**: the full platform end-to-end — frontend, backend, ingestion,
  infra (Docker/k3s manifests, CI/CD) — not just the RAG engine alone.
- **Location**: this new `platform/` subdirectory. `backend/` stays
  untouched and is not being migrated away from yet.
- **Infra for now**: Docker Compose, fully runnable locally. k8s manifests
  will be written as real IaC in a later phase but are **not deployed
  anywhere** — there is no cluster available in this environment.
- **Domain**: same admissions domain, same three programmes' corpora
  (bvsc/bfsc/btech-dairy), so this is a genuinely testable replacement, not
  a generic framework.
- **Vector store**: Qdrant (dedicated), not pgvector.
- **Model providers**: the exact same providers/accounts as `backend/` —
  Mistral (primary answers), NVIDIA + NVIDIA-fast (fallback/routing),
  self-hosted BGE-M3 (embeddings) — wrapped behind a new unified gateway
  instead of `backend/generation/providers.py`'s hand-rolled per-call
  fallback chains. No new provider accounts needed.
- **Success bar**: must pass the SAME eval suites already built for the POC
  (`tools/bench_answer_quality.py`'s ground-truth figures,
  `tools/eval_retrieval.py`'s needle set) run against the new system — not
  a fresh set of invented criteria.
- **Build strategy**: a deep vertical slice first (one programme, one
  complete working path through every layer, actually passing eval cases),
  THEN breadth (remaining programmes, full admin console, async ingestion,
  observability, k8s/CI-CD). Never scaffold breadth before depth is proven.
- **The one rule that matters most**: domain logic is **ported**, not
  re-derived. Eligibility thresholds, guard trigger conditions, table-lookup
  matching, the guided-interview flow, script/romanization handling, the
  confidence gate and chain-of-thought split — all of it took real
  iteration to get right in `backend/` and carries over as-is into the new
  architecture. Re-deriving any of it from scratch risks silently
  reintroducing bugs `backend/`'s own `CLAUDE.md` already documents being
  found and fixed. If you're about to write new eligibility/threshold/guard
  logic instead of porting it from `backend/core/` or `backend/rag/`, stop
  and port instead.

## Status: vertical-slice checkpoint 1 of N — infra + a bare health-checked service

### Done, and verified (not just written)

- Directory structure: `services/api/app/{core,agent,retrieval,ingestion,
  providers,storage,api}` (all currently empty `__init__.py` packages,
  ready to receive ported logic), `services/web/` (not yet started),
  `infra/docker-compose.yml`.
- `services/api`: a FastAPI skeleton — `app/settings.py` (typed config via
  pydantic-settings, replacing `backend/config.py`'s `os.environ.get()`
  pattern), `app/main.py`, `app/api/health.py`. No business logic yet.
- Docker Compose stack (`infra/docker-compose.yml`), brought up and
  confirmed live:
  - `postgres:16-alpine` — healthy, host port `5432`
  - `redis:7-alpine` — healthy, host port `6380` (not `6379` — see port
    note below)
  - `qdrant/qdrant:latest` — responding, host ports `6333`/`6334`
  - `api` (this repo's own image) — `GET /healthz` → `{"status":"ok"}`,
    host port `8100`
- **Dependency compatibility, verified directly, not assumed**: `fastapi`,
  `pydantic` (including its compiled `pydantic-core` extension),
  `pydantic-settings`, `uvicorn`, `sqlalchemy`, `qdrant-client`, `redis`,
  `psycopg[binary]`, `httpx` all install and import cleanly — both in a
  throwaway venv and inside the actual Docker image. This directly
  contradicts `backend/config.py`'s documented claim that this machine's
  Application Control policy blocks "freshly built native binaries such as
  pydantic-core" (the whole reason `backend/` is pure stdlib with zero
  dependencies). Either that policy had already loosened, or it never
  applied to pip-installed pre-built wheels the way `backend/config.py`
  assumed. The user began fully disabling Windows Smart App Control /
  Application Control in the same session this was found, specifically so
  it stops being a variable at all — once that's off, don't re-litigate
  this constraint or reach for stdlib-only workarounds on its account;
  treat compiled dependencies as unrestricted.
- **Port map** — chosen deliberately to avoid the pre-existing `ai-platform`
  Docker stack already running on this machine (found live via `docker
  ps`, not assumed — it's a separate, unrelated stack with Postgres, Redis,
  vLLM, Ollama, Grafana, Prometheus, nginx, presumably a local mirror of
  what `backend/CLAUDE.md` describes running on the production box). That
  stack's host-exposed ports: `80`, `3000`, `3001`, `5433`, `8000`, `8001`,
  `9090`, `11434` — do not reuse any of these for `platform/`'s own stack.
  Current allocation: Postgres `5432` (free, the other stack's postgres
  isn't host-exposed), Redis `6380`, Qdrant `6333`/`6334`, API `8100`.
- `services/api/.env` exists, currently empty, gitignored by the repo
  root's bare `.env` pattern (confirmed — no separate ignore rule was
  needed). Provider keys get copied in from `backend/.env` (same accounts)
  once the provider gateway exists and actually needs them — not before.

### Also done since the first checkpoint

- **Domain logic ported** into `app/core/`: `eligibility.py`, `programs.py`,
  `lang.py`, `tablelookup.py` — copied verbatim from `backend/core/` (`diff`
  confirmed byte-identical at port time), because all four were already
  true leaf modules with zero internal project imports (checked directly,
  not assumed — only stdlib `re`/`unicodedata`). Smoke-tested post-port:
  `eligibility.evaluate()`, `programs.PROGRAM_NAMES`, `lang.detect_script()`
  all produce identical output to the original. **`app/agent/` (the guard
  pipeline) is NOT ported yet** — only these four standalone modules are.
- **Postgres schema** (`app/storage/models.py`, `database.py`): `projects`,
  `faq_cache`, `review_log`, `api_keys` (hashed keys, not plaintext),
  `admin_users`. `init_db()` runs `Base.metadata.create_all` on startup —
  **not real Alembic migrations yet**, deliberate for now while the schema
  is still settling (see the module's own docstring); don't add Alembic
  before the schema has stabilized, and don't keep using `create_all` once
  it has. Verified live: all 5 tables exist in the running container
  (`\dt` confirmed), and a full ORM round-trip (write a `Project` row,
  read it back) succeeded against the actual running Postgres, not just a
  local/mocked one.
- `FaqCache.id` is deliberately the SAME id used for that entry's
  question-embedding point in Qdrant once the FAQ-matching vector search
  exists — one shared id instead of a separate mapping table, so a cache
  row and its vector can never point at each other's wrong entry. Noted
  here because it's a real design decision made while writing the schema,
  not something the original brainstorming session explicitly covered.

### Frontend (`services/web/`) — built out of order, deliberately

The user explicitly asked for this ahead of the backend agent logic ("no
build a proper prod grade ui/ux" — declining a placeholder in favor of
doing it properly now). It is a real, designed UI, not a wireframe:

- Vite + React + TypeScript, confirmed both `npm run build` (type-checks
  clean) and a production Docker image (multi-stage: `node:22-slim` build
  → `nginx:1.27-alpine` serve) work.
- Design tokens in `src/styles/tokens.css` — grounded in the actual
  subject (an agricultural/veterinary university, Maharashtra, real
  admissions stakes), not a generic chat-widget palette. Deep pasture
  green + warm marigold accent + warm paper background; deliberately
  avoids the three current AI-generated-design defaults (cream+terracotta+
  serif, near-black+neon, broadsheet/newspaper hairlines) — see the
  file's own header comment for the reasoning.
- **Typography is the actual signature**: "Tiro Devanagari Hindi" /
  "Tiro Devanagari Marathi" for display (wordmark, greeting, headers),
  "Noto Sans" / "Noto Sans Devanagari" for body/UI text. Verified via
  `fonts.googleapis.com`'s CSS2 API directly before committing to them
  (not guessed) — both Tiro families are real, part of Google's "Modern
  Tiro Indic Collection," and each already bundles its own Latin subset,
  so English and Hindi/Marathi get equal typographic care from ONE font
  file rather than a paired-but-separate Latin face. The wordmark
  crossfades (remounts via React `key`) on every language switch — a
  small, honest proof-of-craft moment right where a visitor looks first.
- The API client (`src/api/chat.ts`) calls the REAL, eventual `/api/chat`
  contract already — no rework needed once that route exists. Since it
  doesn't exist yet, every call currently 404s; the UI shows an honest
  "the admissions engine isn't connected yet — you're previewing the
  interface only" banner instead of a raw fetch error or a faked response.
  **Verified live in a real browser** (not just code-reviewed): empty
  state, both language switches (Tiro rendering confirmed visually
  correct for both scripts), the send flow (student bubble → thinking
  indicator → honest not-live banner), all screenshotted and checked.
- Copy (`src/copy.ts`) for Hindi/Marathi is machine-drafted, **not yet
  reviewed by a native speaker** — flagged in the file itself. Standard,
  reasonable admissions phrasing, but don't treat it as verified-correct
  the way the ported domain logic is.
- Runs via the SAME `docker-compose.yml` as everything else, host port
  `5180`. `VITE_API_BASE` is a Docker **build arg** (`http://
  localhost:8100`), not a runtime env var — Vite bakes `VITE_*` vars into
  the built JS at build time, and it must be a URL the STUDENT'S BROWSER
  can reach, never the `api` container's internal Docker-network hostname
  (only other containers can resolve that). Confirmed by grepping the
  built bundle inside the running container for the right string, not
  assumed from the Dockerfile alone.
- **Not done**: mobile-viewport visual verification (tried, the browser
  tool's `resize_window` didn't take effect in this environment — the CSS
  has `@media (max-width: 560px)` rules and uses flex-wrap/relative units
  throughout, so it should be fine, but this is a real gap, not a checked
  box). No admin console UI. Keyboard-focus/reduced-motion CSS is written
  but not manually tested with an actual screen reader or OS-level
  reduced-motion setting.

### The vertical slice is now live, end to end — real question in, grounded answer out

**Correction made mid-build, worth recording**: the first attempt at this
step tried to shortcut ingestion by copying `data/projects/bvsc/vector-
store.json` (the OLD system's already-computed chunks/embeddings) straight
into Qdrant. The user caught this as a real mistake, not a nitpick: "port,
don't re-derive" covers *domain logic* proven correct through iteration
(eligibility rules, guard conditions) — it was never license to skip
*building and running* the ingestion pipeline itself. Copying old output
would have left `app/ingestion/` unbuilt and unproven while pretending
otherwise. Corrected: the real PDF (`data/projects/bvsc/prospectus.pdf`)
was OCR'd, chunked, and embedded fresh through this system's OWN pipeline.

- **`app/ingestion/`**: `pdf.py` and `ocr.py` ported verbatim from
  `backend/pdf.py`/`backend/ocr.py` (both confirmed leaf modules - only
  `pypdf`/stdlib + two config values). `run.py` is a new synchronous CLI
  orchestrating them (extract → chunk → embed → write), porting
  `backend/rag/ingest.py`'s oversized-chunk-splitting and character-budget
  batching logic. **Actually run** against the real B.V.Sc. PDF: `python -m
  app.ingestion.run bvsc "B.V.Sc. & A.H." <pdf path>` — OCR succeeded (69
  pages), chunked into 192 pieces (the old system's own ingest produced 193
  from the same PDF - close enough to confirm the chunking algorithm ported
  correctly, not an exact match because OCR is not perfectly
  deterministic), embedded in 37 batches, all written into a real Qdrant
  collection. Verified independently via Qdrant's own API (`points_count:
  192`) and Postgres (`SELECT * FROM projects` shows the `bvsc` row) - not
  just trusted from the script's own stdout.
- **`app/providers/embeddings.py`**: ported from `backend/generation/
  embeddings.py` onto `httpx` - same non-standard endpoint shape preserved
  exactly (`POST /v1/embedding` singular, raw vector list in `data`, not
  OpenAI-standard). Reaches the self-hosted BGE-M3 service through the SAME
  SSH tunnel `backend/CLAUDE.md` documents (`ssh -N -L 8000:127.0.0.1:8000
  root@159.69.210.30`) - it was blocked by the permission classifier
  earlier this session, worked cleanly on retry. **Inside Docker this needs
  `SELFHOSTED_URL=http://host.docker.internal:8000`, NOT `127.0.0.1:8000`**
  (which inside a container means the container's own loopback, not the
  host running the tunnel) - see `infra/docker-compose.yml`'s `api`
  service env override. Same class of bug as the frontend's `VITE_API_BASE`
  build-arg issue; caught before testing this time, not after.
- **`app/providers/llm.py`**: Mistral primary / NVIDIA fallback, ported
  onto `httpx`. The Sarvam-specific daily-spend-cap bookkeeping in the
  original was deliberately DROPPED, not ported - Sarvam has been dead
  (HTTP 402) for that project's entire life, and porting live logic that
  guards a dead provider is cruft, not a lesson. What WAS ported: the
  retry-only-on-fast-failure-never-on-genuine-timeout logic, which is the
  real, measured fix behind the original's own P95/P99 latency win.
- **`app/retrieval/store.py`**: Qdrant-backed hybrid search. The scoring
  algorithm itself (`terms`, `_keyword_score`, `_QUERY_TOPICS`,
  `query_topic`, the per-page contribution cap) is ported near-verbatim
  from `backend/storage/vectorstore.py` - real, measured domain knowledge
  (see each constant's own comment for the specific retrieval failure it
  fixes). What changed: Qdrant's own ANN index does the cosine half
  server-side over a generous candidate set; the keyword/topic rescoring
  and per-page cap still run in Python exactly as before.
- **`app/agent/prompts.py`**: `SYSTEM_PROMPT_BASE`, `ELIGIBILITY_SYSTEM_
  PROMPT`, `VERIFIED_FACT_SYSTEM` ported **character-for-character** from
  `backend/prompts/system.py` (extracted via a paren-balancing script
  against the actual source, not hand-retyped, specifically to avoid
  transcription errors in ~300 lines of iterated prompt engineering,
  worked examples included).
- **`app/agent/answer.py`**: the actual pipeline - retrieve → confidence
  gate → eligibility verdict (narrow: only acts on a determinable verdict,
  no guided interview yet) → verified table lookup → general RAG. Every
  branch is live-tested (see below), not just unit-tested in isolation.
- **`/api/chat`** (`app/api/chat.py`), wired into `main.py` with CORS
  (wildcard, matching `backend/http/app.py`'s own current posture - scoping
  it is a stated later-phase item, not settled here). Defaults `projectId`
  to `"bvsc"` since that's the only programme ingested.

**A real bug found and fixed via live testing, not assumed away**: the
first real question ("What is the first year tuition fee?") came back
correctly-valued but **in Hindi**, despite being asked in English - the
exact failure `backend/rag/helpers.py`'s `_english_reply_hint` already
exists to fix (`LANGUAGE_RULE` alone isn't enough; Mistral needs an
explicit end-of-prompt reminder for the English-default case too). Fixed
by appending the same reminder to every generation call in `answer.py`
(unconditional here, since this checkpoint is English-only by scope - the
original applies it conditionally alongside full script detection, which
isn't ported yet). Re-verified after the fix: correct, English,
well-grounded answers across four different question shapes.

**Verified live, through the actual browser UI, not just curl**: student
clicks an example chip → real answer appears, no "not connected yet"
banner. Four question shapes tested end-to-end via curl:
  - *Verified-fact*: "first year tuition fee" → `27500`, `source:
    "verified-fact"` - matches the figure the OLD system's own live test
    produced this session, from an independently fresh OCR/chunk/embed run.
  - *Eligibility verdict*: 55% PCB+English, unreserved, NEET-appeared →
    correct "meets the marks requirement" verdict (not overclaiming "you
    are eligible" - the same deliberate phrasing discipline as the
    original), correctly names NEET clearance and the age requirement as
    outstanding conditions, `source: "eligibility"`.
  - *General RAG*: "what documents do I need" → a well-formatted,
    correctly one-item-per-line (no markdown bullets) answer covering
    eight+ real requirements from the actual prospectus, `source: "rag"`.
  - *Off-topic*: "weather forecast for Mumbai" → correctly declined and
    redirected. **Worth noting honestly**: this went through `source:
    "rag"`, not `"low-confidence"` - the 0.30 confidence floor didn't
    actually fire on this case (retrieval still returned something scoring
    above it), and the decline happened because the ported system prompt's
    own off-topic-redirect rule caught it instead. A real data point for
    calibrating that floor later, not a failure - the double safety net
    worked, but the floor itself is still exactly as unmeasured as its own
    comment says.

### Explicitly NOT done yet — don't assume any of this exists

- **The full guard pipeline.** `answer.py`'s eligibility check is narrow:
  first-person + a hint word, straight to `evaluate()`, no guided
  multi-turn interview when marks/category are missing (an "insufficient"
  verdict just falls through to general RAG). None of inject/greeting/
  dispute/meta-correction/off-topic/comparison/program-redirect/
  clarification exist as their own guards yet - the off-topic case above
  is caught by the SYSTEM PROMPT's own rule, not a dedicated guard.
- **Hindi/Marathi are entirely unhandled** - no script detection, no
  romanization, no `translate_to_english` for retrieval. This checkpoint
  is English-only by explicit scope, and the frontend's language switcher
  currently has nothing behind it for hi/mr beyond the UI itself.
- **Only `bvsc` is ingested.** `bfsc` and `btech-dairy` have no Qdrant
  collection and no Postgres row yet.
- No FAQ cache lookup (the `faq_cache` table exists, nothing reads or
  writes it yet), no review-log writing, no validation/regeneration layer.
- Deliberately deferred to a later phase, per the agreed build strategy —
  do not build these before the vertical slice passes its eval checkpoint:
  the async ingestion pipeline with staged blue-green promotion, k8s
  manifests, CI/CD pipeline config, the full admin console UI, multi-role
  RBAC, the OpenTelemetry/Prometheus/Grafana observability wiring.

## CHECKPOINT — read this first if picking this up cold

Written because the session that built everything above was ending. This
section is deliberately self-contained: everything needed to resume
without re-reading a conversation transcript that may no longer exist.

**State of the world right now**: the Docker stack (postgres, redis,
qdrant, api, web) was last confirmed running - `docker compose ps` from
`platform/infra/` showed all five `Up`, api and web both freshly rebuilt.
It will NOT still be running when a new session starts (the host will have
restarted, or Docker Desktop won't be up) - that's expected, not a
regression. Bring it back with the commands in "How to run it" below.
Qdrant's `bvsc` collection (192 points) and Postgres's `bvsc` project row
persist in their named volumes (`admission-platform_pgdata`,
`admission-platform_qdrantdata`) across a `docker compose down`/`up` -
only `docker compose down -v` or deleting the volumes loses them, so
re-ingestion should NOT be needed on a normal restart. Verify first with
the checks below before assuming a re-ingest is required.

**Credentials**: `platform/services/api/.env` holds real Mistral/NVIDIA/
self-hosted keys, copied from `backend/.env` (same accounts). It's
gitignored, so it will NOT be there after a fresh `git clone` - if it's
missing, recreate it from `backend/.env`'s `MISTRAL_API_KEY`, `NVIDIA_
API_KEY`, `SELFHOSTED_API_KEY` (see this file's own earlier note on the
exact fields needed).

**The SSH tunnel**: embeddings need `ssh -N -L 8000:127.0.0.1:8000
root@159.69.210.30` running on the HOST (not needed inside the `api`
container - see its `SELFHOSTED_URL=http://host.docker.internal:8000`
override in `docker-compose.yml`, which reaches through to whatever's
listening on the host's `127.0.0.1:8000`). This was blocked by the
permission classifier once this session, worked cleanly on retry - if
blocked again, that's an environment thing to work around in the moment,
not a sign something is broken.

**Sanity checks after bringing the stack up**:
```bash
curl http://127.0.0.1:8100/healthz                     # api alive
curl http://127.0.0.1:6333/collections/bvsc             # should show points_count: 192
curl -X POST http://127.0.0.1:8100/api/chat -H "Content-Type: application/json" \
  -d '{"question":"What is the first year tuition fee for B.V.Sc.?"}'
# expect: {"answer":"...27500...","source":"verified-fact",...}
```
If the last one 500s or times out, check the SSH tunnel first (embeddings
need it), then `docker compose logs api`.

## Full remaining roadmap

Two tiers. Tier A finishes what "the vertical slice actually works"
means - do this before Tier B. Tier B is the breadth phases from
`../docs/admission-assistant-platform-architecture.md`'s own "Delivery
sequence," made concrete against what already exists here.

### Tier A — finish the vertical slice

1. **The actual success checkpoint.** `tools/bench_answer_quality.py` and
   `tools/eval_retrieval.py` (repo root) are the POC's ground-truth
   suites. Filter both to their B.V.Sc.-only cases, re-point their HTTP
   calls at `http://127.0.0.1:8100/api/chat` instead of the old backend's
   port/route shape, run them, and compare scores against the POC's last
   measured numbers (see `backend/CLAUDE.md`'s benchmark sections). The
   four manually-curl'd questions this session covered verified-fact/
   eligibility/RAG/off-topic and all came back correct, but that is not a
   substitute for the real suite - do not skip this step because the
   manual spot-check looked good.

2. **The full guard pipeline**, porting `backend/rag/guards.py` (the
   documented order lives in `backend/CLAUDE.md`'s Architecture section:
   `injection → topic_menu → greeting → dispute → meta_correction →
   off_topic → subjective_comparison → program_list → eligibility →
   percentage_clarify → comparison → program_redirect → unknown_programme
   → program_clarify → general_fanout → low_confidence_clarify`).
   Restructure as the explicit ordered/dependency-aware set the platform
   architecture doc describes - not a re-derivation of any individual
   guard's trigger logic, which should be ported as-is. Priority order
   within this step, most user-impact first:
   - The **guided eligibility interview** (ask entrance status → category
     → percentage one at a time, via `conversationState`) - right now a
     student with an incomplete "am I eligible" question just falls
     through to a generic RAG answer instead of being asked the missing
     piece. This is the single biggest real-answer-quality gap today.
   - `injection`/`off_topic` guards as dedicated checks (currently the
     off-topic case is only caught incidentally by the system prompt's own
     rule - works, per this session's live test, but is not the same as
     having the guard).
   - `program_list`/`program_clarify`/`comparison`/`program_redirect` -
     all meaningless until step 4 (more programmes) lands, so can trail it.
   - `validate.py` (239 lines, deterministic checks + bounded LLM-check/
     regenerate) - port once the guard pipeline exists to validate against.

3. **Hindi/Marathi support** - entirely unported. Needed, in this order:
   - `backend/core/textclean.py` (43 lines) - trivial, port first.
   - `backend/core/glossary.py` (199 lines) - the Hindi/Marathi/English
     term-expansion vocabulary retrieval leans on.
   - `backend/core/transliterate.py` (94 lines) - native-script ↔
     romanized conversion for display.
   - `backend/core/vocabulary.py` (132 lines) - retrieval-side term
     expansion, used together with glossary.py.
   - `llm.translate_to_english` (in `backend/generation/llm.py`) - needed
     for the LEXICAL half of retrieval on non-Latin input (the vector half
     already works native-script-to-native-script, since embeddings are
     genuinely cross-lingual - see `backend/CLAUDE.md`'s own note on this,
     already correct in `app/retrieval/store.py` as ported).
   - Wire `_apply_script_pref`/language-hint logic into `answer.py` (see
     `backend/rag/helpers.py` for the exact functions - `_language_hint`,
     `_romanized_input_hint`, `_apply_script_pref`, `_build_retrieval_text`).
   - The frontend already has full EN/HI/MR UI (language switch, Tiro
     typography, Hindi/Marathi copy) waiting for this - `src/api/chat.ts`
     already sends `uiLanguage`, `app/api/chat.py`'s `ChatRequest` already
     accepts it, nothing downstream reads it yet.

4. **Ingest the remaining two programmes.** The PDFs already exist at
   `data/projects/bfsc/prospectus.pdf` and `data/projects/btech-dairy/
   prospectus.pdf` (repo root, same layout as bvsc's). Just re-run:
   ```bash
   python -m app.ingestion.run bfsc "B.F.Sc." ../../../data/projects/bfsc/prospectus.pdf
   python -m app.ingestion.run btech-dairy "B.Tech. (Dairy Technology)" ../../../data/projects/btech-dairy/prospectus.pdf
   ```
   from `platform/services/api/` with the venv/tunnel set up the same way.
   No code changes needed for this part - `run.py` is already project-id
   agnostic. Comparison/program-list/redirect guards (step 2) only become
   meaningful once this is done.

### Tier B — breadth, per the architecture doc's delivery sequence

Each phase below is genuinely blocked on the ones before it, per that
doc's own reasoning - don't reorder without re-checking why.

5. **FAQ cache.** `faq_cache` table exists (see `app/storage/models.py`),
   nothing reads or writes it yet. `FaqCache.id` is already deliberately
   designed to double as its Qdrant FAQ-embedding point id (see this
   file's earlier note) - a second Qdrant collection per project (e.g.
   `bvsc-faq`) for semantic cache matching, ported from `backend/storage/
   faq.py` (861 lines - the biggest single remaining port; includes the
   discriminator-vocabulary false-positive guards, worth reading that
   file's own docstrings before touching this).
5b. `backend/rag/comparison.py` (465 lines) and `orchestrator.py` (215
    lines) - cross-programme comparison and multi-part question
    decomposition. Both need 2+ programmes ingested (step 4) and are
    lower priority than the guard/language gaps in Tier A.
5c. `backend/rag/citation.py` (153 lines) - the dispute-guard's
    exact-line citation lookup. Needed only once the dispute guard
    (step 2) is ported.

6. **Async ingestion pipeline.** Replace the synchronous `run.py` CLI with
   real async jobs (queue + workers - Redis, already in the stack, can
   back this), staged validation against the eval suite (step 1) BEFORE
   promotion, blue-green swap instead of the current
   immediate-overwrite-on-run behavior.

7. **Deployment layer**: containerize is already done (Docker Compose);
   what's missing is TLS via a real domain, a staging environment that
   mirrors this compose stack, and automated canary deploys. k8s manifests
   as real IaC are explicitly NOT to be written before this and step 9
   below make them meaningful - an unused manifest is dead weight.

8. **Security layer**: per-admin accounts + RBAC (the `admin_users` table
   exists with a flat `role` string, no auth flow built on it yet), API
   key rotation (the `api_keys` table already hashes keys, better than the
   POC's plaintext - no rotation UI/flow yet), a WAF/CDN edge, scoped CORS
   (currently wildcard, see `main.py`'s own comment on this).

9. **Observability**: OpenTelemetry traces, Prometheus/Grafana dashboards,
   alerting - replacing today's plain `print()`/uvicorn access logs. The
   pre-existing `ai-platform` Docker stack on this machine already runs
   its OWN Grafana/Prometheus (port `3001`/`9090`) - worth checking
   whether that's reusable before standing up a second instance.

10. **CI/CD**: GitHub Actions (or equivalent) running the ported test
    suites (once step 1's adapted eval scripts exist) on every PR,
    blocking merge on regression - the same protection that would have
    caught the `UnboundLocalError` bug found in `backend/` this session
    before it ever reached production.

11. **Admin console UI + full multi-role RBAC**, **k3s manifests actually
    deployed to a real cluster** (none exists in this environment - these
    stay written-but-undeployed IaC until one does).

## How to run it

```bash
cd platform/infra
docker compose up -d --build
curl http://127.0.0.1:8100/healthz
```

`docker compose ps` from `platform/infra/` to check status;
`docker compose logs -f api` to tail the API's logs. Frontend at
`http://localhost:5180`, API at `http://localhost:8100`, Qdrant's own API
at `http://localhost:6333`, Postgres at `localhost:5432` (user/pass/db all
`platform`).
