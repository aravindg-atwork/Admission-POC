"""The single-answer path entry point - answer()/_answer(), the trimmed
core that ties guards.py (Request 2's structural pre-cache guard stage),
the FAQ cache, orchestrator.py (multi-part decomposition), retrieval,
tablelookup, and validate.py together. Moved and restructured from rag.py
during the 2026-08-13 re-architecture: _answer()'s old ~450-line body of
six sequential early-returns followed by the cache/retrieval/generation
pipeline is now `guards.run_guards(ctx)` (see guards.py) followed by
`_pipeline(ctx)` below - the pipeline body itself is otherwise an
unmodified move, see git history to diff against the pre-move version.
"""

import time
import types

from . import guards
from . import router
from .. import config
from ..trace import events as trace_events
from ..core import tablelookup
from ..core.intent import is_payment_issue
from ..core.lang import detect_devanagari_hi_mr, detect_romanized_indic, detect_script
from ..core import textclean
from ..generation import embeddings, llm
from ..prompts.system import PAYMENT_SYSTEM_PROMPT, _VERIFIED_FACT_SYSTEM
from ..storage import faq, projects, reviewlog, stats, vectorstore
from . import orchestrator
from . import validate
from .helpers import (_add_nri_scope_caveat, _apply_script_pref, _build_retrieval_text,
                       _compact_readings, _system_prompt, _ui_language_matches,
                       _english_reply_hint, _language_hint, _romanized_input_hint,
                       _UI_LANGUAGE_NAMES)


