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

import re

from . import citation, comparison, router, validate
from .helpers import (_apply_script_pref, _assistant_scope, _greeting_prompt, _injection_refusal,
                       _program_name, is_greeting, resolve_conversation_slot)
from .. import config
from ..core import eligibility, programs
from ..core import textclean
from ..core.intent import is_prompt_injection, needs_percentage_clarification
from ..generation import embeddings, llm
from ..storage import projects, vectorstore
from ..prompts.system import (ELIGIBILITY_FACTS_PROMPT, ELIGIBILITY_PROGRAMMES_PROMPT,
                              ELIGIBILITY_SYSTEM_PROMPT)
from ..prompts.canned import (_DISPUTE_PROMPT, _ELIGIBILITY_CATEGORY_OPTIONS,
                               _ELIGIBILITY_CATEGORY_TEXT, _ELIGIBILITY_ENTRANCE_OPTIONS,
                               _ELIGIBILITY_ENTRANCE_TEXT, _META_ACKNOWLEDGE_TEXT,
                               _OFF_TOPIC_TASK_PROMPT, _SUBJECT_PERCENT_ASK_TEXT,
                               _UNKNOWN_PROGRAMME_TEXT,
                               _PROGRAM_LIST_TEXT, _TOPIC_MENU_LEAD_TEXT,
                               _OFF_TOPIC_TRIVIA_PROMPT, _PERCENTAGE_CLARIFY_TEXT,
                               _PERCENTAGE_SCOPE_OPTIONS, _PROGRAM_CLARIFY_TEXT)


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


# --- P2: knowledge-grounded topic/capability menu -------------------------
#
# A broad, unstructured request ("tell me about admission", "what can you
# help with?") has no single retrievable answer - it's a request for a MENU,
# not a question. Two worse shapes were both live before this guard existed:
# falling through to _general_fanout_guard below, which answers from all
# three programmes' corpora at once and produces a multi-paragraph wall of
# text nobody asked to read in full; or generating the menu itself with an
# LLM call, which risks the exact failure comparison.py's
# _fee_table_categories docstring documents this session - a structure
# invented from retrieved prose drifting from what the corpus actually
# contains. So the menu is a small, hand-maintained registry, mirroring
# programs.PROGRAM_NAMES's own "plain dict, no cleverness" shape, and the
# guard below does nothing but pattern-match the trigger and hand back a
# fixed list - no retrieval, no model call, nothing that can hallucinate a
# topic this assistant doesn't actually cover.
#
# Grouped to 6 entries rather than one chip per underlying topic (fee,
# eligibility, application process, dates, documents, seats, reservation,
# programmes - 8 in total) - agent-qustioning system.md section 15 caps a
# menu at "approximately 3-6 options" before it stops reading as a quick
# choice and starts reading as a form. "Dates & documents" and "Seats &
# reservation" are the two merges; both pairs already sit together in a real
# prospectus (the admission-process timeline lists its required documents
# alongside the dates, and the eligibility annexures state seat counts next
# to the reservation percentages), so grouping them loses nothing a student
# would notice as missing.
#
# Each entry's "question" is the exact text sent as a fresh /api/chat message
# when its chip is clicked (see app.js's pickTopic) - a complete, self-
# sufficient question on its own, which is why this needs none of
# pendingClarification's splice machinery (contrast
# _percentage_clarify_guard's scopeOptions just below, which answers only
# HALF a question and must be recombined with the one that came before it -
# see that guard's carryQuestion comment).
_TOPIC_MENU = [
    {"label": "Available programmes", "question": "What programmes do you offer?"},
    {"label": "Eligibility", "question": "What is the eligibility criteria?"},
    {"label": "Fees", "question": "What are the fees?"},
    {"label": "Application process", "question": "How do I apply?"},
    {"label": "Dates & documents", "question": "What are the important dates and documents required?"},
    {"label": "Seats & reservation", "question": "What are the seats and reservation rules?"},
]

# Phrases marking a message as a broad, unstructured request rather than a
# specific question - substring-matched against the lowercased ORIGINAL text
# (never ctx.question - same "detect from what the student actually typed"
# rule as programme detection, see this file's module docstring reference to
# ctx.original_question), same style as comparison.py's
# _ADMISSION_PROCESS_PHRASE. Deliberately a short, literal phrase list rather
# than a word-bag: a bag-of-words check on "tell"+"about"+"admission" would
# also fire on real, specific questions that happen to share those words
# ("please tell me about the admission FEE for B.V.Sc." should be answered
# directly, not menu'd), so this only matches the actual broad SHAPE of the
# request, not its individual words.
_BROAD_ADMISSION_PHRASES = (
    "tell me about admission", "tell me about the admission",
    "tell me about mafsu admission", "know more about admission",
    "information about admission", "information on admission",
    "details about admission", "details on admission",
    "guide me through admission", "guide me about admission",
)

# "What can you help with?" and its common rewordings - see agent-qustioning
# system.md section 11. Kept separate from _BROAD_ADMISSION_PHRASES above
# because the right LEAD TEXT differs (this is a question about the
# ASSISTANT's capabilities, not the admission process itself - see
# canned._TOPIC_MENU_LEAD_TEXT), even though both trigger the same fixed menu.
_CAPABILITY_QUESTION_PHRASES = (
    "what can you help", "what can you do", "how can you help",
    "what do you do", "what all can you do", "what are you able to help",
    "what services do you", "what do you know", "how do you help",
    "what kind of help", "what sort of help",
)

