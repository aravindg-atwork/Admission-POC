"""The answer pipeline - a pragmatic first pass, not the full guard system
yet. Scoped deliberately for this vertical-slice checkpoint (see
../../../CLAUDE.md): retrieval -> confidence gate -> verified table lookup
-> a narrow eligibility-verdict check -> general RAG generation. What's
explicitly NOT here yet, and shouldn't be assumed to exist: the full 16-
guard pipeline (injection/greeting/dispute/comparison/clarification/etc.),
the guided multi-turn eligibility interview, and any Hindi/Marathi handling
(script detection, romanization, translate-to-English for retrieval) - this
checkpoint is English-only by scope, not by oversight. See CLAUDE.md for
what's next.

Every piece actually wired in here is ported logic, not new judgment calls:
the confidence floor, the eligibility/table-lookup precedence, and the
system prompts are all carried over from the proven system, just called
from a simpler pipeline shape.
"""

import re

from ..core import eligibility, lang, programs, tablelookup, vocabulary
from ..providers import embeddings, llm
from ..retrieval import store
from ..settings import get_settings
from ..storage import answer_cache, curated, semantic_faq
from . import guards, knowledge_boundary, language, prompts, validate

_settings = get_settings()

_ELIGIBILITY_HINT_WORDS = {"eligible", "eligibility", "qualify", "qualified", "admit", "admission", "apply"}

# Reproduced live, same failure the original project already documented
# (backend/rag/helpers.py's _english_reply_hint): LANGUAGE_RULE alone
# ("match the student's language") is not enough - a plain English
# question came back in Hindi with no other hint present. This checkpoint
# is English-only by scope (no script detection/romanization ported yet),
# so the hint is appended unconditionally rather than conditionally like
# the original does, matching this phase's own scope, not a shortcut.
_ENGLISH_REPLY_HINT = "\n\n(The question above is written in English - reply in English.)"
_ELIGIBILITY_BOOST_TERMS = "eligibility criteria minimum marks XIIth Std 10+2 pattern qualifying examination"
_IDENTITY_REPEAT = {
    "hi": (
        "मैं MAFSU MITRA (बीटा), MAFSU के स्नातक प्रवेश के लिए सहायक हूँ। मैं B.V.Sc. & A.H., "
        "B.F.Sc. और B.Tech. (Dairy Technology) के लिए आपकी पात्रता चरण-दर-चरण जाँचने और "
        "प्रवेश परीक्षा, फीस, सीट एवं कॉलेज, कोटा एवं आरक्षण, आवश्यक दस्तावेज़ तथा आवेदन प्रक्रिया "
        "समझाने में मदद कर सकता हूँ। मैं बीटा सहायक हूँ और मुझसे गलतियाँ हो सकती हैं, इसलिए अंतिम "
        "प्रवेश निर्णय MAFSU से सत्यापित करें। आप स्वाभाविक रूप से प्रश्न पूछ सकते हैं—जैसे, “मेरे "
        "48% हैं और मैंने NEET दिया है; क्या मैं B.V.Sc. के लिए आवेदन कर सकता हूँ?”"
    ),
    "mr": (
        "मी MAFSU MITRA (बीटा), MAFSUच्या पदवीपूर्व प्रवेशासाठी सहाय्यक आहे. मी B.V.Sc. & A.H., "
        "B.F.Sc. आणि B.Tech. (Dairy Technology) या अभ्यासक्रमांसाठी पात्रता टप्प्याटप्प्याने "
        "तपासण्यात आणि प्रवेश परीक्षा, शुल्क, जागा व महाविद्यालये, कोटा व आरक्षण, आवश्यक कागदपत्रे "
        "आणि अर्ज प्रक्रिया समजावून सांगण्यात मदत करू शकतो. मी बीटा सहाय्यक असल्यामुळे चुका होऊ "
        "शकतात; अंतिम प्रवेश निर्णय MAFSUकडून पडताळून घ्या. तुम्ही सहजपणे प्रश्न विचारू शकता—उदा., "
        "“मला 48% गुण आहेत आणि मी NEET दिली आहे; मी B.V.Sc. साठी अर्ज करू शकतो का?”"
    ),
}


