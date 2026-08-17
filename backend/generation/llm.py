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

from . import providers
from ..storage import atomic
from .. import config
from ..core.lang import detect_script

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
        atomic.write_json(config.SARVAM_USAGE_PATH, {"date": today, "count": count + 1})


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
    "translation. Official names - the university's full name, government scheme "
    "names, portal/website names - must be kept in their original English form "
    "exactly as they appear in the source material, never phonetically rendered or "
    "translated into another script; it is correct and expected for an English name "
    "to appear in the middle of an otherwise Devanagari/Tamil sentence. Never switch "
    "to a different language or script than the student used, and never answer a "
    "real question with only a greeting."
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


def _attempt_timeout(provider, timeout):
    """How long ONE attempt against this provider may take.

    A cloud attempt is held to config.CLOUD_ATTEMPT_TIMEOUT so a stalled call
    fails over quickly rather than hanging the student's request. Local
    providers keep the caller's own budget: there is nothing to fail over TO,
    so cutting them short only turns a slow answer into no answer.

    min(), never a flat override - a caller that asks for less than the cap
    keeps its tighter budget, which is what will let a per-request deadline be
    threaded through here without fighting this function.
    """
    if provider is not None and provider.is_cloud:
        return min(timeout, config.CLOUD_ATTEMPT_TIMEOUT)
    return timeout