# Attribute words that mean a broad-SOUNDING question is actually SPECIFIC -
# reuses _LIST_ATTRIBUTE_WORDS above (the same hand-maintained vocabulary
# _program_list_guard already trusts to tell "what programmes exist" apart
# from "what are the fees for all programmes"), minus "admission" and
# "apply": both appear inside this guard's OWN trigger phrases ("tell me
# about ADMISSION" is the canonical broad example; "how do I APPLY?" is one
# of the menu's own resubmit questions above), so leaving them in the veto
# set would make the guard veto its own trigger phrase and its own menu.
_TOPIC_MENU_VETO_WORDS = _LIST_ATTRIBUTE_WORDS - {"admission", "apply"}


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
    # justifies keeping both nets up - EXCEPT the router-only path is now
    # vetoed by programs.is_shared_topic first. Reproduced live: "I uploaded
    # the wrong document. Can I upload it again?" - an entirely ordinary
    # admission-portal question - got refused outright with "I can only help
    # with admission questions", because the router alone (not
    # is_prompt_injection, which correctly found nothing) classified it as
    # instruction_override. A hard refusal is a worse failure here than the
    # asymmetry above accounts for: unlike a normal clarification, this
    # guard's refusal gives the student no path to "recover by rephrasing" -
    # they were already asking a plain, in-scope question. is_shared_topic
    # already recognizes "upload"/"resubmit"/"resubmission" as portal-
    # mechanics vocabulary for exactly this reason (see its own docstring);
    # reusing it here costs nothing new and closes the gap the same way it
    # already does for _program_clarify_guard.
    if is_prompt_injection(question):
        refusal = _injection_refusal(project_id, ui_language)
        return {"answer": refusal, "pages": [], "model": "guard", "language": language,
                "source": "instruction-override", "speakable": True}
    if _routed(ctx, "intent") == "instruction_override" and not programs.is_shared_topic(question):
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
        query_vector = embeddings.embed_query(query)
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


def _topic_menu_guard(ctx):
    """"Tell me about admission" / "what can you help with?" - a request for
    a MENU, not a question with one retrievable answer. See the registry
    comment above _TOPIC_MENU for why the options are hand-maintained rather
    than generated.

    Placed right after _program_list_guard: both are deterministic,
    registry-only replies with nothing to retrieve, and program_list is the
    narrower, more specific case - "what programmes do you offer" gets the
    actual programme names, not a generic menu that merely includes an
    "Available programmes" entry - so it must win when both could apply.
    Placed well before _general_fanout_guard/_low_confidence_clarify_guard
    (the last resorts before a model call answers from all three programmes
    at once): a broad request reaching either of those is exactly the
    "enormous wall of text nobody asked to read" failure this guard exists to
    head off, and neither of them has any notion of "ask instead of answer"
    for a request that isn't really a question yet.

    Purely deterministic pattern-matching - no router call and no LLM call
    anywhere in this guard (hard requirement, see the P2 task's constraints).
    Unlike every other guard in this file, there is no _routed()-with-
    fallback split here: router.py's classify() schema (_ROUTER_SYSTEM) has
    no field for "this is a broad/unstructured request" to begin with, so
    there is no router opinion to consult even as a first choice - the
    deterministic phrase match below is not a fallback, it's the only path.
    """
    # Soft context-awareness (agent-qustioning system.md section 6): once the
    # conversation already has an intent established - mid-eligibility-flow,
    # or a specific topic already picked this session - re-showing the full
    # broad menu is the same "not listening" failure this file's other guards
    # exist to prevent, just for a different trigger. Deliberately coarse: P1
    # (running in parallel on _eligibility_guard) is still defining what
    # values ctx.conversationState["intent"] actually takes, so this only
    # checks "is ANY intent already established" rather than reading a
    # specific value out of a vocabulary that may still change under it.
    # Narrowing this to "only suppress for intents that are genuinely
    # still-in-progress" is follow-up work once P1's values are settled - see
    # this guard's note in the P2 handoff.
    if ctx.conversationState.get("intent"):
        return None
    original = getattr(ctx, "original_question", ctx.question)
    lower = (original or "").lower()
    is_broad = any(p in lower for p in _BROAD_ADMISSION_PHRASES)
    is_capability = any(p in lower for p in _CAPABILITY_QUESTION_PHRASES)
    if not (is_broad or is_capability):
        return None
    # A specific attribute word means this is a real, answerable question
    # wearing broad-sounding phrasing ("tell me about the admission FEE") -
    # let it fall through to whichever guard/RAG actually answers it, rather
    # than intercepting with a generic menu that would bury the one thing
    # they asked for.
    if programs._words(original) & _TOPIC_MENU_VETO_WORDS:
        return None
    # A named programme means there is a specific corpus this could be
    # answered from directly ("tell me about B.V.Sc. admission") - leave it
    # to the redirect/comparison/RAG guards downstream, which already know
    # how to scope an answer to one programme. The generic multi-programme
    # menu below has nothing to add there and would be a worse answer than
    # what those guards already give to a question that named exactly what
    # it wanted.
    if programs.detect_program(original):
        return None

    lang = _clarify_language(ctx)
    # Capability wins the lead-text choice only when the message matched
    # NOTHING from _BROAD_ADMISSION_PHRASES - a message could in principle
    # match both lists, and "what would you like to know about admission"
    # is the better opening whenever the admission-process phrasing is
    # present at all.
    key = "capability" if is_capability and not is_broad else "broad"
    lead = _TOPIC_MENU_LEAD_TEXT[key].get(lang, _TOPIC_MENU_LEAD_TEXT[key]["en"])
    options = [{"value": t["question"], "label": t["label"]} for t in _TOPIC_MENU]
    return {"answer": lead, "pages": [], "model": "guard", "language": ctx.language,
            "source": "topic-menu", "speakable": True, "topicOptions": options}


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
        options = _PERCENTAGE_SCOPE_OPTIONS.get(clarify_lang, _PERCENTAGE_SCOPE_OPTIONS["en"])
        # carryQuestion: see _program_clarify_guard's identical field - the
        # widget arms pendingClarification with THIS text, and
        # chat_routes.py's is_bare_scope_reply branch splices the reply's
        # scope onto it rather than the bare question the student typed.
        return {"answer": text, "pages": [], "model": "guard",
                "language": language, "source": "clarify-percentage", "speakable": True,
                "scopeOptions": options, "carryQuestion": question}
    return None


