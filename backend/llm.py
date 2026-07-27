"""Chat orchestration: pick a provider, apply spend policy, fall back on failure.

The providers themselves live in providers.py; this module owns the decisions
*around* them - which one is primary, when a cloud call is allowed, the daily
spend cap, and what happens when the primary fails. Keeping policy here means
swapping vendors is a config change, not a code change, which matters because
the vendor choice is still open (Sarvam is capped on the current tier; Bhashini
is a live alternative with a different shape).

Language detection still happens elsewhere (for TTS voice and labeling), not for
picking the chat model - one provider serves all languages.
"""

import json
import threading
from datetime import datetime, timezone

from . import config, providers

_usage_lock = threading.Lock()


def _sarvam_calls_today():
    """Return how many Sarvam calls have been made today (UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        data = json.loads(config.SARVAM_USAGE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return today, 0
    return (today, data.get("count", 0)) if data.get("date") == today else (today, 0)


def _record_sarvam_call():
    with _usage_lock:
        today, count = _sarvam_calls_today()
        config.SARVAM_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.SARVAM_USAGE_PATH.write_text(
            json.dumps({"date": today, "count": count + 1}), encoding="utf-8")


def _sarvam_under_cap():
    """False once today's Sarvam calls hit the daily limit (charge safety)."""
    _, count = _sarvam_calls_today()
    return count < config.SARVAM_DAILY_LIMIT


def sarvam_usage():
    """Public snapshot for the console's Cost panel: {date, count, limit, configured}."""
    date, count = _sarvam_calls_today()
    return {"date": date, "count": count, "limit": config.SARVAM_DAILY_LIMIT,
            "configured": bool(config.SARVAM_API_KEY)}

LANGUAGE_RULE = (
    "IMPORTANT: Reply in the SAME language AND script the student used. If they wrote "
    "in Devanagari, reply in Devanagari (do NOT romanize Hindi into Latin/Hinglish); "
    "Tamil to Tamil script; English to English. Write the way people actually speak "
    "that language, keeping common English loanwords they used (like 'document', "
    "'application', 'college') as-is in their script instead of forcing a formal "
    "translation. Never switch to a different language or script than the student "
    "used, and never answer a real question with only a greeting."
)

def _usable(provider, allow_cloud):
    """Whether this provider may be called for this request.

    Cloud providers carry two extra gates that local ones don't: the per-project
    `allow_cloud` switch, and the account-wide daily spend cap.
    """
    if provider is None or not provider.configured():
        return False
    if provider.is_cloud and (not allow_cloud or not _sarvam_under_cap()):
        return False
    return True


def generate(system_prompt, user_prompt, question, timeout=280, allow_cloud=True):
    """Generate an answer and return (answer_text, model_label).

    Tries the configured primary provider, then the fallback. Which providers
    those are is config, not code (see config.CHAT_PRIMARY / CHAT_FALLBACK), so
    the Sarvam-vs-local-vs-Bhashini decision can be made and A/B tested without
    touching this call path.

    `allow_cloud` is the per-project switch (projects.allow_cloud) - when False
    this project never calls a cloud provider, independent of any key or cap.
    """
    primary = providers.get(config.CHAT_PRIMARY)
    fallback = providers.get(config.CHAT_FALLBACK)

    if _usable(primary, allow_cloud):
        try:
            # Two attempts before giving up on the cloud. How many tokens the
            # reasoning pass burns varies run to run, so a hard question can
            # exhaust the 4096 ceiling once and complete fine on a retry. Worth
            # one extra call: the local fallback is markedly worse at exactly
            # these questions (it misread the hostel fee grid every time), so
            # silently dropping to it costs accuracy where it matters most.
            call_timeout = min(timeout, config.SARVAM_TIMEOUT) if primary.is_cloud else timeout
            for attempt in (1, 2):
                try:
                    result = primary.chat(system_prompt, user_prompt, call_timeout,
                                          question=question)
                    if primary.is_cloud:
                        _record_sarvam_call()
                    return result
                except Exception as exc:  # noqa: BLE001
                    if primary.is_cloud:
                        _record_sarvam_call()  # a truncated attempt still bills
                    if attempt == 2:
                        raise
                    print(f"[llm] {primary.name} attempt 1 failed ({exc!r}); retrying once")
        except Exception as exc:  # noqa: BLE001 - primary down/misconfigured -> fallback
            # This used to be silent - a failed Sarvam call would fall back to
            # gemma2:2b with zero trace of why, making a run of poor-quality local
            # answers (seen in testing: garbled Hindi, a misspelled loanword) look
            # like a model-quality mystery instead of what it was - Sarvam calls
            # quietly timing out/erroring under load. Print, not raise: the
            # fallback itself should still succeed for the student.
            print(f"[llm] {primary.name} failed, falling back to "
                  f"{fallback.name if fallback else 'nothing'}: {exc!r}")

    # Primary unavailable (no key, cap reached, cloud disabled) or it failed.
    if not _usable(fallback, allow_cloud):
        raise RuntimeError(
            f"No usable chat provider: primary={config.CHAT_PRIMARY!r} "
            f"fallback={config.CHAT_FALLBACK!r} (known: {providers.available()})")
    result = fallback.chat(system_prompt, user_prompt, timeout, question=question)
    if fallback.is_cloud:
        _record_sarvam_call()
    return result


_TRANSLATE_SYSTEM = (
    "Translate the following student question into natural English. Output ONLY "
    "the translated question - no quotes, no explanation, no commentary."
)


def translate_to_english(text):
    """Best-effort English translation, used only to make cross-lingual retrieval
    work (nomic-embed-text doesn't align Hindi/Tamil and English closely enough for
    a native-script question to reliably retrieve the right English prospectus
    chunks - verified: a Hindi fee question missed chunks an equivalent English one
    found). Never used for the answer itself, only for the retrieval-side embedding.

    Deliberately always local (allow_cloud=False), never Sarvam: Sarvam-30b has the
    same hard same-language-as-input bias that broke Hinglish generation - tested
    with several prompt phrasings and it just echoes the Hindi/Tamil text back
    instead of translating, no matter the instruction. gemma2:2b has no such bias
    and translated correctly on the first try, so there's no reason to spend a
    Sarvam call (or fight its bias) for this.

    `question=""` in the generate() call suppresses the reply-in-native-script
    reminder the Ollama provider appends for answer generation, which would
    otherwise contradict a translate-to-English instruction. Falls back to the
    original text on any failure - a missed translation should degrade retrieval
    quality, not break the request.

    (This is also the natural seam for Bhashini: a translation provider would
    replace this function's body, leaving every caller untouched.)
    """
    try:
        reply, _ = generate(_TRANSLATE_SYSTEM, text, "", timeout=30, allow_cloud=False)
        reply = reply.strip().strip('"')
        return reply or text
    except Exception:  # noqa: BLE001
        return text
