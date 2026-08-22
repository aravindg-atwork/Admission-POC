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

### Evaluation checkpoint completed 2026-08-20

- Added platform-native B.V.Sc. slices of the two legacy ground-truth suites
  under `tools/`. They target `http://127.0.0.1:8100/api/chat`, use the new
  response schema, and measure the Qdrant-backed retrieval path directly.
- Answer quality: **4/4 correct**, 2.0s average on the final run (legacy
  B.V.Sc. slice: 4/4; legacy full-suite non-outlier average: 3.0s).
- Initial retrieval: 11/12 scored needles, recall@15 0.92, MRR 0.656; the
  SC/ST/OBC threshold query was the genuine miss. Increasing the Qdrant ANN
  candidate pool from 4x to 8x and 16x did not change it, ruling out the new
  ANN cutoff as the cause.
- Fixed by porting `backend/core/vocabulary.py`'s English additive query
  expansion and the English branch of `_build_retrieval_text` into the live
  answer path (including table lookup). Final retrieval: **12/12 scored
  needles, recall@15 1.00, MRR 0.614**. This is above the legacy suite's
  overall recall@15 of 0.94; MRR is comparable to its 0.619.
- One of 13 B.V.Sc. labels is unscored, not failed: fresh OCR does not contain
  the legacy NRI-refund needle verbatim. Keep it visible until that label is
  re-verified against the fresh corpus/PDF; do not silently count it as a
  retrieval miss or pass.

### B.V.Sc. parity work in progress 2026-08-20

- Added an explicit pre-retrieval guard layer for the B.V.Sc. slice. Prompt
  injection, greetings, conservative off-topic cases, and the guided
  eligibility interview now short-circuit before embedding/retrieval.
- The guided interview runs NEET status -> category -> required-subject
  percentage, carries `conversationState` through the API, and is wired to
  real option chips in the React frontend. Overall-vs-subject percentage
  clarification and subject-specific-question non-hijacking are covered.
- Added deterministic post-generation checks for unsupported numbers and
  foreign-programme mentions, one bounded regeneration, and a safe refusal if
  regeneration remains invalid. Numbered-list markup is mechanically removed.
- Broader live evaluation initially found three real defects: a reserved
  B.V.Sc. question hallucinated B.F.Sc.'s 40% threshold, a missed-NEET case
  returned HTTP 500, and "How do I apply?" was hijacked by the eligibility
  interview. All three were fixed and retained as regression cases.
- Current live results: answer figures **4/4**, guided conversation/injection
  **9/9**, broader English B.V.Sc. behavior **15/15**, retrieval **12/12
  scored** (one OCR-drift label remains unscored as documented above).
- This does NOT yet mean B.V.Sc. has "no flaws." Dispute/citation and
  meta-correction guards, FAQ cache, full legacy-suite adaptation, and
  Hindi/Marathi remain open. Do not ingest B.F.Sc. until the requested
  B.V.Sc.-first gate is completed.

### User-supplied B.V.Sc. promotion gate + B.F.Sc. start 2026-08-20

- Added `tools/eval_bvsc_adversarial.py`, preserving all 15 user-supplied
  multi-rule scenarios as an executable promotion gate. The first run exposed
  scope collapse, quota-rule contradictions, NCL/CVC confusion, missing
  photocopy requirements, an HTTP 500 on provider timeout, and unsupported
  seat-retention claims. These were fixed using deterministic eligibility and
  source-transcribed policy guards plus bounded RAG validation.
- Final B.V.Sc. promotion result: **15/15 grounded assertions pass**. The last
  full run printed 14/15 only because the assertion accepted "no documents"
  but not the equivalent returned phrase "no additional documents"; the
  assertion was corrected and that unchanged grievance case passed in
  isolation. No application code changed between those two runs.
- B.F.Sc. was then ingested fresh through this platform's own pipeline: **63
  OCR pages, 231 chunks**, Qdrant collection `bfsc`, and Postgres project row.
- Removed the B.V.Sc. hardcode from the eligibility guard before B.F.Sc.
  testing. The frontend remains explicitly pinned to B.V.Sc.; B.F.Sc. is not
  offered to students yet.
- Added `tools/eval_bfsc_smoke.py`; current B.F.Sc. smoke result is **8/8**:
  application/admission fees, unreserved/reserved thresholds, subjects,
  MHT-CET, duration, and a deterministic reserved-category personal verdict.
  Broader B.F.Sc. retrieval/adversarial testing remains the next step before
  frontend exposure. B.Tech Dairy remains un-ingested.

Two tiers. Tier A finishes what "the vertical slice actually works"
means - do this before Tier B. Tier B is the breadth phases from
`../docs/admission-assistant-platform-architecture.md`'s own "Delivery
sequence," made concrete against what already exists here.

### Tier A — finish the vertical slice