# ---------------------------------------------------------------------------
# P1: guided eligibility interview - conversationState.intent markers this
# guard itself sets and reads (see resolve_conversation_slot's docstring for
# why conversationState is a per-guard-owned, lower-priority source of
# truth, never a router-style opinion). Three "still asking" states, one
# "just finished, might still be swapped" state kept for exactly one more
# turn (see is_category_swap in _eligibility_guard).
_INTERVIEW_ASKING_INTENTS = {
    "eligibility_awaiting_entrance", "eligibility_awaiting_category",
    "eligibility_awaiting_percent",
}
_INTERVIEW_RESOLVED_INTENT = "eligibility_resolved"
# Which markers are worth falling back to conversationState.programme for
# (see the candidate-resolution comment in _eligibility_guard) - every
# "still asking" state, PLUS resolved (since Part B's category-swap needs
# the programme too), but nothing else: an intent belonging to a different
# guard entirely (e.g. P2's topic-menu flow) must never be read as "this is
# an eligibility follow-up".
_INTERVIEW_CONTINUATION_INTENTS = _INTERVIEW_ASKING_INTENTS | {_INTERVIEW_RESOLVED_INTENT}

_ELIGIBILITY_QUESTION_RE = re.compile(
    r"\b(eligib\w*|qualify|qualified|qualifies|admission|admit)\b", re.I)


def _looks_like_eligibility_question(text):
    """Deterministic evidence that `text` is asking about the STUDENT'S OWN
    eligibility, not just the topic of eligibility in general - used only to
    gate the brand-new no_percentage interview branch (see
    _eligibility_guard) against hijacking an unrelated question that happens
    to carry no percentage figure ("what's the hostel fee?" also reaches
    evaluate()'s no_percentage reason, and always has - see that branch's
    comment for the reproduced case).

    Requires BOTH eligibility-topic wording AND first-person language
    (eligibility.describes_self) - topic wording alone caught "What is the
    eligibility criteria for B.V.Sc. & A.H. at MAFSU?" (A1 in
    tools/eval_admissions.py: a general, prospectus-answerable question with
    no personal stake) and intercepted it with an interview question instead
    of its real answer. "Am I eligible for B.V.Sc.?" has both; "what is the
    eligibility criteria" only ever has the first.

    Also excludes programs.is_shared_topic - missed this the first time and
    reproduced live: "If I qualify for NEET, does that automatically
    guarantee admission to MAFSU?" contains "I" (a hypothetical/conditional
    "if I..." framing, not a personal claim about the student's own marks or
    category) and topic wording, so it passed both checks and got swept into
    the interview asking "have you appeared for NEET-UG-2026?" instead of
    answering the general rule directly. "guarantee" is already in
    _SHARED_PORTAL_MARKERS for exactly this question shape (see
    programs.is_shared_topic's own docstring, which documents this near-
    identical case) - reusing that existing exclusion here closes the gap
    instead of inventing a second, narrower one.
    """
    if programs.is_shared_topic(text):
        return False
    return bool(_ELIGIBILITY_QUESTION_RE.search(text or "")
                and eligibility.describes_self(text))


def _slot_update(**fields):
    """A conversationState patch with every None value dropped, so a reply
    that doesn't know a field leaves it alone client-side instead of
    overwriting it with an explicit null - see app.js's slotUpdate merge
    (a plain object spread, which WOULD blank out an omitted-vs-null field
    the same way `{...s, category: null}` blanks a previously-known
    category). Every _eligibility_guard return that seeds conversationState
    goes through this rather than building the dict by hand, so the
    "never write None over a good value" rule can't be forgotten at one call
    site and not another.
    """
    return {k: v for k, v in fields.items() if v is not None}


def _eligibility_interview_ask(ctx, candidate, rule, merged_entrance, merged_category):
    """The next guided-interview question to ask, or None when both
    entrance-exam status and category are already resolved (known, from
    THIS message or an earlier one) and only the percentage itself remains -
    see _eligibility_guard's call site for what happens then.

    Field order deliberately mirrors evaluate()'s OWN early-return sequence
    read top to bottom: entrance-exam status first (evaluate() checks it
    before anything else - a missed exam is disqualifying regardless of
    marks, see missing_entrance_exam's docstring), category second. Subjects
    - evaluate()'s actual second check - are explicitly out of scope for
    this interview (see the P1 brief: a different guard's job), so category
    is asked next instead, ahead of the percentage that is evaluate()'s
    final step and the one thing the student cannot answer by clicking a
    chip - see _PERCENTAGE_CLARIFY_TEXT's reuse at the call site for why
    that one stays free-text.
    """
    lang = _clarify_language(ctx)
    if merged_entrance is None:
        text = _ELIGIBILITY_ENTRANCE_TEXT.get(lang, _ELIGIBILITY_ENTRANCE_TEXT["en"]).format(
            entrance=rule["entrance"])
        options = _ELIGIBILITY_ENTRANCE_OPTIONS.get(lang, _ELIGIBILITY_ENTRANCE_OPTIONS["en"])
        ctx.trace("eligibility", interview_step="entrance", programme=rule["label"])
        return {"answer": text, "pages": [], "model": "guard", "language": ctx.language,
                "source": "eligibility-interview", "speakable": True,
                "interviewOptions": options, "interviewField": "entranceExamStatus",
                "carryQuestion": ctx.question,
                "slotUpdate": _slot_update(programme=candidate,
                                            intent="eligibility_awaiting_entrance")}
    if merged_category is None:
        text = _ELIGIBILITY_CATEGORY_TEXT.get(lang, _ELIGIBILITY_CATEGORY_TEXT["en"])
        options = _ELIGIBILITY_CATEGORY_OPTIONS.get(lang, _ELIGIBILITY_CATEGORY_OPTIONS["en"])
        ctx.trace("eligibility", interview_step="category", programme=rule["label"])
        return {"answer": text, "pages": [], "model": "guard", "language": ctx.language,
                "source": "eligibility-interview", "speakable": True,
                "interviewOptions": options, "interviewField": "category",
                "carryQuestion": ctx.question,
                "slotUpdate": _slot_update(programme=candidate, entranceExamStatus=merged_entrance,
                                            intent="eligibility_awaiting_category")}
    return None


