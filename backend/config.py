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

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_URL = os.environ.get("SARVAM_URL", "https://api.sarvam.ai/v1/chat/completions")
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-30b")
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

# --- FAQ cache ---
# Semantically-close past/seeded questions return instantly, skipping RAG + the LLM.
# A match at or above this cosine threshold is treated as the same question.
FAQ_THRESHOLD = float(os.environ.get("FAQ_THRESHOLD", "0.93"))
FAQ_AUTOCACHE = os.environ.get("FAQ_AUTOCACHE", "1") == "1"

# --- Retrieval ---
TOP_K = int(os.environ.get("TOP_K", "5"))
CHUNK_CHARS = int(os.environ.get("CHUNK_CHARS", "1200"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))

# --- Admin / keys ---
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
DEFAULT_KEY_LABEL = "admission-site"

# --- Server ---
PORT = int(os.environ.get("PORT", "5050"))
