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
outstanding. `_eligibility_facts()`/`_eligibility_fallback_sentence()` gave
those conditions equal weight to the verdict, not a footnote — **except age,
removed again 2026-08-19 on explicit request**: eligible verdicts no longer
mention the age requirement at all (`age_requirement` is still computed in
`core/eligibility.py`'s `RULES`/return dict, just no longer read by either
guards.py function). Entrance-exam-clearance and category-certificate
wording is unaffected. If this needs reverting, the removed blocks were two
`if result["verdict"] == "eligible" and result.get("age_requirement"):`
checks, one in each function.

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
`test_comparison_retry.py`, and `test_exam_based_matching.py` (added
2026-08-18/19) are pure logic against `core/programs.py`/`rag/
comparison.py`/`core/eligibility.py` directly, no backend needed — the odd
ones out among these, everything else here hits the live HTTP API.

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

- **P95 latency — measured, and it is bad.** First real run, 2026-08-18,
  `measure_latency_p95.py` against production, cold cache, all 80
  `eval_admissions.CASES`:

  | | |
  |---|---|
  | min / p50 | 1.0s / 3.0s — median is fine, matches the old benchmark |
  | p90 / p95 / p99 | **56.0s / 80.5s / 240.1s** |
  | max / mean | 240.2s / 18.7s |
  | >15s | 15/80 (18.8%) |
  | errors | 3/80 timed out or dropped outright (Q49, Q56, Q66 — reservation-policy and seat-count questions) |

  This is the number HANDOFF.md's P0 section predicted but never measured:
  median latency hid a tail that 1 in 5 real students would actually hit,
  plus outright failures on ~4% of questions. The fast end (sections A/G,
  1.0-1.1s) is entirely the deterministic paths (eligibility verdicts,
  retired-programme refusals) that skip the LLM round trip — the slow tail
  clusters in reservation/fees/colleges, the sections that go through
  retrieval + generation. **This is now the top-priority open item** — a
  retry/timeout policy on the slow provider path, not a better model (see
  the answer-quality ceiling note above). Re-run
  `tools/measure_latency_p95.py` after any change here rather than trusting
  this table indefinitely; provider tail latency drifts.
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
- ~~B.Tech-Dairy tangent hallucination on `bvsc`'s own single-answer
  path.~~ **Done 2026-08-19** — wasn't the foreign-chunk filter at all: it
  was `_program_redirect_guard` silently redirecting because "dairy" (a
  deliberately bare `btech-dairy` alias) matched inside "Indian Dairy
  Diploma", a real prior qualification named in `bvsc`'s own prospectus.
  Fixed with `programs._NON_PROGRAMME_PHRASES` (see "Architecture" above),
  reproduced and re-verified live on production.
- **Retrieval golden set is thin.** `tools/eval_retrieval_full.py` (added
  2026-08-18) tried to derive gold chunks automatically from
  `eval_admissions.CASES`'s `expect` term lists and could only reliably
  label 2/80 cases — those lists were built for loose answer-checking, not
  verbatim chunk-grounding. A real golden set needs hand-labeling, not
  reuse of the existing eval cases.
- **Indic TTS still broken** — needs the Docker service running or a funded
  `gpt-4o-mini-tts` key.
- No suite covers presentation, tone, or Indic answer *quality* (as opposed
  to source/figure correctness) — repeatedly raised, still open.