def _eligibility_percent_ask(ctx, candidate, merged_category, merged_entrance, reason, result):
    """The last-resort ask: entrance and category are settled (or not
    applicable - overall_not_subject skips them entirely, see the call
    site), only the subject-combination number itself is missing.

    Reason-dependent text, NOT the same canned "overall or subject?" prompt
    for both cases - that was the original design (match _percentage_clarify_
    guard's voice) and it reproduced a real, live loop: a student who typed
    "its overall score" in reply to that exact question got the SAME
    question back verbatim (evaluate() correctly determined overall_not_
    subject and re-asked "overall or subject?" instead of asking for the
    number), and reasonably read that as the assistant not listening -
    "speaking to dumb agent feeling" was the literal live report. The
    student had already resolved the ambiguity; what was still missing was
    the NUMBER, not the SCOPE. no_percentage (genuinely hasn't said either
    way yet) keeps the original ambiguity-resolving text; overall_not_subject
    (already said "overall", still needs the subject figure) uses
    _SUBJECT_PERCENT_ASK_TEXT, which asks for the number directly instead of
    re-asking a question already answered.
    """
    clarify_lang = _clarify_language(ctx)
    if reason == "overall_not_subject":
        text = _SUBJECT_PERCENT_ASK_TEXT.get(clarify_lang, _SUBJECT_PERCENT_ASK_TEXT["en"])
    else:
        text = _PERCENTAGE_CLARIFY_TEXT.get(clarify_lang, _PERCENTAGE_CLARIFY_TEXT["en"])
    ctx.trace("eligibility", verdict="insufficient", reason=reason,
              overall=result.get("overall"), programme=result.get("programme"),
              interview_step="percent")
    return {"answer": text, "pages": [], "model": "guard",
            "language": ctx.language, "source": "clarify-percentage", "speakable": True,
            "carryQuestion": ctx.question,
            "slotUpdate": _slot_update(programme=candidate, category=merged_category,
                                        entranceExamStatus=merged_entrance,
                                        intent="eligibility_awaiting_percent")}


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
        # P1 addition: fall back to the programme carried in
        # ctx.conversationState ONLY while continuing a guided-eligibility
        # interview THIS guard itself started (see _eligibility_interview_ask
        # and the "insufficient" handling below, which set
        # conversationState.intent to one of _INTERVIEW_ASKING_INTENTS while
        # asking, or to _INTERVIEW_RESOLVED_INTENT for one turn after a
        # verdict, so a same-topic follow-up like "what about SC?" can still
        # resolve). Never applied unconditionally: an unconditional seed
        # would let ANY short, programme-free follow-up on the general widget
        # - including one about a totally different topic asked minutes
        # later - get silently answered against a stale programme, which is
        # the exact "deterministic path trusting stale/borrowed state" shape
        # HANDOFF.md's entrance-exam-verdict postmortem warns about, just
        # sourced from conversationState instead of the router this time.
        # Gated further below (see facts/in_active_interview) to also require
        # the CURRENT message look like it is actually continuing the
        # interview, not just that the marker hasn't been cleared yet.
        if not candidate and ctx.conversationState.get("intent") in _INTERVIEW_CONTINUATION_INTENTS:
            candidate = resolve_conversation_slot(candidate, ctx.conversationState.get("programme"))
    else:
        candidate = project_id
    # "Which courses can I apply for?" - answered from the student's own
    # subjects against all three programmes, before anything programme-scoped
    # runs. This family kept collapsing to a single programme: a PCB student
    # was told B.V.Sc. was "the only" course open to them when B.F.Sc. also
    # takes PCB, and a PCM student was sent to B.V.Sc., which requires Biology.
    if eligibility.is_which_programmes_question(original):
        matches = eligibility.eligible_programmes(original_subjects(original))
        if matches:
            ctx.trace("eligibility", kind="which_programmes",
                      programmes=matches)
            spoken = llm.generate_scoped(
                config.CHAT_PRIMARY, ELIGIBILITY_PROGRAMMES_PROMPT,
                _which_programmes_facts(matches) + ctx.hint,
                ctx.question, timeout=60, allow_cloud=ctx.cloud_ok)
            if spoken is not None:
                text, model = spoken
                return {"answer": textclean.clean_for_display(text),
                        "pages": sorted({eligibility.RULES[m]["page"] for m in matches}),
                        "model": model, "language": ctx.language,
                        "source": "eligibility", "speakable": True}
        return None

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
    # Deterministic check only, NOT the router's opinion. Deferring to
    # _routed("unknown_programme") here made this whole path intermittent: the
    # router occasionally flags an ordinary B.V.Sc. eligibility question as a
    # foreign course, and when it did, the verdict was skipped and the slow
    # retrieval path answered instead - the same question resolving in 1.8s
    # with the right figure on one run and 140.8s with the wrong one on the
    # next. mentions_foreign_course covers every retired programme on its own
    # (tested both directions), so nothing is lost by not asking the router.
    if programs.mentions_foreign_course(original):
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

    # ---- P1: guided-interview merge -------------------------------------
    # Everything below builds a "composed" text to hand evaluate() instead of
    # `original` directly, so THIS message's own words (always authoritative
    # - see resolve_conversation_slot's docstring) are combined with whatever
    # earlier turns already established in ctx.conversationState. evaluate()
    # itself is never modified: it still only ever sees plain text and runs
    # its own unchanged extract()/threshold logic on it - this only decides
    # WHAT text to hand it and WHETHER to ask a question first instead.
    rule = eligibility.RULES[candidate]
    facts = eligibility.extract(original)
    state = ctx.conversationState
    in_active_interview = state.get("intent") in _INTERVIEW_ASKING_INTENTS
    # The narrow reactivation case Part B exists for: "what about SC?" after
    # a verdict was already given. Gated on the CURRENT message actually
    # naming a category - never on the marker alone (see the candidate
    # fallback comment above for why an unconditional reopen is unsafe: it
    # turned an unrelated "what's the hostel fee?" into a stale eligibility
    # verdict in testing).
    is_category_swap = (state.get("intent") == _INTERVIEW_RESOLVED_INTENT
                        and facts["category"] is not None)

    # Entrance-exam status: only ever a TEXT-matched negation in evaluate()
    # itself (missing_entrance_exam) - there is no positive-appearance
    # detector, and none is needed, since evaluate() only treats a missing
    # exam as disqualifying, never a stated one as reassuring. `entrance_now`
    # is "no" only when THIS message negates it (via the same regex
    # evaluate() itself will re-run below - deliberately re-derived rather
    # than trusted from a flag, so a swap in EITHER direction always goes
    # through the identical text-matching evaluate() uses) or, while we are
    # the ones who just asked, a bare "no"/"yes"/"pending" reply.
    entrance_negated_now = bool(eligibility.missing_entrance_exam(candidate, original))
    entrance_now = "no" if entrance_negated_now else None
    if entrance_now is None and state.get("intent") == "eligibility_awaiting_entrance":
        entrance_now = eligibility.is_bare_entrance_reply(original)
    merged_entrance = resolve_conversation_slot(entrance_now, state.get("entranceExamStatus"))

    merged_category = resolve_conversation_slot(facts["category"], state.get("category"))

    percent_now = facts["subject_percent"]
    if percent_now is None and facts["overall_percent"] is None \
            and state.get("intent") == "eligibility_awaiting_percent":
        # We are the ones who just asked for the subject-combination
        # percentage specifically, so a lone number in the reply needs no
        # scope cue to disambiguate - see bare_percent's docstring.
        percent_now = eligibility.bare_percent(original)
    merged_percent = resolve_conversation_slot(percent_now, state.get("subjectPercent"))

    composed = original
    # Only synthesize a clause for a fact the CURRENT message does not
    # already carry in a form evaluate() would find on its own - appending a
    # redundant one is harmless (evaluate() just finds the same fact twice),
    # but skipping it keeps `composed` (never shown to the student, only fed
    # to evaluate()) as close to their own words as possible.
    if not entrance_negated_now and merged_entrance == "no":
        composed += f" I did not appear for {rule['entrance']}."
    if facts["category"] is None and merged_category in ("reserved", "unreserved"):
        composed += f" I am in the {merged_category} category."
    if facts["subject_percent"] is None and merged_percent is not None:
        composed += f" {merged_percent}% in the specific subject combination."

    result = eligibility.evaluate(candidate, composed)
    if result["verdict"] not in ("eligible", "not_eligible"):
        reason = result.get("reason")
        if result["verdict"] == "insufficient" and reason == "overall_not_subject":
            # Unchanged from before P1: the student already engaged with a
            # percentage (that's how evaluate() reached this reason at all),
            # so this goes STRAIGHT to the subject-percentage ask, with no
            # entrance/category detour - re-litigating either first would
            # ignore what they just said. tools/eval_admissions.py Q17
            # already states an overall 12th percentage and expects exactly
            # this ask back.
            return _eligibility_percent_ask(ctx, candidate, merged_category, merged_entrance, reason, result)
        if result["verdict"] == "insufficient" and reason == "no_percentage":
            # Only engage the guided interview for a GENUINELY bare "am I
            # eligible?" - `no_percentage` also fires for ANY question with
            # no number in it at all (a scoped widget's "what's the hostel
            # fee?" reaches this exact reason too - see
            # _looks_like_eligibility_question's docstring), and separately
            # for a question that already carries OTHER substantive content
            # the plain RAG path is better placed to answer.
            # `describes_own_subjects` is the same signal evaluate() itself
            # uses to decide whether a message is making a personal claim
            # about subjects at all - reused here to detect "there is
            # already something else worth answering here", not just
            # "nothing was said about marks". Reproduced live: "I have PCB
            # but not Biotechnology. Am I eligible for B.V.Sc.?" (subjects
            # satisfied, no percentage stated either) got intercepted with
            # "have you appeared for NEET?" instead of the subjects-focused
            # answer RAG already gave correctly (tools/eval_admissions.py
            # Q16) - subjects are explicitly out of this interview's scope
            # (see the P1 brief), so a message that raises them belongs to
            # RAG, not to us, even though it also happens to omit a mark.
            if not (in_active_interview or is_category_swap
                    or (_looks_like_eligibility_question(original)
                        and not eligibility.describes_own_subjects(original))):
                return None
            # Ask the highest-priority MISSING field first, mirroring
            # evaluate()'s own early-return order (entrance checked before
            # anything else, then subjects - out of scope for this
            # interview, see the P1 brief - then percentage last). Category
            # sits between entrance and percentage: evaluate() itself has no
            # dedicated "category missing" step (it silently assumes
            # Unreserved - see category_assumed), but category and
            # percentage are used together in that SAME final comparison, so
            # asking it first means the eventual verdict is never phrased as
            # an assumption.
            ask = _eligibility_interview_ask(ctx, candidate, rule, merged_entrance, merged_category)
            if ask is not None:
                return ask
            # Both entrance and category are resolved (known, or not
            # applicable) - only the number itself is missing.
            return _eligibility_percent_ask(ctx, candidate, merged_category, merged_entrance, reason, result)
        return None

    ctx.trace("eligibility", verdict=result["verdict"], programme=result.get("programme"),
              stated=result.get("stated"), required=result.get("required"),
              reason=result.get("reason"))

    facts_text = _eligibility_facts(result)
    reply = llm.generate_scoped(
        config.CHAT_PRIMARY, ELIGIBILITY_SYSTEM_PROMPT, facts_text + ctx.hint,
        ctx.question, timeout=60, allow_cloud=ctx.cloud_ok)
    if reply is None:
        # Never fail the student's question because the phrasing call fell
        # over - the verdict is already decided, so say it plainly.
        return None
    answer_text, model = reply
    # The system prompt already says "use ONLY the numbers given below,
    # introduce no other percentage" - reproduced live anyway: asked to phrase
    # a correct 48%-vs-47.5%-reserved verdict, the model instead opened with
    # SC/ST/OBC SEAT-RESERVATION quota percentages (13%, 7%...) that were
    # nowhere in `facts`, a fluent answer to a question nobody asked. The
    # verdict computation was never wrong - eligibility.evaluate() already
    # decided it deterministically - only the phrasing step drifted. Since
    # `facts` already contains everything needed to say this correctly, an
    # embellished phrasing is not worth the risk of serving it: fall back to
    # a plain deterministic sentence built directly from `result` instead of
    # the model's free-form text. Same principle as validate.py's
    # unsupported_number check, applied to this guard's own LLM call instead
    # of the general RAG path.
    # Trailing-zero normalized ("47.50" == "47.5") - the source prospectuses
    # habitually write two decimals ("47.50% marks in case of Reserved
    # category") and the phrasing model picks that habit up even when
    # `facts` states the bare "47.5", which a literal string comparison
    # would wrongly treat as an unsupported new number.
    def _norm_num(n):
        return n.rstrip("0").rstrip(".") if "." in n else n
    answer_nums = {_norm_num(n) for n in validate._extract_numbers(answer_text)}
    fact_nums = {_norm_num(n) for n in validate._extract_numbers(facts_text)}
    if answer_nums - fact_nums:
        ctx.trace("eligibility", note="phrasing introduced an unsupported number - "
                                       "using deterministic fallback sentence")
        answer_text = _eligibility_fallback_sentence(result)
        model = "guard"
    return {"answer": textclean.clean_for_display(answer_text),
            "pages": [result.get("page")] if result.get("page") else [],
            "model": model, "language": ctx.language,
            "source": "eligibility", "speakable": True,
            # Seeds conversationState for a POSSIBLE follow-up swap ("what
            # about SC?" - see is_category_swap above and the P1 brief's
            # Part B) - kept for exactly one more turn via
            # _INTERVIEW_RESOLVED_INTENT rather than cleared outright, so
            # the very next message can still reference "whichever field was
            # just asked" even though nothing is being asked anymore. None
            # values are dropped (_slot_update), never written as an
            # explicit null - a field the interview never touched (e.g.
            # entrance status, when the student gave category+percentage
            # up front and evaluate() never needed to ask) must stay
            # whatever it already was, not be silently blanked out.
            "slotUpdate": _slot_update(programme=candidate, category=merged_category,
                                        entranceExamStatus=merged_entrance,
                                        subjectPercent=merged_percent,
                                        intent=_INTERVIEW_RESOLVED_INTENT)}