def _build_context(project_id, question, script_pref, ui_language, history=None, route=None,
                   trace_id=None):
    """Runs the language-detection/romanization/hint-building preamble once
    per request and returns the ctx object every guard (guards.py) and the
    pipeline (_pipeline below) read from. `reanswer` is dependency-injected
    here rather than imported by guards.py, so the program-redirect guard
    can recursively call back into _answer() without guards.py importing
    this module (which would recreate the exact cycle this phase removes).
    """
    question = question.strip()
    language = detect_script(question)
    cloud_ok = projects.allow_cloud(project_id)

    # Romanized Hindi/Marathi ("mera fees kitna hai") reads as plain Latin script
    # to detect_script and would otherwise silently fall into the English lane -
    # most students actually type this way day to day, not in native script (see
    # lang.detect_romanized_indic). Once caught, treat it exactly like native-script
    # input from here on: same generation-in-Devanagari + romanize-for-display
    # pipeline, same retrieval-side translation.
    #
    # The student's explicit ui_language selection (the app's own language
    # dropdown) is authoritative here, not just a tiebreaker for the word-list
    # guess - selecting Hindi/Marathi/Tamil means "treat my Latin-script input as
    # this language" even if the word-list heuristic doesn't independently agree
    # (short/ambiguous wording, a marker word missing from the list, etc). Bug
    # seen in testing: a real Hinglish question with an explicit Hindi selection
    # still came back in raw Devanagari, unromanized - detect_romanized_indic
    # hadn't matched (a punctuation-attached marker word slipped under the
    # threshold), so language stayed "latin" and _apply_script_pref never
    # romanized the reply, even though _language_hint had already told the model
    # to answer in Hindi. Deferring to the explicit selection first closes that
    # gap regardless of whether the word-list guess also happens to fire.
    # Whether the question itself arrived in Roman letters. Native-script input
    # keeps its script in the reply; only romanized input gets romanized back
    # (see _apply_script_pref).
    typed_romanized = False
    if language == "latin":
        effective = ui_language if ui_language in ("hi", "mr") else (
            "tamil_ui" if ui_language == "ta" else detect_romanized_indic(question)
        )
        if effective == "tamil_ui":
            language = "tamil"
            typed_romanized = True
        elif effective:
            language = "devanagari"
            typed_romanized = True
            # Reassigned, not just a local - everything downstream (the FAQ cache
            # lookup/store below, in particular) must see this as the effective
            # language too, or a Hinglish question can still collide in cache with
            # an unrelated English one on the same topic (same bug class as the
            # Hindi/Marathi cache collision, just English-vs-Hinglish this time).
            ui_language = effective

    # Built from the FINAL language state, once the romanized-detection above has
    # settled what's actually being asked - never from a ui_language that
    # contradicts the question's own script. A student who picked English in the
    # app but then types (or speaks) a Marathi question, native script or
    # romanized, should get a Marathi answer back, not one force-redirected into
    # English by a stale selector value that has nothing to do with this
    # particular question. Bug seen in testing: a Devanagari question arrived with
    # ui_language still "en" from the picker, and the old unconditional hint told
    # the model "the student selected English - always reply in English" right
    # alongside a question written in Marathi - directly contradicting
    # llm.LANGUAGE_RULE's own "match the student's language" instruction.
    # ui_language only disambiguates Hindi/Marathi when the student explicitly
    # picked one of the two - left at the default (English), a native-script
    # question gets no hint at all under the check above, even though the
    # question text itself is often unambiguous (see detect_devanagari_hi_mr).
    # That gap didn't matter for the previous self-hosted model, which
    # reliably told Hindi and Marathi apart from context alone; the current
    # one does not - confirmed live, it defaults to Hindi under exactly this
    # no-hint condition even when asked a plainly Marathi question. Falling
    # back to the word-list guess here closes that gap the same way it's
    # already closed for romanized input a few lines up, without touching the
    # explicit-selection path (still authoritative when it applies) or the
    # Tamil/Latin cases (still genuinely unambiguous, no guess needed there).
    hint_language = ui_language if _ui_language_matches(language, ui_language) else (
        detect_devanagari_hi_mr(question) if language == "devanagari" else None
    )
    hint = _language_hint(hint_language) if hint_language else ""
    if typed_romanized:
        hint += _romanized_input_hint(_UI_LANGUAGE_NAMES[ui_language])
    elif not hint and language == "latin":
        # Plain English question from a caller that sent no ui_language -
        # without this it reaches the model with no language instruction
        # near the end of the prompt at all, and long answers drift into
        # Hinglish. See _english_reply_hint for the reproduction.
        hint = _english_reply_hint()

    collector = trace_events.TraceCollector(project_id, trace_id)

    # Understand the message ONCE, before any guard runs (see router.py). None
    # on any failure, in which case every guard falls back to the deterministic
    # keyword logic it used before this existed - the router is an upgrade to
    # routing quality, never a new single point of failure.
    # `route` is passed in only by a redirect re-answering the SAME message
    # under another programme (see reanswer below). Re-classifying there cost
    # a second model call per redirected question and let the router disagree
    # with itself between the two passes - the outer call deciding "bfsc" and
    # the inner one, reading a rewritten question, deciding something else.
    reused_route = route is not None
    if route is None:
        route = router.classify(question, history, cloud_ok)
    # Say WHY it is unavailable, not just that it is. An open circuit breaker
    # and a one-off provider timeout look identical in the trace otherwise,
    # and they call for opposite responses: the first means the assistant is
    # running on its keyword floor for the next two minutes and every answer
    # in that window should be read in that light; the second is noise.
    _router_status = router.status()
    collector.record("intent_router", **(
        {"available": False,
         "reason": ("degraded - all routing providers failing, keyword fallback "
                    f"for another {_router_status['secondsRemaining']:.0f}s"
                    if _router_status["degraded"]
                    else "disabled" if not _router_status["enabled"]
                    else "unavailable - using keyword fallback"),
         "degraded": _router_status["degraded"]} if route is None
        else {"available": True, "intent": route["intent"],
              "targetPrograms": route["target_programs"],
              "isComparison": route["is_comparison"],
              "needsProgramClarification": route["needs_program_clarification"],
              "selfScoreAmbiguous": route["self_score_ambiguous"],
              "confidence": route["confidence"],
              "resolvedQuestion": route["resolved_question"],
              # Flagged so the console does not present a carried-over
              # verdict as a fresh classification - a redirected question
              # produces two trace cards but only one model call.
              "reused": reused_route}))

    # Swap in the router's standalone rewrite as the question the PIPELINE
    # works from - retrieval, the FAQ cache key and generation all get "how
    # much is the fee for B.Tech. (Dairy Technology)" instead of the bare
    # "btech" the student actually typed as a follow-up. Only on high
    # confidence: an unsure rewrite is more dangerous than the literal text,
    # since everything downstream then answers a question nobody asked.
    # Language state above is deliberately NOT recomputed from it - it was
    # derived from what the student really typed, and router._validate
    # already rejects a rewrite that changed script.
    effective_question = question
    if route and route["resolved_question"] and route["confidence"] == "high":
        effective_question = route["resolved_question"]

    return types.SimpleNamespace(
        project_id=project_id, question=effective_question, original_question=question,
        script_pref=script_pref,
        ui_language=ui_language, language=language, hint_language=hint_language,
        hint=hint, typed_romanized=typed_romanized, cloud_ok=cloud_ok, route=route,
        history=history or [],
        # Same trace id on the way through a redirect, so a student watching
        # progress sees one continuous run instead of a stream that goes quiet
        # at the redirect and never delivers final_answer.
        reanswer=lambda pid: _answer(pid, effective_question, script_pref, ui_language,
                                      history, route, trace_id=collector.trace_id),
        trace=collector.record,
        # Surfaced so a caller can line an answer up with the trace that
        # produced it. Without it the console could only show a firehose of
        # every request and leave the operator to guess which card was
        # theirs - see the Playground inspector.
        trace_id=collector.trace_id,
    )


