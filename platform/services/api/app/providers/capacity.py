"""Shared provider concurrency and circuit-breaker controls backed by Redis."""

from contextlib import contextmanager
import time
import uuid

import httpx
from redis import Redis

from ..settings import get_settings
from ..storage import telemetry

_settings = get_settings()
_client: Redis | None = None


class ProviderBusyError(RuntimeError):
    pass


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(_settings.redis_url, decode_responses=True)
    return _client


def available(provider: str) -> bool:
    try:
        return not bool(_redis().exists(f"provider:circuit:{provider}"))
    except Exception:
        return True


def record_success(provider: str) -> None:
    telemetry.increment("provider.calls")
    telemetry.increment(f"provider.{provider}.success")
    try:
        _redis().delete(f"provider:circuit:{provider}")
    except Exception:
        pass


def record_usage(provider: str, usage: dict) -> None:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    telemetry.increment(f"provider.{provider}.prompt_tokens", prompt)
    telemetry.increment(f"provider.{provider}.completion_tokens", completion)
    telemetry.increment("provider.tokens", prompt + completion)


def record_failure(provider: str, exc: Exception) -> None:
    telemetry.increment("provider.calls")
    telemetry.increment("provider.failures")
    telemetry.increment(f"provider.{provider}.failure")
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    if status == 429:
        telemetry.increment("provider.rate_limits")
        cooldown = _settings.provider_rate_limit_cooldown_seconds
    elif status is not None and status < 500 and status not in (401, 403):
        return
    else:
        cooldown = _settings.provider_error_cooldown_seconds
    try:
        _redis().setex(f"provider:circuit:{provider}", cooldown, str(status or type(exc).__name__))
    except Exception:
        pass


@contextmanager
def provider_slot():
    """Bound total cloud calls across all API replicas; fail open if Redis fails."""
    token = uuid.uuid4().hex
    key = "provider:active-slots"
    acquired = False
    deadline = time.monotonic() + _settings.provider_queue_wait_seconds
    script = """
    redis.call('zremrangebyscore', KEYS[1], '-inf', ARGV[1])
    if redis.call('zcard', KEYS[1]) < tonumber(ARGV[2]) then
      redis.call('zadd', KEYS[1], ARGV[3], ARGV[4])
      redis.call('expire', KEYS[1], ARGV[5])
      return 1
    end
    return 0
    """
    try:
        while time.monotonic() < deadline:
            now = time.time()
            expiry = now + _settings.cloud_attempt_timeout + 15
            if _redis().eval(
                script, 1, key, now, _settings.provider_max_concurrency,
                expiry, token, _settings.cloud_attempt_timeout + 30,
            ):
                acquired = True
                break
            time.sleep(0.1)
        if not acquired:
            raise ProviderBusyError("All provider slots are busy")
    except ProviderBusyError:
        raise
    except Exception as exc:
        print(f"[provider-capacity] Redis unavailable; capacity gate failed open: {exc!r}")
    try:
        yield
    finally:
        if acquired:
            try:
                _redis().zrem(key, token)
            except Exception:
                pass
