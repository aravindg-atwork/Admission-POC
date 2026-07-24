"""Chat generation: Sarvam cloud for all languages online, one local model offline.

sarvam-m (24B) is strong at English and Hindi/Marathi/Tamil alike, so when a Sarvam
key is configured it handles every language - fast, cloud-side, high quality. When
there's no key or the cloud call fails, a single small local model (gemma2:2b) covers
all languages offline at lower quality. No per-language model split is needed.

Language detection still happens elsewhere (for TTS voice and labeling), just not for
picking the chat model.
"""

import json
import urllib.error
import urllib.request

from . import config

LANGUAGE_RULE = (
    "IMPORTANT: Reply in the SAME language and script the student used. Tamil to "
    "Tamil, Hindi to Hindi, Marathi to Marathi, English to English. Write the way "
    "people actually speak that language, keeping common English loanwords they used "
    "(like 'document', 'application', 'college') as-is in their script instead of "
    "forcing a formal translation. Never switch to a different language than the "
    "student used, and never answer a real question with only a greeting."
)

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


def _ollama_chat(system_prompt, user_prompt, timeout, model=None):
    model = model or config.MODEL_LOCAL
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


def generate(system_prompt, user_prompt, question, timeout=280):
    """Generate an answer and return (answer_text, model_label).

    `question` is accepted for interface stability (language routing hook) but no
    longer selects the model - one model serves all languages.
    """
    if config.SARVAM_API_KEY:
        try:
            return _sarvam_chat(system_prompt, user_prompt, timeout)
        except Exception:  # noqa: BLE001 - cloud down/misconfigured -> local fallback
            return _ollama_chat(system_prompt, user_prompt, timeout)
    return _ollama_chat(system_prompt, user_prompt, timeout)