def _answer(project_id, question, script_pref, ui_language, history=None, route=None,
            trace_id=None):
    ctx = _build_context(project_id, question, script_pref, ui_language, history, route,
                         trace_id=trace_id)
    guard_response = guards.run_guards(ctx)
    result = guard_response if guard_response is not None else _pipeline(ctx)
    # Stamped in one place rather than in each of the many return points, so
    # a guard reply and a full pipeline reply are equally traceable.
    result.setdefault("traceId", ctx.trace_id)
    return result


def _pipeline(ctx):
    question = ctx.question
    project_id = ctx.project_id
    script_pref = ctx.script_pref
    ui_language = ctx.ui_language
    language = ctx.language
    hint_language = ctx.hint_language
    hint = ctx.hint
    typed_romanized = ctx.typed_romanized
    cloud_ok = ctx.cloud_ok
    trace = ctx.trace
    # Intent: payment PROBLEM (not just a payment question - see intent.py). Swaps
    # in a de-escalate-first prompt instead of the general counselor one, and tags
    # the cache entry so it can never surface for/from a plain fee-amount question
    # that happens to embed nearby (same collision risk as the Hindi/Marathi one).
    payment_issue = is_payment_issue(question)
    system_prompt = PAYMENT_SYSTEM_PROMPT if payment_issue else _system_prompt(project_id)
    cache_tags = {"ui_language": ui_language, "intent": "payment_issue" if payment_issue else None}
    # Model allotter, continued (see guards.py's _greeting_guard for the fast-
    # lane half): nothing reaching this point skipped retrieval, so it always
    # gets the quality/Indic-tuned chain (config.CHAT_PRIMARY, Sarvam) -
    # unlike a greeting, a real prospectus-grounded answer can't trade
    # accuracy for speed, in either language. Recorded even on a path that
    # turns out to be a cache hit a few lines below - it documents the
    # standing policy this request would use if generation actually runs.
    trace("model_routing", lane="quality", provider=config.CHAT_PRIMARY,
          reason="retrieval-grounded answer - accuracy over speed" if language == "latin"
                 else "native-language answer needs the Indic-tuned model")

    # Embed once; the vector is reused for both the FAQ lookup and RAG retrieval.
    query_vector = embeddings.embed([question])[0]

    # FAQ cache: instant answer for a question we've seen or seeded before. Cached
    # text is always native-script; script_pref is applied below regardless of
    # whether the answer came from cache or fresh generation.
    # The question text is passed so the cache can reject matches that differ on
    # a meaning-flipping token (1st vs 2nd year, before vs after) despite having
    # near-identical embeddings - see faq._discriminators.
    hit = faq.match(projects.faq_path(project_id), query_vector, cache_tags, question)
    trace("cache_lookup", hit=bool(hit), verified=bool(hit and hit.get("verified")),
          faqId=hit.get("id") if hit else None)
    # A cache hit that was originally produced from a VERIFIED table figure
    # (see tablelookup below) is not trusted on embedding similarity + the
    # discriminator vocabulary alone. Semantic similarity measures topic
    # closeness, not fact identity - "Nagpur hostel fee" and "Mumbai hostel
    # fee" are close enough to collide despite demanding different numbers.
    # Measured 2026-08-11 on a 78-question ground-truth sweep: every single
    # numeric-figure cache failure was exactly this shape (Mumbai served
    # Nagpur's fee, a fee TOTAL served its maintenance-only component, an NRI
    # special fee served an unrelated exam-fee answer) - a topically-close but
    # factually-wrong cache hit that no amount of hand-added discriminator
    # vocabulary closes for good, since the next college/fee-type pairing is
    # always one more gap. So a verified-provenance hit is re-checked against
    # a FRESH, live table lookup (below) before being served, instead of
    # trusted outright - this still skips the LLM answer-generation call on a
    # confirmed hit, so it stays much cheaper than a full regeneration, while
    # making it deterministic that a served number is never stale relative to
    # what a fresh lookup for THIS question resolves to. A hit with no
    # verified provenance (open-ended answers - process descriptions, honesty
    # declines) carries no such risk and returns immediately as before.
    if hit and not hit.get("verified"):
        display, speakable = _apply_script_pref(hit["answer"], language, script_pref, typed_romanized)
        trace("final_answer", answer=display, source="faq-cache", model="faq-cache",
              pages=hit["pages"], speakable=speakable, language=language)
        return {"answer": display, "pages": hit["pages"], "model": "faq-cache",
                "language": language, "source": "faq-cache", "speakable": speakable,
                "faqId": hit.get("id")}

    # Orchestration: a genuinely multi-part question (2+ independent
    # complexity signals - see orchestrator.is_complex) gets its own
    # retrieval fan-out per sub-topic instead of one undifferentiated
    # search. Payment-issue questions are excluded so the tested
    # de-escalation prompt's narrow scope stays untouched. answer_complex
    # returns None (not a dict) whenever decomposition or retrieval didn't
    # actually find anything useful to split on - the normal single-pass
    # path below is always the fallback, never blocked by this attempt.
    if config.ORCHESTRATOR_ENABLED and not payment_issue and orchestrator.is_complex(question):
        trace("routing", decision="orchestrated")
        orchestrated = orchestrator.answer_complex(
            project_id, question, script_pref, ui_language, language,
            hint_language, hint, typed_romanized, cloud_ok, ctx.trace)
        if orchestrated is not None:
            faq_id = None
            if config.FAQ_AUTOCACHE:
                faq_id = faq.add(projects.faq_path(project_id), question, orchestrated["answer"],
                                  orchestrated["pages"], query_vector, cache_tags, verified=None)
            trace("final_answer", answer=orchestrated["answer"], source="orchestrated",
                  model=orchestrated["model"], pages=orchestrated["pages"],
                  speakable=orchestrated["speakable"], language=language,
                  subtopics=orchestrated.get("subtopics"))
            return {**orchestrated, "faqId": faq_id}

    # RAG: retrieve prospectus context, then the language-routed LLM. The vector
    # half of retrieval uses the NATIVE-script question's embedding (query_vector,
    # already computed above), not a translated one - reversed 2026-08-12 from the
    # opposite design. That original design assumed the embedding model didn't
    # align Hindi/Tamil with English closely enough for a native-script vector to
    # find the right chunks, which was true for nomic-embed-text-v1 but was never
    # re-checked after the later switch to bge-m3 (a model built for cross-lingual
    # alignment). Measured on the 68-probe harness (tools/test_retrieval_hi_mr.py):
    # translated-vector retrieval recalled 63/68 (92.6%), with 5 persistent misses
    # blamed on retrieval/TOP_K tuning. Root cause was actually upstream of
    # retrieval - qwen2.5-3b-instruct (translate_to_english's current model)
    # regularly mistranslates Marathi/Hindi to the wrong domain outright (a
    # minimum-marks question came back as "how many documents are required", an
    # attendance question as "how many seats are available"), which no retrieval
    # tuning can fix because the vector is for a different question. Embedding the
    # native-script question directly instead - bypassing translation for the
    # vector, keeping it only for the lexical half below - recovered 67/68 (98.5%),
    # including 4 of those 5 "unfixable" misses. The FAQ-cache vector above already
    # did this (stays untranslated), so this brings RAG retrieval in line with it.
    retrieval_vector = query_vector
    # Text used for the LEXICAL half of retrieval and for the table lookup -
    # see _build_retrieval_text's docstring for why this diverges from
    # `question` (what the student actually typed) for non-Latin input.
    retrieval_text = _build_retrieval_text(question, language, hint_language, ui_language)

    store = vectorstore.load(projects.store_path(project_id))
    # Pass the translated text, not the original: retrieval is hybrid (cosine +
    # keyword overlap), and the keyword half is what lets an exact-phrase lookup
    # like a specific deadline find the schedule table that pure vector
    # similarity ranked out of the top-K. The corpus is English, so a Devanagari
    # question scored zero lexical overlap against every chunk - silently
    # downgrading the entire Hindi/Marathi lane to pure vector search, i.e. the
    # exact behaviour the keyword half was added to fix, in the one lane where
    # it was never measured. Measured on 16 Hindi/Marathi questions with a known
    # answer page: 12/16 retrieved that page before, 16/16 after (together with
    # the translation-prompt fix in llm.translate_to_english).
    top = vectorstore.search(store, retrieval_vector, config.TOP_K, retrieval_text)
    trace("retrieval", topK=len(top),
          chunks=[{"page": e.get("page"), "score": e.get("score"), "snippet": e["text"][:160]} for e in top])

    if not top:
        # No prospectus uploaded for this project yet. An empty excerpts block was
        # tested and found to NOT reliably stop the model from hallucinating a
        # confident-sounding made-up answer (e.g. inventing a specific fee amount)
        # despite the "never invent details" rule - so this makes the no-data case
        # explicit and unambiguous instead, which the model does follow reliably.
        # Not cached: the real answer should appear the moment a prospectus is
        # uploaded, not stay stuck on this message.
        no_data_prompt = (
            "There are NO prospectus excerpts available - none have been uploaded yet "
            "for this project. Do not answer using any outside knowledge or make up "
            "specifics. Instead, warmly and briefly tell the student the prospectus "
            "isn't loaded yet and you can't answer specific questions until it is.\n\n"
            "Question: " + question + hint
        )
        reply, model = llm.generate(system_prompt, no_data_prompt, question, allow_cloud=cloud_ok)
        reply = textclean.clean_for_display(reply)
        display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
        trace("final_answer", answer=display, source="no-context", model=model,
              pages=[], speakable=speakable, language=language)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "no-context", "speakable": speakable}

    # No "[Page N]" label on each excerpt (used to be inline here) - page
    # numbers for citation are already tracked separately in code (`pages`
    # below, straight off `top`, never parsed from anything the model writes),
    # so the label served no functional purpose except as an instruction to
    # the model not to repeat it - and a small model reading "[Page 40]" as
    # the first four words of a block of otherwise-ordinary prose has no way
    # to tell "meta-marker, withhold this" from "content, free to use", so it
    # doesn't reliably withhold it. Confirmed live on the self-hosted 2B model
    # (sarvam-1-gguf-Q4_K_M): despite both this reminder AND the system-prompt
    # rule saying not to, a grievance-filing answer still opened with "तुम्ही
    # [Page N] लेबल केलेल्या पृष्ठांवर..." - it read the marker as literal
    # text to quote, not an instruction to skip. Removing the marker from the
    # excerpt text entirely closes the gap structurally instead of asking an
    # unreliable narrator to selectively censor something it can plainly see.
    context = "\n\n".join(_compact_readings(e["text"]) for e in top)
    # Recency reminder, not just the system-prompt rule: the local fallback
    # model in particular has a documented pattern of ignoring system-prompt
    # rules but reliably following something repeated at the end of the user
    # turn (see _SCRIPT_REMINDER in llm.py) - seen in testing to still cite
    # "you'll find this on page X" here without this, despite the system
    # prompt already saying not to.
    page_reminder = (
        "\n\n(Reminder: answer this fully yourself using the excerpts above - "
        "do NOT tell the student to go check a page number themselves, and do "
        "not mention page numbers at all - the app shows those separately.)"
    )
    # If the question maps cleanly onto one cell of a table, resolve the figure
    # here instead of leaving the model to pick it out of dozens of similar
    # readings - the step it demonstrably got wrong and inconsistently. The
    # model still writes the sentence (so Hindi/Marathi phrasing keeps working),
    # it just isn't the one deciding which number is right. Returns None
    # whenever the match is ambiguous, in which case nothing changes.
    # Same reason the search above uses retrieval_text: the linearized readings
    # this matches against are English ("Hostel Fees - Total for 1st Year at
    # Nagpur: 27300"), so a Devanagari question overlaps zero terms and lookup()
    # returned None for every Hindi/Marathi question ever asked. That left the
    # Indic lane picking fee figures the way this module exists to stop - by
    # asking the model to eyeball a grid of ~45 near-identical rows, which it
    # demonstrably gets wrong. Verified: the Hindi and Marathi answers to "what
    # is the first-year tuition fee" quoted Rs.62635 (the TOTAL admission fee)
    # and, in Marathi, Rs.63135 as the reserved-category figure when reserved is
    # actually Rs.26135 - a ~37,000 rupee error stated with full confidence,
    # while the English answer to the same question was correct.
    verified = tablelookup.lookup(retrieval_text, top)
    # Veto a reading that contradicts the ORIGINAL question, in the student's own
    # language. Routing the lookup through the English translation is what made
    # it work for Indic at all, but it also put a 2B translation model in front
    # of a figure the prompt then tells the model to state as authoritative -
    # so a mistranslation stops being a retrieval nuisance and becomes a
    # confidently wrong number. Observed: "पहले वर्ष की परीक्षा शुल्क" (first-year
    # EXAMINATION fee) was translated as "tuition fee for the first year" and
    # resolved to 27500 instead of 6000.
    #
    # faq's discriminators already encode the fee-type/ordinal vocabulary in
    # Hindi, Marathi and English, so the same comparison that keeps the cache
    # honest is reused here against the descriptor - if the question says exam
    # and the descriptor says tuition, the shortcut is dropped and the model
    # answers from the excerpts instead, which is the safe direction.
    if verified and not faq.compatible_questions(question, verified["descriptor"]):
        verified = None
    trace("table_lookup", matched=bool(verified),
          descriptor=verified["descriptor"] if verified else None,
          value=verified["value"] if verified else None)

    # Reconcile a verified-provenance cache hit (see the note above the cache
    # check) against this fresh lookup. Only an exact VALUE match is trusted;
    # anything else - a different figure, or the fresh lookup coming back
    # empty/ambiguous where the cached entry had a confident one - falls
    # through to a full fresh answer below, which also re-caches a corrected
    # entry for this question. A wrong figure served with confidence is the
    # single worst outcome this whole app exists to avoid, so an unconfirmable
    # cache hit is always treated as a miss, never served on a guess.
    if hit:
        cached_verified = hit.get("verified")
        if verified and cached_verified and verified["value"] == cached_verified["value"]:
            display, speakable = _apply_script_pref(hit["answer"], language, script_pref, typed_romanized)
            trace("final_answer", answer=display, source="faq-cache", model="faq-cache",
                  pages=hit["pages"], speakable=speakable, language=language)
            return {"answer": display, "pages": hit["pages"], "model": "faq-cache",
                    "language": language, "source": "faq-cache", "speakable": speakable,
                    "faqId": hit.get("id")}

    if verified:
        # Locked-template path: phrase the resolved fact alone, with none of
        # the raw excerpts in context (see _VERIFIED_FACT_SYSTEM's docstring
        # for why the full-context "hint" approach wasn't safe enough).
        fact_prompt = (
            f"Verified fact (this is the complete answer - nothing else is "
            f"in scope): {verified['descriptor']}: {verified['value']}\n\n"
            f"Student's question (for language and tone only): {question}" + hint
        )
        reply, model = llm.generate(_VERIFIED_FACT_SYSTEM, fact_prompt, question, allow_cloud=cloud_ok)
        trace("generation", model=model, promptId="verified_fact_system")
        reply = textclean.clean_for_display(reply)
        # Last-resort safety net: if the model still dropped or altered the
        # figure despite the locked prompt, OR answered in the wrong script
        # entirely, a plain, unembellished statement of the fact replaces it
        # rather than risk serving a fluent-looking but broken answer -
        # correct and blunt beats polished and wrong every time here. The
        # script check matters on its own: a weaker self-hosted model, given
        # this same minimal prompt for an English "fourth year tuition fee"
        # question, answered "चौथे वर्ष की शिक्षा नुकसान: 41250" - Hindi, wrong
        # script for an English question, and "नुकसान" (loss/damage) isn't
        # even a correct translation of "fee". The number was right, so the
        # value-substring check alone would have let it through.
        if verified["value"] not in reply or detect_script(reply) != language:
            reply = f"{verified['descriptor']}: {verified['value']}"
        pages = sorted({e["page"] for e in top})
        source = "verified-fact"
    else:
        user_prompt = ("Prospectus excerpts:\n" + context
                       + "\n\nQuestion: " + question + hint + page_reminder)
        reply, model = llm.generate(system_prompt, user_prompt, question, allow_cloud=cloud_ok)
        trace("generation", model=model,
              promptId="payment_system_prompt" if payment_issue else "system_prompt_base")
        reply = textclean.clean_for_display(reply)
        reply = validate.autofix(reply)
        reply = _add_nri_scope_caveat(question, top, reply)
        pages = sorted({e["page"] for e in top})
        source = "payment-issue" if payment_issue else "rag"

        # English-only for the LLM-check/regenerate tier (see
        # validate.py/config.py) - Hetzner's PASS/FAIL reliability on
        # Devanagari/Tamil output is unverified, and this project has
        # repeatedly burned itself checking a cross-lingual assumption only
        # after shipping it. Non-English replies still get the free
        # deterministic pass (unsupported_number/topic_mismatch), just
        # without the LLM escalation/regeneration on top.
        flagged = False
        if config.VALIDATION_ENABLED:
            if language == "latin" and not typed_romanized:
                nri_postprocess = lambda r: _add_nri_scope_caveat(question, top, r)  # noqa: E731
                reply, model, reasons, regenerated = validate.check_and_regenerate(
                    question, context, reply, model, system_prompt, user_prompt,
                    postprocess=nri_postprocess, own_project_id=project_id)
            else:
                reasons = validate.deterministic_checks(question, context, reply, project_id)
                regenerated = False
            trace("validation", reasons=reasons, regenerated=regenerated)
            flagged = bool(reasons) and not regenerated
            if reasons:
                reviewlog.append(projects.review_log_path(project_id), {
                    "kind": "validation_regenerated" if regenerated else "validation_flag",
                    "reasons": reasons, "source": source,
                })

    # Auto-cache the native-script answer so the next similar ask is instant,
    # regardless of which script_pref that later ask uses. `verified` is
    # stored alongside so a future hit on this entry can be re-checked
    # against a fresh table lookup before being served (see the cache-check
    # above) - entries with no verified figure (open-ended answers) skip that
    # extra check and stay on the fast path.
    faq_id = None
    # A FLAGGED answer is never cached. Without this, one bad answer produced
    # in a bad moment becomes the permanent answer: traced 2026-08-17, where
    # "I got 48% in PCB and English... reserved category?" was answered
    # correctly in ~1.0s by the eligibility guard on a clean cache, but a
    # single earlier run that took 71.6s down the retrieval path wrote its
    # wrong answer here - and every later ask was then served that wrong
    # answer from cache, indistinguishable from a pipeline that had regressed.
    # Hours of this session's "intermittency" were that, not randomness.
    #
    # Deliberately keyed on `flagged` rather than `reasons`: a regenerated
    # answer had reasons too, and it was rewritten precisely so it could be
    # trusted. Caching that one is the point of regenerating it.
    if config.FAQ_AUTOCACHE and not flagged:
        faq_id = faq.add(projects.faq_path(project_id), question, reply, pages, query_vector,
                          cache_tags, verified=verified)

    display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
    trace("final_answer", answer=display, source=source, model=model, pages=pages,
          speakable=speakable, language=language)
    return {"answer": display, "pages": pages, "model": model, "language": language,
            "source": source, "speakable": speakable, "faqId": faq_id}


