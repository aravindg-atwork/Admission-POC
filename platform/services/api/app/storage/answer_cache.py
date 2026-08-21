"""Exact-question Redis cache for already validated admission answers.

This cache never performs semantic matching: near-looking admission questions
can differ on one decisive fact. Keys include programme, UI language, and an
operator-controlled source revision so programme/language answers cannot leak
and a prospectus promotion invalidates old entries without a destructive scan.
"""

from hashlib import sha256
import json
import re
import time
import uuid

from redis import Redis

from ..settings import get_settings


_settings = get_settings()
_client: Redis | None = None
_SPACE_RE = re.compile(r"\s+")
_UNSAFE_SOURCES = {"provider-unavailable", "service-unavailable", "provider-busy", "low-confidence", "validation-blocked", "no-context"}


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            _settings.redis_url, decode_responses=True,
            socket_connect_timeout=_settings.redis_operation_timeout_seconds,
            socket_timeout=_settings.redis_operation_timeout_seconds,
        )
    return _client


def _key(project_id: str, question: str, ui_language: str) -> str:
    normalized = _SPACE_RE.sub(" ", question.strip()).casefold()
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    return f"answer:{_settings.faq_cache_revision}:{project_id}:{ui_language}:{digest}"


def _lock_key(project_id: str, question: str, ui_language: str) -> str:
    return "fill-lock:" + _key(project_id, question, ui_language)


def acquire_fill_lock(project_id: str, question: str, ui_language: str = "en") -> str | None:
    """Own one distributed cache fill, preventing identical-request stampedes."""
    token = uuid.uuid4().hex
    try:
        acquired = _redis().set(
            _lock_key(project_id, question, ui_language), token,
            nx=True, ex=_settings.cache_fill_lock_seconds,
        )
        return token if acquired else None
    except Exception as exc:
        print(f"[answer-cache] fill-lock acquire failed: {exc!r}")
        return token  # fail open: Redis trouble must not disable answering


def release_fill_lock(project_id: str, question: str, token: str,
                      ui_language: str = "en") -> None:
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """
    try:
        _redis().eval(script, 1, _lock_key(project_id, question, ui_language), token)
    except Exception as exc:
        print(f"[answer-cache] fill-lock release failed: {exc!r}")


def wait_for_fill(project_id: str, question: str, ui_language: str = "en") -> dict | None:
    deadline = time.monotonic() + _settings.cache_fill_wait_seconds
    while time.monotonic() < deadline:
        cached = get(project_id, question, ui_language)
        if cached is not None:
            return cached
        try:
            if not _redis().exists(_lock_key(project_id, question, ui_language)):
                return None
        except Exception:
            return None
        time.sleep(0.15)
    return None


def get(project_id: str, question: str, ui_language: str = "en") -> dict | None:
    if not _settings.faq_cache_enabled:
        return None
    try:
        raw = _redis().get(_key(project_id, question, ui_language))
        if not raw:
            return None
        result = json.loads(raw)
        result["cacheHit"] = True
        return result
    except Exception as exc:  # cache failure must never block admission answers
        print(f"[answer-cache] read failed: {exc!r}")
        return None


def put(project_id: str, question: str, result: dict, ui_language: str = "en") -> bool:
    if (
        not _settings.faq_cache_enabled
        or result.get("source") in _UNSAFE_SOURCES
        or result.get("interviewField")
        or result.get("carryQuestion")
    ):
        return False
    payload = {**result, "cacheHit": False}
    try:
        _redis().setex(
            _key(project_id, question, ui_language),
            _settings.faq_cache_ttl_seconds,
            json.dumps(payload, ensure_ascii=False),
        )
        return True
    except Exception as exc:
        print(f"[answer-cache] write failed: {exc!r}")
        return False


def invalidate(project_id: str, question: str, ui_language: str = "en") -> bool:
    try:
        return bool(_redis().delete(_key(project_id, question, ui_language)))
    except Exception as exc:
        print(f"[answer-cache] invalidate failed: {exc!r}")
        return False
