"""Central configuration for the Admission Assistant backend.

Pure standard-library Python so it runs directly on the Windows host without any
compiled dependencies (this machine's Application Control policy blocks freshly
built native binaries such as pydantic-core). The heavy ML pieces - embeddings
and Indic TTS - live in Docker containers this backend calls over HTTP.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORE_PATH = DATA_DIR / "vector-store" / "vector-store.json"
KEYS_PATH = DATA_DIR / "api-keys.json"
PROSPECTUS_DIR = DATA_DIR / "prospectus"
STATIC_DIR = Path(__file__).resolve().parent / "static"

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
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-m")

# --- Indic TTS service (Dockerized AI4Bharat) ---
TTS_URL = os.environ.get("TTS_URL", "http://localhost:8001/tts")

# --- FAQ cache ---
# Semantically-close past/seeded questions return instantly, skipping RAG + the LLM.
# A match at or above this cosine threshold is treated as the same question.
FAQ_PATH = DATA_DIR / "faq-cache.json"
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
