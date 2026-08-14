"""The guard stage - Request 2's structural "ask/route before cache" guarantee.

Every early-return that must happen before the FAQ cache or any retrieval
runs lives here as one guard function in GUARDS, checked in order by
run_guards(). The cache lookup physically lives inside answer.py's
_pipeline(), which is only reachable once every guard has returned None -
a future 7th guard is a two-line change (write the function, append it to
GUARDS), and it is automatically checked before cache by construction,
not by getting the order of an if/elif chain right in a 1000-line function.

Each guard unpacks the `ctx` fields it needs into locals at the top (see
answer.py's _build_context for what ctx carries) and its body is otherwise
an unmodified move from rag.py's old _answer() - see git history for the
pre-move inline sequence if you need to diff against it. Returns a fully-
formed answer dict, or None to fall through to the next guard.
"""

from . import citation, comparison
from .helpers import (_apply_script_pref, _assistant_scope, _greeting_prompt, _injection_refusal,
                       _program_name, is_greeting)
from .. import config
from ..core import eligibility, programs
from ..core import textclean
from ..core.intent import is_prompt_injection, needs_percentage_clarification
from ..generation import embeddings, llm
from ..storage import projects, vectorstore
from ..prompts.system import ELIGIBILITY_FACTS_PROMPT, ELIGIBILITY_SYSTEM_PROMPT
from ..prompts.canned import (_DISPUTE_PROMPT, _META_ACKNOWLEDGE_TEXT, _OFF_TOPIC_TASK_PROMPT,
                               _UNKNOWN_PROGRAMME_TEXT,
                               _PROGRAM_LIST_TEXT,
                               _OFF_TOPIC_TRIVIA_PROMPT, _PERCENTAGE_CLARIFY_TEXT,
                               _PROGRAM_CLARIFY_TEXT)


def _clarify_language(ctx):
    """Which language a fixed guard reply should be written in.

    hint_language first (the explicit picker, when it agrees with what was
    actually typed), then the raw ui_language - and finally the question's
    own SCRIPT. That last fallback is the fix: a caller that sends no
    uiLanguage left both of the first two empty, so a Tamil question was
    answered "Which program are you asking about?" in English. The script is
    unambiguous evidence of what the student reads, and Devanagari defaults
    to Hindi only because these canned texts have no separate Marathi-vs-
    Hindi signal to go on at this point - detect_devanagari_hi_mr has
    already had its say via hint_language when it had an opinion.
    """
    explicit = ctx.hint_language or ctx.ui_language
    if explicit:
        return explicit
    if ctx.language == "tamil":
        return "ta"
    if ctx.language == "devanagari":
        return "hi"
    return "en"


_LIST_TRIGGERS = {"what", "which", "list", "all", "available", "offer",
                   "offered", "have", "there", "tell", "kaun", "konte"}
_LIST_NOUNS = {"program", "programs", "programme", "programmes", "course",
                "courses", "degree", "degrees", "अभ्यासक्रम", "कार्यक्रम",
                "कोर्स", "पदवी"}
# Any of these means the question is about a PROPERTY of the programmes
# rather than the set itself, so it belongs to the comparison path.
_LIST_ATTRIBUTE_WORDS = {"fee", "fees", "cost", "eligibility", "eligible",
                          "percentage", "marks", "seat", "seats", "date",
                          "dates", "deadline", "neet", "cet", "exam",
                          "document", "documents", "quota", "reservation",
                          "apply", "admission", "hostel", "duration"}


def _routed(ctx, field):
    """The router's verdict for `field`, or None when there is no usable
    routing decision (unavailable, or too unsure to act on).

    Low-confidence classifications are deliberately dropped rather than
    trusted-with-a-caveat: every caller's fallback is the deterministic
    keyword logic that shipped before the router existed, which is a known
    quantity. "The model was not sure" is a reason to use the predictable
    path, not a reason to guess.
    """
    route = getattr(ctx, "route", None)
    if not route or route["confidence"] == "low":
        return None
    return route[field]


def _injection_guard(ctx):
    question = ctx.question
    project_id = ctx.project_id
    ui_language = ctx.ui_language
    language = ctx.language
    # Intent: instruction-override attempt. Answered from a fixed string with no
    # model call at all, so there is no generation to comply and nothing to
    # auto-cache - the model cannot get this wrong even once. Placed ahead of
    # every other branch because an injection attempt wrapped around an otherwise
    # ordinary-looking question must not reach retrieval or the LLM.
    # Either signal is enough, deliberately. This is the one guard where the
    # two sources are OR'd rather than the router taking over: a missed
    # injection reaches the model, while a false positive costs one honest
    # question a refusal it can recover from by rephrasing. The asymmetry
    # justifies keeping both nets up.
    if is_prompt_injection(question) or _routed(ctx, "intent") == "instruction_override":
        refusal = _injection_refusal(project_id, ui_language)
        return {"answer": refusal, "pages": [], "model": "guard", "language": language,
                "source": "instruction-override", "speakable": True}
    return None


