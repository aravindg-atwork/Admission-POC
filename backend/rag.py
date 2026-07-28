"""RAG orchestration: retrieve prospectus context, route by language, generate.

Ties the pieces together the way a single question flows through the system:
embed the question, find the most relevant prospectus chunks, then ask the
language-appropriate model to answer using only those chunks.
"""

import hashlib
import json
import time
from datetime import datetime, timezone

from . import (config, embeddings, faq, glossary, llm, projects, stats,
               tablelookup, textclean, transliterate, vectorstore)
from .intent import is_payment_issue
from .lang import detect_romanized_indic, detect_script

# Bump whenever extraction or chunking changes in a way that makes an existing
# index stale (see ingest). Mixed into the content hash so already-ingested
# projects rebuild instead of silently keeping data built by the old pipeline.
#   2 - layout-preserving extraction, page-furniture/mojibake stripping,
#       line-boundary chunking, tables kept whole
#   3 - explicit linearized readings appended to table pages
#   4 - table detection widened to 2-column tables (schedule/date grids)
#  11 - single-level year-column fee tables linearized too (Annexure III-A/III-C),
#       which previously produced no readings at all
PIPELINE_VERSION = "11"

SYSTEM_PROMPT_BASE = (
    "You are an admissions counselor for the B.V.Sc. & A.H. program. Answer the "
    "student directly and factually, like a knowledgeable person who respects "
    "their time.\n\n"
    "RULES:\n"
    "- Lead with the answer itself. The very first sentence must contain the "
    "actual fact - the date, the amount, the requirement. No preamble, no "
    "restating the question, no 'that's a great question', no 'let me help you "
    "with that', no 'I understand you're looking for'. Just answer.\n"
    "- Be accurate above all else. Use ONLY the prospectus excerpts provided. "
    "Never invent, estimate, or round a number. If the excerpts genuinely don't "
    "contain the answer, say plainly that the prospectus doesn't specify it and "
    "suggest they contact the admission office - do not fill the gap with a "
    "plausible guess.\n"
    "- Some excerpts are TABLES, kept in their original column layout. A fee "
    "table may hold different amounts per college and per year of study, so "
    "quote the one that actually matches what the student asked, and say which "
    "college or year it applies to. If the question doesn't pin down which "
    "column applies, give the relevant figures with their labels rather than "
    "picking one at random.\n"
    "- CRITICAL: when an excerpt has an 'Explicit readings of the table above' "
    "section, those lines are the authoritative values - each is pre-labelled "
    "'row - group / column: value' and was aligned mechanically, not by eye. Use "
    "them verbatim and do NOT re-derive the figure by counting across the raw "
    "grid, which is easy to misalign. If a reading exists for what was asked, "
    "quote that number and nothing else. Never sum the component rows yourself "
    "when a Total reading is given.\n"
    "- Never tell the student to go check a page number themselves ('you'll find "
    "this on page 9', 'refer to page 4 for details', etc.) - that's not your job "
    "to hand off. You have the excerpt right in front of you, so answer it "
    "completely yourself. The page numbers are already shown separately in the "
    "app for anyone who wants to double check, so there's no need to mention them "
    "in your reply at all.\n"
    "- Write in plain spoken prose only. NEVER use markdown: no asterisks, no "
    "bullet points, no numbered lists, no bold, no headers. If there are several "
    "items, weave them into a natural sentence (\"you'll need three things: your "
    "mark sheet, an ID, and two photos\").\n"
    "- Keep it short - two or three sentences for a simple question. Stop once "
    "you've answered; don't pad with extra offers to help.\n\n"
    "Example of the tone to match:\n"
    "Student asks: \"When was the last day to submit documents?\"\n"
    "Good: \"The deadline was March 1st, but late submissions are accepted until "
    "March 15th with a small late fee.\"\n"
    "Bad (never do this): \"That's a great question! Let me help you with that. It "
    "states in the prospectus that the deadline is March 1st. You can find more "
    "on page 4. Is there anything else I can help you with?\"\n\n"
)

GREETING_PROMPT_BASE = (
    "You are a warm, friendly admissions counselor for the B.V.Sc. & A.H. program. "
    "The student is only greeting you, not asking a question yet. Reply warmly in one "
    "or two short spoken sentences and invite them to ask about eligibility, dates, "
    "fees, or documents. Plain prose only, no markdown, no asterisks or lists. "
)

