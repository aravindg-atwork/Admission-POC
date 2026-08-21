"""Low-overhead operational counters; no student question content is stored."""

from datetime import datetime, timezone

from redis import Redis

from ..settings import get_settings

_settings = get_settings()
_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(_settings.redis_url, decode_responses=True)
    return _client


def increment(name: str, amount: int = 1) -> None:
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pipe = _redis().pipeline()
        pipe.hincrby(f"metrics:{day}", name, amount)
        pipe.expire(f"metrics:{day}", 90 * 86400)
        pipe.execute()
    except Exception:
        pass


def record_chat(project_id: str, result: dict, elapsed_ms: int) -> None:
    source = str(result.get("source") or "unknown")
    increment("chat.requests")
    increment(f"chat.project.{project_id}")
    increment(f"chat.source.{source}")
    increment("chat.cache_hit", int(bool(result.get("cacheHit"))))
    increment("chat.latency_ms_total", max(0, elapsed_ms))
    increment("chat.latency_over_10s", int(elapsed_ms >= 10_000))


def snapshot() -> dict:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        raw = {key: int(value) for key, value in _redis().hgetall(f"metrics:{day}").items()}
    except Exception:
        raw = {}
    requests = raw.get("chat.requests", 0)
    return {
        "date": day,
        "requests": requests,
        "cacheHits": raw.get("chat.cache_hit", 0),
        "cacheHitRate": round(raw.get("chat.cache_hit", 0) / requests, 4) if requests else 0,
        "averageLatencyMs": round(raw.get("chat.latency_ms_total", 0) / requests) if requests else 0,
        "slowRequests": raw.get("chat.latency_over_10s", 0),
        "providerCalls": raw.get("provider.calls", 0),
        "providerFailures": raw.get("provider.failures", 0),
        "providerRateLimits": raw.get("provider.rate_limits", 0),
        "providerTokens": raw.get("provider.tokens", 0),
        "providerBudgetUsed": round(raw.get("provider.calls", 0) / _settings.provider_daily_call_budget, 4) if _settings.provider_daily_call_budget else 0,
        "semanticHits": raw.get("chat.source.semantic-cache", 0),
        "byProject": {name: raw.get(f"chat.project.{name}", 0) for name in ("bvsc", "bfsc", "btech-dairy")},
    }