def _greeting_guard(ctx):
    question = ctx.question
    project_id = ctx.project_id
    hint = ctx.hint
    cloud_ok = ctx.cloud_ok
    language = ctx.language
    script_pref = ctx.script_pref
    typed_romanized = ctx.typed_romanized
    trace = ctx.trace
    # Intent: greeting short-circuit (no retrieval, no cache). The model
    # allotter's one real decision point: a plain "hey" doesn't need Sarvam's
    # Indic-tuned reasoning, so it gets the fast lane (config.GREETING_PROVIDER,
    # e.g. Groq) instead of paying the same ~20s round trip a real retrieval-
    # backed answer does. Gated on language, not just "is this a greeting" -
    # a native-script greeting ("नमस्ते") still needs the quality/Indic-tuned
    # lane, because a general-purpose fast model with no Indic tuning has
    # repeatedly failed this codebase (wrong script, garbled, or silently
    # reverting to English - see config.GROQ_API_KEY's docstring). Recorded as
    # its own "model_routing" trace step so this decision is visible live,
    # not just implied by which model label shows up on the final answer.
    # generate_scoped returns None on any failure (unconfigured, timeout, HTTP
    # error) rather than raising, so an unconfigured or misbehaving fast lane
    # silently falls through to the original full primary/fallback chain -
    # never a broken greeting.
    # Router first (it recognizes greetings the word list never enumerated,
    # in any language), keyword list when it has no confident opinion.
    routed_intent = _routed(ctx, "intent")
    is_a_greeting = routed_intent == "greeting" if routed_intent else is_greeting(question)
    if is_a_greeting:
        result = None
        if language == "latin":
            result = llm.generate_scoped(config.GREETING_PROVIDER, _greeting_prompt(project_id),
                                          question + hint, question, timeout=20, allow_cloud=cloud_ok)
        lane = "fast" if result is not None else "quality"
        trace("model_routing", lane=lane,
              provider=config.GREETING_PROVIDER if lane == "fast" else config.CHAT_PRIMARY,
              reason=("simple greeting, English - fastest reply model" if lane == "fast"
                      else "native-language reply needs the Indic-tuned model" if language != "latin"
                      else "fast lane unavailable - using the quality chain instead"))
        if result is None:
            result = llm.generate(_greeting_prompt(project_id), question + hint, question, timeout=120, allow_cloud=cloud_ok)
        reply, model = result
        reply = textclean.clean_for_display(reply)
        display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "greeting", "speakable": speakable}
    return None


def _dispute_guard(ctx):
    """The student is challenging whether a fact we gave is true.

    This is the one moment a citation earns its place. Normal answers show no
    page references at all now (a row of "p. 5 p. 9 p. 13" under every reply
    read as homework - the student came here because the PDF didn't help), so
    the whole citation budget is spent here, and spent precisely: the real
    page, the real line number, and the line quoted verbatim, straight out of
    the PDF rather than out of the model (see citation.py).

    The wording deliberately holds its ground instead of folding. Caving to
    "that's wrong" when the prospectus plainly says otherwise would make every
    correct answer negotiable; pointing at the exact line lets the student
    check it themselves in seconds and settles it either way.

    Falls through to the normal pipeline whenever there is nothing solid to
    stand on - no prior answer to defend, or no line that matches well enough
    to cite honestly (citation.locate returns [] rather than its best guess).
    """
    if _routed(ctx, "intent") != "dispute_answer":
        return None
    prior = next((t["text"] for t in reversed(ctx.history)
                  if t.get("role") == "assistant" and t.get("text")), "")
    if not prior:
        return None

    # Search the same prospectus the disputed claim came from, restricted to
    # the pages this question actually retrieves - citing a well-matching
    # line from an unrelated part of the document would be worse than not
    # citing at all.
    query = _routed(ctx, "resolved_question") or ctx.question
    try:
        query_vector = embeddings.embed([query])[0]
        store = vectorstore.load(projects.store_path(ctx.project_id))
        top = vectorstore.search(store, query_vector, config.TOP_K, query)
    except Exception as exc:  # noqa: BLE001 - never break the reply over this
        print(f"[dispute] retrieval failed: {exc!r}")
        return None
    pages = sorted({e["page"] for e in top})
    hits = citation.locate(ctx.project_id, prior + " " + query, pages)
    ctx.trace("citation", found=len(hits),
              cites=[{"page": h["page"], "line": h["line"]} for h in hits])
    if not hits:
        return None

    context = "\n".join(f'Page {h["page"]}, line {h["line"]}: {h["text"]}' for h in hits)
    prompt = _DISPUTE_PROMPT.format(program=_assistant_scope(ctx.project_id)) + llm.LANGUAGE_RULE
    user_prompt = (
        f"You previously told the student: {prior}\n\n"
        f"They are now disputing it. These are the exact lines from the prospectus:\n{context}\n\n"
        f"Their message: {ctx.question}{ctx.hint}"
    )
    result = llm.generate_scoped(config.GREETING_PROVIDER, prompt, user_prompt,
                                  ctx.question, timeout=25, allow_cloud=ctx.cloud_ok)
    if result is None:
        result = llm.generate(prompt, user_prompt, ctx.question, timeout=90,
                              allow_cloud=ctx.cloud_ok)
    reply, model = result
    reply = textclean.clean_for_display(reply)
    # The citation itself is appended in code, never left to the model to
    # reproduce - a hallucinated page/line here would defeat the entire point
    # of standing firm, and this is the one claim in the answer that must be
    # exactly right.
    lines = "\n".join(f'Page {h["page"]}, line {h["line"]}: "{h["text"]}"' for h in hits)
    reply = f"{reply}\n\nStraight from the prospectus:\n{lines}"
    display, speakable = _apply_script_pref(reply, ctx.language, ctx.script_pref, ctx.typed_romanized)
    return {"answer": display, "pages": [h["page"] for h in hits], "model": model,
            "language": ctx.language, "source": "cited-source", "speakable": speakable}


