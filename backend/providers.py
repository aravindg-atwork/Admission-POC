"""Pluggable chat backends, selected by config rather than hard-wired.

The provider choice is genuinely unsettled: Sarvam is capped on the current tier
(150 calls/day, 4096 max_tokens) which does not survive an admission window, and
Bhashini is a live alternative with a completely different shape - it translates
rather than generates, so it would pair an English chat model with a translation
step instead of replacing the chat model outright. Committing the codebase to one
vendor before that is decided would mean rewriting the call path twice.

Each provider exposes the same tiny surface:

    configured()                     -> bool   is this usable right now
    chat(system, user, timeout, **kw) -> (answer_text, model_label)

Policy - daily caps, retries, which provider is primary and which is the
fallback - deliberately lives in llm.py, not here. Providers stay thin so a new
one is a single small class, and so the accuracy/cost tradeoffs stay in one
place where they can be reasoned about together.

Adding a Bhashini-backed path (not written here, since it should not ship
untested against a real endpoint) means one class implementing the same two
methods: translate the question to English, delegate to an English chat
provider, translate the answer back. The `question` kwarg already carries the
original text needed for that.
"""

import json
import urllib.error
import urllib.request

from . import config
from .lang import detect_script

_END_TOKENS = ("</s>", "<|im_end|>", "<end_of_turn>", "<eos>")

# gemma2:2b (the local fallback) reliably ignores the system-prompt language rule
# for Indic questions and answers in English instead - verified 3/3 in testing.
# Repeating the instruction at the end of the user turn (recency, not just system
# prompt) fixed it 3/3 in the same test. Cloud models don't need this, so it is
# applied only on the local path to keep the primary prompt untouched.
_SCRIPT_REMINDER = {
    "devanagari": "\n\n(Reply in Hindi/Marathi, using Devanagari script, matching the question above - not in English.)",
    "tamil": "\n\n(Reply in Tamil, using Tamil script, matching the question above - not in English.)",
}


def clean(text):
    # `content` comes back None when a reasoning model spends its entire token
    # budget thinking and never starts the visible answer. Guarding here keeps
    # that from surfacing as an AttributeError deep in the call.
    for token in _END_TOKENS:
        text = (text or "").replace(token, "")
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


class SarvamProvider:
    """Sarvam AI cloud chat (sarvam-30b), strong across English and Indic."""

    name = "sarvam"
    is_cloud = True

    # sarvam-30b is a REASONING model: it emits chain-of-thought into a separate
    # `reasoning_content` field, and those tokens are billed against the same
    # completion budget as the visible answer. Measured: "What is 2+2?" burned
    # 527 completion tokens to produce 13 characters of content. So max_tokens is
    # mostly a reasoning budget, not an answer-length budget - an intuitive
    # looking 1024 truncated real answers mid-sentence because reasoning consumed
    # it before the answer began. 4096 is a hard ceiling on the "starter" tier;
    # asking for more is rejected with HTTP 400, not silently clamped.
    max_tokens = 4096

    def configured(self):
        return bool(config.SARVAM_API_KEY)

    def chat(self, system_prompt, user_prompt, timeout, **_):
        payload = {"model": config.SARVAM_MODEL, "max_tokens": self.max_tokens,
                   "temperature": config.CHAT_TEMPERATURE,
                   "messages": _messages(system_prompt, user_prompt)}
        headers = {"api-subscription-key": config.SARVAM_API_KEY}
        result = _post(config.SARVAM_URL, payload, headers, timeout)
        answer = clean(result["choices"][0]["message"]["content"])
        if not answer:
            # Reasoning ran to the token ceiling without producing an answer.
            # Raise so the caller's fallback path handles it deliberately -
            # previously the None content crashed inside clean(), which *looked*
            # like a network failure in the logs and quietly handed hard
            # questions (exactly the fee-table ones) to the weaker local model.
            raise ValueError("Sarvam returned no answer content (reasoning hit the token cap)")
        return answer, "sarvam:" + config.SARVAM_MODEL


def _ollama_options():
    """Sampling options for Ollama, which nests them under "options" rather than
    accepting them at the top level like the OpenAI-shaped API - a top-level
    temperature here is silently ignored, not rejected.
    """
    options = {"temperature": config.CHAT_TEMPERATURE}
    if config.OLLAMA_SEED:
        options["seed"] = config.OLLAMA_SEED
    return options


class OllamaProvider:
    """Locally hosted model via Ollama - free, private, and slower."""

    name = "ollama"
    is_cloud = False

    def configured(self):
        return bool(config.OLLAMA_URL)

    def chat(self, system_prompt, user_prompt, timeout, question="", model=None, **_):
        model = model or config.MODEL_LOCAL
        user_prompt += _SCRIPT_REMINDER.get(detect_script(question), "")
        payload = {
            "model": model,
            "stream": False,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            # Ollama nests sampling settings under "options", unlike the
            # OpenAI-shaped payload Sarvam takes - a top-level "temperature" is
            # silently ignored here rather than rejected, so it would look set
            # while the model kept running at its 0.8 default.
            "options": _ollama_options(),
            "messages": _messages(system_prompt, user_prompt),
        }
        url = config.OLLAMA_URL.rstrip("/") + "/api/chat"
        try:
            result = _post(url, payload, {}, timeout)
        except urllib.error.HTTPError as exc:
            # A missing model is a config problem, not a dead service - try the
            # configured fallback once before surfacing the error.
            if exc.code == 404 and model != config.MODEL_FALLBACK:
                payload["model"] = config.MODEL_FALLBACK
                result = _post(url, payload, {}, timeout)
                return clean(result["message"]["content"]), config.MODEL_FALLBACK
            raise
        return clean(result["message"]["content"]), model


_REGISTRY = {p.name: p for p in (SarvamProvider(), OllamaProvider())}


def get(name):
    """Provider by name, or None if unknown - callers fall back rather than crash."""
    return _REGISTRY.get((name or "").strip().lower())


def available():
    return sorted(_REGISTRY)