def _retrieval_text(question: str) -> str:
    """Ported English branch of backend.rag.helpers._build_retrieval_text."""
    lower = question.lower()
    asks_eligibility = any(
        word in lower for word in ("eligible", "eligibility", "qualify", "qualified")
    ) or "%" in question
    names_twelfth = "12th" in lower or "xii" in lower or "10+2" in lower
    boost = _ELIGIBILITY_BOOST_TERMS if asks_eligibility and names_twelfth else ""
    base = f"{question} {boost}" if boost else question
    return vocabulary.expand(base)


def _verified_rule_hints(question: str, project_id: str) -> str:
    """Prospectus rules that must survive multi-part synthesis.

    These are narrow, source-transcribed anchors for failures reproduced by
    tools/eval_bvsc_adversarial.py; they constrain phrasing but do not invent
    a new verdict path.
    """
    low = question.lower()
    hints = []
    if "ncl" in low or "non-creamy" in low:
        hints.append("OBC reservation requires a valid Non-Creamy Layer certificate; otherwise the reservation claim is rejected and the candidate may only be considered Unreserved if that eligibility is met.")
    if "blurred" in low or "not visible" in low:
        hints.append("A qualifying-exam marksheet that is not visible is listed as an automatic rejection deficiency. The prospectus also provides a deficient/wrong-document list and a limited resubmission window for only the indicated documents. Explain both rules without guaranteeing resubmission in every case.")
    if "preference form" in low and "next round" in low:
        hints.append("A preference form is required for every round. Once admitted under Regional/State quota, the college or quota cannot be changed. If merely allotted but not reported, consequences depend on whether the allotment was the candidate's first preference; do not claim the current seat is retained or cancelled without that fact.")
    if "after allotment" in low or "personally visit" in low:
        hints.append("After allotment the candidate must personally visit the allotted college with the allotment letter, all originals, self-attested photocopies of all applicable documents, and applicable fees.")
    if "management quota" in low and ("directly" in low or "mafsu allot" in low):
        if project_id == "bvsc":
            hints.append("MAFSU fills management-quota seats in provisionally affiliated private veterinary colleges, and a qualifying NEET-UG-2026 score is required.")
        elif project_id == "btech-dairy":
            hints.append("MAFSU allots management-quota seats in affiliated private Dairy Technology colleges. MHT-CET candidates receive first priority; remaining vacancies are then offered to CUET (ICAR-UG) candidates.")
    return "\n".join(hints)


def _compound_eligibility(question: str) -> bool:
    low = question.lower()
    return any(term in low for term in ("ncl", "non-creamy", "certificate", "compensate"))


def _retrieval_is_confident(top: list[dict]) -> bool:
    """Ported from this project's own session-added confidence gate (see
    backend/rag/helpers.py's retrieval_is_confident) - the #1-ranked chunk's
    score must clear the floor before a free-form answer is generated from
    it, so an out-of-corpus or garbled question gets an honest "not
    confident" reply instead of a fluent answer built on noise.
    """
    return bool(top) and top[0].get("score", 0) >= _settings.retrieval_confidence_floor


def _looks_like_eligibility_question(question: str) -> bool:
    """Narrow, deliberately simpler than backend/rag/guards.py's
    _looks_like_eligibility_question - no guided-interview follow-up yet,
    so this only needs to decide whether to ATTEMPT a verdict, not manage a
    multi-turn slot-filling conversation. Requires first-person language
    (the same describes_self signal the original uses) so a general "what
    is the eligibility criteria" question still falls through to RAG
    instead of being answered as a personal verdict with insufficient
    information.
    """
    low = question.lower()
    if low.startswith("how do i apply") or low.startswith("where do i apply"):
        return False
    return eligibility.describes_self(question) and (
        any(w in low for w in _ELIGIBILITY_HINT_WORDS)
        or ("meet" in low and "requirement" in low)
    )