def _meta_correction_guard(ctx):
    """The student is talking about the CONVERSATION, not asking about
    admissions - correcting a wrong assumption, disputing the last answer,
    asking what was meant.

    Purely router-driven, with no keyword fallback, because no keyword check
    can detect this: the reported failure was "I didn't say I want to get in
    bfsc?" being answered with a B.F.Sc. program overview, precisely BECAUSE
    the literal string "bfsc" appears in a sentence that denies wanting it.
    A matcher sees the token; only reading the sentence sees the negation.
    When the router is unavailable these messages fall through to the normal
    pipeline exactly as they did before - no worse than the old behavior.

    Answered from a fixed, retrieval-free acknowledgement rather than a
    generated one: there is nothing in the prospectus to look up, and the
    honest move is to hand control back to the student instead of guessing
    what they meant a second time.
    """
    if _routed(ctx, "intent") != "meta_or_correction":
        return None
    # Structural backstop, independent of how well the classification is
    # worded: if the router extracted an information need, there is something
    # to ANSWER, so never spend the turn apologizing instead. Reproduced
    # directly - "explain quotas in simple terms" (a plain follow-up asking
    # for a simpler re-explanation) was classified meta_or_correction and
    # answered with "sorry, I got that wrong", which is the same
    # not-listening failure this guard was added to fix, just wearing a
    # different hat. A message that both corrects AND asks gets the answer;
    # only a pure correction, with nothing asked, reaches the acknowledgement.
    if _routed(ctx, "resolved_question"):
        return None
    clarify_lang = _clarify_language(ctx)
    text = _META_ACKNOWLEDGE_TEXT.get(clarify_lang, _META_ACKNOWLEDGE_TEXT["en"])
    return {"answer": text, "pages": [], "model": "guard", "language": ctx.language,
            "source": "meta-correction", "speakable": True}


def _off_topic_guard(ctx):
    """A question with nothing to do with admissions - trivia, or a request to
    perform an unrelated task.

    Short-circuits before retrieval and before the cache, which is the point:
    these used to run the full pipeline, embedding the question, searching the
    prospectus and spending one of the metered daily Sarvam calls to answer
    "what colour is the sky" - flagged directly as wasteful. Now they never
    touch retrieval and are answered on the fast lane (same provider as the
    greeting short-circuit), so an off-topic message costs neither quota nor
    latency.

    Router-only, no keyword fallback: "off topic" is defined by everything a
    question ISN'T about, which is not a list any marker set can hold. Falls
    through to the normal pipeline when the router is unavailable, where the
    system prompt's own off-topic rule still handles it - slower and at the
    cost of a Sarvam call, but correct.
    """
    intent = _routed(ctx, "intent")
    if intent not in ("off_topic_trivia", "off_topic_task"):
        return None
    prompt = (_OFF_TOPIC_TRIVIA_PROMPT if intent == "off_topic_trivia"
              else _OFF_TOPIC_TASK_PROMPT).format(program=_assistant_scope(ctx.project_id))
    result = llm.generate_scoped(config.GREETING_PROVIDER, prompt + llm.LANGUAGE_RULE,
                                  ctx.question + ctx.hint, ctx.question,
                                  timeout=20, allow_cloud=ctx.cloud_ok)
    if result is None:
        result = llm.generate(prompt + llm.LANGUAGE_RULE, ctx.question + ctx.hint,
                              ctx.question, timeout=60, allow_cloud=ctx.cloud_ok)
    reply, model = result
    reply = textclean.clean_for_display(reply)
    display, speakable = _apply_script_pref(reply, ctx.language, ctx.script_pref, ctx.typed_romanized)
    return {"answer": display, "pages": [], "model": model, "language": ctx.language,
            "source": "off-topic", "speakable": speakable}