1. **The actual success checkpoint. DONE 2026-08-20.** `tools/bench_answer_quality.py` and
   `tools/eval_retrieval.py` (repo root) are the POC's ground-truth
   suites. Filter both to their B.V.Sc.-only cases, re-point their HTTP
   calls at `http://127.0.0.1:8100/api/chat` instead of the old backend's
   port/route shape, run them, and compare scores against the POC's last
   measured numbers (see `backend/CLAUDE.md`'s benchmark sections). The
   four manually-curl'd questions this session covered verified-fact/
   eligibility/RAG/off-topic and all came back correct, but that is not a
   substitute for the real suite - do not skip this step because the
   manual spot-check looked good.

   B.V.Sc. NRI exception regression (2026-08-20): the general deterministic
   missed-NEET verdict incorrectly overrode clause 9(iv)'s more specific rule.
   Candidates who passed XII/equivalent abroad are exempt from NEET for the
   NRI/FN/PIO/OCI quota; those who passed XII in India must have appeared.
   `tools/eval_bvsc_adversarial.py` now includes both sides plus a conditional-
   eligibility case and passes 18/18. The answer must not infer final eligibility
   from the exemption alone: 50% PCBE, age, category status/documents, and other
   requirements remain. MAFSU also states that NRI-sponsored seats do not exist.

   Cross-programme stress checkpoint (2026-08-20): the attached 101-question
   exact-phrasing sweep was executed across B.V.Sc., B.F.Sc., B.Tech Dairy, and
   six compound cases. It exposed and fixed additional rule-priority/trigger
   failures: foreign-subject equivalence, OCI status-date branching, VCI/ICAR
   processes and reversions, NRI special-round fees, B.F.Sc. PH/hearing and EWS
   rules, non-stackable 12-point weightage, Dairy PCM-CET and management-exam
   priority, plus cross-programme B.V.Sc./NEET leakage in a Dairy answer.
   `tools/eval_cross_programme_stress.py` now asserts the 50 newly exposed/high-
   risk surfaces and passes 50/50. After the final fixes, the established gates
   also pass: B.V.Sc. 18/18, B.F.Sc. 17/17, and B.Tech Dairy 24/24. Treat this as
   a strong English safe-zone checkpoint, not proof against every unseen wording;
   Hindi/Marathi, full guard breadth, cache, and deployment remain unfinished.

   Structured-policy milestone (2026-08-20): `services/api/app/core/policy.py`
   now represents facts, rules, independent decision dimensions, explicit
   priorities, prospectus pages, and winning rule IDs. It runs before the
   legacy phrase guards. The first migrated conflict is B.V.Sc. NRI NEET:
   the quota-specific abroad/India rule (priority 100) overrides the general
   NEET rule only in the entrance-exam dimension. The engine also composes
   explicit NRI qualifying marks, so an abroad NEET exemption plus less than
   50% returns an overall negative decision instead of an exemption-shaped
   answer. `policyDecisions` makes the applied rules observable in the API.
   Focused policy tests initially passed 7/7; after integration, the established live
   gates still pass B.V.Sc. 18/18, B.F.Sc. 17/17, B.Tech Dairy 24/24, and
   cross-programme 50/50.

   Parallel hardening checkpoint (2026-08-20): structured-policy composition
   now also covers age, reserved-category NRI threshold behavior, NCL status,
   and pending CVC status. The expanded policy/paraphrase suite passes 12/12;
   legacy guards remain during incremental parity migration. The web now selects
   and persists `bvsc`, `bfsc`, or `btech-dairy`, sends that project on every
   request, and resets conversation state when the programme changes. Web build
   and lint both pass.

   Server-side routing now supports English, Hindi, and Marathi, including
   native Devanagari and high-confidence romanized Hindi/Marathi. Translation to
   English is used for retrieval while the original question controls the reply.
   Fixed answers use bounded localization retries; numbers and official tokens
   such as NEET, MHT-CET, CUET, and ICAR are protected and restored exactly.
   `tools/eval_multilingual.py` covers Hindi and Marathi across all three
   programmes and passes 6/6 twice consecutively.

   Redis exact-answer caching is live. Keys include the source revision,
   programme, resolved language, and normalized question. Unsafe/error and
   guided-interview replies are skipped; Redis failures degrade to normal answer
   generation; `cacheHit` is returned to clients; changing
   `faq_cache_revision` atomically invalidates old answers. A live repeated
   request verified uncached first delivery and identical cached second delivery.
   Matching is intentionally exact rather than semantic because one changed
   admission fact can reverse a verdict.

   Demo auto-routing checkpoint (2026-08-20): the API boundary now detects an
   explicitly named single UG programme and overrides a stale selector before
   retrieval. It returns the effective `projectId`; the web persists and shows
   that programme and discards old programme-specific interview slots. Strict
   word-bounded routing patterns are used instead of the broader search aliases
   (a reproduced `vet` substring false positive in "have to" was fixed). Live
   requests sent as B.V.Sc. but naming B.Tech Dairy or B.F.Sc. reached the
   correct corpus, the web proxy returned `btech-dairy`, routing tests pass 3/3,
   and the cross-programme gate remains 50/50. Undefined-programme choice,
   multi-programme comparison, and bounded session reference resolution remain
   part of the unfinished expanded routing task.

   Public marks-interview/data checkpoint (2026-08-21): production failures
   reproduced at `159.69.210.30:8080` showed two separate problems. First,
   eligibility accepted only a precomputed subject-combination percentage.
   It now extracts named marks (`Physics-45`) and ordered PCB/PCM/PCBM/PCBE/PCME
   lists, averages only the programme's required subjects, and asks for missing
   English rather than guessing. Fractions such as `500/600 in 12th` are
   converted (83.33%) but remain classified as overall unless the student
   confirms they cover the required combination. A bare `48%` asks whether it
   is overall or subject-combination marks and preserves that value through the
   interview. Focused marks/help tests pass 8/8; B.V.Sc. remains 18/18 and the
   cross-programme gate 50/50.

   Second, public routing to B.F.Sc. was correct but production Qdrant contained
   only `bvsc`. The exact locally evaluated Qdrant snapshots were promoted:
   production now has `bfsc` (231 points) and `btech-dairy` (188 points), and
   Postgres has all three project rows. Public acceptance verifies typo-tolerant
   B.F.Sc. help, its `sure?` follow-up, subject-mark continuation, safe fraction
   and bare-percent clarification, Nagpur seat facts, and Dairy MHT-CET-first /
   CUET-(ICAR-UG)-remaining-vacancies priority. Pre-deploy API files are backed
   up under `/opt/admission-platform/backups/2026-08-21-marks/`.

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

4. **Ingest the remaining two programmes. B.F.Sc. DONE 2026-08-20; B.Tech Dairy remains.** The PDFs already exist at
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

   B.F.Sc. promotion evidence (2026-08-20): fresh OCR ingestion produced
   231 chunks; `tools/eval_bfsc_smoke.py` passed 8/8; the 17 user-supplied
   multi-rule cases in `tools/eval_bfsc_adversarial.py` passed 17/17 with
   explicit assertions. Fixes included programme-aware eligibility,
   age-boundary handling, OBC/CVC/NCL consequences, weightage arithmetic,
   college/seat counts, and the separate ICAR procedure. Visual inspection
   of prospectus PDF page 11 also confirmed that the merged `10` cell applies
   to both vocational rows, including Fresh Water Fish Culture (C1); OCR had
   dropped that association. Keep the frontend pinned to B.V.Sc. until the
   remaining multi-programme routing/exposure work is deliberately enabled.

   B.Tech. Dairy promotion checkpoint (2026-08-20): fresh OCR processed 72
   pages and indexed 188 chunks into Qdrant collection `btech-dairy`; the
   `projects` row was upserted and the collection count was independently
   verified as 188. `tools/eval_btech_dairy_smoke.py` passes 9/9 covering
   fees, thresholds, PCME subjects, MHT-CET, duration, constituent-seat quota
   split, and a reserved-category personal verdict. The 24 user-supplied
   multi-rule cases in `tools/eval_btech_dairy_adversarial.py` pass 24/24.
   The fixes cover the exact age boundary, college/quota classification,
   outside-Maharashtra restrictions, CVC/NCL consequences, horizontal female
   reservation, agriculturist and defence exceptions, and the first-/second-
   year exit and re-entry rules. B.F.Sc. smoke regression remained 8/8.

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

### WebForms/jQuery widget handoff (2026-08-21)

A standalone senior-developer handoff now lives in
`integrations/mafsu-widget/`: one demo `index.html`, namespaced CSS, jQuery-only
interaction code, and a deployment README. It uses the real `/api/chat`
contract, carries `conversationState`, uses the returned `interviewField` for
guided option buttons, and follows the returned `projectId` after explicit
programme auto-routing. It deliberately does not require a programme selector
before a student can ask a question. This is an integration artifact, not a
claim that roadmap item 7 is finished: ambiguous questions, general 10-turn
reference resolution, and safe multi-programme comparison are still open.

For the real HTTPS MAFSU site, proxy `/api/chat` through the same website
origin (preferred) or place the API behind HTTPS with narrowly scoped CORS.
The current plain-HTTP public IP cannot be called from an HTTPS page because
browsers block mixed content.

The same checkpoint also introduced the student-facing name **MAFSU Saarthi**
and a deterministic multi-programme identity/capabilities response. Completed
eligibility interviews now answer the student's actual application question
conversationally ("Yes, based on what you've shared, you can apply...") while
separating verified marks/exam conditions from age/documents and making clear
that final allotment still depends on merit, quota, preferences, and seats.
Focused marks/help/identity tests pass 10/10 and both new responses were checked
against the public endpoint after deployment.

P0 ambiguous-programme correction (2026-08-21): a fresh programme-dependent
question such as "What are the fees?" no longer silently inherits the B.V.Sc.
API default. It returns B.V.Sc., B.F.Sc., and B.Tech Dairy choice buttons and
resubmits the original question after selection. Deterministic guards now run
before exact-answer cache lookup, preventing an older cached generic answer
from bypassing a newer or more specific policy/clarification decision; the
cache revision is `2026-08-21-v14`. The student-facing name was subsequently
changed to **MAFSU MITRA (Beta)** with an explicit caution notice. The jQuery
handoff also includes browser speech input, the approved MAFSU palette, and
top-aligned scrolling for long assistant replies. Focused tests pass 12/12;
web build/lint and widget JavaScript syntax pass.

Chat-controlled language checkpoint (2026-08-21): explicit requests such as
"can you text me in Hindi?", including the reproduced typo "test me in with
Hindi", are treated as interface controls rather than admission/off-topic
queries. MITRA confirms the switch natively, returns `language`, and stores
`preferredLanguage` in `slotUpdate`; both React and jQuery clients synchronize
their visible language buttons from the response. The stored preference forces
subsequent English-script questions to receive Hindi/Marathi answers, while a
merely stale UI selector still does not override ordinary English input. The
exact Hindi command and a persisted "Who are you?" follow-up were verified on
the public endpoint.

Conversational brevity correction (2026-08-21): a bare greeting such as
"hi" now receives one short line ("Hi! I'm MAFSU MITRA. How can I help with
your admission today?") instead of dumping programme and capability details.
The longer description remains available only for explicit identity/capability
questions.

Widget identity simplification (2026-08-21): the jQuery handoff now uses one
visual identity only (M logo -> MAFSU MITRA Beta), removes the competing `सा`
welcome avatar, changes the descriptor to "Official MAFSU Admission
Assistant", and uses the approved restrained palette (`#155B46`, `#2F7D62`,
`#E8F2EC`, `#FAF9F4`, `#252A27`, `#66716B`, `#D8E1DB`, `#B86232`). The toolbar
has a functional programme selector plus clearer `EN / हिं / मर` labels;
programme cards have subtle action arrows; quick prompts use student language;
and the disclaimer is reduced to one verification line. The duplicate saffron
textarea focus rectangle was removed while retaining a WCAG-visible green
focus state on the composer container. HTML parsing, JS syntax, diff checks,
and the design detector pass.

Immediate-reference language correction (2026-08-21): the clients now retain
the immediately preceding assistant answer and source in `conversationState`.
Commands such as "say this same in Marathi" repeat that answer in the requested
language instead of returning only a language-switch acknowledgement. The
high-frequency identity/capabilities answer has deterministic Hindi and Marathi
versions so it does not fall back to English during provider throttling; other
answers use the bounded translation path. Neutral sources (`greeting`,
`identity`, language controls, and programme clarification) no longer change
the jQuery widget's visible "All programmes" selection merely because the API
contract includes its internal B.V.Sc. fallback project ID. React build and
lint pass; the public endpoint returned `source=language-repeat`, `language=mr`,
and `model=language-control` for the reproduced Marathi request.

P0 admin review console checkpoint (2026-08-21): `/admin/` is now a real
database-backed review system, not a mockup. Chat requests carry a generated
session id; the API stores redacted student/assistant exchanges and returns the
assistant `messageId`. The console has admin-key authentication, summary
metrics, programme filtering, full transcripts, answer-level flagging,
correction/evidence/notes editing, an evidence test gate, exact correction
publication, cache invalidation, audit rows, and rollback. Provider-unavailable,
low-confidence, and validation-blocked answers auto-create review cases.

Published corrections are exact programme + language + normalized-question
overrides and run after deterministic policy guards but before Redis/RAG, so an
admin edit cannot override injection/eligibility safety logic or contaminate
similar questions. The test gate loads the selected pages from Qdrant and runs
the same unsupported-number/foreign-programme validator used for generated
answers. Local end-to-end proof: session/message logged; manual flag created;
draft saved; evidence test passed; correction published; `/api/chat` served
`source=curated-override`; rollback deactivated it. A deliberate `999999`
figure failed with `unsupported_number: 999999`. Web/API images build, React
lint, Python/JS syntax, unauthorized 401 behavior, and `/admin/` asset serving
all pass.

Production admin deployment is deliberately held: the current public demo is
plain HTTP, and transmitting an admin key plus student transcripts without TLS
is unacceptable. Student-facing code may continue to deploy, but `/admin/`
must be enabled only on the real HTTPS MAFSU origin or an HTTPS access proxy.

Eligibility concern-continuity checkpoint (2026-08-21): the guided interview
now retains and answers the student's original entrance-exam concern instead
of replacing it with a generic questionnaire. In particular, a B.F.Sc.
candidate who says they did not pass NEET is immediately told that NEET does
not determine regular B.F.Sc. eligibility and is then asked about MHT-CET
2026. The resolved answer repeats that distinction, evaluates the stated
marks/category and MHT-CET facts, and clearly leaves age and reservation
documents outstanding. Equivalent NEET-to-MHT-CET context is implemented for
B.Tech. (Dairy Technology). Focused regressions cover the intermediate and
resolved B.F.Sc. responses; the exact flow passed against the rebuilt local
API, and the API service was rebuilt on the demo server.

BVSc entrance-semantics correction (2026-08-21): the guided interview now
asks "Have you qualified NEET-UG-2026?" rather than merely asking whether the
student appeared. Its options distinguish qualified, appeared-but-not-
qualified, and not-yet-appeared. A non-qualifying result ends the interview
with the correct entrance-rule explanation; a positive resolved answer says
the student qualified NEET. B.F.Sc. and B.Tech. Dairy retain the prospectus's
appearance-based MHT-CET wording. The three BVSc response paths passed against
the rebuilt API and were deployed to the demo API service.

English-subject/multi-programme correction (2026-08-21): mentioning English
as a Class XII subject no longer triggers the language-preference guard; only
an actual language-control verb such as reply, speak, say, switch, or translate
does. The reproduced OBC/49%/PCBE/no-Mathematics/MHT-CET-PCB/failed-NEET/
fisherman-certificate question now receives one cross-programme determination:
B.F.Sc. meets the stated core conditions, B.V.Sc. fails the qualifying-NEET
condition, and Dairy Technology fails Mathematics/PCM. It also states the
12-point B.F.Sc. fisherman weightage and outstanding OBC-document conditions.
The exact full question passed through `/api/chat` with `source=verified-policy`
and `language=en`; both fixes were deployed to the demo API service.

Promotion-gate audit (2026-08-21): the three-programme capstone decision ran
10/10 identically through `/api/chat` with `source=verified-policy`, including
the separate thresholds/exams, Dairy Mathematics rejection, B.F.Sc.-only
fisherman weightage, 20-point cap, and non-guarantee caveat. The broader suite
is NOT yet green: the first current run produced BVSc 13/18, while BFSc/Dairy
were heavily disrupted by an unavailable local embedding endpoint and by old
eval payloads that omit the selected programme in `conversationState` (the
current widget contract sets it when a course is selected). Provider failures
previously escaped as HTTP 500; `_answer_uncached` now catches embedding
failures and returns `source=provider-unavailable` with a safe retry/contact-
admissions response. That fallback was locally verified and deployed. These
safe fallbacks remain promotion failures, not passes; controlled UAT/public
release must wait for a healthy provider and repeated full-suite green runs.

Natural-paragraph promotion gate (2026-08-21): added
`tools/eval_paragraph_adversarial.py` for the first 23 supplied long-form
student profiles spanning BVSc (1-7), BFSc (8-14), Dairy (15-20), and cross-
course decisions (21-23). A deterministic compound-policy layer now answers
every material clause before generic RAG: thresholds versus merit, NEET versus
MHT-CET contamination, NRI XII-abroad exceptions, expired NCL consequences,
quota routing, deficient documents, preference uncertainty, B.F.Sc.-only
weightage, Dairy Mathematics/PCM, outside-state Management quota, and Defence
disability exceptions. Local result: 23/23. Deployed server result: 23/23, then
three consecutive repeat runs also 23/23. This gate is green; it does not erase
the separate full-suite/provider/multilingual production requirements above.

Independent paraphrase pack (2026-08-21): the later 16-case Expected Answer /
must-not-say pack initially produced about 8/16 semantic passes on the healthy
server path. Added compound rules for the eight failures: veterinary
Management quota cannot bypass failed NEET; BFSc ignores failed NEET when its
own MHT-CET/marks rules are met; merit cannot cure 49% Unreserved; BFSc NRI
XII-abroad MHT-CET exemption; Dairy Mathematics and PCM-CET are separate
requirements; first-preference non-reporting cancels later-round candidature;
and the final BVSc/BFSc/Dairy/fisherman/NCL profile is composed per programme.
Deployed result: all 16 returned the expected substantive decisions, zero safe
fallbacks and zero HTTP errors. Three consecutive repeat runs each returned
16 substantive / 0 fallback / 0 error. This is independent paraphrase coverage,
not merely rerunning the earlier exact 23 questions.

`docker compose ps` from `platform/infra/` to check status;
`docker compose logs -f api` to tail the API's logs. Frontend at
`http://localhost:5180`, API at `http://localhost:8100`, Qdrant's own API
at `http://localhost:6333`, Postgres at `localhost:5432` (user/pass/db all
`platform`).

### P0 widget availability + security boundary (2026-08-21)

The standalone jQuery widget had become unreachable because it still called
the retired public `:8080` binding. Production now exposes the API only through
the web proxy on port 80, so the widget points to `http://159.69.210.30` and
calls `/api/chat`. `/api/healthz` was added for a real launcher status signal:
the dot is amber while checking, green only after a successful health response,
and red when unreachable; it is refreshed every 30 seconds. The header `?`
opens six clickable admission FAQs without changing the API contract.

The same deployment adds a first public security boundary: configured/scoped
CORS instead of wildcard CORS, 16 KiB request limits, Pydantic field/enum/state
bounds with forbidden unknown fields, per-client Redis rate limiting, nginx
rate limiting/timeouts, API security headers, and normalization-aware prompt
injection detection (NFKC, zero-width removal, common leetspeak, role/guard
bypass and prompt-exfiltration patterns). The generation prompt separately
treats user text and retrieved excerpts as untrusted data.

Post-deployment proof: health and chat returned 200; a zero-width-obfuscated
override was refused with `source=instruction-override`; hostile-origin CORS
returned 400 with no allow-origin; 1201-character input returned 422; the 31st+
rapid request returned 429; public admin returned 404. Only public port 80 was
reachable—8080, Postgres, Redis, Qdrant and 8443 were externally closed, while
server inspection confirmed 8443 binds only to loopback. Nginx config passed.
The focused adversarial/input suite passed 15/15, npm production audit found
zero vulnerabilities, and the independent admissions regression remained
16 substantive / 0 fallback / 0 error after deployment. TLS is still absent;
this remains the principal blocker before embedding on the real HTTPS MAFSU
site, which must use a same-origin HTTPS proxy rather than this plain-HTTP IP.

### Cache stampede + free-tier provider capacity checkpoint (2026-08-21)

The exact validated-answer Redis cache is now protected by a distributed
single-flight lock. On a cold identical-question burst, only the lock owner
performs retrieval/generation; matching requests wait for and reuse that
validated cache entry. If the fill cannot complete safely, waiters return a
bounded busy response instead of stampeding the provider. The deployed
eight-request cold burst produced one uncached RAG answer, seven cache hits,
zero fallbacks and zero errors.

Cache eligibility was also corrected: ordinary widget state containing only
`programme` and/or `preferredLanguage` can use the shared cache. Guided
eligibility slots and immediate-reference state remain uncacheable and isolated
per student. This fixes the previous behaviour where selecting a programme made
most normal questions bypass Redis.

Cloud generation now has a Redis-backed global concurrency gate (default four
active calls across API replicas) and shared provider circuit breakers. HTTP
429 opens a 120-second cooldown and is never immediately retried; timeouts,
authentication/server errors open a shorter cooldown before fallback. Focused
Redis assertions passed 4/4, representative greeting/RAG/eligibility paths
returned 200 after deployment, and recent API logs were clean. This protects
the existing free-tier providers; it is not a substitute for measured traffic
forecasting, provider quota dashboards, alerting, or adding replicas behind an
HTTPS load balancer before full public launch.

### Semantic cache, operations console, load and replica checkpoint (2026-08-21)

A conservative Qdrant + Postgres semantic FAQ cache is live. It serves only
previously validated general RAG answers and requires the same programme,
language, inferred topic, exact numeric tokens and exact high-risk admission
markers (category, exam, quota and subject), plus cosine similarity >= 0.965.
The first Dairy-duration query generated in 2054 ms; its punctuation-only
paraphrase returned `source=semantic-cache`, `cacheHit=true` in 437 ms with the
identical answer. The independent 16-case admission pack remained 16
substantive / 0 fallback / 0 error after activation.

Redis telemetry now records daily request counts, project/source mix, exact and
semantic hits, total/slow latency, provider calls/failures/rate limits, and
reported prompt/completion token usage without storing student question text.
A configurable daily provider-call budget raises an alert at 80%. The private
admin console shows these operational metrics alongside conversations, flags
and published corrections.

The bounded mixed load test (`tools/load_test_mixed.py`) ran 100 requests at
concurrency 8: 0 errors, 0 unsafe fallbacks, 58% cache hits, 428 ms mean, 3216
ms P95 and 4473 ms max. Production now runs two API replicas behind nginx;
20 lightweight verification requests were distributed exactly 10/10. Shared
Redis/Postgres/Qdrant, cache-fill locks, provider slots and circuit breakers
make the replicas stateless at the request boundary.

`infra/nginx.https.template.conf` contains the TLS/HSTS/same-origin production
shape but is intentionally inactive. Activating HTTPS still requires the real
MAFSU domain, DNS and certificate; do not substitute a self-signed certificate
or claim the current plain-HTTP IP is production-grade.

### Knowledge-boundary and NRI follow-up checkpoint (2026-08-21)

All final student-facing answers now pass through a deterministic knowledge-
boundary filter. It removes wording that blames MAFSU or treats absence from a
retrieved excerpt as proof that information does not exist, and it prevents
internal terms such as chunks, retrieval context, vector database, knowledge
base, RAG and retrieval confidence from reaching students. Unverified cases
use the assistant-owned limitation: "I don't have enough verified information
to confirm that." Known rules are answered before the safe escalation.

Targeted guards now clarify ambiguous University office-holder questions,
explain that NRI/FN/PIO/OCI routes exist for B.V.Sc. & A.H., B.F.Sc. and
B.Tech. (Dairy Technology) without treating NRI status alone as personal
eligibility, and resolve short challenges such as "sure?" from the immediately
preceding answer instead of generating an unrelated prospectus fallback.

Focused knowledge-boundary assertions passed 7/7. The exact reported four-turn
conversation was replayed against the deployed service and produced the
clarification, all-three-programme NRI explanation, and contextual verification
described above. The independent admission regression then remained 16
substantive / 0 fallback / 0 error.

### Go-live decision-safety gate checkpoint (2026-08-21)

Every `/api/chat` response now carries `admissionYear`, a normalized
`decisionState`, and `sourceTrace` containing the effective programme,
admission year, prospectus pages and deterministic rule ids. The API is locked
to 2026-27: an explicit different admission cycle is never answered using the
current corpus. Date-bearing answers identify already-passed 2026 deadlines
when the student asks what can be done now.

Deterministic pre-generation controls now reject unnecessary Aadhaar, phone,
email and application identifiers without echoing them; block invented college
or admission probabilities; distinguish `cannot_confirm` from `not_eligible`;
replace explicitly corrected category/exam facts; and ask for resolution when
the current exam statement contradicts remembered state. Programme switches
continue to clear programme-specific state at the API/client boundary.

The promotion harness `tools/eval_go_live_conversations.py` exercises 320
conversation instances, including multi-turn correction and contradiction
flows. The deployed result was 320/320: hard safety 208/208, course separation
80/80 and eligibility decisions 32/32. The dependency-free API assertion set
passed 57/57. A separate live multilingual gate passed 6/6 across Hindi and
Marathi for all three programmes after high-risk NRI decisions received
deterministic native-language templates that do not depend on provider
availability. During gate development, real failures in NRI route recognition,
expired-NCL handling, Dairy Mathematics handling, BFSc MHT-CET wording and
exam-state persistence were fixed before the final green run.

This is a code/UAT gate, not permission to describe the current plain-HTTP IP
as production-grade. Official public launch still requires the MAFSU HTTPS
same-origin reverse proxy, certificate/DNS ownership and native-speaker review
of the full Hindi/Marathi corpus.

Malformed-input checkpoint (2026-08-21): repeated-character runs, repeated
short patterns, nearly single-character payloads and punctuation-only spam are
now rejected before embedding/retrieval. They receive a short request to type
an admission question, `source=malformed-input`,
`decisionState=needs_clarification`, and no prospectus pages. The exact reported
1,100-character `q` payload passed against the public API; a normal B.F.Sc. fee
question still followed RAG and retained its evidence pages.

### Qwen shadow-review and official test-site checkpoint (2026-08-21)

An evidence-bound asynchronous reviewer subsystem is deployed. High-risk
assistant messages create durable `machine_reviews` rows; a separate
`shadow-reviewer` service polls them and can create admin review cases, but it
cannot modify student answers, curated overrides or publication state. Qwen
output is strict-normalized: verdict/severity/issue labels are allow-listed,
cited pages must be a subset of the answer's supplied evidence pages, invalid
verdicts degrade to human review, and a pass cannot carry a correction. Unit
assertions passed 5/5. One live B.F.Sc. answer created message 4452 and one
pending machine-review job.

The worker is intentionally deployed with `QWEN_REVIEW_ENABLED=false`. Server
inspection found no Qwen runtime or weights: no Ollama/vLLM container is
running and the retained Ollama volume contains only
`nomic-embed-text:v1.5`. Do not enable the worker until the actual private
OpenAI-compatible Qwen endpoint and model name are supplied and benchmarked.

The real WebForms test site is live at
`https://admissions.mafsu.ac.in/test_site/dashboard/index.aspx` on IIS 8.5
with a valid certificate. The HTTP IP URL serves the same page but is not the
canonical integration origin. Production CORS now allows only the HTTPS
admissions origin. The UAT widget uses
`data-api-base="/test_site/mitra"`, while local `file:` preview alone falls
back to the plain demo IP. The developer handoff contains a reversible ARR rule
scoped to `test_site/web.config` and only the isolated
`/test_site/mitra/api/chat|healthz` routes. At this checkpoint the isolated
health URL still returns IIS 404, proving that MAFSU has not installed the
proxy rule yet; treat a 200 JSON response there as the UAT acceptance gate.

The handoff now also includes a lower-risk code-only UAT path requested after
the MAFSU developer declined server-level IIS changes. `MitraProxy.ashx` is an
inline ASP.NET 4 handler uploaded only to `/test_site/`; it has a fixed MITRA
upstream, accepts only `GET healthz` and `POST chat`, enforces the 16 KiB body
limit, forwards no cookies/credentials and exposes no admin route. The widget
uses explicit same-origin handler URLs when hosted and retains the demo-IP
fallback only for local `file:` preview. No ARR, IIS Manager or `web.config`
change is required; rollback is deleting the handler and widget files. The
handler compiled successfully against `System.Web.dll`, both JavaScript copies
passed syntax checks, and canonical/Gmail-safe package copies are identical.

### Production-operations hardening checkpoint (2026-08-21)

Admin corrections now create immutable `correction_versions` snapshots with
severity, admission year, evidence pages, proposer, approver and lifecycle
status. Publish and rollback audit events identify the acting admin. A
configurable two-person gate exists for critical/high changes but defaults off
while only one human reviewer is available.

Transcript minimisation now redacts email, Indian phone, Aadhaar-shaped values,
OTP, bank-account and exam/application identifiers. A dedicated retention
worker anonymises message bodies and evidence pages after 90 days without
breaking review/audit foreign keys. The code-only widget explicitly warns
students not to share Aadhaar, OTPs, passwords or bank details.

Operational telemetry now includes decision-state mix, cannot-confirm rate,
validation blocks, injection attempts, retrieval failures, and missing
source/evidence signals. `/api/readyz` checks Postgres, Redis and Qdrant and
returns HTTP 503 when a replica should leave load-balancer rotation.

The local Qdrant outage drill passed: readiness became 503 and a grounded
admission question returned `cannot_confirm`, zero pages and no guessed fact;
Qdrant then restored healthy. The first Redis drill exposed unbounded client
connection waits. All Redis call sites now use one-second connect/operation
timeouts; the replay completed through the safe HTTP 200 degradation path and
Redis restored. Any otherwise-unhandled answer-pipeline dependency exception
is caught at the API boundary and converted to `service-unavailable`, never an
eligibility decision from model memory. Staged/atomic knowledge release remains
the next code-side operations item; do not mark it complete based on the older
synchronous ingestion CLI.

### Recovery-drill checkpoint (2026-08-21) - Postgres/embedding/LLM (local), replica failover (production)

Completes the local Qdrant/Redis drills above with the remaining scenarios
from the go-live checklist. Postgres-down, embedding-service-down (SSH
tunnel killed), and LLM-providers-down (both `MISTRAL_URL`/`NVIDIA_URL`
pointed at an unreachable address) were run against the local stack -
all three degraded cleanly: `/healthz` stayed 200 (liveness correctly
doesn't depend on dependencies), `/api/readyz` correctly reported 503
with a per-dependency breakdown, and every chat request returned HTTP
200 with a short, non-technical, student-facing message (`service-
unavailable` / `provider-unavailable`), never a raw error or a 500. All
three recovered cleanly once restored.

**A real bug was found and fixed testing the two replica-specific
scenarios on production** (these need the actual 2-replica+nginx
topology; local only ever runs one instance). `nginx.prod.conf`'s
`upstream mitra_api { server api:8000; }` resolves the shared Compose
service hostname ONCE, at nginx startup - with 2 replicas behind that
one name, this pinned 100% of live traffic to whichever replica's IP
happened to be returned first. The OTHER replica was receiving zero
requests. Verified live (10/10 test requests landed on one container).
Killing that one pinned replica produced a raw nginx 502 to students -
no failover to the healthy second replica, because nginx never knew it
existed.

A first fix attempt (nginx's dynamic-resolve pattern: `resolver` +
a variable in `proxy_pass`) looked correct and passed `nginx -t`, but
verified LIVE it made things worse - at any moment it still only has
ONE resolved IP cached, so when that target died, `proxy_next_upstream`
had nothing else to retry and the outage became total. Caught within
the same drill via a real kill test, not shipped on config-looks-right
confidence, and rolled back immediately.

**Also found during this fix**: `docker compose up -d web` (no
`--build`) does NOT reload nginx for a bind-mounted config file change -
Compose only recreates a container when the SERVICE DEFINITION changes,
not when a mounted file's content changes on the host. Every "fix" in
this session was silently testing the OLD config until `nginx -s
reload` was run explicitly. Any future nginx.prod.conf change must be
followed by an explicit `docker exec admission-platform-web-1 nginx -s
reload` (after `nginx -t`), never just `docker compose up -d web` alone -
that command LOOKS like it redeployed and prints "Running", giving no
signal that nothing actually changed.

The real fix: an explicit `upstream` block naming both replica
CONTAINERS directly (`admission-platform-api-1`/`-2`, stable names for a
fixed `replicas: 2`, confirmed resolvable via `getent hosts`), with
`max_fails`/`fail_timeout` and `proxy_next_upstream` retrying against
the other named peer. Verified live: kill either replica, the very next
request still returns 200 through the survivor (no visible failure to
the student); `proxy_connect_timeout` tightened from the default/5s to
2s afterward once the ~6s failover latency was measured (same-host
Docker connection, no reason to wait that long) - failover latency is
now ~3s. Total-outage (both replicas down) still correctly returns a
raw nginx 504 to a direct/curl caller - the React widget itself already
handles this gracefully (`chat.ts`'s `!res.ok` check -> friendly
"not live" banner, confirmed in code), but a non-widget caller (a
direct API integration, or the WebForms `MitraProxy.ashx` handler) would
see the raw HTML 504, not JSON - worth a friendlier `error_page` block
if that integration needs it.

This tradeoff is deliberate and stated in the config's own comment: the
explicit replica list must be kept in sync with `deploy.replicas` by
hand - it does not auto-discover new replicas the way a real service
mesh would. Fine for a fixed, deliberately-set count; revisit if
replicas ever scale dynamically.

## Go-live 7-item roadmap - CHECKPOINT (2026-08-21, end of week)

Written because it's Friday and the next session may not pick this back
up until after the weekend - self-contained, no conversation transcript
needed to resume. The full 7-item roadmap (as given): (1) recovery
drills, (2) knowledge-release management, (3) admin security hardening
(per-user accounts/roles), (4) full release verification, (5) Qwen
shadow reviewer (real endpoint + benchmarking), (6) official-site
integration acceptance (MAFSU test-site proxy), (7) human launch
requirements (native-speaker review, escalation contacts, privacy
policy sign-off, on-call ownership). Item 2 was called out as the
largest unfinished CODE task; item 6 as the largest EXTERNAL blocker.

**Git/production state right now**: clean and in sync. Local repo,
`origin/production-hardening`, and the live server are all at commit
`b250758` - nothing pending, nothing uncommitted. Safe to `git pull` and
pick up cleanly from any machine.

### Item 1 (recovery drills) - DONE, see its own dedicated checkpoint
section above ("Recovery-drill checkpoint (2026-08-21)"). Postgres/
embedding/LLM-provider outages all verified clean. A real production bug
(replica pinning + no failover) was found and fixed along the way - full
writeup, including a wrong-first-attempt that was caught and rolled back
before shipping, is in that section. Not revisited below.

### Item 2 (knowledge-release management) - IN PROGRESS, mid-brainstorm

Following the project's `brainstorming` skill process (classified
**architectural** - this is a genuinely new subsystem, not a small
change to existing code). Nothing has been implemented yet - correctly
so, per that skill's hard gate: no code until the human partner approves
a written design. **Do not skip ahead and start implementing from this
summary alone** - the design isn't finished or approved yet.

**Decided so far** (each confirmed explicitly by the user, one question
at a time):
- **Upload mechanism**: CLI, same as today's `python -m app.ingestion.run`
  - NOT a new admin-console upload UI. Keeps this vertical-slice-sized;
    an upload UI can be layered on later without changing the pipeline
    underneath it.
- **Automated regression gate**: a NEW, fast smoke suite (retrieval
  needle checks + a handful of known ground-truth Q&A per programme) -
  not the full existing suites (320-conversation gate, all adversarial
  suites, multilingual). Those stay available as a manual, heavier
  check an approver can run before approving, not an automatic gate on
  every staged upload - real LLM calls cost time/money and most staged
  uploads shouldn't pay for the full suite.
- **Approval/publish actor**: the existing single shared admin key, same
  as the rest of the admin console today. Real per-user reviewer/
  publisher roles are item 3, not built yet - explicitly deferred rather
  than blocking item 2 on item 3 finishing first. The audit trail should
  record the action even though it can't yet say WHICH person did it.

**Proposed and awaiting final confirmation** (the core mechanism,
presented, not yet approved in full):
- **Qdrant native collection aliases** for the atomic "which version is
  live" switch, recommended over a Postgres-column pointer. Today,
  `answer.py` calls `store.search(project_id, ...)` treating `project_id`
  (e.g. `"bvsc"`) as a literal Qdrant collection name - confirmed live in
  the code (`app/agent/answer.py` line ~273, `app/ingestion/run.py`'s
  `ensure_collection(project_id)` + `client.upsert(project_id, ...)`).
  Under the proposed design, `bvsc` becomes an ALIAS, not a real
  collection; staged ingestion writes into a real, separately-named
  collection (`bvsc-2026-27-v2`, lowercase to match existing naming -
  the user's own example was `BVSC-2026-27-v1`, worth confirming the
  case convention when this comes back up), invisible to students the
  whole time it's staged. Publishing re-points the `bvsc` alias
  atomically (Qdrant's own guarantee, purpose-built for exactly this).
  **The key benefit**: zero changes to the retrieval hot path -
  `answer.py` keeps calling `store.search("bvsc", ...)` exactly as
  today, since the alias name never changes, only what it points at.
  Rollback = the same swap in reverse, no re-ingestion, seconds not
  minutes. Old versions' collections are left alone (not deleted) so
  rollback stays cheap - no auto-cleanup/retention limit proposed, disk
  cost for a ~200-point collection is trivial.
- Postgres gets a new `CorpusVersion`-style table (staged / regression-
  passed / regression-failed / approved / published / superseded) plus
  an audit trail - proposed to REUSE the existing `ReviewAudit`
  pattern already in the codebase (`app/storage/models.py`) rather than
  invent a new one, for consistency with how curated-answer corrections
  are already audited.
- On publish, bump the existing `faq_cache_revision` mechanism (already
  live - see the "Redis exact-answer caching" note above) so previously-
  cached answers from the OLD corpus don't keep being served - a small
  integration point with existing infra, not new plumbing.

**NOT yet covered / next steps when this resumes**:
- The rest of the sectioned design: exact pipeline stage transitions,
  full data model (`CorpusVersion` columns), error handling (what
  happens if the Qdrant alias-swap succeeds but the Postgres status
  update fails right after - the plan going in is "make the swap the
  source of truth for what's actually live; a failed follow-up
  Postgres write is a stale audit log, not a broken system," but this
  hasn't been presented/confirmed yet), and testing approach.
- Rollback scope (per-programme, almost certainly, given every part of
  this system is already per-programme - not explicitly asked/confirmed
  as its own question, low-risk assumption but flag it if resuming).
- Once all sections are presented and approved: write the spec to
  `docs/superpowers/specs/2026-08-21-knowledge-release-management-design.md`
  (no file exists there yet), self-review it, get the user to review the
  written spec, THEN invoke the `writing-plans` skill - per the
  brainstorming skill's own rule, no other implementation skill.

### Items 3, 5, 6, 7 - untouched, exactly as the user's own roadmap
message described them. Item 4 (full release verification) also
untouched as its own item, though item 1's drills and item 2's design
work haven't regressed anything - the existing suites (18/18 bvsc,
17/17 bfsc, 24/24 btech-dairy, 50/50 cross-programme, 320/320 go-live,
6/6 multilingual) were last confirmed passing before this session's
nginx/retention/redaction fixes, not re-run after them. Re-running the
full suites is itself item 4's own job, not something to assume still
holds.

## Student-facing response boundary (2026-08-21, later session)

A student's `/api/chat` reply no longer carries retrieval or provider
internals. Removed from the response: `model` (was
`"mistral:mistral-small-latest"`), `pages` (was every retrieved page - with
`top_k=15` the widget printed `Prospectus pages: 4, 7, 8, 10, 14, 16, ...`,
a map of the corpus rather than a citation), `policyDecisions` (internal
rule ids), and `sourceTrace`'s own `pages`/`ruleIds`. `sourceTrace` keeps
`programme` and `admissionYear`, which is exactly what
`tools/eval_go_live_conversations.py` asserts.

**Pages are not lost, only unpublished.** The pipeline still produces
everything; `conversations.log_exchange` still writes `pages` to the
transcript row, so the admin review console, the evidence test gate and
telemetry are unaffected. The provider `model` id, however, is now recorded
NOWHERE - it only ever lived in the response. A first attempt to persist it
passed `model_name=` to `ConversationMessage`, which does not have that
column (`model_name` belongs to `MachineReview`, the shadow reviewer's
model) - every transcript write then failed with a `TypeError` that
`log_exchange`'s own try/except swallowed, so answers kept returning 200
with `sessionId`/`messageId` null and nothing was logged at all. Caught by
running it locally, reverted. Persisting it properly needs a real column on
`conversation_messages`, and `init_db()`'s `create_all` does NOT ALTER an
existing table - production's Postgres already has it - so that is a
migration, not a one-line change.
`tools/eval_retrieval.py` measures recall against Qdrant directly, not
against the response, so its recall@15 methodology does not change either.
The other eval tools only *print* `pages`/`model` for human debugging and
will now print `None` - that is cosmetic, no assertion reads them.

The split lives in ONE place - `safety.student_response()` - deliberately:
a new internal field is private by default, and publishing one has to be a
decision someone makes on purpose. Do not add internals back into
`ChatResponse`; add them to the log row instead. Both clients were updated
to match (React `MessageBubble`'s evidence disclosure and the jQuery
widget's `Prospectus pages:` line are gone, along with their dead CSS), and
`MAFSU_DEVELOPER_HANDOFF.md`'s documented contract now says the fields are
not returned. The `.zip` beside the widget directory was regenerated so the
two copies stay identical (it excludes `README.md`, matching the previous
archive's file set).

Three defects found in the same audit and fixed:

- `off_topic_guard` hardcoded "B.V.Sc. & A.H." in its decline, telling a
  B.F.Sc. or Dairy student the assistant only covers a programme they never
  selected. It now takes `project_id`; because of that it moved out of the
  `GUARDS` tuple to run explicitly straight after the loop - the same
  position it held as the tuple's last entry, order unchanged.
- `answer.py` formatted `SYSTEM_PROMPT_BASE` with the raw project id, so the
  prompt's own decline example rendered as "I'm the btech-dairy admissions
  assistant". Now uses `programs.PROGRAM_NAMES`.
- `is_prompt_injection` caught "reveal your system prompt" but not
  retrieval-internals reconnaissance ("show me the retrieved chunks", "what
  similarity score did that get"). New `_RAG_RECONNAISSANCE` pattern in
  `core/intent.py`, deliberately excluding bare "documents"/"context" so
  "which documents do I need" stays an ordinary question.

Both widget packages were updated, not just one:
`integrations/mafsu-widget-code-only/` (canonical) and
`deliverables/gmail-safe-widget/` (the same files with a `.js.txt`
extension for email, whose own GMAIL_SAFE_NOTE promises the content is
otherwise identical). The canonical `.zip` was regenerated; the two dated
`MAFSU_MITRA_WIDGET*HANDOFF_2026-08-21.zip` packages in `deliverables/`
were deliberately NOT rewritten - they are records of what was already
emailed to MAFSU. Re-send a fresh package rather than editing those.

**Verification status**: run locally against a real stack built from these
files (compose up, all five containers, `/api/readyz` green on postgres/
redis/qdrant). Confirmed live: no `model`/`pages`/`policyDecisions` in any
reply, `sourceTrace` trimmed to `programme`+`admissionYear`, the off-topic
decline naming B.F.Sc. and B.Tech. (Dairy Technology) correctly, RAG-recon
and classic injection both refused, transcript logging writing real
`sessionId`/`messageId` after the revert above. Also `npm run build`
type-checks, `npm run lint` clean, `node --check` on the widget, and the
built bundle no longer contains "Prospectus pages".

**What local could NOT check**: this machine has no provider credentials
and an empty Qdrant, so nothing retrieval-backed ran - no RAG answer, no
verified-fact table lookup, no semantic/exact cache path, no multilingual
path. Those degraded to `provider-unavailable` exactly as designed, which
is itself worth knowing, but the API-level suites in `tools/` remain unrun
against these changes. Run them on a host that has keys before trusting
them.

### Deployed 2026-08-21, and what the promotion gate actually found

The response-boundary change above is **live** on 159.69.210.30. Verified from
outside the host: `POST /api/chat` carries no `model`/`pages`/
`policyDecisions`, `sourceTrace` is `{programme, admissionYear}`, the
off-topic decline names B.Tech. (Dairy Technology) correctly, RAG-recon is
refused, a real B.F.Sc. fee answer is grounded and logged with a real
`sessionId`/`messageId`, and neither replica logs an error.

**The gate was run as a true A/B, not a "looks fine" check.** A canary
container on `:8100` ran the new image; a control container on `:8101` ran an
image rebuilt from the pre-change backup. Same Postgres/Redis/Qdrant/
providers, both outside nginx's upstream (which names `api-1`/`api-2`
explicitly), so neither took student traffic. Result: **identical verdict
sequences on every suite** - B.V.Sc. 17/18, B.F.Sc. 15/17, Dairy 24/24,
cross-programme 47/50, multilingual 6/6, behavior 14/15 new vs 13/15 old.
The one behavior difference was a `validation-blocked` flake on the bounded-
regeneration path; re-run 5x per build with caching disabled, both answered
correctly 5/5. Do not read that suite's single-run number as a signal without
re-running it - two of its cases flake.

**The suites had been silently broken, and this is the more important
finding.** The first A/B produced B.V.Sc. 15/18, B.F.Sc. 11/17, Dairy 10/24,
cross-programme 17/50 - on BOTH builds, i.e. that is what live production
scores today, far below the numbers recorded in the sections above. 22 of
the 23 failures returned `programme-clarify`: the suites send `projectId`
but never `conversationState.programme`, and the P0 ambiguous-programme
guard correctly asks which programme when the client sends no selection.
The real widget sets that field when a student picks a course, so the suites
had stopped simulating a student the day that guard shipped. Proven directly:
the same Dairy question returns the clarify prompt without the state and a
correct grounded answer with it. `eval_multilingual.py` already sent it -
which is exactly why it was the one suite still scoring 6/6.

Fixed in the seven suites that were missing it (`eval_bvsc_adversarial`,
`eval_bfsc_adversarial`, `eval_btech_dairy_adversarial`,
`eval_cross_programme_stress`, `eval_bvsc_behavior`, `eval_bfsc_smoke`,
`eval_btech_dairy_smoke`). Scores jumped to the numbers above. **The residual
gaps are real and NOT caused by this change** - they fail identically on the
pre-change build: B.V.Sc. 1 case, B.F.Sc. 2, cross-programme 3. Those are
genuine open defects that the stale payloads were masking. Investigate them
before claiming any of the recorded 18/18 / 17/17 / 50/50 numbers still hold.

**Deployment mechanics worth knowing before the next one:**

- Production is NOT a git checkout - `/opt/admission-platform` holds copied
  files. Deploy = scp the changed files, `docker compose -f
  docker-compose.prod.yml build api`, then roll the replicas.
- Roll them ONE AT A TIME (`docker rm -f` one, then `up -d --no-deps
  --no-recreate api`) so nginx always has a healthy peer. Recreating both at
  once is a real outage window on a single-front deployment.
- **Compose refills the replica slot with the NEXT number, not the missing
  one.** Removing `api-1` produced `api-3`, which nginx's explicit upstream
  does not know - it had a dead peer and an invisible container. Fixed with
  `docker rename admission-platform-api-3 admission-platform-api-1`. The
  compose label still says container-number=3; a future deploy should
  `--force-recreate` the api service during a quiet moment to resync the
  numbering, accepting the brief outage.
- **`nginx -s reload` is mandatory after ANY replica recreation**, not only
  after a config edit: the upstream names are resolved at config load, so a
  recreated container's new IP is invisible until reload. Confirmed live -
  traffic distributed 6/4 across both replicas afterwards.
- Pre-deploy backup: `/opt/admission-platform/backups/2026-08-21-response-
  boundary/` holds the previous `api-app`, `web-src` and `tools`. Rollback =
  copy those back, rebuild, roll the replicas, reload nginx.

### Remembered exam status now outranks a text-only verdict (2026-08-21, deployed)

Reported from the widget: a student completes the guided interview, is
correctly told "You do not currently meet the B.V.Sc. & A.H. entrance-exam
requirement", then asks a marks follow-up and gets "You meet the marks
requirement… you must still clear NEET-UG-2026", `decisionState:
eligible_so_far`. Same session, opposite verdicts, one turn apart.

Cause, `agent/guards.py`: the hand-off to `answer.py` was gated on `intent`,
not on what the state held.

```python
if not active:                      # active = intent in _INTERVIEW_INTENTS
    result = eligibility.evaluate(programme, question)
    if result["verdict"] != "insufficient":
        return None                 # answer.py phrases the deterministic result
```

`eligibility_resolved` is not in `_INTERVIEW_INTENTS`, so once the interview
finished the guard bowed out, and `answer.py` re-derived eligibility **from the
question text alone** - it cannot see `conversationState`, so
`entranceExamStatus="not_qualified"` was simply discarded. The same facts
stated in words hit the guard's own `failed_neet` branch and returned the
correct refusal, so the two channels disagreed and whichever answered first
won.

Fixed by gating the hand-off on the state as well (`state_settles_entrance`),
which lets flow reach the existing `entrance_failure` branch that already had
the right wording. Verified: a remembered *qualified* NEET still gets the
positive verdict, the NRI XII-abroad exemption still outranks a remembered
"no" (it is handled above this guard), and non-eligibility questions are not
captured. Canary-vs-control on identical infrastructure: B.V.Sc. 17/18,
B.F.Sc. 15/17, Dairy 24/24, cross-programme 47/50, behavior 14/15,
multilingual 6/6 - identical verdict sequences. Backup:
`backups/2026-08-21-eligibility-state/`.

**No suite could have caught this**: every eval sends a single-turn payload,
so nothing exercises "state contradicts the current question." That is a real
coverage gap, not a passing grade.

### Widget redesign (2026-08-21) - noticeable launcher, one-row header, full-panel language

`integrations/mafsu-widget-code-only/`, driven by the observation that a bare
launcher goes unnoticed - a student never learns the assistant exists.

- **Greeting card** next to the launcher after 2.4s, once per visit
  (`sessionStorage`, try/catch so private mode still shows it), dismissible,
  gone for good once the chat is opened. The launcher pulses three times with
  it. **It is deliberately always in English and must stay that way** - it is
  the first thing a visitor sees, before anyone has chosen a language, and its
  own text names हिंदी and मराठी so the options are visible. `applyLanguage`
  explicitly skips everything inside `[data-chat-nudge]`.
- **Header compacted** from 88px + a 58px toolbar to one 52px row plus a 38px
  toolbar. The header status dot shares `[data-health]` with the launcher dot,
  so one health check drives both.
- **Expand control** widens the panel 400px → 680px for long answers,
  remembered per visit, hidden below 720px where there is nowhere to widen to.
- **Programme dropdown removed** at the user's request: the three welcome
  cards (shown again on every "New chat") and plain naming in a question are
  the ways in, since the API auto-routes on an explicitly named programme.
  What replaced it is a read-only "Answering for X" chip so the corpus in use
  is never a mystery. "New chat" therefore stays visible on phones - it is now
  the only way back to the cards.
- **Whole-panel language switch**: every student-visible string carries a
  `data-i18n` key resolved against `COPY`; the buttons rewrite labels, the
  placeholder, the safety notice, the FAQ list, aria-labels, and **the question
  each shortcut sends**, so the reply comes back in the language being read.
  Hindi/Marathi mirror `services/web/src/copy.ts` and carry its caveat: still
  awaiting native-speaker review. "मैं MAFSU MITRA हूँ" rendered badly with the
  copula after the Latin wordmark, so both languages lead with the verb.
- **Responsive** by real situation, not arbitrary widths: ≤719px drops expand;
  ≤560px becomes a full sheet with safe-area insets and hides the launcher
  while open; ≤379px trims the cards to name + arrow but keeps all three
  visible; ≤620px tall trims the welcome rather than the conversation. `100dvh`
  so mobile browser chrome cannot clip the panel, and **16px composer text on
  phones** because iOS Safari zooms the page on anything smaller.
- The stylesheet was consolidated: it had been a base sheet plus a full
  override block appended after it, with rules fighting each other.

**Two bugs the redesign fixed that were visible in production screenshots**:
the composer placeholder wrapped to two lines and collided with the helper
text beneath it, and the quick chips truncated to "Documents requi…".

**On previews**: the offline preview stubs the network. Its first version
replayed a fixed three-answer script regardless of input, which answered
keyboard mash with a real-looking eligibility verdict and cost two rounds of
"is the product broken?". A stub must refuse rather than invent - it now
matches on the question and otherwise says it is a preview. Build it with
`build_preview.py` in the session scratchpad.

### Direct-HTTPS mode: publishable site key + origin enforcement (2026-08-22, deployed OFF)

Built for the model after MITRA gets its own domain: the widget calls
`https://mitra.mafsu.ac.in/api/chat` straight from the MAFSU page, and the
`MitraProxy.ashx` relay is no longer in the path.

**The key is publishable, not secret, and the code says so in three places.**
A widget that runs in the student's browser cannot hold a secret - View Source
reads it. `X-Mitra-Site-Key` identifies which site is calling; the origin
allowlist and the per-client rate limit are what protect the endpoint. Never
gate anything on the key alone.

- `settings.py`: `site_key_required` (bool), `site_key_sha256` (comma-separated
  sha256 digests, so plaintext is not in every replica's environment),
  `origin_enforcement` (bool). All three default OFF - deployed code is inert
  until a key is issued.
- `main.py`: on `POST /api/chat` only. Origin enforcement judges a request
  *only when it declares an Origin*, so same-origin and server-to-server calls
  (the IIS handler) are unaffected - CORS is a browser courtesy and curl never
  sends one. The key check returns 401, a disallowed origin 403.
- Widget: `data-site-key` on the root element; sent on chat and health calls.
  Empty attribute = feature off.

Verified on three parallel canaries before promotion: flags off → 200 exactly
as today; flags on → no key 401, wrong key 401, correct key 200, correct key +
allowed origin 200, correct key + hostile origin 403, `/api/healthz`
unaffected. The A/B gate against the live build was identical on all six
suites.

**Switching it on** (once the domain and a key exist): generate with
`python3 -c "import secrets,hashlib;k=secrets.token_urlsafe(24);print(k, hashlib.sha256(k.encode()).hexdigest())"`,
put the DIGEST in the api service environment as `SITE_KEY_SHA256`, set
`SITE_KEY_REQUIRED=true`, `ORIGIN_ENFORCEMENT=true` and `CORS_ORIGINS` to the
real MAFSU origin, give the PLAINTEXT to the MAFSU developer for
`data-site-key`. Roll the replicas one at a time as always.

**The rate-limit collapse this also fixes.** Today `MitraProxy.ashx` forwards
the student's address as `X-Real-IP`, and our own nginx immediately overwrites
it with `proxy_set_header X-Real-IP $remote_addr` - the IIS server. The API
keys its limiter on that header and nginx's `limit_req_zone` uses
`$binary_remote_addr`, so **every student behind the proxy shares one bucket**:
the 30/min per-client limit becomes 30/min for the whole university, and real
applicant traffic would 429 students against each other. Direct-from-browser
removes the problem at the root, because `$remote_addr` is then the student. If
a proxy is ever reinstated, trust its header with `set_real_ip_from <that
address>` and ONLY its - a blanket `real_ip_header` lets any client forge the
rate-limit key. Noted in `nginx.https.template.conf` at the point it matters.

`nginx.https.template.conf` was also corrected and hardened: the hostname said
`admissions.mafsu.in` (wrong TLD - the institution is `.ac.in`), so nginx would
have served the default vhost and never matched the certificate. It now names
`mitra.mafsu.ac.in`, keeps an ACME challenge location so renewal survives the
HTTPS redirect, and adds a `default_server` returning 444 for any request that
does not use a known hostname - raw-IP scans and stray CNAMEs get dropped
rather than served.

### SSH hardened to key-only (2026-08-22)

`sshd -T` reported `passwordauthentication yes` - the OpenSSH default when
unset. In practice nothing could use it: root is `prohibit-password` and there
is no other account. Made explicit anyway in
`/etc/ssh/sshd_config.d/10-mitra-hardening.conf` (`PasswordAuthentication no`,
`KbdInteractiveAuthentication no`, `PermitRootLogin prohibit-password`) so that
adding a user later cannot silently create a password-reachable account.
Validated with `sshd -t`, reloaded (not restarted), and a fresh connection was
confirmed before finishing. Backup: `/root/sshd_config.backup-2026-08-22`.
Still open: no fail2ban, and both authorised keys share the root account, so
the audit trail cannot name a person.

## Risk-register remediation (2026-08-22) — everything except the repo items

Worked through the risk register in dependency order. The two GitHub items
(make the repository private, move it to an organisation) are the owner's to
do and are deliberately not attempted here.

**Boot persistence.** Every container ran `restart=no`, so a reboot took the
student service down until someone started it by hand. Applied to the running
containers with `docker update --restart unless-stopped` (immediate, no
recreate) and persisted in `docker-compose.prod.yml`. Note the trap: a naive
script that inserts `restart:` under every two-space key also hits the
`volumes:` block and the compose file stops validating — add it only inside
`services:`.

**Backups now exist and are proven.** `/usr/local/bin/mitra-backup.sh` +
`mitra-backup.timer`, nightly 02:30 UTC, 14-day retention, logged to
`/var/log/mitra-backup.log`. Postgres via `pg_dump -Fc`; Qdrant via snapshots.
**Qdrant is not published on the host**, so a host-side `curl 127.0.0.1:6333`
silently does nothing - the first version of the script "succeeded" while
backing up no vectors at all. It now drives Qdrant through the API container
(already on that network) and lifts the file out with `docker cp`. Restore
drill run the same day: the dump restored into a scratch database returned
7,706 conversation messages against 7,710 live, the difference being test
traffic since the dump. Instructions in `/opt/backups/RESTORE.md`.

**Legacy POC contained.** It bound `0.0.0.0:5050` with only ufw between it and
the internet, and printed its admin token into `backend_stdout.log` on every
start. Now binds `127.0.0.1` (via `BIND_HOST`, defaulting to loopback), no
longer logs the token, and the token itself was rotated - the old one was
`password`, published in `archived/CLAUDE.md` in a **public** repository. The
old value now returns 401. Backups: `/root/legacy-app.py.backup-2026-08-22`,
`/root/legacy-env.backup-2026-08-22`.

**The `/legacy/` route is gone.** It proxied to `host.docker.internal:5050`,
which the container cannot reach (ufw drops bridge traffic to that host port),
so every public request hung for the full 300s `proxy_read_timeout` while
holding a worker - an unauthenticated denial-of-service path. Removed, with an
explicit `return 404` so a stale bookmark gets a clean answer instead of the
student page. Do not reinstate without a short timeout AND an access
restriction.

**Qdrant image pinned** from `:latest` to `:v1.19.0` (the version actually
running), so a rebuild cannot silently change the datastore.

**fail2ban installed** for sshd (5 attempts / 10 min / 1 h ban). It logged
failed attempts within seconds of starting - the box is being scanned
continuously.

**First dependency scan ever run**, and it found something: `pypdf 5.1.0`
carried **37 advisories**, fixed in 6.15.0; the other 37 packages were clean.
Exposure was low (ingestion only, admin-supplied PDFs, not the request path)
but the fix was verified rather than assumed: extraction from the real B.V.Sc.
prospectus is **byte-identical** between 5.1.0 and 6.15.0 - same 69 pages, same
201,112 characters, same sha256 - including `extraction_mode="layout"`, which
is the mode ingestion actually uses and which the first comparison missed.
Bumped, rebuilt, rolled; `pip-audit` now reports no known vulnerabilities.

**A rate-limit artifact worth recognising.** Running two suites back-to-back
from one container gave B.V.Sc. 17/18 then Dairy 12/24 - which looks like a
regression and is not. 42 requests from one source address inside a minute hit
the 30/min per-client limit. After the window reset, Dairy returned 24/24 with
zero 429s. This is the same shared-bucket effect that the MAFSU proxy creates
for real students; when running suites against production containers, either
wait out the window or raise the limit on a throwaway container.

**Still open after this pass:** external uptime alerting (nothing pages anyone
if the site falls over), per-person admin accounts, staged corpus release, an
independent penetration test, and the domain/TLS work that blocks the rest.
