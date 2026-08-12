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

    def chat(self, system_prompt, user_prompt, timeout, temperature=None, **_):
        payload = {"model": config.SARVAM_MODEL, "max_tokens": self.max_tokens,
                   "temperature": config.CHAT_TEMPERATURE if temperature is None else temperature,
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


def _ollama_options(temperature=None):
    """Sampling options for Ollama, which nests them under "options" rather than
    accepting them at the top level like the OpenAI-shaped API - a top-level
    temperature here is silently ignored, not rejected.
    """
    options = {"temperature": config.CHAT_TEMPERATURE if temperature is None else temperature}
    if config.OLLAMA_SEED:
        options["seed"] = config.OLLAMA_SEED
    return options


class OllamaProvider:
    """Locally hosted model via Ollama - free, private, and slower."""

    name = "ollama"
    is_cloud = False

    def configured(self):
        return bool(config.OLLAMA_URL)

    def chat(self, system_prompt, user_prompt, timeout, question="", model=None, temperature=None, **_):
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
            "options": _ollama_options(temperature),
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


class SelfHostedProvider:
    """Team-run OpenAI-shaped server exposing several small/mid models.

    is_cloud = False deliberately: _usable() in llm.py gates any is_cloud
    provider behind the per-project allow_cloud switch AND Sarvam's own daily
    call cap (_sarvam_under_cap), which is Sarvam-specific bookkeeping that
    has nothing to do with this server. Treating it as "local" policy-wise -
    same as Ollama - is correct even though the call itself goes out over the
    network: there is no spend cap here to enforce.
    """

    name = "selfhosted"
    is_cloud = False

    def configured(self):
        return bool(config.SELFHOSTED_URL and config.SELFHOSTED_API_KEY)

    def chat(self, system_prompt, user_prompt, timeout, question="", model=None, temperature=None, **_):
        # `question` is blank for translate_to_english's call (see llm.py) -
        # fall back to scripting off user_prompt so that call still routes to
        # the Indic-capable model instead of defaulting to the English one.
        script = detect_script(question or user_prompt)
        model = model or (
            config.SELFHOSTED_MODEL_INTL if script in ("devanagari", "tamil")
            else config.SELFHOSTED_MODEL_EN
        )
        # Same reminder Ollama needs (see OllamaProvider.chat): a smaller
        # model is more likely to drop the system-prompt language rule for
        # Indic questions than sarvam-105b was.
        user_prompt += _SCRIPT_REMINDER.get(detect_script(question), "")
        # max_tokens and repetition control were both missing here originally
        # (unlike SarvamProvider, which at least caps max_tokens=4096) - on
        # the small quantized models this server runs (sarvam-1-gguf-Q4_K_M
        # is 2B), low CHAT_TEMPERATURE plus no repetition penalty is a
        # textbook degenerate-loop trigger. Reproduced directly: a plain
        # Marathi hostel-availability question spun into the same Q&A pair
        # repeated as 35+ numbered list items, still going when the caller's
        # own 120s timeout cut it off.
        #
        # frequency_penalty/presence_penalty (OpenAI fields) plus llama.cpp's
        # own repeat_penalty were all sent together as a hedge, on the
        # assumption the OpenAI fields were "inert if unused." That
        # assumption was wrong: the self-hosted server was silently dropping
        # all three (a server-side bug, since fixed 2026-08-11) - so they had
        # zero real effect the whole time this was tuned. Once the server
        # started actually honoring them, having all three stacked
        # simultaneously over-suppressed the small model so hard it could no
        # longer generate anything novel and just echoed the question back
        # verbatim instead of answering - confirmed on two separate Marathi
        # questions. repeat_penalty alone (llama.cpp's native, most targeted
        # mechanism) at 1.15 is what actually works: breaks the repetition
        # loop without over-suppressing. Do not add frequency_penalty/
        # presence_penalty back without deliberately re-testing the combined
        # effect - they are no longer inert.
        payload = {
            "model": model, "stream": False,
            "temperature": config.CHAT_TEMPERATURE if temperature is None else temperature,
            "max_tokens": 1024,
            "repeat_penalty": 1.15,
            "messages": _messages(system_prompt, user_prompt),
        }
        # The server accepts both; Bearer matches the standard OpenAI shape
        # its request/response bodies otherwise follow.
        headers = {"Authorization": f"Bearer {config.SELFHOSTED_API_KEY}"}
        # Confirmed against this server: POST /v1/chat, not the standard
        # OpenAI /v1/chat/completions path.
        url = config.SELFHOSTED_URL.rstrip("/") + "/v1/chat"
        result = _post(url, payload, headers, timeout)
        return clean(result["choices"][0]["message"]["content"]), "selfhosted:" + model


class HetznerProvider:
    """Hetzner Inference API - genuinely OpenAI-compatible (standard
    /v1/chat/completions, unlike SelfHostedProvider's nonstandard /v1/chat),
    exposing noticeably larger models than the self-hosted server it was
    added to replace as CHAT_FALLBACK 2026-08-12.

    is_cloud = False for the same reason as SelfHostedProvider: llm.py's
    _usable() gates any is_cloud=True provider behind Sarvam's daily-cap
    bookkeeping, which has nothing to do with this service's own (separate,
    unmetered-here) usage.
    """

    name = "hetzner"
    is_cloud = False

    def configured(self):
        return bool(config.HETZNER_API_KEY)

    def chat(self, system_prompt, user_prompt, timeout, question="", model=None, temperature=None, **_):
        model = model or config.HETZNER_MODEL
        # Same reminder Ollama/self-hosted need (see their .chat methods) -
        # not yet verified whether these specific models need it as much as
        # the small self-hosted ones did, but costs nothing to include and
        # avoids re-discovering the same Indic-language-drop bug blind.
        user_prompt += _SCRIPT_REMINDER.get(detect_script(question), "")
        payload = {
            "model": model,
            "temperature": config.CHAT_TEMPERATURE if temperature is None else temperature,
            "messages": _messages(system_prompt, user_prompt),
        }
        headers = {"Authorization": f"Bearer {config.HETZNER_API_KEY}"}
        url = config.HETZNER_URL.rstrip("/") + "/chat/completions"
        result = _post(url, payload, headers, timeout)
        return clean(result["choices"][0]["message"]["content"]), "hetzner:" + model


_REGISTRY = {p.name: p for p in (SarvamProvider(), OllamaProvider(), SelfHostedProvider(), HetznerProvider())}


def get(name):
    """Provider by name, or None if unknown - callers fall back rather than crash."""
    return _REGISTRY.get((name or "").strip().lower())


def available():
    return sorted(_REGISTRY)