def _program_list_guard(ctx):
    """"What programmes do you offer?" - answered from the registry, not the
    prospectus and not a model.

    Reported directly: "what all program there is?" was met with "Which
    program are you asking about?" and a list of six buttons. The router had
    even understood it correctly ("what are the available programmes?") and
    still set needs_program_clarification, because the deterministic rule
    behind that flag only asks "does the answer vary per programme, and did
    they name one?" - which is true here, yet the question is precisely a
    request for the list. Asking someone to pick from a list in order to
    tell them what the list is, is the most literal possible not-listening.

    Deterministic and model-free: the assistant knows its own programmes
    (programs.PROGRAM_NAMES), so there is nothing to retrieve and nothing to
    get wrong. Placed ahead of comparison and clarification, both of which
    would otherwise claim this question.

    Deliberately narrow. A question about an ATTRIBUTE across programmes
    ("which courses require NEET", "what are the fees for all courses") is a
    real comparison and must fall through - it is only the bare "what is on
    offer" that is answered here.
    """
    question = ctx.question
    words = programs._words(question)
    asks_for_set = bool(words & _LIST_TRIGGERS) and bool(words & _LIST_NOUNS)
    if not asks_for_set:
        return None
    # An attribute word means they want those programmes COMPARED on
    # something, which the comparison path handles properly.
    if words & _LIST_ATTRIBUTE_WORDS:
        return None
    if programs.detect_program(question):
        return None

    names = list(programs.PROGRAM_NAMES.values())
    lang = _clarify_language(ctx)
    lead = _PROGRAM_LIST_TEXT.get(lang, _PROGRAM_LIST_TEXT["en"]).format(count=len(names))
    body = lead + "\n\n" + "\n".join(names)
    options = [{"projectId": pid, "label": name}
               for pid, name in programs.PROGRAM_NAMES.items()]
    return {"answer": body, "pages": [], "model": "guard", "language": ctx.language,
            "source": "program-list", "speakable": True, "clarifyOptions": options}


def _percentage_clarify_guard(ctx):
    question = ctx.question
    language = ctx.language
    hint_language = ctx.hint_language
    ui_language = ctx.ui_language
    # Ambiguous personal percentage: checked BEFORE cross-program comparison
    # below, since a question naming several programs at once ("am I eligible
    # for bvsc, bfsc, b.tech?") would otherwise reach the comparison path
    # first and get answered (possibly inconsistently per program - the
    # reported bug) instead of asked about. See
    # intent.needs_percentage_clarification's docstring.
    routed_ambiguous = _routed(ctx, "self_score_ambiguous")
    ambiguous = (routed_ambiguous if routed_ambiguous is not None
                 else needs_percentage_clarification(question, language))
    if ambiguous:
        # Same "picked by hint_language, not just the raw UI selector" rule
        # as _program_clarify_guard below - a Hindi/Marathi question that
        # trips the guard must not get an English clarification back.
        clarify_lang = _clarify_language(ctx)
        text = _PERCENTAGE_CLARIFY_TEXT.get(clarify_lang, _PERCENTAGE_CLARIFY_TEXT["en"])
        return {"answer": text, "pages": [], "model": "guard",
                "language": language, "source": "clarify-percentage", "speakable": True}
    return None