def _with_language(result: dict, ctx: language.LanguageContext) -> dict:
    """Attach language metadata and localize fixed English guard replies."""
    result = dict(result)
    result["answer"] = knowledge_boundary.apply(result.get("answer", ""))
    fixed_english = result.get("model") in ("guard", "policy-engine", "none", "validator")
    answer_low = result.get("answer", "").lower()
    if ctx.language in ("hi", "mr") and result.get("source") == "structured-policy" and "nri/fn/pio/oci" in answer_low and "xii" in answer_low:
        stated = re.search(r"stated (\d+(?:\.\d+)?)%", result["answer"], re.I)
        mark = stated.group(1) if stated else ""
        meets = "meets the 50%" in answer_low
        if ctx.language == "hi":
            result["answer"] = (
                f"आपके NEET न देने से ही आप अपात्र नहीं होते। B.V.Sc. के NRI/FN/PIO/OCI नियम में विदेश से XII या समकक्ष परीक्षा उत्तीर्ण उम्मीदवार को NEET-UG-2026 से छूट है। "
                + (f"आपके बताए {mark}% इस कोटे की Physics, Chemistry, Biology या Biotechnology और English में 50% की आवश्यकता पूरी करते हैं। अंतिम पात्रता के लिए 31 December 2026 तक 17 वर्ष की आयु, वैध NRI/FN/PIO/OCI स्थिति और आवश्यक दस्तावेज़ भी जरूरी हैं।" if meets else f"लेकिन आपके बताए {mark}% इस कोटे की Physics, Chemistry, Biology या Biotechnology और English में आवश्यक 50% से कम हैं। NEET की छूट अंकों, आयु, स्थिति या दस्तावेज़ों की शर्त को समाप्त नहीं करती।")
            )
        else:
            result["answer"] = (
                f"NEET न दिल्यामुळेच तुम्ही अपात्र ठरत नाही. B.V.Sc. च्या NRI/FN/PIO/OCI नियमानुसार परदेशातून XII किंवा समकक्ष परीक्षा उत्तीर्ण उमेदवाराला NEET-UG-2026 मधून सूट आहे. "
                + (f"तुमचे नमूद केलेले {mark}% या कोट्यासाठी Physics, Chemistry, Biology किंवा Biotechnology आणि English मधील 50% अट पूर्ण करतात. अंतिम पात्रतेसाठी 31 December 2026 पर्यंत 17 वर्षे वय, वैध NRI/FN/PIO/OCI दर्जा आणि आवश्यक कागदपत्रेही आवश्यक आहेत." if meets else f"परंतु तुमचे नमूद केलेले {mark}% या कोट्यासाठी आवश्यक 50% पेक्षा कमी आहेत. NEET सूट गुण, वय, दर्जा किंवा कागदपत्रांच्या अटी रद्द करत नाही.")
            )
        result["model"] = "policy-localization"
        result["language"] = ctx.language
        return result
    if ctx.language in ("hi", "mr") and (
        fixed_english or lang.detect_script(result.get("answer", "")) != "devanagari"
    ):
        result = dict(result)
        result["answer"], result["model"] = llm.localize_answer(result["answer"], ctx.language)
    result["language"] = ctx.language
    return result


