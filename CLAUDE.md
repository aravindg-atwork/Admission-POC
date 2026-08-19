# Working notes for Claude

Operational context for this repo. Read before changing anything in `backend/`.
Companion file: `HANDOFF.md` (machine-migration setup, gitignored data transfer).
This file is the one kept current session-to-session — if the two disagree,
trust this one and fix HANDOFF.md's claim, not the other way round.

## Running it

Windows box. No native/compiled dependencies (see HANDOFF.md §2 for why).

```bat
.venv-backend\Scripts\python.exe run_backend.py
```

Serves on `:5050` locally — student widget at `/`, operator console at `/admin`.
Admin token is `ADMIN_TOKEN` in `.env` (`password` — **settled, do not re-flag
or suggest changing it**, that decision has been made explicitly more than
once).

Always use `.venv-backend\Scripts\python.exe`, never bare `python`/`python3` —
the system interpreter has none of the dependencies.

After changing a prompt OR any guard/eligibility logic, **clear the FAQ cache
on every project, not just `default`** — a question asked on the general
widget is answered by whichever programme it routes to and cached *there*.
Clearing `default` alone leaves the real answer cached and you end up testing
the cache, not the fix:

```bash
for p in default bvsc bfsc btech-dairy; do
  curl -X POST "localhost:5050/admin/projects/$p/cache/clear" -H "X-Admin-Token: password"
done
```

**Use `127.0.0.1`, never `localhost`, in any script that calls the backend
with `urllib`.** Unlike curl/browsers, `urllib` doesn't race IPv4/IPv6 —
`localhost` resolves to `::1` first and eats ~2s per request before falling
back. Every script under `tools/` was fixed to `127.0.0.1` 2026-08-18; keep
new ones consistent.

**Windows console is cp1252 and cannot print Devanagari or some Unicode
(e.g. ZWJ `‍`).** A naive `print()` on Hindi/Marathi output throws
`UnicodeEncodeError` and looks like a crash, or gets misread as "garbled
answer" if you catch the exception. Either `sys.stdout.reconfigure(encoding="utf-8")`
at the top of the script, or write output to a file with `encoding="utf-8"`
and read it back.

## Production deployment

Live at **159.69.210.30** (Hetzner, `ai-hub-nbg1-01`), port 80, no domain.
Co-located on a box that already ran an `ai-platform` Docker stack serving
`qwen2.5-3b-instruct` chat + `bge-m3` embeddings via `api+postgres+redis`
(kept running — other things depend on them); the stack's own **nginx was
removed** to free port 80 for this project. This admission backend runs as a
plain `python3` process on the host, not in Docker.

- Service: `systemctl {status,restart} admission-poc` — `Restart=on-failure`,
  logs to `backend_stdout.log`/`backend_stderr.log` under `/opt/admission-poc`.
- Deploy pipeline (no CI, all manual): edit locally → compile-check
  (`python -m py_compile <file>`) → restart local backend → verify locally →
  commit + push to `production-hardening` → `scp` each changed file
  **individually to its correct path** (a flat multi-file `scp ... dest-dir/`
  silently drops subdirectory structure — every file lands directly in
  `backend/`) → delete `__pycache__` on the server → `systemctl restart
  admission-poc` → `curl /healthz` → **MD5 checksum parity check** (`certutil
  -hashfile <file> MD5` locally, `md5sum <file>` on the server — must match) →
  live smoke-test the specific fix → clear FAQ cache on all four projects.
- SSH key: not committed (obviously). Ask the user if it isn't already in
  `~/.ssh/` or the session scratchpad.
- **Local testing needs an SSH tunnel to reach the shared qwen/bge-m3
  service.** `.env`'s `SELFHOSTED_URL=http://127.0.0.1:8000` is a LOCAL
  port — on the Windows dev box this only resolves if something is
  forwarding it to the production box's `docker-proxy` (also on
  `127.0.0.1:8000`, production-side). If it drops (observed mid-session:
  `netstat` showed nothing on local `:8000`, retrieval-backed chat requests
  50x'd with `WinError 10061 ... actively refused`, while greeting/routing
  requests — which don't need embeddings — kept working fine, which is the
  tell), re-open it: `ssh -N -L 8000:127.0.0.1:8000 root@159.69.210.30`.
  Opening a **backgrounded, persistent** tunnel may be blocked by the
  permission classifier in auto mode — if so, don't fight it: fall back to
  testing directly against production (`http://159.69.210.30`) instead,
  which needs no tunnel and is where the fix has to work anyway.