def _eligibility_guard(ctx):
    """Decide "am I eligible?" in code; let the model only phrase the verdict.

    Runs BEFORE _percentage_clarify_guard, and only acts when the verdict is
    genuinely determinable - returning None otherwise, so a student who cited
    a bare "60%" still gets asked what it is of. The order matters the other
    way round too: with clarify first, "I have 51% overall but only 45% in PCB
    and English" was answered with "is that your overall score or those
    subjects?", a question the student had already answered in the same
    sentence.

    Why it exists: the 2026-08-14 evaluation failed four of these, and every
    failure was a comparison performed inside fluent prose rather than a
    retrieval problem. Q25 measured a 51% aggregate against a rule the
    prospectus states on the subject combination and told a student with 45%
    in those subjects that they were eligible. Q13 and Q28 used 40% where
    B.V.Sc. reserved is 47.50%. Q50 asserted no lower reserved threshold
    exists at all, four questions before stating it correctly.

    A verdict of "insufficient" deliberately returns None and lets the normal
    pipeline answer - this guard replaces the arithmetic, not the assistant.
    """
    if not config.ELIGIBILITY_GUARD_ENABLED:
        return None
    original = getattr(ctx, "original_question", ctx.question)
    project_id = ctx.project_id
    # Scoped to a programme whose thresholds we hold. On the general widget a
    # programme the student named routes here via target_programs; with none
    # named there is nothing to evaluate against.
    routed = _routed(ctx, "target_programs") or []
    named = programs.detect_program(original)
    if project_id == config.DEFAULT_PROJECT_ID:
        # The student's OWN words first; the router only as a fallback. Taking
        # routed[0] ahead of detect_program made this guard tell a student who
        # asked about "veterinary" that they were not eligible for B.Tech.
        # (Dairy Technology) because they had no Mathematics - a confident
        # verdict about a course they never mentioned. Same corroboration rule
        # the redirect guard already follows, and the same reason.
        candidate = named or (routed[0] if len(routed) == 1 else None)
    else:
        candidate = project_id
    # Threshold LOOKUPS ("what percentage do SC/ST/OBC candidates need?")
    # carry no marks, so evaluate() would report insufficient and let them
    # fall through to retrieval - which answered Q50 with "50%, and no
    # separate lower threshold for these categories", turning eligible
    # reserved-category students away four questions before stating the real
    # 47.50% correctly. Answered from the table instead.
    # Never answer a threshold lookup about a programme we do not serve. This
    # branch quoted B.V.Sc.'s 47.5% at "what is the minimum percentage
    # required for Ph.D. admission?" and at an M.V.Sc. question - the exact
    # undergraduate-figures-for-a-postgraduate-question trap the retired-
    # programme refusal exists to prevent, reintroduced by a fast path that
    # never asked whose requirement was being requested.
    if _routed(ctx, "unknown_programme") or programs.mentions_foreign_course(original):
        return None

    if eligibility.is_threshold_question(original):
        rows = eligibility.thresholds_for(original, candidate)
        if rows:
            ctx.trace("eligibility", kind="threshold_lookup", rows=len(rows))
            facts = _threshold_facts(rows)
            spoken = llm.generate_scoped(
                config.CHAT_PRIMARY, ELIGIBILITY_FACTS_PROMPT, facts + ctx.hint,
                ctx.question, timeout=60, allow_cloud=ctx.cloud_ok)
            if spoken is not None:
                text, model = spoken
                return {"answer": textclean.clean_for_display(text),
                        "pages": sorted({r[4] for r in rows}),
                        "model": model, "language": ctx.language,
                        "source": "eligibility", "speakable": True}
        return None

    # Verdicts need a specific programme's thresholds; lookups did not.
    if candidate not in eligibility.RULES:
        return None

    result = eligibility.evaluate(candidate, original)
    if result["verdict"] not in ("eligible", "not_eligible"):
        return None

    ctx.trace("eligibility", verdict=result["verdict"], programme=result.get("programme"),
              stated=result.get("stated"), required=result.get("required"),
              reason=result.get("reason"))

    facts = _eligibility_facts(result)
    reply = llm.generate_scoped(
        config.CHAT_PRIMARY, ELIGIBILITY_SYSTEM_PROMPT, facts + ctx.hint,
        ctx.question, timeout=60, allow_cloud=ctx.cloud_ok)
    if reply is None:
        # Never fail the student's question because the phrasing call fell
        # over - the verdict is already decided, so say it plainly.
        return None
    answer_text, model = reply
    return {"answer": textclean.clean_for_display(answer_text),
            "pages": [result.get("page")] if result.get("page") else [],
            "model": model, "language": ctx.language,
            "source": "eligibility", "speakable": True}


def _threshold_facts(rows):
    """The requirement table, written out for the model to say aloud.

    Every programme is listed when the question did not pin one down, because
    the reserved threshold really does differ between them - 47.50% for
    B.V.Sc. against 40% for the other two - so any single figure would be
    wrong for two thirds of the people asking.
    """
    lines = ["FACTS (already verified against the prospectus, state exactly these "
             "and introduce no other number):"]
    for label, category, percent, subjects, page in rows:
        lines.append(f"- {label}, {category} category: {percent}% in {subjects}, "
                     f"taken together.")
    lines.append("The percentage is on those subjects TAKEN TOGETHER, not on the "
                 "overall 12th aggregate - say so, because students routinely "
                 "assume it is their overall percentage.")
    if len({r[0] for r in rows}) > 1:
        lines.append("They did not say which programme, and the requirement is not "
                     "the same for all of them, so give each one rather than "
                     "picking a single figure.")
    lines.append("Do not say the prospectus fails to specify a reserved-category "
                 "requirement - it specifies one, and it is listed above.")
    return "\n".join(lines)


