"""Chat generation: Sarvam cloud for all languages online, one local model offline.

sarvam-m (24B) is strong at English and Hindi/Marathi/Tamil alike, so when a Sarvam
key is configured it handles every language - fast, cloud-side, high quality. When
there's no key or the cloud call fails, a single small local model (gemma2:2b) covers
all languages offline at lower quality. No per-language model split is needed.

Language detection still happens elsewhere (for TTS voice and labeling), just not for
picking the chat model.
"""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config
from .lang import detect_script

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

# gemma2:2b (the local fallback) reliably ignores the system-prompt language rule for
# Indic questions and answers in English instead - verified 3/3 in testing. Repeating
# the instruction at the end of the user turn (recency, not just system prompt) fixed
# it 3/3 in the same test. Sarvam doesn't need this, so it's only applied to the local
# path to keep the primary path's prompt untouched.
_SCRIPT_REMINDER = {
    "devanagari": "\n\n(Reply in Hindi/Marathi, using Devanagari script, matching the question above - not in English.)",
    "tamil": "\n\n(Reply in Tamil, using Tamil script, matching the question above - not in English.)",
}

_END_TOKENS = ("</s>", "<|im_end|>", "<end_of_turn>", "<eos>")


def _clean(text):
    for tok in _END_TOKENS:
        text = text.replace(tok, "")
    return text.strip()


def _post(url, payload, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _messages(system_prompt, user_prompt):
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _sarvam_chat(system_prompt, user_prompt, timeout):
    payload = {"model": config.SARVAM_MODEL, "messages": _messages(system_prompt, user_prompt)}
    headers = {"api-subscription-key": config.SARVAM_API_KEY}
    result = _post(config.SARVAM_URL, payload, headers, timeout)
    return _clean(result["choices"][0]["message"]["content"]), "sarvam:" + config.SARVAM_MODEL


def _ollama_chat(system_prompt, user_prompt, timeout, model=None, question=""):
    model = model or config.MODEL_LOCAL
    user_prompt += _SCRIPT_REMINDER.get(detect_script(question), "")
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "messages": _messages(system_prompt, user_prompt),
    }
    url = config.OLLAMA_URL.rstrip("/") + "/api/chat"
    try:
        result = _post(url, payload, {}, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and model != config.MODEL_FALLBACK:
            payload["model"] = config.MODEL_FALLBACK
            result = _post(url, payload, {}, timeout)
        else:
            raise
    return _clean(result["message"]["content"]), model


def generate(system_prompt, user_prompt, question, timeout=280, allow_cloud=True):
    """Generate an answer and return (answer_text, model_label).

    `question` is accepted for interface stability (language routing hook) but no
    longer selects the model - one model serves all languages. `allow_cloud` is the
    per-project switch (projects.allow_cloud) - when False this project never calls
    Sarvam at all, independent of the key or the account-wide daily cap.
    """
    if allow_cloud and config.SARVAM_API_KEY and _sarvam_under_cap():
        try:
            # Short timeout: if the cloud stalls, fail over to local instead of hanging.
            result = _sarvam_chat(system_prompt, user_prompt, min(timeout, config.SARVAM_TIMEOUT))
            _record_sarvam_call()
            return result
        except Exception:  # noqa: BLE001 - cloud down/misconfigured -> local fallback
            return _ollama_chat(system_prompt, user_prompt, timeout, question=question)
    # No key, cap reached, or this project has cloud disabled -> stay local.
    return _ollama_chat(system_prompt, user_prompt, timeout, question=question)


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
    reminder _ollama_chat adds for answer generation, which would otherwise
    contradict a translate-to-English instruction. Falls back to the original text
    on any failure - a missed translation should degrade retrieval quality, not
    break the request.
    """
    try:
        reply, _ = generate(_TRANSLATE_SYSTEM, text, "", timeout=30, allow_cloud=False)
        reply = reply.strip().strip('"')
        return reply or text
    except Exception:  # noqa: BLE001
        return text