- **Debugging a single guard's logic doesn't need the tunnel (or even a
  running server) at all.** `rag.answer` is shadowed by `rag/__init__.py`'s
  `from .answer import answer` re-export, so `from backend.rag import
  answer` binds the FUNCTION, not the module — import the submodule
  directly instead: `from backend.rag.answer import _build_context`. Build
  a real `ctx` with `_build_context(project_id, question, "auto", "en")`
  (pure language-detection/hint-building, no network call) and call any
  guard directly, e.g. `guards._eligibility_guard(ctx)` — this only hits
  the network for an actual LLM call (Mistral/NVIDIA, unaffected by the
  local tunnel being down), never embeddings/retrieval. Far faster than a
  full HTTP round-trip for isolating exactly which check inside a guard is
  firing or bailing — this is how the "which programmes" branch-order bug
  below was actually found.

## Scope

Three undergraduate programmes, 2026-27 prospectuses. Postgraduate
programmes (M.V.Sc., Ph.D., M.Tech.) were retired 2026-08-14 — projects
deleted and aliases removed from `core/programs.py`.

| project id | programme | has its own corpus? |
|---|---|---|
| `default` | — (general entry point) | **no** — routes/clarifies only |
| `bvsc` | B.V.Sc. & A.H. | yes |
| `bfsc` | B.F.Sc. | yes |
| `btech-dairy` | B.Tech. (Dairy Technology) | yes |