def _eligibility_facts(result):
    """The computed verdict, written out as facts for the model to phrase.

    Deliberately states the verdict as already-decided rather than handing
    over the numbers and asking for a conclusion - handing over the numbers
    is what produced the wrong answers this replaces.
    """
    programme = result.get("programme")
    if result["reason"] == "subjects":
        return (f"VERDICT (already decided, state exactly this): the student is NOT "
                f"eligible for {programme}. Reason: {programme} requires "
                f"{result['required_subjects']}, and they are missing: "
                f"{', '.join(result['missing'])}. Tell them this plainly and say what "
                f"the requirement is. Do not soften it into a maybe.")
    verdict = "IS eligible for" if result["verdict"] == "eligible" else "is NOT eligible for"
    lines = [
        f"VERDICT (already decided, state exactly this): the student {verdict} "
        f"{programme} on the marks they gave.",
        f"Their stated marks in {result['required_subjects']}: {result['stated']}%.",
        f"The requirement for the {result['category']} category: {result['required']}%.",
    ]
    if result.get("category_assumed"):
        lines.append("They did not state a category, so this used the Unreserved "
                     "requirement - say so, and mention the reserved requirement is "
                     "lower, so they can correct you if they are in a reserved category.")
    if result["verdict"] == "eligible" and result.get("entrance"):
        lines.append(f"Meeting this threshold is only the eligibility bar - they must "
                     f"also have {result['entrance']}. Mention that, briefly.")
    lines.append("Lead with the verdict in the first sentence. Do not re-derive it, "
                 "do not hedge it, and do not quote any other percentage.")
    return "\n".join(lines)


def _comparison_guard(ctx):
    question = ctx.question
    script_pref = ctx.script_pref
    ui_language = ctx.ui_language
    language = ctx.language
    hint_language = ctx.hint_language
    hint = ctx.hint
    typed_romanized = ctx.typed_romanized
    cloud_ok = ctx.cloud_ok
    # Cross-program comparison: a question that genuinely spans several
    # programs ("which courses require NEET vs MHT-CET", "compare B.V.Sc.
    # and B.F.Sc.") checked BEFORE the single-program redirect below, since
    # detect_program alone would only ever catch the first-named program and
    # silently drop the rest. See programs.needs_comparison's docstring for
    # why this was added: a live benchmark found the single-project-scoped
    # answer either honestly refused these outright or answered incompletely
    # from only one program with no indication anything was missing.
    routed_comparison = _routed(ctx, "is_comparison")
    is_comparison = (routed_comparison if routed_comparison is not None
                     else programs.needs_comparison(question))
    # On a programme-scoped widget, only compare when the student named the set
    # themselves. Otherwise they are already inside one programme and a
    # cross-programme answer is a scope leak rather than extra helpfulness:
    # "can I apply if I took Biology instead of Maths?" on the B.Tech widget
    # came back covering all three and led with B.V.Sc. The router is not the
    # thing to fix - reading a Biology/Maths contrast as a comparison is
    # defensible - so the scope check sits downstream of it and applies
    # whichever source set the flag.
    if is_comparison and ctx.project_id != config.DEFAULT_PROJECT_ID:
        if not programs.comparison_is_explicit(
                getattr(ctx, "original_question", question)):
            ctx.trace("routing", decision="comparison_declined_scoped",
                      projectId=ctx.project_id)
            is_comparison = False
    if is_comparison:
        # Prefer the programs the router says are actually being asked about -
        # it excludes ones named only as the student's own prior degree, or
        # named in order to rule them OUT, which the alias matcher counts
        # either way. Needs 2+ to be a real comparison set; below that fall
        # back to comparison_targets' own default (the three UG programs).
        routed_targets = _routed(ctx, "target_programs") or []
        target_programs = (routed_targets if len(routed_targets) >= 2
                           else programs.comparison_targets(
                               getattr(ctx, "original_question", question)))
        ctx.trace("routing", decision="comparison", targetPrograms=target_programs)
        return comparison._answer_comparison(target_programs, question,
                                   script_pref, ui_language, language, hint_language,
                                   hint, typed_romanized, cloud_ok, ctx.trace)
    return None


