"""Chat generation: Mistral primary, NVIDIA fallback - the same provider
pair backend/generation/providers.py uses today, ported onto httpx instead
of urllib (a transport change, not a logic change) and with the
Sarvam-specific daily-spend-cap bookkeeping deliberately dropped - Sarvam
has been dead (HTTP 402, no credits) for the entire life of the original
project per its own CLAUDE.md, and porting live logic that guards a dead
provider would be carrying forward cruft, not a lesson. If a real per-
provider spend cap is needed later, it belongs in the unified gateway the
platform architecture doc describes, backed by Redis - not resurrected
here as dead Sarvam-shaped code.

What IS ported, because it's a real, measured lesson: only retry a FAST
failure (an HTTP error, a connection refused), never a genuine timeout - a
timeout already consumed its full attempt budget once, and retrying
identically just pays that budget again for no better odds. This is what
backend/generation/llm.py's `_is_timeout` exists for, and it's the fix
behind that project's own documented P95/P99 latency win.
"""

import httpx

from ..core.lang import detect_script
from ..settings import get_settings

_settings = get_settings()

LANGUAGE_RULE = (
    "IMPORTANT: Reply in the SAME language AND script the student used. If they wrote "
    "in Devanagari, reply in Devanagari (do NOT romanize Hindi into Latin/Hinglish); "
    "English to English. Write the way people actually speak that language, keeping "
    "common English loanwords they used (like 'document', 'application', 'college') "
    "as-is in their script instead of forcing a formal translation. Official names - "
    "the university's full name, government scheme names, portal/website names - must "
    "be kept in their original English form exactly as they appear in the source "
    "material, never phonetically rendered or translated into another script. Never "
    "switch to a different language or script than the student used, and never answer "
    "a real question with only a greeting."
)

_SCRIPT_REMINDER = {
    "devanagari": "\n\n(Reply in Hindi/Marathi, using Devanagari script, matching the question above - not in English.)",
}


def _messages(system_prompt: str, user_prompt: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _clean(text: str | None) -> str:
    return (text or "").strip()


def _is_timeout(exc: Exception) -> bool:
    """A genuine attempt-timed-out failure, as opposed to a fast one (HTTP
    error, connection refused). httpx raises a distinct TimeoutException
    family - simpler to check than urllib's URLError-wrapped socket.timeout
    the original had to unwrap, but the same underlying distinction.
    """
    return isinstance(exc, httpx.TimeoutException)


def _call_mistral(system_prompt: str, user_prompt: str, question: str,
                   timeout: float, temperature: float | None) -> tuple[str, str]:
    model = _settings.mistral_model
    user_prompt = user_prompt + _SCRIPT_REMINDER.get(detect_script(question), "")
    resp = httpx.post(
        _settings.mistral_url.rstrip("/") + "/chat/completions",
        json={
            "model": model,
            "temperature": _settings.chat_temperature if temperature is None else temperature,
            "max_tokens": _settings.mistral_max_tokens,
            "messages": _messages(system_prompt, user_prompt),
        },
        headers={"Authorization": f"Bearer {_settings.mistral_api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    answer = _clean(resp.json()["choices"][0]["message"].get("content"))
    if not answer:
        raise ValueError("mistral returned no answer content")
    return answer, f"mistral:{model}"


def _call_nvidia(system_prompt: str, user_prompt: str, question: str,
                  timeout: float, temperature: float | None) -> tuple[str, str]:
    model = _settings.nvidia_fast_model
    user_prompt = user_prompt + _SCRIPT_REMINDER.get(detect_script(question), "")
    resp = httpx.post(
        _settings.nvidia_url.rstrip("/") + "/chat/completions",
        json={
            "model": model,
            "temperature": _settings.chat_temperature if temperature is None else temperature,
            "max_tokens": _settings.nvidia_max_tokens,
            "messages": _messages(system_prompt, user_prompt),
        },
        headers={"Authorization": f"Bearer {_settings.nvidia_api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    answer = _clean(resp.json()["choices"][0]["message"].get("content"))
    if not answer:
        raise ValueError("nvidia returned no answer content (reasoning hit the token cap)")
    return answer, f"nvidia:{model}"


def generate(system_prompt: str, user_prompt: str, question: str = "",
             timeout: float = 60, temperature: float | None = None) -> tuple[str, str]:
    """Generate an answer, returning (answer_text, model_label). Tries
    Mistral first; on failure, NVIDIA. A fast failure on Mistral gets one
    retry before falling back (the reasoning-token-ceiling shape); a
    genuine timeout does not, and falls back immediately.
    """
    call_timeout = min(timeout, _settings.cloud_attempt_timeout)
    if _settings.mistral_api_key:
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                return _call_mistral(system_prompt, user_prompt, question, call_timeout, temperature)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == 2 or _is_timeout(exc):
                    break
                print(f"[llm] mistral attempt 1 failed ({exc!r}); retrying once")
        print(f"[llm] mistral failed, falling back to nvidia: {last_exc!r}")

    if not _settings.nvidia_api_key:
        raise RuntimeError("No usable chat provider: mistral and nvidia both unconfigured")
    return _call_nvidia(system_prompt, user_prompt, question,
                        min(timeout, _settings.cloud_attempt_timeout), temperature)