**`default` does NOT hold a corpus.** It used to (through 2026-08-16), and
that double duty caused 7/80 eval failures — any question naming no programme
answered confidently from B.V.Sc. data. Split into its own `bvsc` project;
`programs.PROGRAM_NAMES` is `{"bvsc", "bfsc", "btech-dairy"}` — `"default"` is
never a key in it. **Do not put a corpus back on `default`, and do not assume
`default` and `bvsc` are the same project** — they are not, `config.
DEFAULT_PROJECT_ID == "default"` is a distinct id from `"bvsc"`, and code that
conflates them (or old docs that say "`default` doubles as the B.V.Sc.
corpus") is describing the pre-split state. `helpers._assistant_scope` is what
makes `default`'s self-description name all three programmes while it holds
none of them itself.

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

**Mistral has a real rate limit, and heavy same-session testing hits it.**
Observed live 2026-08-19: a session that ran three full 80-question P95
measurements plus dozens of other test scripts back-to-back started
getting `HTTPError 429: Too Many Requests` on every `mistral` call, which
cascaded — every request fell back to `nvidia` (20-130s), and
`nvidia-fast` (the ROUTER's own provider) independently started timing
out too, triggering `[router] all providers failing - pausing
classification for 120s, using keyword routing`. The THIRD P95 re-run
that session stalled for 20+ minutes on a single question because of
this, not because of an application bug — checked via `journalctl`/the
stdout log on the server, not guessed. **If a live measurement run looks
anomalously slow partway through, check `backend_stdout.log` for `429`/
`TimeoutError` lines before concluding the code regressed** — a normal,
lightweight single request (`curl`/one Python script) succeeding quickly
right after is the tell that it's rate-limit pressure from your OWN
recent test volume, not a real slowdown. Space out heavy test batches
rather than firing them back-to-back; there is no code fix for this, it
is a quota ceiling.

Dead or exhausted, do not rely on:
- **Sarvam** — HTTP 402, no credits. Was `CHAT_PRIMARY` for most of this project's life.
- **Groq** — 100k tokens/**day** free ceiling, reached inside one test run.
- **Hetzner** — alive but 52-77s for a trivial prompt.
- **TTS** (`TTS_URL`, local Docker on :8001) — connection refused. Indic voice
  is therefore broken. Mistral TTS does NOT fix it: ten voices, all
  `en_us`/`en_gb`, zero Indic, and English already has a browser voice.
  `gpt-4o-mini-tts` is the promising candidate; an OpenAI key was supplied
  2026-08-14 but had **zero credits**, so nothing is wired up.

## Architecture

`backend/` is layered; nothing imports upward.

```
core/        pure logic (lang, programs, intent, eligibility, tablelookup)
storage/     projects, apikeys, faq, vectorstore, stats
generation/  providers, llm, embeddings, speech
prompts/     system.py (LLM prompts), canned.py (fixed replies), registry.py
rag/         router → guards → answer/comparison/orchestrator → validate/provenance
http/        app.py dispatch + admin/chat/trace routes
trace/       live SSE observability
```

**Guard order matters** (`rag/guards.py`, `GUARDS` list). Runs before the FAQ
cache is reachable, which is deliberate: clarification can never be skipped
by a cache hit. Current order (verify against the file — this list has grown
twice this project already and will again):

```
injection → topic_menu → greeting → dispute → meta_correction → off_topic →
program_list → eligibility → percentage_clarify → comparison →
program_redirect → unknown_programme → program_clarify → general_fanout →
low_confidence_clarify
```

`rag/router.py` classifies intent in one call. It returns `None` on **any**
failure and every guard falls back to deterministic keyword logic — the
router is an upgrade, never a dependency. `ROUTER_ENABLED=false` reverts
everything. The router is also **non-deterministic across calls on the same
ambiguous input** — it has been observed assigning two different intent
labels to the identical question on different runs. Never trust it alone for
anything a guard treats as a veto; always corroborate with a deterministic
check (`detect_program`, `is_shared_topic`, etc).

**`programs.is_shared_topic(text)`** — a portal-mechanics vocabulary check
(register/login/upload/resubmit/pay/guarantee/...). Originally built for one
guard, now reused as a deterministic veto in three places
(`_program_clarify_guard`, `_injection_guard`, `_off_topic_guard`) to close
gaps where the router mis-classifies ordinary portal questions. Reach for
this pattern again before inventing a new one-off fix for the same shape of
router false-positive.

**Guided eligibility interview** (`_eligibility_guard` +
`_eligibility_interview_ask`/`_eligibility_percent_ask` in `guards.py`,
`core/eligibility.py`). When a bare "am I eligible?" is missing entrance-exam
status, category, or the right percentage, the guard now asks one question at
a time (entrance → category → subject-percentage) instead of a single blunt
"please clarify" — driven by `interviewOptions`/`interviewField`/`slotUpdate`
in the response, echoed back by the client as `conversationState`
(`{programme, intent, category, subjectPercent, overallPercent,
entranceExamStatus}`) on the next request. **The current message's own words
always win over anything carried in `conversationState`** —
`resolve_conversation_slot()` enforces this; never trust the carried state
over what the student just typed.

**Eligibility verdicts intentionally say "meets the marks requirement", not
"is eligible".** Changed 2026-08-1x after review: a flat "you are eligible"
overclaimed certainty while entrance-exam clearance, age (17 by 31 Dec 2026 —
verified for all three programmes, each on its own prospectus's general
eligibility section), and category-certificate requirements were still
outstanding. `_eligibility_facts()`/`_eligibility_fallback_sentence()`
give those conditions equal weight to the verdict, not a footnote.

**`detect_program(text)` returns only the FIRST-named programme** when a
question names several (`detect_programs_multi()[0]`) — by design, for the
single-programme redirect/lookup callers it was built for. Any NEW call site
that might see multiple programmes in one question (comparison, eligibility
verdicts, threshold lookups) must check `detect_programs_multi()` itself and
decline (fall through) when it returns more than one, rather than silently
picking the first. `_eligibility_guard` had exactly this bug through
2026-08-18: a three-programme eligibility question silently computed a
verdict against only the first-named programme's thresholds. Fixed; watch
for the same shape elsewhere before adding a new `detect_program()` call.

**Fixing the deterministic multi-programme check does NOT automatically
protect the router-fallback path — they are two separate guesses that
both need the same guard.** `_eligibility_guard`'s candidate resolution is
`named or (routed[0] if len(routed) == 1 else None)`: the 2026-08-18 fix
above corrected `named`'s multi-programme handling, but left the `routed`
fallback trusting the router's single-target classification unconditionally
— found live 2026-08-19, a compound question naming both `bvsc` and `bfsc`
still got a confident single-programme `bvsc` verdict because the router
(independently, wrongly) classified `target_programs` as `['bvsc']`. Fixed
by gating the router fallback on `not multi_named` too, not just on
`named is None`. When two signals feed the same decision (a deterministic
check and a router opinion), a fix to one is not a fix to the combination
— test the combined behaviour, not each input in isolation.

**`detect_programs_multi()`/`detect_program()` also tolerate a single-edit
typo** in the three core abbreviations only (`bvsc`/`bfsc`/`btech`, via
`programs._typo_matched_projects` — see its docstring). The longer
descriptive aliases (`vet`, `dairy`, `fishery`...) deliberately do NOT get
this: they're real, common enough words that fuzzing them misfires
(`"dairy"` is edit-distance-1 from `"daily"`). Extend
`_TYPO_EXCLUDED_WORDS` if a new common-word collision turns up — do not
widen the abbreviation set or loosen the uniqueness rule to fix one.

**`_program_redirect_guard` fires on ANY project, not just `default`** —
a scoped widget's own API key doesn't protect it from being silently
redirected elsewhere if `detect_program()` finds a different programme's
alias in the text. This is what turned "dairy" being a bare `btech-dairy`
alias into a real bug: "Is an Indian Dairy Diploma equivalent to 12th
standard?", asked on the `bvsc`-scoped widget about a real prior
qualification named in `bvsc`'s own prospectus, got silently redirected to
`btech-dairy`'s admission requirements instead of answering from `bvsc`'s
own content. Fixed with `programs._NON_PROGRAMME_PHRASES`/
`_strip_non_programme_phrases` — known collision phrases are stripped from
the normalized text before alias matching runs. Same lesson as the
`detect_program()`-returns-only-first-match note above: a bare, short
alias is powerful and cheap, but every new one is a new false-positive
surface against ordinary English — sweep for collisions before trusting
one, the way `_TYPO_EXCLUDED_WORDS` and this were both found.

**`_SELF_CREDENTIAL_RE` (self-completed-degree exclusion) didn't
distinguish a past claim from a future/hypothetical one.** "What all exam
**should** i have passed for bfsc eligibility?" — naming `bfsc` explicitly
— matched on "i have passed" and treated `bfsc` (named right after) as the
student's OWN already-completed degree to exclude from routing, so the
question lost its programme and fell through to `clarify-program` asking
which one. "should i have passed" asks about a FUTURE requirement, not a
claim of already holding a credential; "I completed my B.V.Sc." is the
opposite. Fixed with `_HYPOTHETICAL_MODAL_RE` — a modal word (should/
would/could/must/need to) immediately before the match means it isn't a
genuine self-credential claim. Same lesson again: a regex built for one
real case, tested only against that case, will eventually meet a second
one it wasn't checked against.

**Exam-based "which programme am I eligible for" matching**
(`eligibility.is_which_programmes_by_exam_question`/`eligible_programmes_
by_exam`, wired into `_eligibility_guard`) mirrors the existing
subjects-based version on a different axis — NEET admits to `bvsc` only,
CET/MHT-CET admits to `bfsc`+`btech-dairy`. **Checked BEFORE the subjects
branch, not after** — found live: the subjects branch's own
`describes_own_subjects` matches bare "I have" ("I have cleared MHT-CET"),
so with subjects-first ordering it claimed the question, found zero
subject matches (there are none), and hard-returned `None`, dead-ending
the guard before the exam branch ever got a turn. Checking the exam
branch first works because it requires one of ITS OWN specific verbs
(passed/cleared/qualified/appeared/gave/took/sat/wrote) next to a
recognised exam name — a genuine subjects-only question never matches
that, so still falls through correctly. **The general lesson, not just
this one bug**: when two independent "does this question belong to me"
checks can both fire on the same text, whichever runs first and
hard-returns `None` silently kills the other — always check by testing
the ACTUAL guard/branch order with a real question, not just each
detector function in isolation returning the right boolean.
`is_which_programmes_by_exam_question` deliberately does NOT require the
subjects branch's `_APPLY_RE` too — the literal reported phrasing typo'd
"eligible" as "eligiblie", which `_APPLY_RE`'s exact match doesn't catch,
and `_WHICH_PROGRAMMES_RE` combined with a clear first-person exam claim
is unambiguous enough alone.

**No typo tolerance on entrance-exam names** (`neet`/`cet`) — deliberately
never added, unlike the programme abbreviations. Both are short enough
that their edit-distance-1 neighbours are common real words ("meet",
"feet", "neat" for neet; "get", "set", "yet", "vet" for cet), so fuzzing
either would misfire constantly. A genuinely garbled name (reported live:
"quet") stays unrecognised on purpose.

**Thumbs up/down feedback only ever worked for `faqId`-backed answers**
(plain RAG/FAQ-cache hits) — every guard-served answer (eligibility
verdicts, the guided interview, comparisons, clarify-percentage/
program...) never gets a `faqId` by design (guards run before the FAQ
cache and are never cached themselves — see the guided-interview note
above), so the feedback buttons silently never appeared for a large and
growing share of real conversations. `/api/feedback` (`chat_routes.
handle_feedback`) now accepts `traceId`+`source` as a fallback target for
these, recorded via `reviewlog.append` (no cache entry exists to update,
just an event — same shape/discipline the system's own self-detected
near-misses already use). `app.js` stores `traceId` per message and shows
feedback whenever either `faqId` or `traceId` is present AND the bot is
actually answering rather than asking a clarifying question
(`interviewOptions`/`clarifyOptions`/`scopeOptions`/`topicOptions` all
absent). Scoped to the student widget only — the admin console's
Playground already has full trace inspection, a richer diagnostic tool
than a dislike button.

**Client-side (`static/app.js`/`admin-app.js`) React stale-closure
gotcha**: `setState()` followed by an immediate function call in the *same*
synchronous handler reads the PRE-update state, because the closure that
call runs in was created at the last render, before the update lands. Fixed
throughout by computing the next value explicitly
(`const next = {...conversationState, [field]: value}`) and passing it as an
override parameter to `send()`, never by calling `send()` right after
`setState()` and hoping it sees the new value.

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

**`storage/faq.py:_lock` must stay an `RLock`.** Every writer holds it across
a read-modify-write and reads via `_load()`, which takes the same lock on its
id-backfill path. As a plain `Lock` that is a self-deadlock that never
releases, and since the lock is module-global it wedges FAQ writes for every
project at once - including `add()` on ordinary chat traffic. It hides well:
a warm, fully-backfilled file never triggers the backfill.

**Redirect stdout with `python -u` when benchmarking.** Python block-buffers
stdout to a file, so a long run shows an empty output file the whole time and
looks hung when it is fine.

**"management quota"/"management seat" and similar bare-word collisions.**
`_FOREIGN_COURSE_WORDS` matches short bare words like "management" that also
appear in completely ordinary MAFSU-scoped phrases. Fixed narrowly with a
disambiguator-word gate (only exclude "management" from that set when
"quota"/"seat"/"seats" is also present) rather than removing the word
outright — removing it would reopen the original false-negative it exists
to catch. If a new collision word turns up, extend the gate, don't redesign it.

**Reproduce before you fix.** LLM-path answers have real run-to-run
variance; several apparent regressions this project turned out to be
generation-variance noise, not a code change. Re-run the exact same failing
question 1-3 times before concluding anything broke.

## Testing

```bash
ADMIN_TOKEN=password .venv-backend/Scripts/python.exe tools/bench_answer_quality.py
```

The one suite that checks **figures**, not just which path answered. Ground
truth read from the PDFs. Each case has a `forbid` list holding another
programme's figure — that is what contamination looks like.

Other scripts (`test_matrix`, `test_clarification`, `test_projects`,
`test_hinglish`, `test_retrieval_hi_mr`) assert on `source` and language, not
correctness of figures. All fixed to use `127.0.0.1` 2026-08-18;
`test_clarification.py` also had its project id fixed (`mvsc` → `bvsc` — the
old one was deleted in the 2026-08-14 retirement and the whole suite 404'd
before it could check anything). `test_retrieval_hi_mr` is quota-free.
`test_programme_typo_tolerance.py`, `test_program_alias_false_positives.py`,
`test_comparison_retry.py`, `test_exam_based_matching.py`, `test_double_
negation.py`, `test_raw_marks_conversion.py`, and `test_compound_query_
split.py` (added 2026-08-18/19) are pure logic against `core/programs.py`/
`rag/comparison.py`/`core/eligibility.py` directly, no backend needed —
the odd ones out among these, everything else here hits the live HTTP
API. `test_eligibility_candidate_resolution.py` is the one exception that
needs a constructed `ctx` (via `rag.answer._build_context`) with a
simulated `ctx.route` rather than either extreme — the bug it covers is in
how a guard COMBINES a deterministic check with the router's opinion, not
in either one alone. `test_validation_skip_budget.py`, `test_program_
list_original_question.py`, `test_horizontal_quota_note.py`, and
`test_subjective_comparison_guard.py` (added 2026-08-19) are the same
constructed-`ctx` style. `test_presentation_quality.py` hits the live
HTTP API like most of this list, covering Marathi script-consistency,
tone robustness, and markdown-leak checks — not yet run against
production, see the rate-limit note under "Providers".

`tools/measure_latency_p95.py` (added 2026-08-18): reuses
`eval_admissions.CASES`, records every response time, reports
p50/p90/p95/p99 via linear interpolation — answers HANDOFF.md's open "p95
unmeasured" item instead of eyeballing a few slow-looking cases.

`tools/test_conversation_flows.py` (added 2026-08-18) exercises the guided
eligibility interview and topic-menu chips as multi-turn conversations —
`eval_admissions.py`'s `C()` framework is single-turn only and can't. Drives
the same mechanism `static/app.js`'s `pickInterview`/`pickTopic` use: resend
the server's `carryQuestion`, with `conversationState` built by setting
exactly the field a chip click would set.

Long runs: write output to the session scratchpad, not `/tmp` (it does not
persist on this Windows box). Never `pkill -f` a pattern matching your own
command — it kills the wrapper shell before the work starts.

## Benchmark, 2026-08-14 (post-OCR, pre-eligibility-interview)

`14/14 correct, avg 9.0s`. Read the distribution, not the average:

| | |
|---|---|
| 12 of 14 cases | 1.3-5.1s |
| median | ~2.6s, inside the 1-3s target |
| one outlier | 87.4s (btech-dairy admission fee) |
| avg excluding it | 3.0s |

The outlier did **not** reproduce - the same question on a cold cache ran
1.55s and 2.12s immediately after. Treat it as provider tail latency, not a
slow path to go optimise.

This benchmark predates the guided-interview/topic-menu/conversationState
work and the "meets the marks requirement" phrasing change — re-run before
trusting it as a description of current answer quality, not just latency.

## Open

- **P95 latency — measured, partially fixed, still open.** First run
  2026-08-18 (production, cold cache, all 80 `eval_admissions.CASES`):
  p50 3.0s, p90 56.0s, **p95 80.5s, p99 240.1s**, max 240.2s, 3/80 errors,
  15/80 (18.8%) over 15s. Root cause traced to `llm.generate()`'s
  primary-provider retry: a genuine TIMEOUT already consumed its full
  `call_timeout` budget, and retrying identically paid that same budget
  again before the fallback even got a turn — up to 2×`CLOUD_ATTEMPT_TIMEOUT`
  wasted on the worst-case shape. Fixed (`_is_timeout`, only skips the
  retry on a genuine timeout, not on a fast HTTP/connection error, which
  still gets the original retry-then-fallback behaviour). Re-measured
  2026-08-19, same 80 questions, cold cache:

  | | before | after |
  |---|---|---|
  | errors | 3/80 | **0/80** |
  | max | 240.2s | **180.9s** (−25%) |
  | p99 | 240.1s | **165.0s** (−31%) |
  | mean | 18.7s | 16.1s |
  | >15s | 18.8% | 13.8% |
  | p50 / p90 / p95 | 3.0s / 56.0s / 80.5s | 4.4s / 62.4s / 89.4s |

  Honest read: the fix eliminated the catastrophic worst case (every
  outright failure gone, max/p99 both cut by a quarter to a third) — that
  part is real and verified. p50/p90/p95 ticked up slightly, most likely
  ordinary run-to-run provider variance (a live cloud call, not a
  controlled benchmark) rather than a regression — the change structurally
  can only *reduce* time on the retry-then-fallback path, never add to the
  fast path.

  **Second fix, same day**: `config.ORCHESTRATOR_PROVIDER` (`hetzner` by
  default, documented at 52-77s for a TRIVIAL prompt) is the LLM-check/
  regeneration escalation a flagged answer triggers
  (`VALIDATION_LLM_CHECK_ENABLED=true` on production) — running that
  AFTER an already-slow main generation call is exactly the same
  sequential-compounding shape, just a second instance of it. `ctx.
  started_at` (`rag/answer.py`) plus `config.VALIDATION_LLM_CHECK_BUDGET_
  SECONDS` (default 20s) now skip that escalation once a request has
  already run long — deterministic checks still run either way, only the
  expensive LLM step is skipped, degrading to the same already-proven-
  safe path Hetzner's own failures already take. `tools/test_validation_
  skip_budget.py`. Verified live: happy path unaffected (2.4s).

  **A third re-measurement attempt the same day was inconclusive** —
  stalled 20+ minutes on one question, traced to `mistral` (the primary)
  hitting its own rate limit (`HTTPError 429`) from this session's own
  test volume (three 80-question P95 runs plus dozens of other scripts
  back to back), cascading into `nvidia` fallback + the router's own
  `nvidia-fast` timing out too. Killed, not trusted as data — see the
  new rate-limit note under "Providers" above. **A clean re-run is still
  needed** to know whether the second fix moved the needle; do it in
  its own session/after a gap from other heavy testing, not stacked
  onto more test volume.

  **Still the top-priority open item**: the tail is less catastrophic,
  not fixed. Re-run `tools/measure_latency_p95.py` after any further
  change here rather than trusting any of these tables indefinitely.
- ~~No regression coverage for the guided eligibility interview or
  topic-menu chips.~~ **Done 2026-08-18** —
  `tools/test_conversation_flows.py`, 12/12 passing, stable across repeat
  runs.
- ~~Programme-name typo tolerance not implemented.~~ **Done 2026-08-18** —
  `core/programs.py`'s `_typo_matched_projects` (see the "Architecture"
  section above and `tools/test_programme_typo_tolerance.py`, 10/10
  passing). Scoped narrowly to the three core abbreviations only, with a
  uniqueness rule so "bvsc"/"bfsc" (mutually edit-distance-1 of each other)
  can't typo-correct into one another, plus a small excluded-word set for
  real words that happen to collide (`"tech"` → `"btech"`).
- ~~Age/NCL-certificate facts only verified for `bvsc`.~~ **Done 2026-08-18**
  — the earlier assumption (NRI-section-only for `bfsc`/`btech-dairy`) was
  actually checked against the source text this time and turned out wrong:
  both state the identical age rule in their own general eligibility
  section too (`bfsc` page 10 item 4, `btech-dairy` page 5 item 4, same list
  position as `bvsc`'s). All three `RULES` entries now carry
  `age_requirement`; the NCL-certificate note in `guards.py` was already
  programme-agnostic and needed no change.
- ~~Comparison-path retry/accept-reject logic bug.~~ **Done 2026-08-19** —
  `rag/comparison.py`'s `_flagged_problems` (see `tools/test_comparison_
  retry.py`, 7/7 passing). The old check compared `len({pid: [numbers]})`,
  which counts programmes-with-a-problem, not the number of actual flagged
  figures — now compares the flattened problem set directly.
- **Hindi/Marathi language-detection mismatch** on certain question
  phrasings — not yet isolated to a specific pattern.
- ~~Double negation gave the exact opposite eligibility verdict.~~ **Done
  2026-08-19** — found via an adversarial stress test built specifically
  to answer "what still fails on twisted questions": "It is not true that
  I haven't passed NEET" (= HAS passed) matched `missing_entrance_exam`'s
  negation pattern on the inner "haven't passed NEET" and told the student
  the exact opposite of the truth. Genuine double-negation parsing isn't
  something a regex can do reliably, so the fix does NOT try to flip the
  match into a positive claim (equally risky a guess) — `core/eligibility.
  py`'s `_DOUBLE_NEGATION_FRAME_RE` recognises the outer-negation framings
  that flip an inner negation's meaning ("it is not true that...", "it's
  false that...") and treats exam status as UNKNOWN rather than asserting
  either way — same "don't guess when ambiguous" discipline the guided
  interview already follows. `tools/test_double_negation.py`, 5/5.
- ~~Raw marks fractions ("300 out of 500") were silently ignored.~~ **Done
  2026-08-19** — found in the same stress test: `extract()` only ever
  recognised an explicit "%"/"percent" marker, so a stated fraction with
  no percentage sign got treated as no marks at all and fell into the
  guided interview instead of a real verdict. `_MARKS_OUT_OF_RE` converts
  a fraction into the same value space `_PERCENT_RE` already produces,
  then runs through the IDENTICAL subject/overall cue-scoping — protected
  against false positives (dates, unrelated fractions like a document
  count) by that same pre-existing cue requirement. `tools/test_raw_
  marks_conversion.py`, 7/7.
- ~~False-premise exam questions weren't corrected.~~ **Done 2026-08-19** —
  "Since B.V.Sc. admission is based on JEE score, what JEE score do I
  need?" never repeated the false "JEE" claim as fact, but never named
  the real exam either. `ELIGIBILITY_FACTS_PROMPT` now states the fixed
  exam-to-programme mapping and instructs the model to correct a wrong
  assumption explicitly. LLM phrasing, not a deterministic guarantee (the
  underlying verdict/facts were always correct) — verified 2/2 on retry
  and live on production.
- ~~Compound/multi-part questions degrade through the comparison path.~~
  **Done 2026-08-19** — a 3-part question ("what is the fee, and also am
  I eligible..., and also is hostel compulsory?") embedded as ONE blended
  query diluted retrieval for each sub-topic; the B.V.Sc. fee chunk never
  surfaced at all, even though it retrieves cleanly asked alone.
  `comparison._split_compound_query`/`_retrieve_top_multi` split on the
  connective phrases a compound question actually uses ("and also", "as
  well as"), retrieve each sub-question separately, and merge round-robin
  so no sub-topic gets crowded out. `tools/test_compound_query_split.py`.
  **While verifying this live, found a second, related bug**: the same
  compound question (naming BOTH B.V.Sc. and B.F.Sc.) still answered as a
  single confident B.V.Sc. verdict with B.F.Sc. dropped — the router
  classified `target_programs` as the single-item `['bvsc']`, and
  `_eligibility_guard`'s router-fallback (`named or (routed[0] if
  len(routed)==1 else None)`) trusted that single router guess even
  though the student's own text plainly named two programmes,
  reintroducing the exact "silently pick one, drop the rest" bug the
  2026-08-18 fix closed for the deterministic path — just via the router
  path instead. Fixed: a single-target router classification is only
  trusted when the text names ZERO programmes; naming two or more falls
  through regardless of what the router thinks.
  `tools/test_eligibility_candidate_resolution.py`. Both verified live:
  the compound question now compares both programmes and correctly
  states B.V.Sc.'s real fee.
- ~~B.Tech-Dairy tangent hallucination on `bvsc`'s own single-answer
  path.~~ **Done 2026-08-19** — wasn't the foreign-chunk filter at all: it
  was `_program_redirect_guard` silently redirecting because "dairy" (a
  deliberately bare `btech-dairy` alias) matched inside "Indian Dairy
  Diploma", a real prior qualification named in `bvsc`'s own prospectus.
  Fixed with `programs._NON_PROGRAMME_PHRASES` (see "Architecture" above),
  reproduced and re-verified live on production.
- ~~Retrieval golden set is thin.~~ **Expanded 2026-08-19** —
  `tools/eval_retrieval.py` (the hand-verified-needle file, NOT
  `eval_retrieval_full.py`'s failed auto-derivation attempt — that one's
  2/80 problem is a different file and still unfixed if anyone revisits
  it) grew from 14 to 34 cases, covering fees/refund/documents/hostel/
  weightage/reservation — categories the original 14 (eligibility
  thresholds, entrance exams, duration only) never touched. Every new
  needle verified present verbatim in its own project's vector-store.json
  before being added. Run against production (needs the embedding
  service — see the SSH-tunnel note above; `tools/eval_retrieval.py` was
  copied to `/opt/admission-poc/tools/` and run there directly, sidestepping
  the local tunnel issue entirely):

  **recall@15: 32/34 = 0.94, MRR: 0.619** — confirms the previously-reported
  ~0.93/~0.65 figures hold under a much larger, more diverse set, not an
  artifact of the narrow original 14. Two genuine misses: "can i do dairy
  tech with biology" (pre-existing, already documented as an unfixable-
  by-reranking query-rewriting case) and a NEW one — **"What is the
  domicile certificate requirement for B.Tech Dairy Technology?" never
  retrieves the right chunk, not yet investigated.**
- **Indic TTS still broken** — needs the Docker service running or a funded
  `gpt-4o-mini-tts` key.
- ~~No suite covers presentation, tone, or Indic answer quality.~~
  **Partially done 2026-08-19** — `tools/test_presentation_quality.py`:
  Marathi script-consistency (native + romanized; `test_hinglish.py`
  only ever covered Hindi), tone robustness (rude/terse input still
  gets a real, substantive answer), and a markdown-leak check (plain
  spoken prose must never contain `#`/`-`/`**bold**` markers). Honest
  about the limit, stated in the file's own docstring: whether an
  answer genuinely reads WELL in Marathi is a judgement call a script-
  ratio check cannot make — that still needs a human pass (or a future
  LLM-judge, deliberately not added given this project's repeated
  latency-over-an-extra-LLM-call tradeoffs elsewhere, see the
  `ORCHESTRATOR_PROVIDER` history). Not yet run against production —
  see the rate-limit note under "Providers": deliberately deferred to
  avoid adding more load right after the P95 rate-limit incident.
- ~~Softer gaps found in a 2026-08-19 adversarial stress test~~ — all
  three fixed 2026-08-19:
  - ~~Leading/false-premise question doesn't push back.~~ **Done** — root
    cause was `_program_list_guard` reading `ctx.question` (the router's
    paraphrase) instead of `ctx.original_question`, the same bug class
    CLAUDE.md already documents, just never audited for in this guard.
    "Since I'm clearly not eligible for B.V.Sc., what other programme
    should I consider?" got paraphrased into something like "what other
    programmes are available", dropping the word "eligible" the guard's
    own attribute-word exclusion depends on. Fixed; now falls through to
    the grounded RAG pipeline instead of a confident generic menu.
    `tools/test_program_list_original_question.py`.
  - ~~Multi-category stacking gets a shallow answer.~~ **Done** for the
    PWD half — verified against the source ("5% of total intake capacity
    seats... reserved for Physically Handicapped candidate"): PWD is a
    SEPARATE horizontal seat quota, not a different marks percentage.
    `_threshold_facts` now says so explicitly when PWD/disability is
    mentioned. `tools/test_horizontal_quota_note.py`. **EWS's own
    classification deliberately left untouched and unresolved** — see
    the new item below, this is a real open question, not settled by
    this fix.
  - ~~Subjective/trick comparison loses intent.~~ **Done** — new
    `_subjective_comparison_guard` (checked ahead of `_program_list_guard`
    in `GUARDS`) answers "which is easier to get into?"-shaped questions
    directly and deterministically, acknowledging there's no factual
    "easier" rather than falling into the generic menu OR being deferred
    to `_comparison_guard` (deliberately NOT done — that prompt's "give a
    direct, complete verdict per program" instruction has no safeguard
    against fabricating a difficulty ranking for a subjective question).
    `tools/test_subjective_comparison_guard.py`.
  - ~~Chip-rendering "garbled UI" report could not be reproduced.~~ Still
    unreproduced live, but a real, verifiable gap was found by reading
    the CSS directly: `.chip` had no `max-width` at all — a flex-column
    item with `align-items: flex-start` sizes to its own content's
    max-content width by default, and a `<button>` doesn't wrap text
    unless something bounds its width first, so a long label had nothing
    stopping it from overflowing a narrow viewport. Fixed defensively
    (`max-width: 100%`, `word-wrap: break-word` on `.chip`) even without
    a confirmed live repro — this is real regardless of whether it's the
    exact cause of that one report.
- **NEW, genuinely unresolved: does EWS get the reserved (47.5%) or
  unreserved (50%) marks threshold?** `core/eligibility.py`'s
  `_RESERVED_WORDS` currently includes `"ews"`, treating an EWS-
  identifying student as needing only the reserved-category percentage.
  Checked against the source 2026-08-19 and found genuinely ambiguous:
  `bvsc`'s prospectus (page 14, "6.4 Reservation for female candidates")
  lists "*Unreserved, EWS, SC, ST, VJ/DT(a), NT(b), NT(c), NT(d), OBC,
  SEBC & SBC*" — EWS named as its OWN category, distinct from both
  "Unreserved" and the caste-based reserved categories, matching how
  India's EWS reservation works nationally (economically weaker section
  WITHIN the general/open category, not a caste-based reservation) — but
  that confirms EWS has its own SEAT allocation, not which MARKS
  threshold applies to it. The actual eligibility-criteria section (page
  4) states only a binary Unreserved/Reserved split and never mentions
  EWS by name. Deliberately NOT changed without an explicit source
  statement — this codebase's standing rule is never to state a number
  the source doesn't support, and getting an EWS student's qualifying
  percentage wrong in either direction is a real-stakes mistake, not a
  cosmetic one. Needs someone to find (or ask the admissions office for)
  the explicit rule before `_RESERVED_WORDS` is touched.