def _program_redirect_guard(ctx):
    question = ctx.question
    project_id = ctx.project_id
    # Program disambiguation/redirect.
    # The router's target list is the meaning-aware version of
    # detect_program: it already excludes a program named only as the
    # student's own completed degree, or named in order to deny it. Exactly
    # one target means "this question is about that program".
    # Detected against what the student ACTUALLY typed, never ctx.question.
    # ctx.question is the router's rewrite, and the router is instructed to
    # strip the programme name out of it (it belongs in target_programs).
    # So when the router also returns an empty target list - which it does,
    # observed, for a message containing the literal word "bvsc" - the
    # programme has been erased from both places at once and the question
    # looks unattributed. Reproduced: "what is the application fee for bvsc"
    # answered with "Which program are you asking about?".
    original = getattr(ctx, "original_question", question)
    # A redirect moves the answer to ANOTHER programme's prospectus, so it
    # demands evidence in the text - not the router's word alone. The router
    # returned target_programs=['bfsc'] for "which subjects do I need in
    # 12th", a question naming no programme whatsoever, and the guard duly
    # sent a request made on the B.TECH key to B.F.Sc., which answered
    # "Physics, Chemistry, Biology and English" - correct for B.F.Sc.,
    # wrong for B.Tech (Mathematics), and indistinguishable from a real
    # answer. A scoped widget must never be hijacked to another programme
    # by a hallucinated target.
    #
    # detect_program is the corroboration: it only fires on an alias
    # actually present in what the student typed. The router still decides
    # WHICH programme when several are named or the wording is oblique; it
    # just cannot conjure one out of nothing.
    detected = programs.detect_program(original)
    routed_targets = _routed(ctx, "target_programs")
    if routed_targets and len(routed_targets) == 1 and detected:
        named_program = routed_targets[0]
    else:
        named_program = detected
    if named_program and named_program != project_id:
        # Explicitly names a DIFFERENT program than the one this request is
        # currently scoped to ("what is the B.Tech Dairy fee" typed into the
        # default widget, or - the case that motivated widening this beyond
        # the default project on 2026-08-12 - "eligibility for bvsc
        # admission" asked on the M.V.Sc. project after a student used the
        # header's program-switcher pill to move there and then asked about
        # a different program without switching back). Originally gated to
        # `project_id == config.DEFAULT_PROJECT_ID` on the reasoning that
        # every other project's widget was permanently scoped to one program
        # by which API key it was embedded with, so a mismatched question
        # there couldn't happen - true until the switcher pill (see
        # app.js's ProgramPicker) let a single session's apiKey move between
        # projects mid-conversation. Reproduced directly: on the mvsc
        # project, "what are the eligibilities required for bvsc admission?"
        # matched mvsc's own cached "What are the eligibility criteria for
        # admission?" entry (M.V.Sc.'s prerequisite CGPA figures, which
        # legitimately reference a B.V.Sc. degree - so not even a wrong
        # cache entry, just the wrong project's answer to a question that
        # named a different one) and answered confidently instead of
        # redirecting. Answer from that program's own data directly rather
        # than silently answering from the current project's excerpts, which
        # would just be a confident wrong-program answer. A plain recursive
        # call, not a client-side key switch: this same backend process
        # already has direct access to any project's rag pipeline via
        # project_id, so there's no need to round-trip through the frontend
        # for this path (contrast the ambiguous case below, which genuinely
        # cannot be resolved without asking - the backend has no way to
        # guess among six).
        redirected = ctx.reanswer(named_program)
        redirected["answeredForProgram"] = named_program
        return redirected
    return None


def _unknown_programme_guard(ctx):
    """The student named a course this university's assistant does not cover.

    Answered from a fixed list, with no retrieval and no model call, because
    the failure being fixed is the assistant answering ANYWAY. Asked "what is
    the fee for the MBA programme" it replied "Rs. 62,635 for unreserved
    category" - B.V.Sc.'s admission fee, quoted fluently under the name of a
    course MAFSU does not run. Nothing in the reply hinted it was about a
    different degree.

    That is the same family as the Ph.D. figure served under B.V.Sc.'s
    heading: retrieval always returns its best match, and "best match" is
    never empty, so a question about something absent from the corpus comes
    back looking exactly like a question about something present in it.

    Runs after the programme-redirect guard so a question naming one of OUR
    programmes is routed there first, and only a genuinely foreign course
    reaches this.
    """
    # Either signal is enough. The router flags Ph.D. reliably but not
    # M.V.Sc. - too close in shape to B.V.Sc. - so three M.V.Sc. questions
    # were answered from the B.V.Sc. corpus, one of them explaining the
    # undergraduate migration procedure under the heading of a postgraduate
    # degree. Requiring the router's agreement meant the deterministic check
    # could only ever narrow this guard, never trigger it, which is the wrong
    # way round for a refusal whose job is to catch what routing missed.
    original_text = getattr(ctx, "original_question", ctx.question)
    if not (_routed(ctx, "unknown_programme")
            or programs.mentions_foreign_course(original_text)):
        return None
    # Corroboration, same principle as the redirect guard: if the student
    # actually named one of ours, this is not a foreign course whatever the
    # router thinks.
    original = getattr(ctx, "original_question", ctx.question)
    # "Naming one of ours" does not cancel a postgraduate marker. "Can I apply
    # for M.V.Sc. if my veterinary degree is from another university?" names
    # B.V.Sc. via "veterinary" - as the student's OWN prior degree - and that
    # match used to cancel the refusal, so the question was answered with
    # B.V.Sc.'s undergraduate migration procedure under an M.V.Sc. heading.
    if programs.detect_program(original) and not programs.mentions_foreign_course(original):
        return None
    # Second corroboration: the student must actually have named a course.
    # The router read "MAFSU" - the university itself - as a foreign course
    # and this guard refused "How do I apply for MAFSU admission?" and "Where
    # can I find the MAFSU prospectus?", two of the most ordinary questions a
    # student asks, in 0.8s each. Turning away in-scope questions is a worse
    # and far more frequent failure than the wrong-corpus answer this guard
    # exists to prevent, so it now needs evidence in the student's own words.
    if not programs.mentions_foreign_course(original):
        ctx.trace("routing", decision="unknown_programme_declined_no_course_named")
        return None
    names = ", ".join(programs.PROGRAM_NAMES.values())
    lang = _clarify_language(ctx)
    text = _UNKNOWN_PROGRAMME_TEXT.get(lang, _UNKNOWN_PROGRAMME_TEXT["en"]).format(programmes=names)
    return {"answer": text, "pages": [], "model": "guard", "language": ctx.language,
            "source": "unknown-programme", "speakable": True}