def _eligibility_fallback_sentence(result):
    """A plain, always-correct sentence built directly from the computed
    verdict, with no LLM call - the safe fallback when the phrasing model
    introduces a number `facts` never gave it (see the call site above).
    Deliberately mechanical rather than warm; correctness over tone here,
    since this path only runs when the fluent version already proved
    untrustworthy once for this exact request.
    """
    programme = result.get("programme")
    if result["reason"] == "entrance_exam":
        return (f"No, you are not eligible for {programme}: you said you did not "
                f"appear for {result['entrance']}, and admission is made on the "
                f"basis of that examination, with no route around it.")
    if result["reason"] == "subjects":
        return (f"No, you are not eligible for {programme}: it requires "
                f"{result['required_subjects']}, and you are missing "
                f"{', '.join(result['missing'])}.")
    verdict = "Yes, you are eligible for" if result["verdict"] == "eligible" else "No, you are not eligible for"
    sentence = (f"{verdict} {programme}: your {result['stated']}% in "
                f"{result['required_subjects']} is measured against the "
                f"{result['category']} category requirement of {result['required']}%.")
    if result["verdict"] == "eligible" and result.get("entrance"):
        sentence += f" Meeting this is only the eligibility bar - you must also have {result['entrance']}."
    return sentence


def original_subjects(text):
    """The subjects the student says they studied."""
    return eligibility.extract(text)["subjects"]