def answer(project_id: str, question: str, conversation_state: dict | None = None,
           ui_language: str = "en") -> dict:
    state = conversation_state or {}
    # Programme selection and a persisted language preference do not change
    # the factual answer. Guided-interview/reference slots do, and must never
    # share a cache entry with another student.
    cacheable_request = set(state).issubset({"programme", "preferredLanguage"})
    requested_language = language.requested_language(question)
    preferred_language = requested_language or state.get("preferredLanguage")
    language_ctx = language.prepare(
        question,
        preferred_language or ui_language,
        force_selected=bool(preferred_language),
    )
    previous_answer = state.get("lastAssistantAnswer")
    if (
        requested_language
        and language.requests_repeat(question)
        and isinstance(previous_answer, str)
        and previous_answer.strip()
    ):
        previous_source = state.get("lastAssistantSource")
        if previous_source == "identity" and requested_language in _IDENTITY_REPEAT:
            repeated = _IDENTITY_REPEAT[requested_language]
            model = "language-control"
        elif requested_language == "en":
            source_language = state.get("preferredLanguage") or "hi"
            repeated = llm.translate_to_english(previous_answer, source_language)
            model = "translation-to-english"
        else:
            repeated, model = llm.localize_answer(previous_answer, requested_language)
        return {
            "answer": repeated,
            "source": "language-repeat",
            "model": model,
            "pages": [],
            "slotUpdate": {"preferredLanguage": requested_language},
            "language": requested_language,
        }
    # Deterministic safety, eligibility, and clarification rules always run
    # before cache lookup. A cached generic answer must never bypass a newer
    # or more specific policy decision.
    guarded = guards.run_guards(question, conversation_state, project_id)
    if guarded is not None:
        return _with_language(guarded, language_ctx)
    reviewed = curated.get(project_id, language_ctx.language, question)
    if reviewed is not None:
        reviewed["language"] = language_ctx.language
        return reviewed
    if cacheable_request:
        cached = answer_cache.get(project_id, question, language_ctx.language)
        if cached is not None:
            return cached
    fill_token = None
    if cacheable_request:
        fill_token = answer_cache.acquire_fill_lock(project_id, question, language_ctx.language)
        if fill_token is None:
            filled = answer_cache.wait_for_fill(project_id, question, language_ctx.language)
            if filled is not None:
                return filled
            fill_token = answer_cache.acquire_fill_lock(project_id, question, language_ctx.language)
            if fill_token is None:
                return _with_language({
                    "answer": "Many students are asking the same question right now. Please retry in a moment; I won't guess or spend another provider request while the verified answer is being prepared.",
                    "source": "provider-busy", "model": "capacity-guard", "pages": [],
                }, language_ctx)
    try:
        result = _with_language(
            _answer_uncached(project_id, question, conversation_state, language_ctx),
            language_ctx,
        )
        query_vector = result.pop("_queryVector", None)
        if cacheable_request and query_vector is not None:
            semantic_faq.put(
                project_id, language_ctx.language, question, result, query_vector,
            )
        if cacheable_request:
            answer_cache.put(project_id, question, result, language_ctx.language)
        return result
    finally:
        if fill_token is not None:
            answer_cache.release_fill_lock(
                project_id, question, fill_token, language_ctx.language,
            )


