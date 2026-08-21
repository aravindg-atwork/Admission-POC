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
import re

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


_TRANSLATE_NAMES = {"hi": "Hindi", "mr": "Marathi"}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_OFFICIAL_TOKENS = (
    "B.V.Sc.", "B.F.Sc.", "MAFSU", "NEET", "NRI", "FN", "PIO", "OCI",
    "MHT-CET", "CUET", "ICAR", "NCL",
)


def translate_to_english(text: str, source_language: str | None = None) -> str:
    """Best-effort translation for retrieval only.

    The generated answer never uses this text.  Naming the source language and
    admissions domain prevents short Marathi questions being guessed as Hindi
    (or reinterpreted as a different topic).  Non-Latin output is rejected as
    a failed translation, and all provider failures degrade to the original
    question rather than failing the student's request.
    """
    name = _TRANSLATE_NAMES.get(source_language)
    if name:
        system = (
            f"Translate this {name} question into English. It is a university "
            "admissions question. Translate literally and preserve exact intent, "
            "programme names, categories, dates, percentages and amounts. Output "
            "ONLY the translated question."
        )
    else:
        system = (
            "Translate this student question into natural English. Preserve exact "
            "intent, names and numbers. Output ONLY the translated question."
        )
    try:
        # question="" deliberately suppresses the answer-language script reminder.
        translated, _ = generate(system, text, question="", temperature=0.0)
    except Exception:  # noqa: BLE001 - translation is an optional retrieval aid
        return text
    translated = translated.strip().strip('"').strip("'")
    if not translated or detect_script(translated) != "latin":
        return text
    return translated


def localize_answer(text: str, target_language: str) -> tuple[str, str]:
    """Translate a deterministic English answer without weakening its facts.

    If the provider drops/changes a number or does not return Devanagari, the
    English original is returned.  This is intentionally a safety fallback,
    not a claim that arbitrary machine translation has native-speaker quality.
    """
    name = _TRANSLATE_NAMES.get(target_language)
    if not name:
        return text, "none"
    system = (
        f"Translate the answer into natural {name} in Devanagari. Preserve every "
        "number, percentage, date, currency amount, programme name and official "
        "English proper name exactly. Do not add or remove eligibility conditions. "
        "Keep every __KEEP_n__ placeholder exactly unchanged; it will be restored "
        "after translation. Output ONLY the translated answer."
    )
    required_numbers = re.findall(r"\d+(?:[.,]\d+)?%?", text)
    required_tokens = [token for token in _OFFICIAL_TOKENS if token in text]
    protected = text
    replacements: list[tuple[str, str]] = []
    for index, value in enumerate(sorted(set(required_tokens + required_numbers), key=len, reverse=True)):
        placeholder = f"__KEEP_{index}__"
        protected = protected.replace(value, placeholder)
        replacements.append((placeholder, value))
    # Providers occasionally ignore the requested target language while still
    # returning success. Retry a bounded number of times and accept only a
    # Devanagari result that preserves every source number.
    for _attempt in range(3):
        try:
            # The source is English; passing it as ``question`` would append an
            # English-oriented script signal and conflict with this instruction.
            localized, model = generate(system, protected, question="", temperature=0.0)
        except Exception:  # noqa: BLE001
            continue
        if any(placeholder not in localized for placeholder, _ in replacements):
            continue
        for placeholder, value in replacements:
            localized = localized.replace(placeholder, value)
        # Marathi/Hindi generation sometimes renders otherwise-correct source
        # figures with Devanagari digits. Normalize only the digit glyphs back
        # to their source ASCII form before applying the exact-number check.
        localized = localized.translate(_DEVANAGARI_DIGITS)
        if (
            detect_script(localized) == "devanagari"
            and all(n in localized for n in required_numbers)
            and all(token in localized for token in required_tokens)
        ):
            return localized, model
    return text, "translation-fallback"