# A dedicated prompt for payment PROBLEMS (not payment questions - see
# intent.is_payment_issue), not just a variation of SYSTEM_PROMPT: the goal here
# is de-escalation first, since most payment scares resolve on their own within
# a day or two, and a needless complaint costs the student a real grievance fee
# and costs the admissions office time on something that wasn't actually broken.
PAYMENT_SYSTEM_PROMPT_BASE = (
    "You are a warm, practical admissions counselor helping a student who's having "
    "trouble with a payment (application fee, admission fee, hostel fee, etc.).\n\n"
    "RULES:\n"
    "- Answer calmly and reassuringly - payment scares are stressful, and most "
    "resolve on their own within a day or two. But get to the substance quickly: "
    "one brief reassuring sentence, then straight into the actual steps - don't "
    "pad with extended scene-setting like \"let's walk through this together\" "
    "before saying anything useful.\n"
    "- Walk them through quick self-checks FIRST, before suggesting any formal "
    "complaint: (1) if the payment page showed an error but money may have been "
    "debited, banks and payment gateways can take several hours to a few business "
    "days to confirm success or auto-reverse a failed attempt, so it's often not "
    "urgent yet; (2) don't retry the same payment until they've confirmed with "
    "their bank whether the first attempt actually went through, to avoid double-"
    "paying; (3) check the admission portal itself for the payment status - that's "
    "the source of truth, not just a bank SMS or a page that failed to load.\n"
    "- Only if they say they've already checked and it's still unresolved, offer to "
    "help them write a short, clear message they can submit themselves (never say "
    "you will send anything - they send it). Ask for the transaction date, amount, "
    "and any reference/error number so the message has real specifics instead of "
    "vague complaints.\n"
    "- Be precise and honest about the escalation channel, don't oversell it: the "
    "university's only documented complaint process is an online grievance "
    "submission through the official website, and it is specifically framed around "
    "provisional merit list disputes - it also charges its own grievance fee and "
    "has a strict deadline. Mention it as the one real formal channel that exists, "
    "but be clear it isn't built for a payment/technical glitch specifically, and "
    "that contacting their bank's support and the college's admission office "
    "directly is usually the faster, more appropriate first step for that.\n"
    "- If the prospectus excerpts below include specific fee amounts or refund "
    "percentages relevant to their question, use those exact figures - never "
    "invent a number.\n"
    "- Plain spoken prose only. No markdown, no bullet symbols - weave steps into "
    "natural sentences, the way a caring counselor would say it out loud.\n"
    "- Keep the whole reply tight - well under 200 words. This is a checklist "
    "the student needs fast, not an essay.\n\n"
)

SYSTEM_PROMPT = SYSTEM_PROMPT_BASE + llm.LANGUAGE_RULE
GREETING_PROMPT = GREETING_PROMPT_BASE + llm.LANGUAGE_RULE
PAYMENT_SYSTEM_PROMPT = PAYMENT_SYSTEM_PROMPT_BASE + llm.LANGUAGE_RULE


_UI_LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "en": "English"}


def _language_hint(ui_language):
    """Explicit disambiguation for the model, built from the language the student
    picked in the app's own selector - not inferred. Hindi and Marathi share
    Devanagari script, so detect_script (and the model, left to guess from wording
    alone) can't reliably tell them apart on short/ambiguous questions; this closes
    that gap for the case that actually matters. A no-op when the caller didn't
    pass a recognized ui_language (e.g. legacy callers, tests).
    """
    name = _UI_LANGUAGE_NAMES.get(ui_language)
    if not name:
        return ""
    confusable = " (not Hindi)" if name == "Marathi" else " (not Marathi)" if name == "Hindi" else ""
    return f"\n\n(The student selected {name} in the app - always reply in {name}{confusable}.)"


def _romanized_input_hint(name):
    """The student typed in Roman script but the words are Hindi/Marathi, not
    English (see lang.detect_romanized_indic) - e.g. "mera fees kitna hai".
    Without this, the model reads Latin script and, despite LANGUAGE_RULE's
    general "match their language" instruction, tends to default to English -
    there's no native-script cue to anchor it. Tells it explicitly to generate in
    Devanagari anyway, reusing the same reliable native-generate-then-romanize
    pipeline as script_pref="auto" (see _apply_script_pref) rather than asking
    for direct Roman-script generation, which transliterate.py's docstring notes
    is unreliable.
    """
    return (
        f"\n\n(The student typed this question in Roman/Latin letters, but it's "
        f"{name} written phonetically (\"Hinglish\"/\"Marathinglish\"), not English - "
        f"e.g. \"mera fees kitna hai\" means \"what is my fee\" in Hindi. Generate "
        f"your answer in proper Devanagari script, matching {name} - it will be "
        f"automatically romanized back for display. Do NOT answer in English.)"
    )


def _apply_script_pref(text, language, script_pref):
    """Romanized (Hinglish/Tanglish) is a display-time transformation, not a
    generation-time one - asking the model to write Roman-script Hindi/Tamil
    directly proved unreliable (see transliterate.py), so generation always stays
    native-script and this converts afterward, deterministically. Returns
    (display_text, speakable). No-op for anything without a native script (e.g.
    English) or under an explicit "native" request.

    Romanized is the default for Hindi/Marathi/Tamil - most students type and
    read code-mixed Roman script day to day, not the native script - so
    script_pref of "auto" or "hinglish" both romanize; only an explicit "native"
    choice keeps Devanagari/Tamil script as-is.
    """
    if script_pref != "native" and language in ("devanagari", "tamil"):
        return transliterate.to_romanized(text, language), False
    return text, True