def _answer_uncached(project_id: str, question: str, conversation_state: dict | None,
                     language_ctx: language.LanguageContext) -> dict:
    try:
        query_vector = embeddings.embed_query(language_ctx.retrieval_question)
    except Exception as exc:  # provider/network failure must never become HTTP 500
        print(f"[embedding-provider] query failed: {exc!r}")
        return {
            "answer": (
                "I can't safely verify that from the prospectus right now because "
                "the retrieval service is temporarily unavailable. Please try again "
                "shortly or confirm this case with the MAFSU admission office."
            ),
            "source": "provider-unavailable",
            "model": "none",
            "pages": [],
            "language": language_ctx.language,
        }
    if not conversation_state or set(conversation_state).issubset({"programme", "preferredLanguage"}):
        semantic_hit = semantic_faq.lookup(
            project_id, language_ctx.language, question, query_vector,
        )
        if semantic_hit is not None:
            return semantic_hit
    retrieval_text = _retrieval_text(language_ctx.retrieval_question)
    top = store.search(project_id, query_vector, _settings.top_k, retrieval_text)

    if not top:
        return _with_language({
            "answer": "I don't have enough verified information to answer that safely right now. Please try again shortly or confirm the question with the appropriate MAFSU admission authority.",
            "source": "no-context", "model": "none", "pages": [],
        }, language_ctx)

    if not _retrieval_is_confident(top):
        reply, model = llm.generate(
            prompts.SYSTEM_PROMPT_BASE.format(program=programs.PROGRAM_NAMES.get(project_id, project_id)) + llm.LANGUAGE_RULE,
            "There is not enough verified information to answer this safely. Say: "
            "'I don't have enough verified information to confirm that.' If a verified "
            "part is known, state it first. Suggest a targeted clarification or the "
            "appropriate admission authority. Never blame MAFSU or mention retrieval, "
            "context, excerpts, a knowledge base, vectors, chunks, or RAG.\n\n"
            f"Question: {question}" + language_ctx.reply_hint,
            language_ctx.generation_question,
        )
        return {"answer": reply, "source": "low-confidence", "model": model, "pages": [],
                "language": language_ctx.language}

    pages = sorted({e["page"] for e in top})
    context = "\n\n".join(e["text"] for e in top)
    rule_hints = _verified_rule_hints(question, project_id)
    grounded_context = f"{context}\n\nVerified rule anchors:\n{rule_hints}" if rule_hints else context

    # Eligibility verdict - checked before table lookup, same precedence as
    # the original (a personal verdict question should never fall through
    # to a generic table figure). Only acts on a determinable verdict;
    # "insufficient" falls through to general RAG rather than attempting
    # the guided interview this checkpoint doesn't have yet.
    if _looks_like_eligibility_question(question):
        result = eligibility.evaluate(project_id, question)
        if result["verdict"] in ("eligible", "not_eligible"):
            facts = _eligibility_facts_text(result) + language_ctx.reply_hint
            low_question = question.lower()
            if result.get("reason") == "percentage" and result["verdict"] == "eligible" and (
                "ncl" in low_question or "non-creamy" in low_question
            ):
                rule = eligibility.RULES[project_id]
                return _with_language({
                    "answer": (
                        f"You meet the {rule['label']} marks requirement: your {result['stated']:g}% is above the "
                        f"{result['required']:g}% reserved-category threshold. Your qualifying {rule['entrance']} status "
                        f"also satisfies the {rule['entrance']} condition stated in your question, subject to the remaining "
                        "admission requirements. For OBC reservation you need a valid Non-Creamy Layer certificate; "
                        "without it, the reservation claim is rejected and you can only be considered Unreserved if "
                        "you meet the Unreserved eligibility requirements."
                    ),
                    "source": "eligibility", "model": "guard", "pages": [rule["page"]],
                }, language_ctx)
            if _compound_eligibility(question):
                compound_prompt = (
                    f"Deterministic eligibility decision:\n{facts}\n\n"
                    f"Prospectus excerpts and verified anchors:\n{grounded_context}\n\n"
                    f"Student's full multi-part question: {question}\n\n"
                    "State the locked eligibility decision first, then answer every additional part. "
                    "The entrance score cannot compensate for a failed qualifying-exam threshold."
                )
                reply, model = llm.generate(
                    prompts.ELIGIBILITY_SYSTEM_PROMPT, compound_prompt,
                    language_ctx.generation_question,
                )
                reply = validate.autofix(reply)
                reasons = validate.deterministic_checks(question, grounded_context + "\n" + facts, reply, project_id)
                if not reasons:
                    return {"answer": reply, "source": "eligibility", "model": model,
                            "pages": [result["page"]] if result.get("page") else pages,
                            "language": language_ctx.language}
            reply, model = llm.generate(
                prompts.ELIGIBILITY_SYSTEM_PROMPT, facts, language_ctx.generation_question
            )
            return {"answer": reply, "source": "eligibility", "model": model,
                    "pages": [result["page"]] if result.get("page") else pages,
                    "language": language_ctx.language}

    # Verified table lookup - code picks the number, the model only phrases it.
    verified = tablelookup.lookup(retrieval_text, top)
    if verified:
        fact_prompt = (
            f"Verified fact (this is the complete answer - nothing else is in "
            f"scope): {verified['descriptor']}: {verified['value']}\n\n"
            f"Student's question (for tone only): {question}" + language_ctx.reply_hint
        )
        reply, model = llm.generate(
            prompts.VERIFIED_FACT_SYSTEM, fact_prompt, language_ctx.generation_question
        )
        if verified["value"] not in reply:
            reply = f"{verified['descriptor']}: {verified['value']}"
        return {"answer": reply, "source": "verified-fact", "model": model, "pages": pages,
                "language": language_ctx.language}

    # General RAG.
    system_prompt = prompts.SYSTEM_PROMPT_BASE.format(program=programs.PROGRAM_NAMES.get(project_id, project_id)) + llm.LANGUAGE_RULE
    user_prompt = (
        f"Prospectus excerpts:\n{grounded_context}\n\nQuestion: {question}\n\n"
        "(Answer this fully yourself using the excerpts above - do not tell the "
        "student to go check a page number themselves. Answer every part of a multi-part question, "
        "and preserve every applicable verified rule anchor.)" + language_ctx.reply_hint
    )
    try:
        reply, model = llm.generate(system_prompt, user_prompt, language_ctx.generation_question)
    except Exception as exc:  # noqa: BLE001 - provider exhaustion must not become HTTP 500
        print(f"[generation] all providers failed: {exc!r}")
        return _with_language({"answer": "The admissions answer service is temporarily unavailable. Please try this question again shortly.",
                "source": "provider-unavailable", "model": "none", "pages": pages}, language_ctx)
    reply = validate.autofix(reply)
    reasons = validate.deterministic_checks(question, grounded_context, reply, project_id)
    if reasons:
        print(f"[validation] draft flagged for {project_id}: {reasons}")
        retry_prompt = user_prompt + (
            "\n\nA previous draft failed deterministic review: " + "; ".join(reasons) +
            ". Regenerate using only numbers and programme names present in the excerpts."
        )
        retry, retry_model = llm.generate(
            system_prompt, retry_prompt, language_ctx.generation_question
        )
        retry = validate.autofix(retry)
        if not validate.deterministic_checks(question, grounded_context, retry, project_id):
            reply, model = retry, retry_model
        else:
            print(f"[validation] regeneration still unsafe for {project_id}")
            return _with_language({
                "answer": "I don't have enough verified information to confirm that safely. Please clarify the exact programme or circumstance, or confirm the individual case with the appropriate MAFSU admission authority.",
                "source": "validation-blocked", "model": "validator", "pages": pages,
            }, language_ctx)
    return {"answer": reply, "source": "rag", "model": model, "pages": pages,
            "language": language_ctx.language, "_queryVector": query_vector}