def _program_clarify_guard(ctx):
    project_id = ctx.project_id
    question = ctx.question
    hint_language = ctx.hint_language
    ui_language = ctx.ui_language
    language = ctx.language
    if project_id == config.DEFAULT_PROJECT_ID:
        # The ambiguous case (no program named at all, but the topic varies
        # per program) stays default-only: on any other project, a bare "how
        # much is the fee" is unambiguous in context - it means that
        # project's fee - so there is nothing to clarify.
        # Deterministic veto: if the question literally names a programme,
        # never ask which programme it is about, whatever the router thinks.
        # Observed - "what is the application fee for bvsc" came back with
        # "Which program are you asking about?" because the router returned
        # an empty target list for a message containing the word bvsc, and
        # its clarify flag was trusted over plain evidence sitting in the
        # text. Asking someone to name something they just named is the
        # single most irritating failure this assistant has, and the keyword
        # matcher is exactly right about this narrow question.
        if programs.detect_program(getattr(ctx, "original_question", question)):
            return None
        routed_needs = _routed(ctx, "needs_program_clarification")
        needs_clarify = (routed_needs if routed_needs is not None
                         else programs.needs_program_clarification(question))
        if needs_clarify:
            # No program named at all, and the topic is one that genuinely
            # varies per program (see programs.py) - nothing useful to
            # search for or cache yet, so no retrieval or LLM call either.
            clarify_lang = _clarify_language(ctx)
            text = _PROGRAM_CLARIFY_TEXT.get(clarify_lang, _PROGRAM_CLARIFY_TEXT["en"])
            options = [{"projectId": pid, "label": name} for pid, name in programs.PROGRAM_NAMES.items()]
            return {"answer": text, "pages": [], "model": "guard", "language": language,
                    "source": "clarify-program", "speakable": True, "clarifyOptions": options}
    return None


GUARDS = [
    _injection_guard,
    _greeting_guard,
    # Both sit ahead of every clarification/routing guard below: a correction
    # or an off-topic message has no program to disambiguate and nothing to
    # retrieve, so asking "which program did you mean?" about it would be the
    # same not-listening failure they were added to fix.
    _dispute_guard,
    _meta_correction_guard,
    _off_topic_guard,
    _program_list_guard,
    _eligibility_guard,
    _percentage_clarify_guard,
    _comparison_guard,
    _program_redirect_guard,
    _unknown_programme_guard,
    _program_clarify_guard,
]


def run_guards(ctx):
    for guard in GUARDS:
        response = guard(ctx)
        # Traced from here, not inside each guard function, so every guard
        # gets this for free - an admin watching the live trace sees which
        # guards were checked and which one (if any) actually fired, in
        # order, without each of the 6 guard bodies needing its own
        # near-identical trace call.
        ctx.trace("guard", name=guard.__name__, fired=response is not None)
        if response is not None:
            # Emitted here for the same reason, and because without it a
            # guard-answered request NEVER closes its trace: the live console
            # marks a trace finished only when it sees final_answer, which
            # only _pipeline used to send. Every greeting, clarification,
            # correction and off-topic reply therefore sat on "Thinking..."
            # forever in the console while the student already had their
            # answer - reported directly, and visible as four stuck cards
            # against one that completed.
            ctx.trace("final_answer", answer=response.get("answer", ""),
                      source=response.get("source", "guard"),
                      model=response.get("model", "guard"),
                      pages=response.get("pages", []),
                      speakable=response.get("speakable", True),
                      language=response.get("language"))
            return response
    return None