# Exact-match greetings across the supported languages. Deliberately not length-based:
# a longer question in any script must never be mistaken for a greeting.
GREETINGS = {
    "hi", "hey", "hello", "yo", "hii", "hiya", "hey there",
    "thanks", "thank you", "thankyou", "ok", "okay", "bye", "goodbye",
    "namaste", "namaskar", "vanakkam", "vanakam",
    "வணக்கம்", "नमस्ते", "नमस्कार", "हाय", "हेलो",
}


def is_greeting(text):
    return text.lower().strip().strip("!.?,। ") in GREETINGS


def answer(project_id, question, script_pref="auto", ui_language=None):
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
    result = _answer(project_id, question, script_pref, ui_language)
    stats.record(projects.stats_path(project_id), result["source"], result["model"],
                 result["language"], round((time.time() - t0) * 1000))
    return result


def _answer(project_id, question, script_pref, ui_language):
    question = question.strip()
    language = detect_script(question)
    cloud_ok = projects.allow_cloud(project_id)
    hint = _language_hint(ui_language)

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
    if language == "latin":
        effective = ui_language if ui_language in ("hi", "mr") else (
            "tamil_ui" if ui_language == "ta" else detect_romanized_indic(question)
        )
        if effective == "tamil_ui":
            language = "tamil"
            hint += _romanized_input_hint(_UI_LANGUAGE_NAMES["ta"])
        elif effective:
            language = "devanagari"
            # Reassigned, not just a local - everything downstream (the FAQ cache
            # lookup/store below, in particular) must see this as the effective
            # language too, or a Hinglish question can still collide in cache with
            # an unrelated English one on the same topic (same bug class as the
            # Hindi/Marathi cache collision, just English-vs-Hinglish this time).
            ui_language = effective
            hint += _romanized_input_hint(_UI_LANGUAGE_NAMES[effective])

    # Intent: greeting short-circuit (no retrieval, no cache).
    if is_greeting(question):
        reply, model = llm.generate(GREETING_PROMPT, question + hint, question, timeout=120, allow_cloud=cloud_ok)
        reply = textclean.clean_for_display(reply)
        display, speakable = _apply_script_pref(reply, language, script_pref)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "greeting", "speakable": speakable}

    # Intent: payment PROBLEM (not just a payment question - see intent.py). Swaps
    # in a de-escalate-first prompt instead of the general counselor one, and tags
    # the cache entry so it can never surface for/from a plain fee-amount question
    # that happens to embed nearby (same collision risk as the Hindi/Marathi one).
    payment_issue = is_payment_issue(question)
    system_prompt = PAYMENT_SYSTEM_PROMPT if payment_issue else SYSTEM_PROMPT
    cache_tags = {"ui_language": ui_language, "intent": "payment_issue" if payment_issue else None}

    # Embed once; the vector is reused for both the FAQ lookup and RAG retrieval.
    query_vector = embeddings.embed([question])[0]

    # FAQ cache: instant answer for a question we've seen or seeded before. Cached
    # text is always native-script; script_pref is applied below regardless of
    # whether the answer came from cache or fresh generation.
    # The question text is passed so the cache can reject matches that differ on
    # a meaning-flipping token (1st vs 2nd year, before vs after) despite having
    # near-identical embeddings - see faq._discriminators.
    hit = faq.match(projects.faq_path(project_id), query_vector, cache_tags, question)
    if hit:
        display, speakable = _apply_script_pref(hit["answer"], language, script_pref)
        return {"answer": display, "pages": hit["pages"], "model": "faq-cache",
                "language": language, "source": "faq-cache", "speakable": speakable}

    # RAG: retrieve prospectus context, then the language-routed LLM. Retrieval uses
    # an English-translated version of non-English questions - the prospectus is
    # predominantly English text, and the embedding model doesn't align Hindi/Tamil
    # with English closely enough for the original-language vector to reliably find
    # the right chunks (verified: a Hindi fee question missed chunks an equivalent
    # English one found). The FAQ-cache vector above stays untranslated on purpose,
    # so cache matching stays consistent with how earlier entries were embedded.
    retrieval_vector = query_vector
    # Text used for the LEXICAL half of retrieval and for the table lookup, as
    # opposed to `question`, which is what the student actually typed. These
    # diverge for Indic input and keeping them separate is the point: both of
    # those mechanisms compare against an English prospectus, so handing them
    # Devanagari guarantees zero matches (see below).
    retrieval_text = question
    if language != "latin":
        translated = llm.translate_to_english(question, ui_language)
        if translated and translated != question:
            retrieval_vector = embeddings.embed([translated])[0]
            # Append the deterministic domain terms rather than relying on the
            # translation alone. The 2B translator drops or inverts exactly the
            # domain nouns that decide which part of the prospectus is relevant
            # (a reservation-percentage question came back as a question about
            # fees, and duly retrieved the fee tables), so the terms it must not
            # lose are added mechanically. Used only for the lexical half of
            # retrieval and the table lookup - never shown to the student, and
            # never embedded, so a spurious term costs ranking noise at worst.
            retrieval_text = " ".join(
                filter(None, [translated, glossary.english_terms(question)]))

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
        display, speakable = _apply_script_pref(reply, language, script_pref)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "no-context", "speakable": speakable}

    context = "\n\n".join("[Page {}] {}".format(e["page"], e["text"]) for e in top)
    # Recency reminder, not just the system-prompt rule: the excerpts themselves
    # are labeled "[Page N]", and the local fallback model in particular has a
    # documented pattern of ignoring system-prompt rules but reliably following
    # something repeated at the end of the user turn (see _SCRIPT_REMINDER in
    # llm.py) - seen in testing to still cite "you'll find this on page X" here
    # without this, despite the system prompt already saying not to.
    page_reminder = (
        "\n\n(Reminder: answer this fully yourself using the excerpts above - do "
        "NOT tell the student to go check a page number themselves. The [Page N] "
        "labels are for your reference only, never to be repeated back to them.)"
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
    verified_block = ""
    if verified:
        verified_block = (
            "\n\nVERIFIED FIGURE (resolved directly from the table, already "
            "checked against the correct row and column - treat this as the "
            "answer and state this exact number, do not look for another):\n"
            f"{verified['descriptor']}: {verified['value']}"
        )

    user_prompt = ("Prospectus excerpts:\n" + context + verified_block
                   + "\n\nQuestion: " + question + hint + page_reminder)
    reply, model = llm.generate(system_prompt, user_prompt, question, allow_cloud=cloud_ok)
    reply = textclean.clean_for_display(reply)
    pages = sorted({e["page"] for e in top})

    # Auto-cache the native-script answer so the next similar ask is instant,
    # regardless of which script_pref that later ask uses.
    if config.FAQ_AUTOCACHE:
        faq.add(projects.faq_path(project_id), question, reply, pages, query_vector, cache_tags)

    display, speakable = _apply_script_pref(reply, language, script_pref)
    return {"answer": display, "pages": pages, "model": model, "language": language,
            "source": "payment-issue" if payment_issue else "rag", "speakable": speakable}


def ingest(project_id, pdf_path):
    """Extract, chunk, embed and store a prospectus PDF for a project.

    Skips re-embedding entirely when the PDF is byte-identical to what's
    already indexed for this project AND the extraction pipeline hasn't changed
    since (both tracked via a hash in manifest.json) - re-uploading the same
    prospectus, or restarting against unchanged data, costs nothing. Returns
    counts plus `skipped: True` when the skip path was taken.

    The pipeline version is part of that hash on purpose. Hashing only the PDF
    bytes meant a change to extraction or chunking left every project silently
    serving an index built by the old, worse code - the file hadn't changed, so
    the skip path fired and the fix never reached the data. Bumping
    PIPELINE_VERSION forces a rebuild everywhere on next ingest.
    """
    from . import pdf as pdf_module

    pdf_bytes = pdf_path.read_bytes()
    content_hash = hashlib.sha256(
        pdf_bytes + PIPELINE_VERSION.encode("utf-8")
    ).hexdigest()

    manifest_path = projects.manifest_path(project_id)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("hash") == content_hash:
            return {"pagesProcessed": manifest["pagesProcessed"],
                     "chunksIndexed": manifest["chunksIndexed"], "skipped": True}

    pages = pdf_module.extract_pages(pdf_path)
    chunks = pdf_module.chunk_pages(pages)

    vectors = []
    # Modest batches keep any single request well inside the HTTP timeout.
    # (A round of ingest timeouts here looked like batch size being too large,
    # but the real cause was a wedged embedding-service process - after a
    # restart the same 3KB table chunks embed in well under a second.)
    batch = 8
    for i in range(0, len(chunks), batch):
        vectors.extend(embeddings.embed([c["text"] for c in chunks[i:i + batch]]))

    store = [{"page": c["page"], "text": c["text"], "vector": v} for c, v in zip(chunks, vectors)]
    vectorstore.save(projects.store_path(project_id), store)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "hash": content_hash, "pagesProcessed": len(pages), "chunksIndexed": len(chunks),
        "embeddedAt": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")

    return {"pagesProcessed": len(pages), "chunksIndexed": len(chunks), "skipped": False}
