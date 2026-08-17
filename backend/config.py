"""Central configuration for the Admission Assistant backend.

Pure standard-library Python so it runs directly on the Windows host without any
compiled dependencies (this machine's Application Control policy blocks freshly
built native binaries such as pydantic-core). The heavy ML pieces - embeddings
and Indic TTS - live in Docker containers this backend calls over HTTP.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Load BASE_DIR/.env into the environment (stdlib, no dependency).

    Values already set in the real environment win, so inline overrides still work.
    The .env file is gitignored and holds secrets like SARVAM_API_KEY.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DATA_DIR = BASE_DIR / "data"
KEYS_PATH = DATA_DIR / "api-keys.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# --- Projects (multi-tenant: one prospectus/pipeline per project) ---
PROJECTS_REGISTRY_PATH = DATA_DIR / "projects.json"
PROJECTS_DIR = DATA_DIR / "projects"
DEFAULT_PROJECT_ID = "default"

# --- Embedding service (Dockerized nomic-embed-text) ---
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8000/embed")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")

# Two timeouts, because the two callers have nothing in common but the endpoint.
#
# Ingest embeds a batch of whole OCR'd table pages against a CPU service, and
# nobody is waiting on it - 120s was measured as too short once entire tables
# started being embedded as single chunks, hence the generous ceiling.
#
# A query embeds ONE short question with a student watching a browser spinner,
# and it used to share that same 600s. The embedding service occasionally 503s,
# so a single bad call could pin a request thread for ten minutes - most of the
# eighteen-minute hang recorded against Q66. Nothing downstream bounded it
# because nothing anywhere sets a request budget.
EMBEDDING_QUERY_TIMEOUT = int(os.environ.get("EMBEDDING_QUERY_TIMEOUT", "15"))
EMBEDDING_INGEST_TIMEOUT = int(os.environ.get("EMBEDDING_INGEST_TIMEOUT", "600"))

# --- Admission control (see http/concurrency.py) ---
# How many answers may be in flight at once. ThreadingHTTPServer has no ceiling
# of its own, and each answer holds a thread for seconds AND a slot against a
# rate-limited provider. Measured here: one SEQUENTIAL 75-question eval run
# drew eleven `HTTPError 429` responses from Mistral, so the provider - not
# this process - is the binding constraint at the 10-50 concurrent students
# this deployment is sized for. Holding the queue here makes it visible and
# refusable instead of turning into a 429 nobody can act on.
# 0 disables the ceiling entirely (fails open on a misconfigured value).
MAX_CONCURRENT_CHATS = int(os.environ.get("MAX_CONCURRENT_CHATS") or "8")
# A short grace wait so a brief burst becomes a small delay rather than a
# refusal; only sustained overload should be refused.
CHAT_QUEUE_WAIT_SECONDS = float(os.environ.get("CHAT_QUEUE_WAIT_SECONDS") or "2.0")
CHAT_RETRY_AFTER_SECONDS = int(os.environ.get("CHAT_RETRY_AFTER_SECONDS") or "5")

# --- Self-hosted embeddings (BGE-M3, multilingual) ---
# Set EMBEDDING_PROVIDER=selfhosted to route embeddings through the same
# self-hosted server as chat (SELFHOSTED_URL/SELFHOSTED_API_KEY above)
# instead of the local nomic-embed-text-v1 service (EMBEDDING_URL above).
# The point is cross-lingual retrieval: nomic-embed-text doesn't align
# Hindi/Marathi/Tamil with English closely enough for a native-script
# question to reliably retrieve the right English prospectus chunks, which
# is why every non-English question currently pays for a translate-to-
# English round trip before retrieval (see llm.translate_to_english) - a
# round trip that has been the source of several bugs today. BGE-M3 is
# trained for direct cross-lingual alignment and could remove that step from
# the retrieval path entirely. Added 2026-08-11 while the model was still
# downloading on the user's server - UNVERIFIED against a live endpoint;
# confirm the actual request/response shape (embeddings.py currently guesses
# the OpenAI-standard POST /v1/embeddings convention, matching how vLLM/TEI/
# llama.cpp servers commonly expose embeddings) before trusting this in
# production, the same way SELFHOSTED_URL's chat path turned out to deviate
# from the OpenAI standard (POST /v1/chat, not /v1/chat/completions).
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "local")
SELFHOSTED_EMBEDDING_MODEL = os.environ.get("SELFHOSTED_EMBEDDING_MODEL", "bge-m3")

# --- Ollama + model routing ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Keep models resident in memory so there is no per-request cold start.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

# Model strategy (simplified): one strong cloud model handles ALL languages when
# online, one small local model covers everything offline.
#
#   - Online : Sarvam AI cloud (sarvam-m) - a 24B model strong at English AND
#              Hindi/Marathi/Tamil. Fast (cloud) and high quality across the board.
#   - Offline: gemma2:2b - a single instruction-tuned local model. Good English,
#              acceptable Indic. Used when there's no Sarvam key or the cloud is down.
#
# gemma2:2b handles English well too, so a separate English model (previously
# llama3.2:3b) is unnecessary. Set SARVAM_API_KEY to enable the cloud path; the key
# is read from the environment only - never hard-code it here.
MODEL_LOCAL = os.environ.get("MODEL_LOCAL", "gemma2:2b")
MODEL_FALLBACK = os.environ.get("MODEL_FALLBACK", "llama3.1")

# --- Self-hosted LLM API (OpenAI-shaped, custom endpoint path) ---
# CHAT DUTY REMOVED 2026-08-12: leadership decided against depending on this
# shared server for answer generation at all - Sarvam is fast enough as
# CHAT_PRIMARY, and HetznerProvider (see providers.py) replaced this as
# CHAT_FALLBACK. SELFHOSTED_MODEL_EN/INTL below and SelfHostedProvider's
# per-request model routing are now DEAD CODE under the current .env - both
# only execute if CHAT_FALLBACK is set back to "selfhosted" (confirmed via
# grep: every remaining call site branches on that check). Left in place
# rather than deleted, in case this server's chat duty is ever revived; this
# server's EMBEDDING duty (SELFHOSTED_EMBEDDING_MODEL, EMBEDDING_PROVIDER
# above) is unaffected and still live.
#
# Everything below this point describes history from when this server DID
# handle chat (through 2026-08-12 morning) - kept for that record, not
# because it's still operative.
#
# A team-run server exposing several models over an OpenAI-compatible
# body/response shape - except completions are POSTed to /v1/chat, not the
# standard /v1/chat/completions.
#
# SELFHOSTED_MODEL_EN / SELFHOSTED_MODEL_INTL split the self-hosted tier by
# language, kept as two separate settings even though both point at
# qwen2.5-3b-instruct as of 2026-08-12, in case the right model per lane
# diverges again later (it already has once - see history below).
#
# sarvam-1-gguf-Q4_K_M (2B) was the INTL pick through 2026-08-11 on the
# reasoning that it was the only model on this server reliably handling
# Hindi/Marathi/Tamil script. That reasoning didn't hold up under this
# project's actual RAG-sized prompts (~3.5-5.9K tokens, 9-10 retrieved
# excerpts): captured the exact live request/response for a real Marathi
# question and replayed it directly against the server three separate ways -
# default settings echoed the question back with zero content, repeat_penalty
# tuned to stop a 35+ line repetition loop instead produced a DIFFERENT
# zero-content echo, and even full-context repeat_last_n=-1 only fixed it at
# 114s (not demo-viable). qwen2.5-3b-instruct (3B) handled the IDENTICAL
# captured payload correctly on the first attempt, no tuning, 84s, coherent
# Devanagari, clean stop. Switched INTL to it on that evidence; not yet
# separately validated on Tamil script specifically (the repro that drove
# this was Marathi/Devanagari) - re-check if Tamil answers regress.
#
# The EN pick changed once already for an unrelated reason: glm-4-9b-chat was
# the pick on 2026-08-11 morning, but by that afternoon it showed as
# "available" (not "running", no bound port) on GET {SELFHOSTED_URL}/v1/models
# - unloaded on the server side - while qwen2.5-3b-instruct was actually
# running, so that's what EN moved to.
#
# SelfHostedProvider.chat() picks between the two settings per-request via
# detect_script (see providers.py) unless a caller passes model= explicitly.
# This is a config change, not a code change, if the server's lineup shifts
# again - which it has repeatedly; this is a live, mutable list on someone
# else's infrastructure, re-check GET {SELFHOSTED_URL}/v1/models for
# status:"running" before assuming a name here still exists.
SELFHOSTED_URL = os.environ.get("SELFHOSTED_URL", "")
SELFHOSTED_API_KEY = os.environ.get("SELFHOSTED_API_KEY", "")
SELFHOSTED_MODEL_EN = os.environ.get("SELFHOSTED_MODEL_EN", "qwen2.5-3b-instruct")
SELFHOSTED_MODEL_INTL = os.environ.get("SELFHOSTED_MODEL_INTL", "qwen2.5-3b-instruct")

# --- Hetzner Inference API (OpenAI-shaped, standard /v1/chat/completions) ---
# Added 2026-08-12 to replace SelfHostedProvider as CHAT_FALLBACK: genuinely
# OpenAI-compatible (unlike the self-hosted server's nonstandard /v1/chat
# path above), noticeably larger/more capable models (35B-1T range vs.
# qwen2.5-3b-instruct's 3B), and moves this app's fallback load off the
# shared self-hosted server entirely (embeddings still go through
# SELFHOSTED_URL above - unrelated to this). One model for both EN and INTL
# lanes, unlike the self-hosted split above - no evidence yet that a model
# this much larger needs the same per-language routing a 3B model did;
# revisit with SELFHOSTED_MODEL_EN/INTL's split pattern if a real Indic
# regression turns up.
HETZNER_API_KEY = os.environ.get("HETZNER_API_KEY", "")
HETZNER_URL = os.environ.get("HETZNER_URL", "https://inference.hetzner.com/api/v1")
HETZNER_MODEL = os.environ.get("HETZNER_MODEL", "Qwen/Qwen3.6-35B-A3B-FP8")

# --- Groq (OpenAI-shaped, LPU inference - added for latency-insensitive-quality
# lanes like the greeting short-circuit, NOT the main Sarvam-vs-Hetzner answer
# path). is_cloud = False for the same reason as Hetzner/SelfHosted above -
# this has its own separate account/limits, not Sarvam's metered quota.
# Never used for the main RAG answer: the 2026-08-13 decision to keep Sarvam
# primary was explicitly "never let language quality regress, even on
# fallback," which ruled out non-Indic-tuned fast providers for THAT path.
# A greeting reply is a much lower quality bar (no retrieval, no figures to
# get wrong), so it's a reasonable, scoped exception - see GREETING_PROVIDER.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = os.environ.get("GROQ_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- NVIDIA NIM (OpenAI-shaped) ---
# Adopted 2026-08-14 after Sarvam returned HTTP 402 "No credits available."
# and Groq hit its 100k tokens/day free ceiling. Two models, two roles - see
# NvidiaProvider. Model ids verified against /v1/models AND actually called:
# the catalogue lists several that return 404 when used.
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_URL = os.environ.get("NVIDIA_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
NVIDIA_FAST_MODEL = os.environ.get("NVIDIA_FAST_MODEL", "meta/llama-3.1-8b-instruct")
NVIDIA_MAX_TOKENS = int(os.environ.get("NVIDIA_MAX_TOKENS", "4096"))

# --- Mistral AI (OpenAI-shaped) ---
# Separate account with its own limits, so benchmarking and experiments do
# not drain the quota the working configuration runs on.
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_URL = os.environ.get("MISTRAL_URL", "https://api.mistral.ai/v1")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-medium-latest")
MISTRAL_MAX_TOKENS = int(os.environ.get("MISTRAL_MAX_TOKENS", "1500"))
# Speech-to-text (see generation/speech.py). Voxtral handles Hindi and
# Marathi; Mistral's TTS voices are English-only, so text-to-speech stays
# with TTS_URL below.
STT_MODEL = os.environ.get("STT_MODEL", "voxtral-mini-latest")
STT_TIMEOUT = int(os.environ.get("STT_TIMEOUT", "60"))
# Document OCR (see ocr.py). Off by default: it is a paid call over a whole
# prospectus, and pypdf remains a working extractor. Turn it on when table
# fidelity matters more than ingest cost - which it does here, because
# pypdf loses the label-to-figure association in fee grids.
OCR_ENABLED = os.environ.get("OCR_ENABLED", "false").lower() == "true"
OCR_MODEL = os.environ.get("OCR_MODEL", "mistral-ocr-latest")
OCR_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "600"))

# --- Chat provider selection (see providers.py) ---
# Which backend answers questions, and what to fall back to when it fails or is
# unavailable. Config rather than code because the choice is genuinely open:
# Sarvam's current tier caps calls/day and max_tokens, and Bhashini is a live
# alternative built around translation rather than generation. Set
# CHAT_PRIMARY=ollama to run fully local and free (slower, weaker on tables -
# though the deterministic table lookup removes most of that gap).
CHAT_PRIMARY = os.environ.get("CHAT_PRIMARY", "sarvam")
CHAT_FALLBACK = os.environ.get("CHAT_FALLBACK", "ollama")

# Sampling temperature for answer generation. No temperature was being sent at
# all, so both providers ran at their API defaults - roughly 1.0 for Sarvam's
# OpenAI-compatible endpoint and 0.8 for Ollama. That is a creative-writing
# setting, and it showed: the same question produced materially different
# answers between runs. Measured on repeated runs of the identical Hindi probe
# "40% marks still gets admission, right?" - one run correctly refused, another
# answered "हाँ, ... मिल सकता है" (yes, you can), which is false and is exactly
# the kind of confident agreement that misleads a student. The FAQ cache then
# freezes whichever answer happened to come first and serves it to everyone.
#
# This is an extraction task against supplied excerpts, not a generative one, so
# a low temperature is the correct default: quoting the right figure has one
# right answer. Not 0 - the Sarvam model is a reasoning model and fully greedy
# decoding tends to make such models loop on hard prompts - but low enough that
# repeated asks agree.
CHAT_TEMPERATURE = float(os.environ.get("CHAT_TEMPERATURE", "0.2"))

# Fixed sampling seed for the local model. Ollama otherwise picks a random seed
# per request, so even at temperature 0.2 the same question produced different
# output between runs - and the local model's most important job is translating
# the question for retrieval, where a different wording changes which chunks are
# found. Measured directly: the same 68-question retrieval bank scored 95.6% and
# 98.5% on consecutive runs with no code change between them, purely from
# translation drift, and a fee question resolved to the wrong table cell on one
# run and the right one on the next.
#
# A fixed seed makes that reproducible: a retrieval failure stays failed until it
# is actually fixed, instead of disappearing on re-run and returning in front of
# a student. Set OLLAMA_SEED=0 to restore random sampling.
OLLAMA_SEED = int(os.environ.get("OLLAMA_SEED", "42"))

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_URL = os.environ.get("SARVAM_URL", "https://api.sarvam.ai/v1/chat/completions")
# sarvam-30b was retired by Sarvam and now returns HTTP 400 on every request
# ("Model 'sarvam-30b' has been deprecated. Please use one of the available
# models instead: sarvam-105b."). Nothing about that failure is visible from the
# app: llm.generate catches it and falls back to gemma2:2b, so the entire system
# silently served a 2B local model instead of the cloud one - which is where the
# garbled Hindi/Marathi answers were coming from, not from any of the retrieval
# or prompting work. Verified on 2026-07-30 by calling the API directly.
#
# If Indic answer quality ever regresses for no apparent reason, check this line
# and the backend's startup "Models :" line before looking anywhere else.
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-105b")
# Charge safety: hard cap on Sarvam cloud calls per day. Once exceeded, the backend
# silently falls back to the local model so it can never drift into paid usage. The
# FAQ cache means repeated questions don't count against this at all.
SARVAM_DAILY_LIMIT = int(os.environ.get("SARVAM_DAILY_LIMIT", "150"))
SARVAM_USAGE_PATH = BASE_DIR / "data" / "sarvam-usage.json"
# Short timeout so a stalled cloud call fails over fast instead of hanging the
# UI. Applies to ONE attempt against ANY cloud provider - primary or fallback.
#
# Renamed from SARVAM_TIMEOUT 2026-08-17. The old name had stopped describing
# what the value does: Sarvam has been dead on HTTP 402 for weeks, yet this
# figure silently governed whichever cloud provider was primary (Mistral), so
# anyone reading llm.generate saw a Sarvam-specific knob bounding a Mistral
# call. SARVAM_TIMEOUT is still honoured as an env var and still exported as an
# alias below - renaming without that would quietly change the timeout on every
# deployment whose .env sets the old name, including this one.
# `or`, not a get() default: a key that is PRESENT but empty (a bare
# "CLOUD_ATTEMPT_TIMEOUT=" line in .env, which is easy to leave behind while
# commenting a value out) returns "", which would both shadow the alias and
# crash int() at import time - taking the whole server down before it serves
# one request.
CLOUD_ATTEMPT_TIMEOUT = int(
    os.environ.get("CLOUD_ATTEMPT_TIMEOUT")
    or os.environ.get("SARVAM_TIMEOUT")
    or "45")
SARVAM_TIMEOUT = CLOUD_ATTEMPT_TIMEOUT  # backward-compatible alias

# --- Orchestration / validation / self-learning (2026-08-12) ---
# ORCHESTRATOR_PROVIDER is deliberately never "sarvam" in normal operation:
# every new call path added by this feature (sub-topic answers, the
# validator, a failed-review regeneration retry) is Hetzner-only by
# construction, so none of it can compete with the single user-facing
# answer call for Sarvam's metered daily quota - see llm.generate_scoped's
# docstring. This is a design principle, not just today's quota situation -
# it means this feature can never make a FUTURE quota crunch worse either.
ORCHESTRATOR_PROVIDER = os.environ.get("ORCHESTRATOR_PROVIDER", "hetzner")

# Which provider answers the greeting short-circuit (see rag/guards.py's
# _greeting_guard) - deliberately separate from ORCHESTRATOR_PROVIDER above,
# since that one's choice is about sub-agent reasoning quality and this one
# is purely about not making a student wait ~20s for "hey, how can I help".
# Falls through to the normal CHAT_PRIMARY/CHAT_FALLBACK chain automatically
# if unconfigured or a call fails (see llm.generate_scoped's None contract),
# so an empty GROQ_API_KEY is a no-op, not a broken greeting.
GREETING_PROVIDER = os.environ.get("GREETING_PROVIDER", "groq")

# --- Intent router (2026-08-13) - see rag/router.py ---
# One structured classification call in front of the guard stage, so routing
# decisions come from READING the message rather than from substring/regex
# matching. Same provider reasoning as ORCHESTRATOR_PROVIDER above: never
# "sarvam", because this is a bounded reading task that must not compete
# with the single user-facing answer call for the metered daily quota.
# ROUTER_ENABLED is the kill switch - turning it off reverts every routing
# decision to the deterministic keyword logic, which is still in place as
# the fallback for any individual failed call anyway.
ROUTER_ENABLED = os.environ.get("ROUTER_ENABLED", "true").lower() == "true"
ROUTER_PROVIDER = os.environ.get("ROUTER_PROVIDER", "groq")
# Tried when the primary router provider fails or rate-limits. EMPTY BY
# DEFAULT, and that default is a measurement, not an oversight: Hetzner - the
# only other non-metered option - answers a trivial prompt in 52-77s, so it
# cannot complete inside any timeout that may sit in front of a student's
# question. Enabling it made the failure path WORSE, not better: a Groq 429
# returns in well under a second, but the request then sat ~35s waiting on a
# fallback that was never going to finish before dropping to keyword routing
# regardless. Fast keyword routing beats a slow one.
#
# Set this to a provider name if a genuinely fast second option appears (a
# paid Groq tier, another LPU host). The chain, per-provider timeouts and
# breaker below are all still in place and will use it.
ROUTER_FALLBACK_PROVIDER = os.environ.get("ROUTER_FALLBACK_PROVIDER", "")
# Short by design: the router sits in front of EVERY answer, so a stalled
# routing call must fail over to the deterministic guards fast rather than
# adding its own timeout to the student's wait.
ROUTER_TIMEOUT = int(os.environ.get("ROUTER_TIMEOUT", "12"))
# The fallback needs a far longer leash than the primary. 12s is generous
# for Groq (sub-second in practice) but too tight for Hetzner, which
# answers the same classification in 7-15s - measured: with one shared
# 12s budget, a Groq 429 fell through to Hetzner and then timed out, so
# the fallback existed on paper and never actually completed. A slow
# classification still beats no classification, because the alternative
# is keyword routing.
ROUTER_FALLBACK_TIMEOUT = int(os.environ.get("ROUTER_FALLBACK_TIMEOUT", "35"))

# Master switches - each piece can be independently disabled without
# touching the others, matching this codebase's existing per-feature flag
# pattern (FAQ_AUTOCACHE below).
ORCHESTRATOR_ENABLED = os.environ.get("ORCHESTRATOR_ENABLED", "true").lower() == "true"
VALIDATION_ENABLED = os.environ.get("VALIDATION_ENABLED", "true").lower() == "true"

# Decide "am I eligible?" in core/eligibility.py instead of letting the model
# compare the numbers inside its prose. Set false to revert to the behaviour
# that failed four questions of the 2026-08-14 evaluation: measuring a 51%
# aggregate against a rule the prospectus states on the subject combination,
# and quoting 40% where B.V.Sc.'s reserved threshold is 47.50%.
ELIGIBILITY_GUARD_ENABLED = os.environ.get(
    "ELIGIBILITY_GUARD_ENABLED", "true").lower() == "true"
# Deterministic checks (validate.deterministic_checks) always run when
# VALIDATION_ENABLED is true and cost nothing; this second switch gates
# ONLY the bounded LLM check + regeneration on top of them, so the
# zero-cost signal can be verified against real traffic before spending
# any Hetzner calls on it (see the plan's staged rollout).
VALIDATION_LLM_CHECK_ENABLED = os.environ.get("VALIDATION_LLM_CHECK_ENABLED", "false").lower() == "true"

# Last-resort clarification, added 2026-08-17. Every guard above this one
# already either fires deterministically or checks _routed() itself (which
# drops low-confidence router opinions in favour of keyword logic - see
# guards._routed's docstring). What reaches the very end of GUARDS with
# route["confidence"] == "low" is the leftover: the router was unsure AND no
# deterministic guard could classify the question either, so without this
# switch it falls straight into free-form RAG generation on a question
# nobody actually resolved - answering confidently on a guess.
#
# NOT the same change as the three attempts HANDOFF.md's "clarification
# guard punishes clever ideas" section warns were tried and reverted. Those
# made _program_clarify_guard itself MORE trigger-happy (deterministic-only,
# self-consistency sampling) and regressed sections E/F because a percentage
# or policy question that was already being classified fine got caught too.
# This guard only sees what every other guard already gave up on - it cannot
# steal a question those were handling correctly, because if the question
# reached the end of the guard order at all, none of them fired. Still
# gated behind a switch and measured before/after per that same section's
# instruction, since "no other guard fired" is a different bar than "the
# question was genuinely ambiguous" and the two have not been proven to be
# the same set of questions yet.
LOW_CONFIDENCE_CLARIFY_ENABLED = os.environ.get(
    "LOW_CONFIDENCE_CLARIFY_ENABLED", "true").lower() == "true"

# Orchestrator: complexity trigger + sub-topic fan-out (see orchestrator.py).
ORCHESTRATOR_MIN_WORDS = int(os.environ.get("ORCHESTRATOR_MIN_WORDS", "35"))
ORCHESTRATOR_MAX_SUBTASKS = int(os.environ.get("ORCHESTRATOR_MAX_SUBTASKS", "3"))
ORCHESTRATOR_TIMEOUT = int(os.environ.get("ORCHESTRATOR_TIMEOUT", "60"))
# Retrieval chunks per sub-topic in an orchestrated answer, deliberately
# smaller than config.TOP_K (15): that number was tuned for ONE topic's
# context filling the whole prompt, but an orchestrated question pulls from
# several sub-topics at once - same reasoning as rag.py's
# _COMPARISON_TOP_K_PER_PROGRAM (10), which was itself raised from an
# initial 6 after live-testing found 6 too tight for even a single topic
# (see rag.py's comment on that constant) - starting at the already-
# measured-sufficient value here rather than re-discovering the same gap.
ORCHESTRATOR_TOP_K_PER_SUBTASK = int(os.environ.get("ORCHESTRATOR_TOP_K_PER_SUBTASK", "10"))

# Validation: the bound is hard-coded in code (exactly one validator call,
# exactly one regeneration attempt - see validate.py/rag.py), not a loop
# driven by this number. VALIDATION_MAX_ROUNDS exists as a named constant
# for clarity/future reference only; deliberately not used to drive
# iteration - an unbounded validate-regenerate loop on a service already
# averaging ~30s/answer is a runaway-latency/cost risk, not a robustness
# win (see the plan's "deliberate deviations" section).
VALIDATION_MAX_ROUNDS = int(os.environ.get("VALIDATION_MAX_ROUNDS", "1"))
# 45s timed out on Hetzner's 35B model for a real validator call that
# genuinely needed ~60-90s (measured directly, see llm_check's docstring
# context) - a too-tight timeout here silently fails PASS (see llm_check's
# safe-degrade rule), which is the wrong failure mode for a check whose
# whole job is catching a wrong answer. 90s costs latency only on the rare
# path where a deterministic check already found something to escalate.
VALIDATION_TIMEOUT = int(os.environ.get("VALIDATION_TIMEOUT", "90"))

# Self-learning: how much flagged/review-log history counts, and how many
# repeats of the same pattern justify surfacing it at all - low defaults
# since this project's total daily volume is small (see stats).
PATTERN_WINDOW_DAYS = int(os.environ.get("PATTERN_WINDOW_DAYS", "14"))
PATTERN_MIN_OCCURRENCES = int(os.environ.get("PATTERN_MIN_OCCURRENCES", "3"))
# A single GLOBAL overlay file, not per-project: faq.py's _CONTRAST_FORMS/
# _ORDINAL_FORMS discriminator vocabulary is itself module-level and shared
# across every project's cache, so learned additions to it are global too.
LEARNED_DISCRIMINATORS_PATH = BASE_DIR / "data" / "learned-discriminators.json"

# --- Indic TTS service (Dockerized AI4Bharat) ---
TTS_URL = os.environ.get("TTS_URL", "http://localhost:8001/tts")
# The proxy timeout was 180s, which is BELOW how long this actually takes:
# measured on this host, one sentence took 252s in Hindi and 166s in Marathi
# (CPU inference for a 0.9B model). So the Hindi path reliably exceeded the
# timeout, the proxy returned 503 "TTS service unavailable", and the UI's error
# branch falls back to the browser's built-in device voice - which is why the
# natural AI4Bharat voice was never heard even though the service was healthy
# and generating valid audio the whole time.
#
# Raised well clear of the observed worst case. Note this makes the failure
# honest, not fast: a 3-4 minute wait is still not viable for live use, and the
# real fix is GPU inference or a smaller voice model.
TTS_TIMEOUT = int(os.environ.get("TTS_TIMEOUT", "600"))

# --- OCR service (Dockerized Baidu Unlimited-OCR) ---
OCR_SERVICE_URL = os.environ.get("OCR_SERVICE_URL", "http://localhost:8002/ocr")
OCR_SERVICE_API_KEY = os.environ.get("OCR_SERVICE_API_KEY", "")

# --- Browser extension auto-config ---
# The extension calls /api/extension/register on install and gets all settings
# back. Admin sets these via the admin console (not the extension popup).
EXTENSION_SETTINGS_PATH = DATA_DIR / "extension-settings.json"
DEFAULT_EXTENSION_SETTINGS = {
    "driveFolderId": "",
    "quotationTextSelector": "",
    "sendButtonSelector": ".btn-global.btn-add-roles",
    "fileInputSelector": 'input[type="file"][accept=".pdf,.jpg,.jpeg"]',
    "emailBodySelector": "",
    "matchThreshold": 0.55,
    "ocrServiceUrl": "http://localhost:8002",
    "attachmentNoteTemplate": "",
    "skipNoteTemplate": "",
    "injectNoteOnSkip": False,
}

# --- FAQ cache ---
# Semantically-close past/seeded questions return instantly, skipping RAG + the LLM.
# A match at or above this cosine threshold is treated as the same question.
# Chosen from the measured score distribution on this corpus, not by feel.
# Genuine paraphrases of a cached question score 0.91-0.99 ("where is the
# college located" vs "Where are the colleges located?" = 0.913), while
# genuinely different questions top out around 0.58 ("How do I contact the
# hostel warden?" vs "Is hostel accommodation available?" = 0.579). That is a
# wide, safe gap. The old 0.93 sat just above the paraphrase band and so missed
# most real rephrasing - only 1 of 5 natural paraphrases hit the cache, which
# matters enormously at admission scale where a miss costs a 5-30s LLM call.
# 0.88 captures the paraphrase band while staying ~0.30 clear of any false hit.
FAQ_THRESHOLD = float(os.environ.get("FAQ_THRESHOLD", "0.88"))
# Upper bound on cached entries per project. Every distinct question stores a
# 768-float vector, so an admission rush would otherwise grow this file without
# limit. Curated (seeded) entries are never pruned; the oldest auto-cached ones
# go first. 0 disables pruning.
#
# The cap is really a latency budget. Matching is a pure-Python scan costing a
# measured ~0.05ms per entry, and it is GIL-bound, so it limits concurrent
# throughput rather than just adding delay: 1000 entries is ~50ms per request
# (~20 requests/sec per core). Raising this trades throughput for a higher cache
# hit rate - worth it only if a hit is still far cheaper than the 5-30s LLM call
# it avoids, which it is, so tune upward only alongside more worker processes.
FAQ_MAX_ENTRIES = int(os.environ.get("FAQ_MAX_ENTRIES", "1000"))
# How long auto-cached answers may sit in memory before being written to disk.
# Rewriting the whole cache file on every miss stalls writers; entries are
# reproducible, so a short delay costs nothing but a re-answer after a hard
# crash. 0 writes through immediately.
FAQ_FLUSH_SECONDS = float(os.environ.get("FAQ_FLUSH_SECONDS", "5"))
FAQ_AUTOCACHE = os.environ.get("FAQ_AUTOCACHE", "1") == "1"

# --- Retrieval ---
# 8, not 5: the admission-schedule table ranked 9th for "last date to submit the
# online application form" - a near miss that left the model answering from an
# unrelated page that happened to mention a different deadline. Table pages
# compete poorly on cosine similarity because one chunk covers many rows, so the
# extra headroom matters more than the slightly longer prompt.
# 10, raised from 8: measured on the 68-question Hindi/Marathi retrieval bank
# (tools/test_retrieval_hi_mr.py), which sweeps K against known answer pages.
# 8 left two reservation-percentage questions and a domicile question just
# outside the window - the right chunk ranked 9th or 10th, so the model answered
# from pages that did not contain the fact and correctly said it wasn't
# specified. K=10 took recall to 68/68 for both languages; 12 and 14 added
# nothing, so this is the knee of the curve rather than a guess.
#
# 15, raised from 10 on 2026-08-12: that 68/68 result was measured against
# nomic-embed-text-v1 (the originally documented embedding model, see
# docs/MODELS_AND_DEPLOYMENT.md), not what's actually running - EMBEDDING_PROVIDER
# has since moved to selfhosted BGE-M3 (see .env), and nobody re-validated K
# against the new embedding space until this date. Re-run on BGE-M3: K=10
# had quietly regressed to 61/68 (89.7%), not the documented 100%. Swept
# 5/7/10/15 - K=15 recovered the most (63/68, 92.6%) and also gave the best
# table-lookup accuracy (15/17, still 0 confidently wrong at every K tested).
# Trade-off, not a free win: noise (non-gold chunks retrieved) rises with K
# too (measured ~88% of retrieved chunks are non-gold at K=15, vs ~83% at
# K=10) - accepted deliberately, since the recall wins are real chunks that
# were missing entirely, not just more padding. 5 probes (reservation-%
# questions, attendance, college locations) stayed missed at every K from 5
# to 15 - a genuine BGE-M3 semantic-retrieval gap for those topics, not a
# windowing problem, and not fixed by raising K further. Left as a tracked
# gap - likely needs a chunking/content fix (e.g. markdown-sourced ingestion)
# rather than more retrieval headroom. See tools/test_retrieval_hi_mr.py to
# re-measure if the embedding model or corpus changes again.
TOP_K = int(os.environ.get("TOP_K", "15"))
CHUNK_CHARS = int(os.environ.get("CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))

# --- Prospectus auto-refresh (Firecrawl) ---
# Detects when a project's live source page/PDF changes (new academic year, a
# mid-year fee revision) and re-runs the extract/chunk/embed pipeline without
# anyone manually re-downloading and re-uploading a PDF. Firecrawl only does the
# "did this change" detection and hands back the current bytes - the actual
# extraction still goes through pdf.py's tuned pipeline unchanged (see
# prospectus_watch.py). Works against the hosted API or a self-hosted Firecrawl
# instance (point FIRECRAWL_URL at it) the same way the other services here run
# in Docker on this host.
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_URL = os.environ.get("FIRECRAWL_URL", "https://api.firecrawl.dev").rstrip("/")
# Hours, not minutes - a prospectus changes at most a handful of times a year,
# so there is no benefit to polling faster and it would only burn Firecrawl
# calls. 0 or unset watch_enabled per-project both mean "never" regardless.
PROSPECTUS_WATCH_INTERVAL_HOURS = float(os.environ.get("PROSPECTUS_WATCH_INTERVAL_HOURS", "6"))
PROSPECTUS_WATCH_TIMEOUT = int(os.environ.get("PROSPECTUS_WATCH_TIMEOUT", "60"))

# --- Admin / keys ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "password")
DEFAULT_KEY_LABEL = "admission-site"

# --- Server ---
PORT = int(os.environ.get("PORT", "5050"))