def _which_programmes_facts(matches):
    """Which programmes their subjects open, and which they close, as facts.

    Names the programmes they are NOT eligible for too: "which can I apply
    for" is really "where do I stand", and a student who studied PCM needs to
    know B.V.Sc. is closed to them more than they need a list of one.
    """
    eligible = [eligibility.RULES[m] for m in matches]
    excluded = [r for pid, r in eligibility.RULES.items() if pid not in matches]
    lines = ["FACTS (already checked against the prospectus, state exactly these):"]
    for rule in eligible:
        lines.append(f"- ELIGIBLE for {rule['label']}, which requires "
                     f"{rule['subject_label']} and {rule['entrance']}.")
    for rule in excluded:
        lines.append(f"- NOT eligible for {rule['label']}: it requires "
                     f"{rule['subject_label']}, which their subjects do not cover.")
    lines.append("List every programme above. Do not say one of them is the ONLY "
                 "option unless exactly one is listed as eligible.")
    lines.append("This is about subjects only - they still need the minimum "
                 "percentage and the entrance exam, so say that briefly at the end.")
    return "\n".join(lines)


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
    if result["reason"] == "entrance_exam":
        # Phrased hardest of the three. The failure being replaced (Q19) was
        # not a wrong figure but a self-contradiction - "Yes, you can still get
        # admission" followed by "you must also appear for MHT-CET" - which is
        # what a model produces when it weighs strong marks against a missed
        # exam instead of being told the verdict. So the No is stated first and
        # every escape route is closed explicitly.
        return (f"VERDICT (already decided, state exactly this): the student is NOT "
                f"eligible for {programme}. Reason: they have said they did not "
                f"appear for {result['entrance']}, and admission to {programme} is "
                f"made on the basis of that examination - there is no admission "
                f"without it. Lead with a clear 'No' in the very first sentence. Do "
                f"NOT say they can still get admission. Do NOT offer 12th marks, "
                f"subjects, or any other route as a way around it. You may close "
                f"with one short sentence about appearing for {result['entrance']} "
                f"for the next admission cycle.")
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
        # Router first, deterministic word list as the fallback.
        #
        # This was briefly changed to deterministic-only, on the grounds that
        # the router returned three different verdicts for six identical calls
        # of this field. That instability was real but it was NOT the main
        # cause of the flapping test results - most of that turned out to be
        # the FAQ cache serving a wrong answer produced in one bad moment (see
        # answer.py's flagged-answer rule). With that fixed, the router's
        # judgement is worth more than the word list's literalism.
        #
        # Measured, deterministic-only: sections B/C/D held or improved, but E
        # fell 9/9 -> 5/9 and F 8/11 -> 6/10, because a word list cannot tell
        # "what is the reservation POLICY?" (shared across all three
        # programmes) from "what percentage do reserved candidates need?"
        # (differs), nor "is hostel accommodation compulsory?" (shared) from
        # "what is the hostel fee?" (differs). Both questions contain the same
        # marker word; only reading them apart works.
        routed_needs = _routed(ctx, "needs_program_clarification")
        # Router still decides alone when it has an opinion (routed_needs is
        # not None) - EXCEPT it can no longer silently skip a clarification
        # the narrow, proven-safe marker set already knows to ask for (see
        # programs.needs_program_clarification_strong's docstring: excludes
        # "reservation"/"reserved"/"quota", the one collision this codebase
        # already measured - section E 9/9 -> 5/9 - when the full marker set
        # was OR'd in unconditionally). With no router opinion at all
        # (unavailable/low confidence), the FULL marker set is still the
        # fallback, unchanged from before today.
        if routed_needs is None:
            needs_clarify = programs.needs_program_clarification(question)
        else:
            needs_clarify = routed_needs or programs.needs_program_clarification_strong(question)
        # Shared-topic veto applies even to a router "yes" - previously it
        # only ever fed the deterministic fallback/force-ask paths above, so
        # a router false positive on a genuinely shared question (hostel fee,
        # "does MAFSU consider 12th marks or entrance-exam marks") had no way
        # to be overridden back to "just answer it". See
        # programs.is_shared_topic's docstring for the reproduced cases.
        if needs_clarify and programs.is_shared_topic(question):
            needs_clarify = False
        if needs_clarify:
            # No program named at all, and the topic is one that genuinely
            # varies per program (see programs.py) - nothing useful to
            # search for or cache yet, so no retrieval or LLM call either.
            clarify_lang = _clarify_language(ctx)
            text = _PROGRAM_CLARIFY_TEXT.get(clarify_lang, _PROGRAM_CLARIFY_TEXT["en"])
            options = [{"projectId": pid, "label": name} for pid, name in programs.PROGRAM_NAMES.items()]
            # `question`, not original_question: when this fires right after
            # a percentage-clarify round-trip (see chat_routes.py's
            # pendingClarification handling), `question` is already the
            # recombined "60% overall, ..." text - carrying THAT forward is
            # what makes the two clarifications chain correctly instead of
            # the second one reverting to the bare pre-percentage question.
            return {"answer": text, "pages": [], "model": "guard", "language": language,
                    "source": "clarify-program", "speakable": True, "clarifyOptions": options,
                    "carryQuestion": question}
    return None


