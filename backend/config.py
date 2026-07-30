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

# Legacy single-tenant paths - read only during one-time migration into
# data/projects/default/ (see projects.migrate_legacy_if_needed).
LEGACY_STORE_PATH = DATA_DIR / "vector-store" / "vector-store.json"
LEGACY_PROSPECTUS_DIR = DATA_DIR / "prospectus"
LEGACY_FAQ_PATH = DATA_DIR / "faq-cache.json"
LEGACY_STATS_PATH = DATA_DIR / "stats.json"

# --- Embedding service (Dockerized nomic-embed-text) ---
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://localhost:8000/embed")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")

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
# Short timeout so a stalled cloud call fails over to the local model fast, instead
# of hanging the UI. Sarvam normally answers in ~5-12s.
SARVAM_TIMEOUT = int(os.environ.get("SARVAM_TIMEOUT", "45"))

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
TOP_K = int(os.environ.get("TOP_K", "10"))
CHUNK_CHARS = int(os.environ.get("CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))

# --- Admin / keys ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
DEFAULT_KEY_LABEL = "admission-site"

# --- Server ---
PORT = int(os.environ.get("PORT", "5050"))