def generate(system_prompt, user_prompt, question, timeout=280, allow_cloud=True, model=None,
             temperature=None):
    """Generate an answer and return (answer_text, model_label).

    Tries the configured primary provider, then the fallback. Which providers
    those are is config, not code (see config.CHAT_PRIMARY / CHAT_FALLBACK), so
    the Sarvam-vs-local-vs-Bhashini decision can be made and A/B tested without
    touching this call path.

    `allow_cloud` is the per-project switch (projects.allow_cloud) - when False
    this project never calls a cloud provider, independent of any key or cap.

    `model` overrides a provider's own default/auto-routed model choice (see
    SelfHostedProvider.chat's script-based routing) - needed by
    translate_to_english, which always wants the English-strong model
    regardless of the input script, the opposite of what that auto-routing
    would pick for Indic input.

    `temperature` overrides config.CHAT_TEMPERATURE for this call only -
    needed by translate_to_english for the same reason `model` is: a
    mechanical extraction task (what does this question mean in English)
    benefits from being as close to deterministic as this server allows,
    which the shared answer-generation temperature was never tuned for.
    Reproduced directly: the SAME question, translated twice in a row at the
    shared 0.2 temperature, came back different enough (correct one run,
    wrong table row picked the next) to make tools/test_retrieval_hi_mr.py's
    "CONFIDENTLY WRONG" count non-reproducible between runs - a real problem
    for using that harness to validate anything, not just a translation
    quality nuisance.
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
            call_timeout = _attempt_timeout(primary, timeout)
            for attempt in (1, 2):
                try:
                    result = primary.chat(system_prompt, user_prompt, call_timeout,
                                          question=question, model=model, temperature=temperature)
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
    try:
        # Capped the same way the primary is. This used to take the full
        # `timeout` while the primary was held to CLOUD_ATTEMPT_TIMEOUT, which
        # is backwards - the fallback is the slower, less reliable path, so it
        # was the one allowed to run longest. With a 280s default that made one
        # generate() worth 45 + 45 + 280 = 370s, and the answer path makes
        # three to five of them.
        result = fallback.chat(system_prompt, user_prompt,
                               _attempt_timeout(fallback, timeout),
                               question=question, model=model,
                               temperature=temperature)
    except Exception as exc:  # noqa: BLE001 - both providers down (seen 2026-08-12:
        # bge-m3/glm-4-9b-chat went "running"->"stopped" mid-session with no
        # warning). This used to be unguarded, unlike the primary call above
        # it - the raw provider exception (e.g. "HTTP Error 503: Service
        # Unavailable") propagated straight through rag.py to server.py's
        # generic handler and out to the student as-is. Same pattern as the
        # primary's own failure handling: print the real error for whoever's
        # debugging, raise something a student should actually read.
        print(f"[llm] {fallback.name} (fallback) also failed: {exc!r}")
        raise RuntimeError(
            "The assistant is temporarily unavailable. Please try again in a few minutes."
        ) from exc
    if fallback.is_cloud:
        _record_sarvam_call()
    return result


def generate_scoped(provider_name, system_prompt, user_prompt, question, timeout=60,
                     model=None, temperature=None, allow_cloud=True):
    """Call exactly ONE named provider - no primary/fallback chain, unlike
    generate() above. For orchestration roles added 2026-08-12 (sub-agent
    answers, validator critique, regeneration retries) that must never
    compete with the single user-facing answer call for Sarvam's metered
    daily quota - every caller of this function is expected to pass
    config.ORCHESTRATOR_PROVIDER ("hetzner" by default), which is_cloud=False
    (see HetznerProvider's own docstring: "no spend cap here to enforce"),
    so _usable()'s cap gate is a no-op for the normal case. Still routed
    through _usable() defensively rather than skipping it, so a future
    misconfiguration (ORCHESTRATOR_PROVIDER accidentally set to "sarvam")
    still respects the cap instead of silently draining it.

    Returns None on ANY failure (unconfigured, timeout, HTTP error) instead
    of raising - every caller in orchestrator.py/validate.py treats None as
    "skip this step and fall back to the existing single-pass behavior",
    never as a reason to error out or block the student's answer, matching
    this codebase's standing safe-degrade pattern (see
    translate_to_english's try/except below).
    """
    provider = providers.get(provider_name)
    if not _usable(provider, allow_cloud):
        return None
    try:
        result = provider.chat(system_prompt, user_prompt, timeout, question=question,
                                model=model, temperature=temperature)
    except Exception as exc:  # noqa: BLE001 - see docstring: failure here is not fatal
        print(f"[llm] generate_scoped({provider_name!r}) failed: {exc!r}")
        return None
    if provider.is_cloud:
        _record_sarvam_call()
    return result


_TRANSLATE_SYSTEM = (
    "Translate the following student question into natural English. Output ONLY "
    "the translated question - no quotes, no explanation, no commentary."
)

_LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "ta": "Tamil"}


def _translate_system(ui_language):
    """Naming the source language and the domain measurably fixes gemma2:2b.

    The bare prompt above gave it no anchor and it guessed from surface form,
    which went badly on Marathi specifically: "वर्गांमध्ये किमान किती उपस्थिती
    आवश्यक आहे?" (minimum attendance required in classes) came back as "How many
    attendees are required at least in the circle?", and "तात्पुरती गुणवत्ता यादी"
    (provisional merit list) as "the quality list for the Tatpurti". It also
    inverted meaning outright once - rendering a minimum-attendance question as
    "the minimum number of absences allowed". Those translations feed retrieval,
    so a mistranslation doesn't produce a wrong answer, it produces a confident
    "the prospectus doesn't specify" for a fact that is plainly in the
    prospectus - which is what a student sees.

    Naming the domain rather than supplying a glossary was deliberate: a version
    listing term equivalents bled the glossary into the output ("What is the
    total admission fee for each class/class category?"). Falls back to the
    original prompt when the caller has no explicit language to name.
    """
    name = _LANGUAGE_NAMES.get(ui_language)
    if not name:
        return _TRANSLATE_SYSTEM
    return (
        f"Translate this {name} question into English. It was asked by a student "
        "to a university admissions assistant, so translate it as an admissions "
        "question about fees, dates, eligibility, documents, attendance, seats, "
        "hostel, admission rounds or grievances/complaints. "
        "Translate literally and preserve the exact intent - do not add, "
        "generalise or reinterpret. Output ONLY the translated question."
    )


def translate_to_english(text, ui_language=None):
    """Best-effort English translation, used only to make cross-lingual retrieval
    work (nomic-embed-text doesn't align Hindi/Tamil and English closely enough for
    a native-script question to reliably retrieve the right English prospectus
    chunks - verified: a Hindi fee question missed chunks an equivalent English one
    found). Never used for the answer itself, only for the retrieval-side embedding.

    Deliberately always local (allow_cloud=False), never Sarvam: Sarvam-105b has
    the same hard same-language-as-input bias that broke Hinglish generation -
    tested with several prompt phrasings and it just echoes the Hindi/Marathi/
    Tamil text back instead of translating, no matter the instruction.

    Deliberately forces model=config.SELFHOSTED_MODEL_EN rather than letting
    SelfHostedProvider auto-route by input script, which would send Indic
    input to SELFHOSTED_MODEL_INTL instead. This is defensive, not currently
    load-bearing: as of 2026-08-11 both config values point at the same model
    (qwen2.5-3b-instruct), so forcing EN here has no actual behavioral effect
    either way right now.

    The reason the forcing exists at all: on 2026-08-11, with SELFHOSTED_MODEL_EN
    set to glm-4-9b-chat and SELFHOSTED_MODEL_INTL set to sarvam-1-gguf-Q4_K_M,
    the INTL model tested with a hard same-language-as-input bias on translation
    specifically - asked to translate Tamil "what is the first-year tuition fee",
    it answered directly in Tamil instead, inventing a figure (Rs. 10,000 vs the
    real Rs. 27,500); a Marathi documents question got an invented, wrong-domain
    checklist; a Hindi question came back in Marathi, untranslated. The EN model
    at the time translated all three correctly. That was a real, model-specific
    defect, not a general property of "the INTL slot" - it has NOT been re-tested
    against whatever model SELFHOSTED_MODEL_INTL actually points to today, and
    won't be exercised at all while the two config values keep resolving to the
    same model. Re-verify this specific bias (native-script input, asked to
    translate, does it comply or answer-in-place-and-invent-a-figure) before
    ever removing this forced override or assuming SELFHOSTED_MODEL_INTL is
    safe for translation - the non-Latin-script tripwire below catches a
    reintroduced bias at runtime either way, but silently degrades to
    untranslated retrieval rather than failing loudly.

    `question=""` in the generate() call suppresses the reply-in-native-script
    reminder the self-hosted provider appends for answer generation, which
    would otherwise contradict a translate-to-English instruction. The
    non-Latin-script check below is kept as a second tripwire even with the
    explicit model - a translation that isn't actually in Latin script is
    treated as a failed translation, not a successful one, so a future model
    swap that reintroduces the same bias degrades retrieval instead of
    poisoning it with a wrong number. Falls back to the original text on any
    failure - a missed translation should degrade retrieval quality, not break
    the request.

    (This is also the natural seam for Bhashini: a translation provider would
    replace this function's body, leaving every caller untouched.)
    """
    # The forced-model override only means something for providers that
    # split EN/INTL or otherwise care which model name they're handed -
    # guarded so a future CHAT_FALLBACK=ollama doesn't get handed a model
    # name ("glm-4-9b-chat") that isn't one of its own. HetznerProvider (see
    # providers.py) uses one model for both lanes, so no override is needed
    # there - HETZNER_MODEL is already its default.
    model = config.SELFHOSTED_MODEL_EN if config.CHAT_FALLBACK == "selfhosted" else None
    try:
        # temperature=0.0, not the shared CHAT_TEMPERATURE (0.2) - this is a
        # mechanical "what does this mean in English" extraction, not
        # generation, and even 0.2 was enough sampling variance to flip the
        # same question between a correct and a wrong table-row match on
        # consecutive runs (see generate()'s docstring for the reproduction).
        # Fully greedy is safe here specifically because this call is always
        # local/self-hosted (allow_cloud=False, see docstring above) - the
        # "reasoning model loops at temperature 0" risk that keeps the main
        # answer-generation temperature at 0.2 is a Sarvam-specific concern
        # that never applies to this call path.
        reply, _ = generate(_translate_system(ui_language), text, "", timeout=30,
                            allow_cloud=False, model=model, temperature=0.0)
        reply = reply.strip().strip('"')
        if not reply or detect_script(reply) != "latin":
            return text
        return reply
    except Exception:  # noqa: BLE001
        return text