def _general_fanout_guard(ctx):
    """A general question on the entry point: answer from ALL programmes.

    Runs after _program_clarify_guard, so anything that genuinely differs per
    programme still gets asked about rather than answered three ways.

    This exists because of the 2026-08-16 split. Before it, `default` held the
    B.V.Sc. corpus, so "can a student who passed 12th from another board
    apply?" was answered - from B.V.Sc. alone, silently, whichever programme
    the student actually wanted. After the split `default` holds no corpus, so
    the same question reached an empty store and got "no prospectus has been
    uploaded yet", which is worse: the first answer was at least true for a
    third of askers.

    Neither is acceptable when the honest answer is "the same for all three".
    So the question fans out across every programme's corpus and is answered
    once. Reuses the comparison path, which already retrieves per project,
    checks provenance and redacts figures it cannot source - built for
    "compare A and B", and a general question is the degenerate case of it.
    """
    if ctx.project_id != config.DEFAULT_PROJECT_ID:
        return None
    original = getattr(ctx, "original_question", ctx.question)
    if programs.detect_program(original):
        return None          # names a programme - the redirect guard owns it
    targets = list(programs.PROGRAM_NAMES)
    ctx.trace("routing", decision="general_fanout", targetPrograms=targets)
    return comparison._answer_comparison(
        targets, ctx.question, ctx.script_pref, ctx.ui_language, ctx.language,
        ctx.hint_language, ctx.hint, ctx.typed_romanized, ctx.cloud_ok, ctx.trace)