def _eligibility_facts_text(result: dict) -> str:
    """Facts written out for the model to phrase - same "verdict already
    decided, state it" shape as backend/rag/guards.py's _eligibility_facts,
    scoped down to the percentage-verdict case only (no entrance-exam or
    subjects reasons yet - those require the fuller guard logic this
    checkpoint hasn't ported).
    """
    if result.get("reason") == "entrance_exam":
        return "\n".join([
            f"VERDICT (already decided): the student does NOT currently meet the admission requirement for {result['programme']}.",
            f"Reason: they stated that they did not appear for {result['entrance']}, which is required.",
            "Lead with the negative verdict. Do not contradict it or discuss marks as if they override the exam requirement.",
        ])
    if result.get("reason") == "subjects":
        return "\n".join([
            f"VERDICT (already decided): the student does NOT meet the subject requirement for {result['programme']}.",
            f"Required subjects: {result['required_subjects']}.",
            f"Missing required subjects: {', '.join(result.get('missing') or [])}.",
            "Lead with the negative verdict.",
        ])
    verdict = "MEETS THE MARKS REQUIREMENT for" if result["verdict"] == "eligible" else "is NOT eligible for"
    lines = [
        f"VERDICT (already decided, state exactly this): the student {verdict} "
        f"{result['programme']} on the marks they gave.",
        f"Their stated marks in {result['required_subjects']}: {result['stated']}%.",
        f"The requirement for the {result['category']} category: {result['required']}%.",
    ]
    if result["verdict"] == "not_eligible":
        lines.append("A good entrance-exam score cannot compensate for failing the qualifying-examination marks threshold.")
    if result.get("category_assumed"):
        lines.append("They did not state a category, so this used the Unreserved requirement.")
    if result["verdict"] == "eligible" and result.get("entrance"):
        lines.append(f"Meeting the marks requirement is NOT the same as being admitted - "
                     f"they must also clear (not just appear for) {result['entrance']}.")
    if result["verdict"] == "eligible" and result.get("age_requirement"):
        lines.append(f"They must also meet the age requirement: {result['age_requirement']}.")
    lines.append("Lead with the verdict in the first sentence.")
    return "\n".join(lines)
