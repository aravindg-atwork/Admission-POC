"""Typed configuration, loaded from environment variables (and a .env file
in local/dev, via pydantic-settings). This is the direct replacement for
backend/config.py's plain os.environ.get() calls - the difference is every
value here is typed and validated at process start, so a missing or
malformed setting fails loudly at startup instead of surfacing as a
confusing runtime error three layers deep the first time it's actually used.

Values below are ported from backend/config.py's own defaults/reasoning
where a matching setting exists there - see that file's comments for the
measurement behind e.g. MAX_CHUNK_CHARS or CLOUD_ATTEMPT_TIMEOUT. Not a
1:1 copy of every setting backend/config.py has - only what this phase's
ported modules actually read (see each setting's own comment for which
module uses it).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Service ---
    service_name: str = "admission-assistant-api"
    environment: str = "local"
    admin_api_key: str = ""
    admin_require_two_person_high_risk: bool = False
    conversation_retention_days: int = 90
    retention_poll_hours: int = 24
    cors_origins: str = "http://159.69.210.30,http://localhost:5180,http://127.0.0.1:5180,null"
    chat_rate_limit_per_minute: int = 30
    max_request_bytes: int = 16384

    # --- Postgres ---
    postgres_dsn: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"

    # --- Redis (ephemeral state only - session, rate limits; never durable data) ---
    redis_url: str = "redis://localhost:6380/0"
    redis_operation_timeout_seconds: float = 1.0
    faq_cache_enabled: bool = True
    faq_cache_ttl_seconds: int = 86400
    # Increment when prospectus content or deterministic policy changes.
    # Including this revision in every key makes invalidation atomic.
    faq_cache_revision: str = "2026-08-21-v14"
    cache_fill_lock_seconds: int = 120
    cache_fill_wait_seconds: int = 55
    semantic_faq_enabled: bool = True
    semantic_faq_threshold: float = 0.965
    semantic_faq_max_entries_per_project: int = 2000

    # --- Qdrant ---
    qdrant_url: str = "http://localhost:6333"

    # --- Model providers - same accounts/keys as the existing POC, read from
    # the SAME .env values so nothing new needs provisioning for this slice.
    mistral_api_key: str = ""
    mistral_url: str = "https://api.mistral.ai/v1"
    mistral_model: str = "mistral-small-latest"
    mistral_max_tokens: int = 1500

    nvidia_api_key: str = ""
    nvidia_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_fast_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_max_tokens: int = 4096

    # An extraction task (quote the right figure) has one right answer, not
    # a creative-writing one - see backend/config.py's CHAT_TEMPERATURE for
    # the measured reasoning (the same question answered differently between
    # runs at the API default of ~1.0).
    chat_temperature: float = 0.2
    # Bounds ONE cloud attempt, so a stalled call fails over instead of
    # hanging the student's request - ported value, see backend/config.py's
    # CLOUD_ATTEMPT_TIMEOUT.
    cloud_attempt_timeout: int = 45
    provider_max_concurrency: int = 4
    provider_queue_wait_seconds: int = 8
    provider_rate_limit_cooldown_seconds: int = 120
    provider_error_cooldown_seconds: int = 20
    provider_daily_call_budget: int = 500

    # Optional self-hosted shadow reviewer. It never participates in the
    # student response path and cannot publish curated answers.
    qwen_review_enabled: bool = False
    qwen_review_url: str = ""
    qwen_review_api_key: str = ""
    qwen_review_model: str = "qwen2.5:7b-instruct"
    qwen_review_timeout_seconds: int = 90
    qwen_review_poll_seconds: int = 5

    selfhosted_url: str = "http://127.0.0.1:8000"
    selfhosted_api_key: str = ""
    selfhosted_embedding_model: str = "bge-m3"
    embedding_query_timeout: int = 15
    embedding_ingest_timeout: int = 600

    # --- Ingestion (see app/ingestion/) ---
    chunk_chars: int = 1200
    chunk_overlap: int = 200
    # The embedding service refuses a single input between 5,000 and 6,000
    # chars - measured directly by the original project, not guessed (see
    # backend/rag/ingest.py's MAX_CHUNK_CHARS comment). 4,500 leaves headroom.
    max_chunk_chars: int = 4500
    ocr_enabled: bool = True
    ocr_model: str = "mistral-ocr-latest"
    ocr_timeout: int = 600

    # --- Retrieval ---
    top_k: int = 15
    # Deliberately conservative and unmeasured on THIS system yet - see
    # backend/config.py's RETRIEVAL_CONFIDENCE_FLOOR comment for why this
    # number specifically is a starting point, not a tuned value.
    retrieval_confidence_floor: float = 0.30

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    # Cached: Settings() re-parses the environment/`.env` file on every call
    # otherwise, which is wasted work for values that never change during a
    # process's lifetime - same reasoning as vectorstore.py's mtime-keyed
    # cache in the existing POC, just for config instead of a data file.
    return Settings()