def _low_confidence_clarify_guard(ctx):
    """Last resort: nothing above classified this, and the router wasn't
    sure either. Ask instead of letting free-form RAG generation guess.

    Deliberately the LAST guard, not an early gate on the router's
    confidence field generally - see _routed()'s docstring, which already
    has every earlier guard fall back to deterministic keyword logic on low
    confidence rather than trust an unsure router opinion. Those guards
    still fire correctly on plenty of low-confidence questions; this one
    only ever sees what they ALL passed on, i.e. the router was unsure AND
    keyword logic found nothing to classify either. That combination is
    what used to fall straight into RAG and get answered fluently on a
    guess - the same shape of failure _eligibility_guard's docstring
    describes for percentages, generalized to "no guard could place this
    question at all", not just the percentage case.

    See config.LOW_CONFIDENCE_CLARIFY_ENABLED for why this is switched and
    measured separately from the three reverted attempts HANDOFF.md
    documents: those made an EARLY guard more eager and caught questions
    that were already being handled correctly. This one only fires after
    everything else has already declined.
    """
    if not config.LOW_CONFIDENCE_CLARIFY_ENABLED:
        return None
    route = getattr(ctx, "route", None)
    if not route or route.get("confidence") != "low":
        return None
    # Same scope gate _program_clarify_guard already has, missing here until
    # now: on a project the student is ALREADY scoped to (bvsc/bfsc/
    # btech-dairy - reached via that programme's own widget/API key, not the
    # general one), "which programme are you asking about?" is nonsensical -
    # there is only one. Reproduced directly: asked "What is the fee?" using
    # bvsc's own key, this guard still replied asking the student to pick
    # between B.V.Sc./B.F.Sc./B.Tech Dairy - on the B.V.Sc.-only widget. Any
    # genuine ambiguity on a scoped project is about WHAT was asked, not
    # WHICH programme, so this guard has nothing useful to add there; let RAG
    # answer with the one programme's own full context instead of asking a
    # question that already has a one-word, already-known answer.
    if ctx.project_id != config.DEFAULT_PROJECT_ID:
        return None
    # Same deterministic veto _program_clarify_guard already has, missing
    # here until now: if the question names a programme, never ask which one
    # it is about. Reproduced directly - "I am eligible for B.V.Sc. but my
    # NEET score is low. Does MAFSU have any separate entrance examination?"
    # named B.V.Sc. in plain text and still got "which program are you asking
    # about?", because this guard only checked the router's confidence field,
    # never the text itself. _program_clarify_guard's own comment calls this
    # shape "the single most irritating failure this assistant has" - true
    # here too, just reached through a different guard.
    if programs.detect_program(getattr(ctx, "original_question", ctx.question)):
        return None
    clarify_lang = _clarify_language(ctx)
    text = _META_ACKNOWLEDGE_TEXT.get(clarify_lang, _META_ACKNOWLEDGE_TEXT["en"])
    # clarifyOptions, same as _program_clarify_guard: this guard fires when
    # the router itself couldn't classify the question at all, which is
    # exactly the case a student benefits most from picking a programme by
    # button instead of having to guess what free-text answer would move
    # things forward.
    options = [{"projectId": pid, "label": name} for pid, name in programs.PROGRAM_NAMES.items()]
    ctx.trace("routing", decision="low_confidence_clarify")
    return {"answer": text, "pages": [], "model": "guard", "language": ctx.language,
            "source": "clarify-lowconfidence", "speakable": True, "clarifyOptions": options,
            "carryQuestion": ctx.question}


GUARDS = [
    _injection_guard,
    # Ahead of _greeting_guard, not grouped with _program_list_guard below
    # where it reads more naturally - moved here after live testing showed
    # the router classifying "What can you help with?" as intent="greeting"
    # ("only a greeting/thanks, nothing asked" per _ROUTER_SYSTEM - a
    # conversational capability question is close enough in TONE to fool it,
    # even though something is plainly being asked). With _greeting_guard
    # first, that question was answered by the fast-lane LLM instead of this
    # guard's grounded registry - not wrong, but exactly the "generated
    # capability list" shape the P2 task's hard constraint says to avoid.
    # Safe to run this early: _topic_menu_guard's trigger phrases
    # (_BROAD_ADMISSION_PHRASES/_CAPABILITY_QUESTION_PHRASES) share no
    # vocabulary with GREETINGS' exact-match set or with a real dispute/
    # correction/off-topic message, so moving ahead of every guard below
    # costs nothing for any of them.
    _topic_menu_guard,
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
    _general_fanout_guard,
    _low_confidence_clarify_guard,
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