def answer(project_id, question, script_pref="auto", ui_language=None, history=None,
           trace_id=None):
    """Student -> intent -> FAQ cache -> RAG -> LLM -> answer.

    Returns {answer, pages, model, language, source, speakable}. `source` is
    'faq-cache' for an instant cache hit, otherwise 'rag'. Greetings short-circuit
    before any of it. `script_pref` ("auto" | "native") controls Hindi/Marathi/Tamil
    output script - romanized (Hinglish/Tanglish) is the default since that's how
    most students actually type and read, "native" is the explicit opt-in for
    Devanagari/Tamil script. Romanized answers come back non-speakable since the
    TTS voice can't pronounce Romanized text correctly. `ui_language` ("en" | "hi" |
    "mr" | "ta" | None) is the language the student picked in the app's own
    selector - used to explicitly disambiguate Hindi vs Marathi for the model
    instead of leaving it to guess from the question's wording alone (see
    _language_hint). Every call is timed and recorded (counts/timing only, never
    question text) for that project's own dashboard and cost panel.
    """
    t0 = time.time()
    result = _answer(project_id, question, script_pref, ui_language, history,
                     trace_id=trace_id)
    stats.record(projects.stats_path(project_id), result["source"], result["model"],
                 result["language"], round((time.time() - t0) * 1000))
    return result
