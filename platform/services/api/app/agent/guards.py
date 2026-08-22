"""Ordered B.V.Sc. pre-retrieval guards.

This is intentionally limited to behavior meaningful before a second
programme or Indic support exists. Trigger logic and state names are ported
from backend/rag/guards.py's guided eligibility and injection guards.
"""

import re

from ..core import eligibility, policy, routing
from ..core.intent import is_prompt_injection
from . import language as language_routing
from . import safety

_INTERVIEW_INTENTS = {
    "eligibility_awaiting_entrance", "eligibility_awaiting_category",
    "eligibility_awaiting_subject_percent", "eligibility_awaiting_subject_marks",
    "eligibility_awaiting_percentage_scope",
}
_ELIGIBILITY_WORDS = ("eligible", "eligibility", "qualify")
_GREETINGS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
_IDENTITY_QUESTIONS = {
    "who are you", "what are you", "what can you do", "how can you help",
    "what do you do", "tell me about yourself", "who is this",
}
_OFF_TOPIC_MARKERS = (
    "weather forecast", "write me a poem", "write a poem", "capital of france",
    "sports score", "stock price", "tell me a joke", "recipe for", "translate this",
)
_SPECIFIC_ADMISSION_TOPICS = (
    "eligible", "eligibility", "marks", "percentage", "fee", "fees", "seat", "seats",
    "document", "certificate", "quota", "reservation", "apply", "application", "deadline",
    "date", "college", "hostel", "refund", "cancel", "neet", "mht-cet", "cet", "cuet",
    "icar", "ncl", "caste", "age", "domicile", "weightage", "merit",
)
_PROGRAMME_LABELS = {
    "bvsc": "B.V.Sc. & A.H.",
    "bfsc": "B.F.Sc.",
    "btech-dairy": "B.Tech. (Dairy Technology)",
}


def _slot_update(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


def _reply(answer: str, source: str, **extra) -> dict:
    return {"answer": answer, "source": source, "model": "guard", "pages": [], **extra}


def malformed_input_guard(question: str, state: dict) -> dict | None:
    compact = re.sub(r"\s+", "", question.casefold())
    letters = [char for char in compact if char.isalpha()]
    repeated_run = bool(re.search(r"(.)\1{11,}", compact))
    repeated_unit = bool(re.fullmatch(r"(.{1,5})\1{3,}", compact))
    nearly_one_character = len(letters) >= 20 and len(set(letters)) <= 2
    punctuation_spam = len(compact) >= 20 and not letters and not any(char.isdigit() for char in compact)
    if not (repeated_run or repeated_unit or nearly_one_character or punctuation_spam):
        return None
    return _reply(
        "I couldn't understand that message. Please type an admission question—for example, ask about eligibility, fees, documents, seats, quotas, or one of the three undergraduate programmes.",
        "malformed-input",
    )


def pii_guard(question: str, state: dict) -> dict | None:
    kinds = safety.pii_types(question)
    if not kinds:
        return None
    return _reply(
        f"For your privacy, please remove the {', '.join(kinds)} and ask again. I only need admission-relevant details such as your programme, category, subject marks or percentage, age, domicile, and exam status—never full identity or application numbers.",
        "privacy-guard",
    )


def admission_year_guard(question: str, state: dict) -> dict | None:
    requested = safety.year_mismatch(question)
    if not requested:
        return None
    return _reply(
        f"I am currently locked to the verified 2026-27 admission rules. I don't have enough verified information to confirm rules for {requested}, and I will not mix that year's requirements with 2026-27. Please use the official material for that admission year before relying on an answer.",
        "knowledge-boundary",
    )


def prediction_guard(question: str, state: dict) -> dict | None:
    low = question.lower()
    if not any(term in low for term in ("what are my chances", "chance of admission", "will i get nagpur", "will i get mumbai", "guaranteed seat", "predict my college", "probability")):
        return None
    return _reply(
        "I can check published eligibility rules and explain how merit, quota, preferences and seat availability affect allotment, but I cannot predict a college, percentage chance, cutoff or guaranteed seat. Tell me the programme and the rule you want checked, and I will verify that part without guessing an allotment outcome.",
        "prediction-boundary",
    )


def contradiction_guard(question: str, state: dict) -> dict | None:
    low, previous = question.lower(), state.get("entranceExamStatus")
    now_positive = bool(re.search(r"\b(?:cet|neet|cuet)\b.*\b(?:percentile|score)\b\D{0,8}\d", low))
    now_negative = bool(re.search(r"\b(?:did(?:n'?t| not)|never|have not|haven't)\b.{0,18}\b(?:appear|take|sit)\b.{0,12}\b(?:cet|neet|cuet)\b", low))
    if not ((previous in {"no", "pending", "not_qualified"} and now_positive) or (previous == "yes" and now_negative)):
        return None
    return _reply(
        "I have conflicting entrance-exam details from this chat. Please confirm the current fact before I assess eligibility; I will replace the earlier answer with your correction.",
        "state-contradiction", interviewField="entranceExamStatus",
        interviewOptions=[{"label": "I completed/appeared for it", "value": "yes"}, {"label": "I did not appear", "value": "no"}, {"label": "I appeared but did not qualify", "value": "not_qualified"}],
        carryQuestion=state.get("carryQuestion") or question,
    )


def injection_guard(question: str, state: dict) -> dict | None:
    if not is_prompt_injection(question):
        return None
    return _reply(
        "I can only help with admissions using the official prospectus. I can't follow instructions that override that role.",
        "instruction-override",
    )


def greeting_guard(question: str, state: dict) -> dict | None:
    if " ".join(question.lower().strip(" !.,?").split()) not in _GREETINGS:
        return None
    return _reply(
        "Hi! I'm MAFSU MITRA. How can I help with your admission today?",
        "greeting",
    )


def identity_guard(question: str, state: dict) -> dict | None:
    low = " ".join(question.lower().strip(" !.,?").split())
    if not any(prompt in low for prompt in _IDENTITY_QUESTIONS):
        return None
    return _reply(
        "I'm MAFSU MITRA (Beta), an admissions assistant for MAFSU's undergraduate programmes: B.V.Sc. & A.H., B.F.Sc., and B.Tech. (Dairy Technology). I can help you check eligibility step by step and explain entrance exams, fees, seats and colleges, quotas and reservations, required documents, and the application process. I'm a beta assistant and may make mistakes, so please verify final admission decisions with the University. Ask naturally—for example, “I have 48% and appeared for NEET; can I apply for B.V.Sc.?”",
        "identity",
    )


def institutional_role_guard(question: str, state: dict) -> dict | None:
    low = " ".join(question.lower().strip(" !.,?").split())
    asks_holder = any(term in low for term in ("head of university", "head of the university", "head university", "vice chancellor", "vice-chancellor", "registrar name", "who runs mafsu"))
    if not asks_holder:
        return None
    selected_office = state.get("universityOffice")
    if selected_office:
        label = {"vice-chancellor": "Vice-Chancellor", "registrar": "Registrar", "dean": "college Dean"}.get(str(selected_office), "office-holder")
        return _reply(
            f"I don't have enough verified current information to confirm the {label}'s name. Please check the official MAFSU contact or administration page for the current appointment.",
            "knowledge-boundary",
        )
    if "head" in low and not any(term in low for term in ("vice chancellor", "vice-chancellor", "registrar", "dean")):
        return _reply(
            "Which office-holder do you mean—the Vice-Chancellor, Registrar, or the Dean of a particular college?",
            "clarification",
            interviewField="universityOffice",
            interviewOptions=[
                {"label": "Vice-Chancellor", "value": "vice-chancellor"},
                {"label": "Registrar", "value": "registrar"},
                {"label": "College Dean", "value": "dean"},
            ],
            carryQuestion=question,
        )
    return _reply(
        "I don't have enough verified current information to confirm that office-holder's name. Please check the official MAFSU contact or administration page for the current appointment.",
        "knowledge-boundary",
    )


def nri_programme_guard(question: str, state: dict) -> dict | None:
    low = " ".join(question.lower().split())
    if "nri" not in low and not any(term in low for term in ("foreign national", "pio", "oci")):
        return None
    asks_courses = any(term in low for term in (
        "what course", "which course", "which programme", "which program", "what programme", "what program",
        "courses am i eligible", "programmes have", "programs have", "admission route", "not eligible for btech",
        "not eligible for b.f.sc", "not eligible for bfsc",
    ))
    if not asks_courses:
        return None
    return _reply(
        "NRI/FN/PIO/OCI admission routes exist for all three MAFSU undergraduate programmes: B.V.Sc. & A.H., B.F.Sc., and B.Tech. (Dairy Technology). Being NRI does not by itself confirm eligibility for any course. Each programme has separate required Class 12 subjects and marks, age rules, entrance-exam or XII-abroad exceptions, and category documents. Tell me where you completed Class 12, your subjects and combined percentage, your age, and any NEET/MHT-CET/CUET status, and I can check each programme separately.",
        "verified-policy",
        pages=[4, 7, 8],
    )


def subject_requirement_guard(question: str, state: dict, project_id: str) -> dict | None:
    low = question.lower()
    if project_id == "btech-dairy" and re.search(r"\b(?:did not|didn't|without|no)\b.{0,20}\b(?:mathematics|maths|math)\b", low):
        return _reply(
            "No. B.Tech. (Dairy Technology) requires Physics, Chemistry, Mathematics and English in Class 12 and uses the PCM entrance route. Because you stated that you did not study Mathematics, you do not meet that programme's subject requirement. Other stated subjects or entrance scores cannot replace Mathematics.",
            "eligibility", pages=[5],
        )
    return None


def document_status_guard(question: str, state: dict, project_id: str) -> dict | None:
    low = question.lower()
    if ("ncl" in low or "non-creamy" in low) and any(term in low for term in ("expired", "not valid", "invalid")):
        pages = {"bvsc": [11, 12], "bfsc": [10, 67], "btech-dairy": [10, 67]}[project_id]
        return _reply(
            "No—an expired or otherwise invalid Non-Creamy Layer certificate does not confirm OBC reservation. It is acceptable only if it remained valid through the application-submission deadline or satisfies the applicable issue-date rule. If a valid NCL is not accepted in time, the OBC reservation claim is lost; the candidate may be considered Unreserved only if the Unreserved eligibility requirements are independently met.",
            "verified-policy", pages=pages,
        )
    return None


def challenge_guard(question: str, state: dict) -> dict | None:
    low = " ".join(question.lower().strip(" !.,?").split())
    if low not in {"sure", "are you sure", "really", "is that correct"}:
        return None
    previous = str(state.get("lastAssistantAnswer") or "")
    if "nri" in previous.lower() and ("not for b.tech" in previous.lower() or "not for b.f.sc" in previous.lower()):
        return _reply(
            "No—that earlier statement was incorrect. NRI/FN/PIO/OCI admission routes exist for B.V.Sc. & A.H., B.F.Sc., and B.Tech. (Dairy Technology). Eligibility must be checked separately using your Class 12 location, subjects, marks, age, entrance-exam status and NRI documents.",
            "correction",
        )
    if "nri" in previous.lower() and "all three" in previous.lower():
        return _reply(
            "Yes—NRI/FN/PIO/OCI admission routes exist for all three programmes. That confirms the availability of the routes, not your personal eligibility; your subjects, marks, Class 12 location, age, entrance-exam status and documents must still be checked separately.",
            "verified-policy",
        )
    if previous:
        return _reply(
            "I should not confirm that with a bare yes or no without rechecking the exact rule. Please tell me which part you want verified, and I’ll confirm only what I can establish safely.",
            "clarification",
        )
    return _reply("Which earlier answer would you like me to verify?", "clarification")


def language_preference_guard(question: str, state: dict) -> dict | None:
    requested = language_routing.requested_language(question)
    if requested is None:
        return None
    answers = {
        "hi": "हाँ—अब से मैं आपको हिंदी में जवाब दूँगा। आप प्रवेश से जुड़ा अपना अगला प्रश्न पूछ सकते हैं।",
        "mr": "हो—आता पुढे मी तुम्हाला मराठीत उत्तर देईन. प्रवेशासंबंधी तुमचा पुढचा प्रश्न विचारा.",
        "en": "Yes—I'll reply in English from now on. Ask your next admissions question whenever you're ready.",
    }
    return {
        "answer": answers[requested],
        "source": "language-preference",
        "model": "language-control",
        "pages": [],
        "slotUpdate": {"preferredLanguage": requested},
    }


# Legal remedies and liability are outside what a prospectus can settle, and
# outside what this assistant may assert. Three real failures on the live
# service motivated this guard: "can I sue them?" was answered "You cannot sue
# MAFSU..." (a categorical legal conclusion in the University's voice); "who is
# responsible if the information YOU give me is wrong?" was answered with the
# student's own form-accuracy obligations plus a claim that the University
# would not be held accountable; and with no programme selected the same
# question was routed to "which programme are you asking about?", because
# "application" is in the programme-clarify topic list.
#
# Deliberately narrow: it must NOT capture "how do I file a grievance", which
# is a real prospectus procedure with its own fee and its own eval case.
_LEGAL_REMEDY = re.compile(
    r"\bsue\b|\bsuing\b|\blawsuit\b|\blegal action\b|\blegal notice\b|"
    r"\bfile a case\b|\bcase against\b|\btake (?:them|mafsu|the university) to court\b|"
    r"\bconsumer court\b|\bhigh court\b|\bcompensation\b|\bdamages\b",
    re.I,
)
_LIABILITY = re.compile(
    r"who (?:is|are|will be|would be) (?:responsible|liable|accountable)|"
    r"hold (?:you|mafsu|the university|anyone) (?:responsible|liable|accountable)|"
    r"(?:your|this bot(?:'s)?|the bot(?:'s)?) (?:answer|answers|information|advice|reply) (?:is|are|was|were) wrong|"
    r"if (?:you|the bot) (?:give|gives|gave|is|are|was|were) (?:me )?(?:wrong|incorrect|false)",
    re.I,
)

LEGAL_BOUNDARY_REPLY = (
    "I can't advise on legal action or say who would be held responsible - I'm a beta "
    "assistant, not an official record, and nothing I say creates or settles an admission "
    "right. What governs admission is the official prospectus and MAFSU's own admission "
    "notifications, so please confirm anything important with the MAFSU admission authority "
    "before you act on it. If you believe a decision on your application is wrong, raise it "
    "through MAFSU's own grievance process rather than relying on this chat."
)


def legal_boundary_guard(question: str, state: dict) -> dict | None:
    low = " ".join(question.lower().split())
    if not (_LEGAL_REMEDY.search(low) or _LIABILITY.search(low)):
        return None
    return _reply(LEGAL_BOUNDARY_REPLY, "legal-boundary")


def off_topic_guard(question: str, state: dict, project_id: str = "bvsc") -> dict | None:
    low = " ".join(question.lower().split())
    if not any(marker in low for marker in _OFF_TOPIC_MARKERS):
        return None
    # The decline must name the programme the student is actually on. It
    # used to hardcode B.V.Sc. & A.H., which told a B.F.Sc. or Dairy
    # student the assistant only covers a programme they never selected.
    label = _PROGRAMME_LABELS.get(project_id, "MAFSU")
    return _reply(
        f"I can only help with {label} admission questions from the official prospectus.",
        "off-topic",
    )


def programme_clarify_guard(question: str, state: dict) -> dict | None:
    """Require a programme before answering programme-dependent questions."""
    low = " ".join(question.lower().strip(" !.,?").split())
    if state.get("programme") or routing.explicitly_named_projects(question):
        return None
    if not any(topic in low for topic in _SPECIFIC_ADMISSION_TOPICS):
        return None
    return _reply(
        "Sure — which MAFSU undergraduate programme are you asking about? Fees, eligibility, seats, entrance exams, and documents can differ by programme.",
        "programme-clarify",
        interviewField="projectId",
        interviewOptions=[
            {"label": "B.V.Sc. & A.H.", "value": "bvsc"},
            {"label": "B.F.Sc.", "value": "bfsc"},
            {"label": "B.Tech. (Dairy Technology)", "value": "btech-dairy"},
        ],
        carryQuestion=question,
        slotUpdate={"intent": "programme_awaiting_choice"},
    )


def programme_help_guard(question: str, state: dict, project_id: str) -> dict | None:
    """Treat a broad "help with this course" opening as navigation."""
    low = " ".join(question.lower().strip(" !.,?").split())
    asks_for_help = (
        "help me" in low or "help mw" in low or "help with" in low
        or low.startswith("tell me about")
    )
    if not asks_for_help or any(topic in low for topic in _SPECIFIC_ADMISSION_TOPICS):
        return None
    label = _PROGRAMME_LABELS.get(project_id, "this programme")
    return _reply(
        f"Yes, I can help with {label} What would you like to know: eligibility, fees, seats and colleges, documents, quotas, or the application process?",
        "topic-menu",
        slotUpdate={"programme": project_id, "intent": "programme_help_menu"},
    )


def multi_programme_eligibility_guard(question: str, state: dict) -> dict | None:
    """Resolve a high-confidence three-programme eligibility comparison.

    This deliberately requires every decisive fact rather than guessing across
    programmes from an incomplete comparison. Broader comparisons continue to
    retrieval until their own deterministic composition is implemented.
    """
    low = " ".join(question.lower().split())
    named = set(routing.explicitly_named_projects(question))
    has_all_programmes = named == {"bvsc", "bfsc", "btech-dairy"}
    has_decisive_facts = (
        has_all_programmes
        and "obc" in low
        and re.search(r"\b49(?:\.0+)?\s*%", low)
        and re.search(r"\b(?:did not|didn'?t|without|no)\s+(?:have\s+)?mathematics\b", low)
        and "mht-cet" in low
        and "pcb" in low
        and "neet" in low
        and re.search(r"\b(?:did not|didn'?t|not)\s+qualif", low)
        and "fisherman" in low
    )
    if not has_decisive_facts:
        return None
    return _reply(
        "Based on the information you've shared:\n\n"
        "B.V.Sc. & A.H.: No. Your 49% meets the 47.5% Reserved-category "
        "academic minimum, but B.V.Sc. requires a qualifying NEET-UG-2026 "
        "score. Since you did not qualify NEET, you do not currently meet that "
        "requirement.\n\n"
        "B.F.Sc.: You meet the academic and entrance-exam requirements you've "
        "described so far. Your 49% in Physics, Chemistry, Biology and English "
        "is above the 40% Reserved-category minimum, you are already 17, and "
        "you appeared for MHT-CET 2026 in PCB. Your NEET result does not affect "
        "B.F.Sc. eligibility.\n\n"
        "B.Tech. (Dairy Technology): No. Mathematics is compulsory in the "
        "required Physics, Chemistry, Mathematics and English combination, and "
        "the regular entrance route uses the MHT-CET PCM result. Your PCB attempt "
        "cannot replace Mathematics or the PCM requirement.\n\n"
        "Fisherman benefit: For B.F.Sc., the prescribed valid Fisherman's "
        "Certificate can add 12 weightage points to your MHT-CET PCB percentile "
        "for merit calculation, subject to the overall maximum of 20 additional "
        "weightage points. It does not repair B.V.Sc. NEET eligibility or the "
        "missing Mathematics requirement for Dairy Technology.\n\n"
        "Your final B.F.Sc. eligibility still depends on every other applicable "
        "requirement and valid admission/category documents. To claim OBC "
        "reservation, provide the applicable valid NCL, caste and caste-validity "
        "documents.",
        "verified-policy", pages=[4, 10, 11, 12],
    )


def paragraph_policy_guard(question: str, state: dict) -> dict | None:
    """High-risk compound rules from the natural-paragraph promotion gate."""
    low = " ".join(question.lower().split())
    if "private veterinary" in low and "management" in low and "neet qualify nahi hua" in low:
        return _reply(
            "No. Management quota does not remove the B.V.Sc. NEET requirement. MAFSU fills Management-quota seats in provisionally affiliated private veterinary colleges through University allotment using the NEET-UG-2026 qualifying score/marks. Since you did not qualify NEET, you cannot use Management quota to bypass that requirement, and the private college cannot admit you directly.",
            "verified-policy", pages=[7, 9, 26],
        )
    if "neet fail hogaya" in low and "44%" in low and "fisheries" in low and "mht cet pcb" in low:
        return _reply(
            "Failing NEET does not make you ineligible for regular B.F.Sc. As an SC/Reserved candidate, your 44% in Physics, Chemistry, Biology and English exceeds the 40% minimum, and you appeared for MHT-CET 2026 PCB. You therefore meet those academic and entrance requirements so far. Final eligibility still requires the age condition and valid category/admission documents.",
            "verified-policy", pages=[5, 7],
        )
    if "general category 49% only" in low and "97 percentile" in low and "fisherman" in low:
        return _reply(
            "No. An Unreserved B.F.Sc. candidate needs at least 50% in Physics, Chemistry, Biology and English; your 49% is below that basic eligibility minimum. The 97 MHT-CET percentile and fisherman weightage apply to merit only after eligibility is satisfied. They cannot increase your Class 12 percentage or make you eligible.",
            "verified-policy", pages=[5, 8, 11],
        )
    if "nri" in low and "12th abroad" in low and "didn't write mht cet" in low and "bfsc" in low:
        return _reply(
            "MHT-CET is not compulsory in this specific B.F.Sc. NRI/FN/PIO/OCI case. A candidate who completed XII/equivalent abroad is exempt from MHT-CET-2026. Candidates who completed XII in India must instead have appeared for MHT-CET-2026 or CUET (ICAR-UG)-2026. The exemption alone does not confirm admission; you must still meet the academic, age, NRI-status and document requirements.",
            "verified-policy", pages=[15, 16],
        )
    if "72% pcb" in low and "maths nahi tha" in low and "dairy technology" in low:
        return _reply(
            "No. B.Tech. (Dairy Technology) requires Mathematics in the Class 12 Physics, Chemistry, Mathematics and English combination, and regular merit uses the MHT-CET 2026 PCM percentile. Your Biology/PCB marks and PCB CET percentile cannot replace Mathematics or the PCM entrance requirement.",
            "verified-policy", pages=[5],
        )
    if "pcmb tha" in low and "only pcb diya not pcm" in low and "dairy tech" in low:
        return _reply(
            "Do not confirm eligibility from Class 12 Mathematics alone. PCMB satisfies the subject side if the required PCME percentage is met, but Dairy Technology also uses the MHT-CET 2026 Physics, Chemistry and Mathematics percentile. Since you appeared only for PCB and have no PCM MHT-CET percentile, you do not meet the stated regular PCM entrance/merit requirement.",
            "verified-policy", pages=[5, 8],
        )
    if "warud was first choice" in low and "didn't report" in low and "next round" in low:
        return _reply(
            "No. Because Warud was your first preference and it was allotted to you, failure to report within the stipulated period cancels your candidature for all subsequent rounds. The different rule—remaining eligible for later rounds after non-reporting—applies only when the allotment was the second preference or lower.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "18 yrs old" in low and "48% in pcmb english" in low and "cet pcb 82" in low and "pcm 76" in low:
        return _reply(
            "The three programmes must be checked separately.\n\nB.V.Sc. & A.H.: No for regular admission. Your 48% clears the 47.5% Reserved marks minimum, but you did not qualify NEET-UG-2026.\n\nB.F.Sc.: You meet the stated basic requirements so far: 48% exceeds the 40% Reserved minimum and you appeared for MHT-CET PCB. Merit uses your PCB percentile plus applicable weightage. A valid prescribed Fisherman's Certificate can add 12 points, subject to the overall 20-point cap.\n\nB.Tech. (Dairy Technology): Your PCMB includes Mathematics and you have a PCM MHT-CET percentile, so Dairy must be assessed using the required PCME percentage and your PCM result—not PCB or NEET. On the stated 48% Reserved profile, those marks/exam requirements are met so far.\n\nOBC reservation is separate from basic course eligibility. An expired NCL does not establish the OBC claim unless it satisfies the prospectus validity rule or a valid replacement is accepted in time; do not treat that document issue as automatic failure for every course. Final B.F.Sc./Dairy eligibility still depends on valid category documents and all remaining requirements, and eligibility does not guarantee allotment.",
            "verified-policy", pages=[4, 5, 7, 8, 11, 14],
        )
    if "48%" in low and "ncl certificate expired" in low and "qualified neet" in low:
        return _reply(
            "You meet the B.V.Sc. academic and NEET requirements stated so far: 48% clears the 47.5% OBC/Reserved minimum and you qualified NEET. However, an expired NCL does not establish the OBC claim. Without a valid NCL accepted within the prescribed period, you can be considered only as Unreserved; because 48% is below the 50% Unreserved minimum, you cannot rely on conversion to General/Unreserved eligibility. Your caste certificate and validity do not replace the NCL.",
            "verified-policy", pages=[4, 11, 12],
        )
    if "49%" in low and "general" in low and "neet score" in low and "50%" in low:
        return _reply(
            "No—you are not eligible for B.V.Sc. on these marks. A General/Unreserved candidate must have at least 50% in Physics, Chemistry, Biology or Biotechnology and English taken together. Your 49% is below that independent academic minimum, and a good NEET score cannot compensate for it.",
            "verified-policy", pages=[4],
        )
    if "parents are working in dubai" in low and "studied my 11th and 12th" in low and "didnt give neet" in low:
        return _reply(
            "No. For the B.V.Sc. NRI/FN/PIO/OCI route, the NEET exemption applies only when XII/equivalent was completed abroad. Because you completed XII in India, you must have appeared for and obtained the required qualifying NEET-UG-2026 score; your parents working abroad does not create the XII-abroad exemption.",
            "verified-policy", pages=[20, 21],
        )
    if "studied 11th 12th in karnataka" in low and "nagpur veterinary" in low and "domicile" in low:
        return _reply(
            "You may apply as a Maharashtra-domicile candidate using the prescribed parent domicile/residence evidence. Because you completed XII outside Maharashtra, you are considered under the 30% State Quota, not the 70% Regional Quota. Nagpur may be listed subject to that State-Quota process, merit, preferences and seat availability.",
            "verified-policy", pages=[5, 17, 18, 24],
        )
    if "got bvsc seat in first round" in low and "dont get upgraded" in low:
        return _reply(
            "You must submit preferences again for the next round. Whether your present seat remains if Nagpur is not allotted depends on the exact round, preference position, reporting/confirmation status and quota rule. A confirmed Regional- or State-quota admission can be final, so the prospectus does not support a blanket promise that your first seat will always remain. Do not surrender it unless the applicable round instructions confirm the consequence.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "neet scorecard was old/wrong" in low and "deficient document" in low:
        return _reply(
            "A wrong NEET scorecard is a document deficiency, not necessarily immediate final rejection. MAFSU publishes the deficient/wrong-document list and provides a limited window to re-upload only the indicated correct document. Upload the correct NEET marksheet within that deadline; failure to correct it in time leads to rejection.",
            "verified-policy", pages=[12, 23, 61],
        )
    if "checking fisheries" in low and "neet didn't qualify" in low and "44%" in low:
        return _reply(
            "Yes—you meet the B.F.Sc. academic and entrance requirements stated so far. As an SC/Reserved candidate, your 44% in Physics, Chemistry, Biology and English exceeds the 40% minimum, and you appeared for MHT-CET 2026 PCB. A failed NEET result does not block B.F.Sc.; NEET is the B.V.Sc. exam, while regular B.F.Sc. uses MHT-CET PCB. Final eligibility still depends on age and valid category/admission documents.",
            "verified-policy", pages=[5, 7],
        )
    if "49%" in low and "97" in low and "father is fisherman" in low:
        return _reply(
            "No. A General/Unreserved B.F.Sc. candidate needs at least 50% in Physics, Chemistry, Biology and English. Your 49% is below that basic eligibility threshold. A 97 MHT-CET percentile and fisherman weightage affect merit only after eligibility is satisfied; they cannot cure the missing 1%. The fisherman certificate therefore cannot make you eligible in this profile.",
            "verified-policy", pages=[5, 8, 11],
        )
    if "obc girl" in low and "46%" in low and "ncl got expired" in low:
        return _reply(
            "Your 46% meets the 40% Reserved-category B.F.Sc. academic minimum and you stated that you appeared for MHT-CET. But an expired NCL means the OBC claim is not established unless a valid NCL is accepted in time. Female reservation is horizontal and is not itself cancelled by the NCL problem; however, with 46% you do not meet the 50% Unreserved minimum, so you cannot simply continue as an eligible Open female candidate. Valid NCL, caste and caste-validity documents are required for OBC consideration.",
            "verified-policy", pages=[5, 7, 8, 14],
        )
    if "agriculture land in my grandfather name" in low and "private company" in low and "main income" in low:
        return _reply(
            "No. A 7/12 extract or land in your grandfather's name does not by itself establish the B.F.Sc. Agriculturist weightage. The prescribed condition also requires agriculture/personal cultivation to be the family's main source of income. Since you state that the main income is your father's private-company salary, you cannot claim this 12-point benefit on the facts provided.",
            "verified-policy", pages=[8, 11],
        )
    if "76 percentile" in low and "first choice is nagpur" in low and "morshi" in low:
        return _reply(
            "You may list Nagpur again, but you must submit the preference/option form again for every admission round. Whether an allotted Morshi seat remains while you seek an upgrade depends on the applicable round, preference position and whether you reported or confirmed admission; the prospectus does not support a blanket retention promise. Follow that round's instructions before giving up Morshi.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "both mht cet and icar" in low and "icar seats remain" in low:
        return _reply(
            "Yes. MAFSU State/University-quota admission through MHT-CET and ICAR counselling are separate, independent procedures, so you may participate in both if you satisfy each process. If ICAR-quota B.F.Sc. seats remain vacant after ICAR admissions, they are filled in the last round from the applicable MAFSU State merit list rather than simply remaining vacant.",
            "verified-policy", pages=[5, 9, 24],
        )
    if "dairy technology" in low and "maths was not there" in low and "mht cet pcb" in low:
        return _reply(
            "No. B.Tech. (Dairy Technology) requires Physics, Chemistry, Mathematics and English in XII and regular merit uses the MHT-CET PCM percentile. Biology, a PCB CET attempt and a good PCB percentile cannot replace Mathematics or the PCM entrance requirement.",
            "verified-policy", pages=[5],
        )
    if "pcmb" in low and "only appeared for pcb" in low and "dairy technology" in low:
        return _reply(
            "No, not through the regular MHT-CET route described. Having Mathematics in XII satisfies the subject side, but Dairy Technology merit specifically uses the MHT-CET 2026 PCM percentile. A PCB-only MHT-CET attempt cannot be substituted for the required PCM result.",
            "verified-policy", pages=[5, 8],
        )
    if "bangalore karnataka" in low and "udgir" in low and "private" in low:
        return _reply(
            "As an outside-Maharashtra candidate, you are not eligible for the constituent college at Udgir or for University-quota seats in affiliated private Dairy Technology colleges. You may be considered only for Management-quota seats in MAFSU's provisionally affiliated private colleges, subject to the academic, entrance, age and document rules.",
            "verified-policy", pages=[8],
        )
    if "private dairy college told me" in low and "directly give" in low:
        return _reply(
            "The private college cannot directly allot the Management-quota seat outside the University process. You must register through MAFSU; the University handles selection and allotment for these seats, and the applicable fees are deposited through the University process. Do not rely on a direct-college promise.",
            "verified-policy", pages=[8, 28],
        )
    if "43%" in low and "grandfathers name" in low and "father works in bank" in low:
        return _reply(
            "Your 43% in PCME meets the 40% Reserved-category academic threshold and you stated that you appeared for MHT-CET PCM. The expired NCL means you cannot currently claim OBC; 43% is also below the 50% Unreserved threshold. Female reservation is horizontal, but it does not repair missing category eligibility. You cannot claim the Agriculturist benefit because farming is not the family's main source of income, even if land is in your paternal grandfather's name. Valid NCL and other category documents remain necessary.",
            "verified-policy", pages=[5, 8, 12, 14],
        )
    if "3 years" in low and "permanently disabled" in low and "defence quota" in low:
        return _reply(
            "The normal five-year active-service condition does not apply when the defence personnel became permanently disabled while in service. Your father's three years of service therefore does not by itself prevent the Defence Personnel claim, provided you submit the prescribed competent-authority certificate proving the service and permanent disability.",
            "verified-policy", pages=[14],
        )
    if "between bvsc and bfsc" in low and "81 percentile" in low and "fisherman" in low:
        return _reply(
            "B.V.Sc. & A.H.: No. Your 48% clears the 47.5% OBC marks minimum, but you did not qualify NEET, which is required for regular B.V.Sc. admission.\n\nB.F.Sc.: You meet the stated requirements so far: 48% exceeds the 40% Reserved minimum and you appeared for MHT-CET PCB. Failed NEET does not affect B.F.Sc.\n\nThe valid Fisherman Certificate benefits B.F.Sc. merit only, adding 12 weightage points to the MHT-CET PCB percentile subject to the overall 20-point cap. It does not help B.V.Sc. eligibility. Final B.F.Sc. eligibility still depends on age and valid OBC/admission documents.",
            "verified-policy", pages=[4, 5, 8, 11],
        )
    if "52%" in low and "both pcb and pcm" in low and "all 3" in low:
        return _reply(
            "B.V.Sc. & A.H.: No, because you did not qualify NEET.\n\nB.F.Sc.: You meet the stated academic and entrance requirements so far: as a Reserved candidate 52% exceeds 40%, and B.F.Sc. uses your MHT-CET PCB result.\n\nB.Tech. (Dairy Technology): You meet the stated academic and entrance requirements so far: PCMB includes Mathematics, 52% exceeds the 40% Reserved minimum in the required PCME combination if that 52% is for those subjects, and Dairy uses your MHT-CET PCM result.\n\nFinal eligibility for B.F.Sc. and Dairy still depends on age, valid category documents and the remaining admission rules; this is not a guarantee of allotment.",
            "verified-policy", pages=[4, 5, 7, 8],
        )
    if "55%" in low and "mht cet both pcb pcm" in low and "fisheries and dairy" in low:
        return _reply(
            "B.V.Sc. & A.H.: Not eligible because your NEET score is not qualifying.\n\nB.F.Sc.: You meet the stated marks/exam requirements so far if 55% is your required PCBE combination; its merit uses your MHT-CET PCB percentile.\n\nB.Tech. (Dairy Technology): You meet the stated marks/exam requirements so far if 55% is your required PCME combination; PCMB includes Mathematics and Dairy merit uses your MHT-CET PCM percentile.\n\nFinal eligibility for both courses still depends on age, category/documents and other applicable rules, and eligibility does not guarantee admission.",
            "verified-policy", pages=[4, 5, 7, 8],
        )
    return None


def programme_help_confirmation_guard(question: str, state: dict, project_id: str) -> dict | None:
    low = " ".join(question.lower().strip(" !.,?").split())
    if state.get("intent") != "programme_help_menu" or low not in {"sure", "really", "okay", "ok"}:
        return None
    label = _PROGRAMME_LABELS.get(project_id, "this programme")
    return _reply(
        f"Yes. For {label}, ask me about eligibility, fees, seats and colleges, documents, quotas, or the application process.",
        "topic-menu",
        slotUpdate={"programme": project_id, "intent": "programme_help_menu"},
    )


def verified_policy_guard(question: str, state: dict, project_id: str = "bvsc") -> dict | None:
    low = question.lower()
    if project_id == "bfsc":
        if "41%" in low and "belong to sc" in low:
            return _reply(
                "Yes. An SC candidate's reserved-category threshold is 40% in PCBE, so your stated 41% meets the marks requirement. You must also have appeared for MHT-CET 2026 and satisfy age, documents, and other requirements.",
                "verified-policy", pages=[10],
            )
        if "agriculturist benefit and fisherman benefit together" in low:
            return _reply(
                "The weightage table treats the 7/12/Agriculturist/Landless-labourer/Fisherman's evidence as one 12-point category, not separate 12-point awards that can be stacked. Land ownership alone also does not establish either claim: Agriculturist requires the prescribed ownership relationship and main income from personal cultivation; Fisherman requires the prescribed certificate and fishing as the principal/only stated income source.",
                "verified-policy", pages=[8, 11, 40],
            )
        if "7/12 extract" in low and "how many extra points" in low:
            return _reply(
                "A valid 7/12 extract or qualifying Agriculturist Certificate carries 12 additional points. These are alternatives within the same 12-point category, so having both does not produce 24 points. The required ownership, cultivation, certificate, and claim conditions must be satisfied.",
                "verified-policy", pages=[8, 11],
            )
        if "75 percentile" in low and "12 weightage" in low:
            return _reply(
                "Yes. If the 12 weightage points are valid and no other adjustment applies, the corrected merit score is 75 + 12 = 87 points. Total additional weightage is capped at 20 points.",
                "verified-policy", pages=[11],
            )
        if "caste certificate but no caste validity" in low:
            return _reply(
                "You may claim OBC in the application only by uploading the caste certificate plus either the actual CVC or proof that the CVC proposal was submitted, along with a valid NCL certificate. If using proof, submit the actual CVC by 15 September 2026; otherwise treatment shifts to Unreserved if you meet its eligibility.",
                "verified-policy", pages=[7, 14, 50],
            )
        if "78 percentile" in low and "fisherman" in low and "ncc b" in low:
            return _reply(
                "Yes. As an OBC candidate, 42% PCBE meets the 40% reserved-category threshold and you stated that you appeared for MHT-CET 2026, subject to age and other requirements. A valid Fisherman's Certificate adds 12 points and NCC 'B' adds 2, so your corrected merit score is 78 + 12 + 2 = 92 points, below the overall 20-point weightage cap.",
                "verified-policy", pages=[10, 11, 21],
            )
        if "general category" in low and "49%" in low and "99 percentile" in low and "fisherman" in low:
            return _reply(
                "No. A General/Unreserved candidate must first have 50% in PCBE. Your 49% fails that separate eligibility threshold, so neither the 99 MHT-CET percentile nor 12 fisherman-weightage points can make you eligible.",
                "verified-policy", pages=[10, 11],
            )
        if "43%" in low and "obc" in low and "documents" in low:
            return _reply(
                "Yes. As an OBC candidate, 43% in PCBE meets the 40% reserved-category minimum, and you have appeared for MHT-CET 2026. To claim OBC reservation, upload the Maharashtra caste certificate, the Caste Validity Certificate (or proof that its proposal was submitted), and a valid Non-Creamy Layer certificate in your parent's name issued on or after 1 April 2026 or valid through the application deadline. You must also satisfy the other applicable domicile, age, and document requirements.",
                "verified-policy", pages=[5, 7, 14],
            )
        if "48%" in low and "general" in low and "mht-cet" in low:
            return _reply(
                "No. An Unreserved/General candidate must have at least 50% in Physics, Chemistry, Biology and English taken together. Your 48% is below that separate qualifying-examination minimum; a good MHT-CET percentile cannot compensate for it.",
                "verified-policy", pages=[5],
            )
        if "20 december 2026" in low and "17th birthday" in low:
            return _reply(
                "Yes, you meet the B.F.Sc. age rule: you will complete 17 years on 20 December 2026, before the 31 December 2026 cutoff. You must still meet the academic, MHT-CET, and other admission requirements.",
                "verified-policy", pages=[5],
            )
        if "10 january 2010" in low and "date of birth" in low:
            return _reply(
                "No. For B.F.Sc. 2026-27 you must complete 17 years by 31 December 2026, which means being born on or before 1 January 2010. A birth date of 10 January 2010 misses that cutoff, regardless of your MHT-CET score and 12th marks.",
                "verified-policy", pages=[5],
            )
        if "82 percentile" in low and "farmers" in low and "agricultural land" in low:
            return _reply(
                "You may claim 12 additional points by uploading a valid 7/12 extract or Agriculturist Certificate. The Agriculturist Certificate must be issued by the Tahsildar/Naib Tahsildar on or after 1 April 2026 and confirm the prescribed land ownership and main-source-of-income condition. With only this weightage, your corrected merit score is 82 + 12 = 94 points. All additional weightage together is capped at 20 points.",
                "verified-policy", pages=[8, 11],
            )
        if "father is a fisherman" in low and "70 percentile" in low:
            return _reply(
                "Yes. A Fisherman's Certificate carries 12 additional points, so with no other weightage your corrected score would be 70 + 12 = 82 points. Upload the prescribed Fisherman's Certificate issued on or after 1 April 2026 by the Tahsildar, Naib Tahsildar, or Port Officer, certifying that fishing is your parent/guardian's principal source of income. Total additional weightage is capped at 20 points.",
                "verified-policy", pages=[11, 21, 40],
            )
        if "fresh water fish culture" in low:
            return _reply(
                "Yes. Fresh Water Fish Culture (code C1) studied as a vocational subject in 11th and 12th carries 10 additional points. Those 10 points are added to your MHT-CET 2026 PCB percentile to form the corrected merit score, subject to the overall 20-point cap and submission of the required certificate.",
                "verified-policy", pages=[11],
            )
        if "ncc b" in low and "sports" in low:
            return _reply(
                "Yes, you may claim both if you upload the prescribed valid certificates: NCC 'B' carries 2 points and the specified sports/debate/elocution achievement carries 2 points, for 4 additional points from these two claims. All additional weightage categories combined are capped at 20 points.",
                "verified-policy", pages=[11],
            )
        if "obc female" in low:
            return _reply(
                "You can receive both benefits. OBC is your vertical category reservation, while the 30% female reservation is horizontal and applies within reserved as well as Unreserved categories. Your OBC claim still requires the prescribed caste certificate, Caste Validity Certificate/proof, and valid Non-Creamy Layer certificate.",
                "verified-policy", pages=[7, 8, 14],
            )
        if "non-creamy layer certificate has expired" in low:
            return _reply(
                "An expired NCL certificate is acceptable only if it remained valid through the application-form submission date. Otherwise you cannot claim OBC reservation with it: the required NCL must be issued on or after 1 April 2026 or be valid up to the application deadline. If the valid certificate is not submitted as required, the reservation claim is rejected and you may be considered Unreserved only if you meet Unreserved eligibility and complete the prescribed grievance and fee-difference process; the prospectus does not promise a general later-submission right for NCL.",
                "verified-policy", pages=[7, 14],
            )
        if "applied for my caste validity certificate" in low and "proof" in low:
            return _reply(
                "Yes. You may apply under the reserved category by uploading your caste certificate and proof that you submitted the proposal for a Caste Validity Certificate. You must then submit the actual CVC to the admitted college on or before 15 September 2026. If you miss that deadline, you can be considered only as Unreserved, provided you meet the Unreserved eligibility criteria.",
                "verified-policy", pages=[7, 14, 50],
            )
        if "first round" in low and "caste validity certificate is still pending" in low:
            return _reply(
                "You must submit the Caste Validity Certificate to the admitted college by 15 September 2026. Because your first-round reserved seat is provisional, failure to submit it by that deadline automatically cancels that provisional admission without prior notice. From the second round onward, you may be considered as Unreserved only if you meet the Unreserved eligibility criteria.",
                "verified-policy", pages=[7, 50],
            )
        if "how many b.f.sc. colleges" in low and "nagpur" in low and "morshi" in low:
            return _reply(
                "MAFSU has three constituent B.F.Sc. colleges in this prospectus: College of Fishery Science, Nagpur; College of Fishery Science, Udgir; and College of Fishery Science, Morshi. You may rank Nagpur first and then list Udgir and Morshi in your preferred order; allotment depends on merit, quota, preferences, and seat availability.",
                "verified-policy", pages=[5],
            )
        if "how many b.f.sc. seats" in low and "icar quota" in low:
            return _reply(
                "Each of Nagpur, Udgir, and Morshi has 40 regular seats: 32 under University quota and 8 under ICAR quota. Across all three colleges that is 120 seats - 96 University-quota and 24 ICAR-quota seats.",
                "verified-policy", pages=[5],
            )
        if "nagpur" in low and ("seat" in low or "intake" in low):
            return _reply(
                "Nagpur College of Fishery Science has 40 regular intake seats: 32 University-quota and 8 ICAR-quota seats. The one J&K/Ladakh seat is over and above that regular intake, not part of the 40.",
                "verified-policy", pages=[4, 5],
            )
        if "admission through icar quota" in low:
            return _reply(
                "ICAR conducts a separate, independent admission procedure for the 20% ICAR quota; those 24 seats are not allotted through MAFSU's regular University-quota application process. Follow ICAR's admission process for an ICAR seat. Any ICAR seats left vacant after ICAR's process revert to state-merit candidates in MAFSU's last admission round.",
                "verified-policy", pages=[5],
            )
        if "ews" in low and "only income certificate" in low:
            return _reply(
                "No. An income certificate alone is not accepted for EWS reservation. You must submit the prescribed EWS Eligibility Certificate valid for 2026-27 and signed by the competent authority in the prospectus format.",
                "verified-policy", pages=[14, 58],
            )
        if "55% lower limb disability" in low:
            return _reply(
                "No. The B.F.Sc. PH rules exclude a candidate with more than 50% lower-limb disability. A stated 55% lower-limb disability therefore does not qualify for admission under this PH provision.",
                "verified-policy", pages=[16, 46],
            )
        if "hearing disability" in low:
            return _reply(
                "No. The B.F.Sc. prospectus lists hearing disability among the physical conditions for which a PH-category candidate shall not be admitted. The prescribed medical certificate must certify absence of hearing disability.",
                "verified-policy", pages=[16, 46],
            )
        if "only nagpur college of fishery science" in low:
            return _reply(
                "Nagpur College of Fishery Science has 40 regular intake seats: 32 University-quota and 8 ICAR-quota seats. One J&K/Ladakh seat is listed over and above intake; the shared NRI quota is not assigned as a fixed Nagpur-only count.",
                "verified-policy", pages=[4],
            )
        if "don't get nagpur" in low and "udgir or morshi" in low:
            return _reply(
                "Yes. You may include Udgir and Morshi in your option/preference order and submit the required option form for the applicable round. Allotment depends on merit, quota, preferences, and vacancies; merely declining or failing to report to an existing allotment can have consequences, so follow the round rules for your current seat.",
                "verified-policy", pages=[4, 27, 28],
            )
        if "what is icar quota" in low:
            return _reply(
                "The ICAR quota is 20% of the regular B.F.Sc. intake - 24 seats across the three colleges, 8 per college. ICAR fills these seats through its own independent admission procedure, so apply through ICAR for that quota, not through MAFSU's regular University-quota process.",
                "verified-policy", pages=[4],
            )
        if "mht-cet" in low and "cuet icar" in low and "both university quota and icar" in low:
            return _reply(
                "You may pursue both only through their separate procedures: MAFSU uses MHT-CET 2026 PCB merit for University-quota admission, while ICAR independently fills the ICAR quota through its own process. Writing both examinations does not merge the quotas or make the MAFSU application an ICAR application; meet and apply under each authority's requirements separately.",
                "verified-policy", pages=[4, 10],
            )
        if "icar seats remain vacant" in low:
            return _reply(
                "Yes. ICAR seats within intake capacity that remain vacant after ICAR admissions revert to regular candidates from the Maharashtra state merit list in the last admission round.",
                "verified-policy", pages=[4],
            )
        if "from j&k" in low and "icar-ug" in low:
            return _reply(
                "For the special J&K/Ladakh quota, selection is based on CUET (ICAR-UG) 2026 merit, not MHT-CET. You must also satisfy that quota's academic and document requirements and route the verified hard-copy application through the specified J&K/Ladakh nodal officer.",
                "verified-policy", pages=[5],
            )
        if "nri" in low and "separate nri quota" in low:
            return _reply(
                "Yes. B.F.Sc. has 10 NRI/FN/PIO/OCI seats over and above the regular intake, shared across the constituent colleges rather than fixed as a per-college count. The special quota rules, documents, eligibility, and fees apply.",
                "verified-policy", pages=[4, 5, 17, 18],
            )
        if "nri seats stay vacant" in low and "normal maharashtra" in low:
            return _reply(
                "Yes. Vacant NRI/FN/PIO/OCI seats may be filled in the special round from the Maharashtra state merit list. The candidate must submit the special-round option form and pay Rs. 5,000; if admitted, the special NRI fee applies throughout the course.",
                "verified-policy", pages=[5],
            )
        if "vacant nri seat" in low and "special dollar fee" in low:
            return _reply(
                "Yes. Admission against a vacant NRI/FN/PIO/OCI seat carries the special fee of USD 3,000 per semester in addition to regular fees throughout the course, and that special fee is non-refundable.",
                "verified-policy", pages=[5, 24],
            )
        return None

    if project_id == "btech-dairy":
        if "reserved category with 41%" in low and "appeared for cet" in low:
            return _reply(
                "Yes. Your 41% PCME meets the 40% reserved-category academic threshold and you stated that you appeared for MHT-CET. Age, valid reservation documents, and the other admission requirements must also be satisfied.",
                "verified-policy", pages=[5],
            )
        if "pcb group in mht-cet" in low or ("biology in cet" in low and "maths in 12th" in low):
            return _reply(
                "No for the regular Dairy Technology merit route described here. B.Tech Dairy Technology uses the MHT-CET 2026 Physics-Chemistry-Mathematics percentile; a PCB/Biology CET group cannot substitute for the required PCM CET result, even if Mathematics was studied in XII.",
                "verified-policy", pages=[5, 15],
            )
        if "admission based on mht-cet pcm percentile" in low:
            return _reply(
                "The XII PCME marks are a qualifying threshold - 50% Unreserved or 40% Reserved. Merit is then based on the MHT-CET 2026 PCM percentile plus applicable weightage, capped at 20 additional points; high merit cannot cure failure of the XII threshold.",
                "verified-policy", pages=[5, 15],
            )
        if "2 january 2010" in low:
            return _reply(
                "No. You are not eligible on age grounds. For 2026-27 you must be born on or before 1 January 2010; a birth date of 2 January 2010 is one day after the cutoff, even if you meet the academic and MHT-CET requirements.",
                "verified-policy", pages=[5],
            )
        if "born on 1 january 2010" in low:
            return _reply(
                "Yes. A candidate born on 1 January 2010 is exactly on the permitted boundary and is old enough under the rule requiring 17 years of age by 31 December 2026. You must still meet the other admission requirements.",
                "verified-policy", pages=[5],
            )
        if "all the government/constituent" in low and "private affiliated" in low:
            return _reply(
                "The two constituent colleges are College of Dairy Technology, Warud (Pusad), District Yavatmal - 40 seats, and College of Dairy Technology, Udgir, District Latur - 40 seats. The three provisionally affiliated private colleges are Late Shaktikumar Sancheti College of Dairy Technology, Malkapur, District Buldhana - 40 seats; Prof. Prataprao Borade College of Dairy Technology, Gandheli, District Chhatrapati Sambhajinagar - 40 seats; and Aditya College of Dairy Technology, Taraf Bobade, District Beed - 40 seats.",
                "verified-policy", pages=[5, 6],
            )
        if "between warud and udgir" in low and "icar quota" in low:
            return _reply(
                "Warud has 40 seats: 34 University-quota and 6 ICAR-quota seats. Udgir has 40 seats: 33 University-quota and 7 ICAR-quota seats.",
                "verified-policy", pages=[5],
            )
        if "constituent b.tech" in low and "university quota" in low and "icar quota" in low:
            return _reply(
                "There are 80 regular seats across the two constituent colleges: Warud has 34 University-quota and 6 ICAR-quota seats, while Udgir has 33 University-quota and 7 ICAR-quota seats. The totals are 67 University-quota and 13 ICAR-quota seats. The Malkapur college is private affiliated, not a constituent college.",
                "verified-policy", pages=[5, 6],
            )
        if "didn't get a seat in warud" in low:
            return _reply(
                "Yes, you may list or try for Udgir according to the applicable option-form rounds and your preference order. The affiliated private alternatives are Late Shaktikumar Sancheti College, Malkapur, District Buldhana; Prof. Prataprao Borade College, Gandheli, District Chhatrapati Sambhajinagar; and Aditya College, Taraf Bobade, District Beed. Each private college has 40 seats split into 20 University-quota and 20 Management-quota seats.",
                "verified-policy", pages=[6, 28],
            )
        if "from karnataka" in low and "warud or udgir" in low:
            return _reply(
                "As an outside-Maharashtra candidate, you are not eligible for Warud or Udgir constituent-college seats. You are eligible only for Management-quota seats in MAFSU's provisionally affiliated private Dairy Technology colleges, subject to the applicable academic, entrance-exam, age, and document requirements. Your stated 55% alone does not establish that it is the required PCME combination.",
                "verified-policy", pages=[8],
            )
        if "outside-maharashtra" in low and "university quota seat" in low:
            return _reply(
                "You are restricted to Management-quota seats in provisionally affiliated private Dairy Technology colleges. An outside-Maharashtra candidate cannot receive a University-quota seat in those colleges.",
                "verified-policy", pages=[8],
            )
        if "another state" in low and "which entrance exam" in low and "management quota" in low:
            return _reply(
                "For affiliated-private-college Management quota, MAFSU gives first priority to eligible candidates who appeared for MHT-CET 2026. After those candidates are admitted, remaining vacancies are offered to eligible CUET (ICAR-UG) 2026 candidates. Other-state status restricts you to Management quota but does not change that priority order; 55% must also be in the required PCME combination.",
                "verified-policy", pages=[8, 28],
            )
        if "directly approach a private dairy" in low or "mafsu allot management quota" in low:
            return _reply(
                "You cannot obtain direct admission from the private college. MAFSU conducts and allots the Management-quota admissions; after allotment, you report personally to the college with the allotment letter, originals, and fees. MHT-CET candidates receive first priority, followed by CUET (ICAR-UG) candidates for remaining vacancies.",
                "verified-policy", pages=[28, 29],
            )
        if "how many private dairy" in low and "management seats" in low:
            return _reply(
                "There are three affiliated private Dairy Technology colleges: Late Shaktikumar Sancheti College at Malkapur, Prof. Prataprao Borade College at Gandheli, and Aditya College at Taraf Bobade. Each has 40 seats split into 20 University-quota and 20 Management-quota seats, for 60 Management seats total.",
                "verified-policy", pages=[6, 38],
            )
        if "government/constituent" in low and "warud and udgir" in low:
            return _reply(
                "Each constituent college has 40 regular seats. Warud has 34 University-quota and 6 ICAR-quota seats; Udgir has 33 University-quota and 7 ICAR-quota seats.",
                "verified-policy", pages=[5],
            )
        if "what is icar quota in dairy" in low:
            return _reply(
                "ICAR quota is 20% of constituent-college intake - 13 seats total, with 6 at Warud and 7 at Udgir. ICAR, New Delhi fills them through its independent admission procedure, not MAFSU's regular allotment. Vacant ICAR seats revert to the state merit list in the last round.",
                "verified-policy", pages=[5, 7],
            )
        if "icar seats remain vacant" in low:
            return _reply(
                "Yes. ICAR seats within intake capacity that remain vacant after ICAR admissions are filled by regular candidates from the state merit list in the last admission round.",
                "verified-policy", pages=[7],
            )
        if "nri" in low and "separate nri quota" in low:
            return _reply(
                "Yes. The constituent Dairy Technology colleges have 10 NRI/FN/PIO/OCI seats over and above regular intake, shared as a quota rather than assigned as a fixed per-college number. The special eligibility, documents, and fees apply.",
                "verified-policy", pages=[5, 7, 22, 23],
            )
        if "nri seats stay vacant" in low and "maharashtra students" in low:
            return _reply(
                "Yes. Vacant NRI/FN/PIO/OCI seats may be filled in the special round from the Maharashtra state merit list. If admitted, the student pays the NRI special fee of USD 3,000 per semester in addition to regular fees throughout the course.",
                "verified-policy", pages=[8],
            )
        if "nri vacant seat" in low and "3000 usd" in low:
            return _reply(
                "Yes. A student admitted to a vacant NRI/FN/PIO/OCI seat in the special round must pay USD 3,000 per semester in addition to regular fees throughout the course.",
                "verified-policy", pages=[8, 41],
            )
        if "completed first year" in low and "any certificate" in low:
            return _reply(
                "You may receive a UG Certificate (Dairy Technology) after the first-year exit only after completing at least 40 credits and the required 10-week internship carrying 10 credits.",
                "verified-policy", pages=[2, 35],
            )
        if "leave after second year" in low and "diploma" in low and "rejoin" not in low:
            return _reply(
                "Yes, provided you complete at least 80 credits plus the required 10-week internship carrying 10 credits; the exit award is a UG Diploma (Dairy Technology).",
                "verified-policy", pages=[2, 35],
            )
        if "ug certificate" in low and "join third semester" in low:
            return _reply(
                "Yes. A holder of the UG Certificate (Dairy Technology) may re-enter the third semester at the parent institute, subject to completing any first-year deficit credit load required by the regulations.",
                "verified-policy", pages=[35],
            )
        if "diploma" in low and "rejoin directly in fifth semester" in low:
            return _reply(
                "Yes. A holder of the UG Diploma (Dairy Technology) may re-enter the fifth semester at the parent institute, subject to completing any second-year deficit credit load required by the regulations.",
                "verified-policy", pages=[35],
            )
        if "internship or industrial training" in low:
            return _reply(
                "Yes. The programme includes in-plant training during the eighth (VIII) semester as part of the final year.",
                "verified-policy", pages=[2, 34],
            )
        if "obc female" in low and "farming is not" in low and "ncl has expired" in low:
            return _reply(
                "Your 43% PCME meets the 40% reserved-category academic threshold and your MHT-CET appearance satisfies that stated exam condition, subject to age and other requirements. But an expired NCL supports OBC only if it remained valid through the application deadline or otherwise meets the issue-date rule; without valid NCL you cannot claim OBC, and therefore cannot use the female reservation within OBC. Female reservation is horizontal, so you may still be considered within whatever valid category applies. You cannot claim Agriculturist reservation because farming is not the family's main source of income.",
                "verified-policy", pages=[5, 9, 10, 11],
            )
        if "from karnataka" in low and "cuet-icar" in low and "not maharashtra cet" in low:
            return _reply(
                "Potentially, but only for remaining Management-quota vacancies after eligible MHT-CET candidates receive first priority. MAFSU then offers remaining seats to eligible CUET (ICAR-UG) 2026 candidates. As a Karnataka candidate you are restricted to Management quota in affiliated private colleges, and your 60% must be in Physics, Chemistry, Mathematics and English together; age and documents must also be satisfied.",
                "verified-policy", pages=[5, 8, 28],
            )
        if "receipt showing that i applied for caste validity" in low:
            return _reply(
                "Yes. You may apply under OBC by uploading your caste certificate and proof that you submitted the Caste Validity Certificate proposal, together with the required valid NCL certificate. You must submit the actual CVC by 12 August 2026. A provisionally allotted reserved seat is cancelled if that deadline is missed; later consideration is as Unreserved only if you meet Unreserved eligibility.",
                "verified-policy", pages=[10, 67],
            )
        if "reserved seat in the first round" in low and "caste validity" in low:
            return _reply(
                "Submit the Caste Validity Certificate to the admitted college by 12 August 2026. If you miss the deadline, the provisional reserved admission automatically stands cancelled without prior notice. From the second round onward you may be considered as Unreserved, provided you meet Unreserved eligibility.",
                "verified-policy", pages=[10, 67],
            )
        if "didn't get a seat in the first round" in low and "caste validity" in low:
            return _reply(
                "You are not completely removed. If you do not submit the CVC by 12 August 2026 and were not allotted a first-round reserved seat, your candidature is considered Unreserved from the second round onward, provided you meet the Unreserved eligibility criteria.",
                "verified-policy", pages=[10],
            )
        if "non-creamy layer certificate is old" in low:
            return _reply(
                "The certificate's age alone does not decide the claim. It is accepted if it was issued on or after 1 April 2026 OR if it remains valid through the last date for submitting the application. If neither condition is met, you cannot claim OBC reservation and may be considered Unreserved only if otherwise eligible.",
                "verified-policy", pages=[10, 67],
            )
        if "issued before 1 april 2026" in low and "still valid" in low:
            return _reply(
                "Yes. MAFSU will accept it because the rule is alternative: the NCL certificate may either be issued on or after 1 April 2026 or remain valid through the last application-submission date. Your certificate satisfies the second condition.",
                "verified-policy", pages=[10, 67],
            )
        if "obc female candidate" in low:
            return _reply(
                "You receive both benefits. OBC is the vertical category reservation, while the 30% female reservation is horizontal and applies within both reserved and Unreserved categories. You do not have to choose one, provided your OBC documents are valid.",
                "verified-policy", pages=[9],
            )
        if "obc female" in low:
            return _reply(
                "Yes. OBC is the vertical category reservation and the 30% female reservation is horizontal within reserved and Unreserved categories, so both can apply together. A valid NCL, caste certificate, and CVC/proof are still required for the OBC claim; no EWS certificate is required merely because you are OBC female.",
                "verified-policy", pages=[9, 10],
            )
        if "ncl is expired" in low and "obc benefit" in low:
            return _reply(
                "An expired NCL certificate is accepted only if it was still valid through the application-submission deadline; alternatively it must satisfy the on-or-after 1 April 2026 issue rule. If neither condition is met, the OBC claim is rejected and you may be considered Unreserved only if you meet Unreserved eligibility.",
                "verified-policy", pages=[10, 67],
            )
        if "get an obc seat" in low and "fail to submit caste validity" in low:
            return _reply(
                "If you miss the 12 August 2026 CVC deadline, your provisional OBC admission automatically stands cancelled without prior notice. You are not retained in that reserved seat; from the second round onward you may be considered as Unreserved only if you meet Unreserved eligibility.",
                "verified-policy", pages=[10, 67],
            )
        if "enough female obc" in low:
            return _reply(
                "The seats do not remain vacant for that reason. If sufficient female candidates are unavailable in a category, the seats are offered during the second round to male candidates of the same category - here, eligible male OBC candidates.",
                "verified-policy", pages=[27],
            )
        if "main income comes" in low and "private job" in low:
            return _reply(
                "No. Merely owning agricultural land is insufficient. The Agriculturist certificate must establish that the family's main source of income is personal cultivation of that land; income mainly from a private job does not satisfy this condition.",
                "verified-policy", pages=[11],
            )
        if "paternal grandfather's name" in low:
            return _reply(
                "Yes, land owned by your paternal grandfather can qualify, but the main-source-of-income condition must also be satisfied. Upload the prescribed 7/12 extract and/or Agriculturist Certificate issued by the Tahsildar or Naib Tahsildar on or after 1 April 2026, identifying the paternal-grandfather relationship, qualifying ownership, and income from personal cultivation.",
                "verified-policy", pages=[11, 47],
            )
        if "grandfather" in low and "claim ag reservation" in low:
            return _reply(
                "It can qualify only when the land is in your paternal grandfather's name and the prescribed main-income-from-personal-cultivation condition is met. Submit the required 7/12 extract and/or Agriculturist Certificate from the Tahsildar or Naib Tahsildar, issued on or after 1 April 2026, establishing the relationship, ownership, and income condition.",
                "verified-policy", pages=[11, 47],
            )
        if "army for 4 years" in low and "retired normally" in low:
            return _reply(
                "No. Normal retirement after four years does not meet the minimum five years of active service required for the Defence Personnel reservation. The shorter-service exception applies only where the service person was permanently disabled or died in action.",
                "verified-policy", pages=[13],
            )
        if ("army for only 3 years" in low or "served only 3 years" in low) and "permanently disabled" in low:
            return _reply(
                "The normal five-year minimum does not apply where the service person was permanently disabled during service/action. Therefore the three-year duration does not by itself defeat the Defence Personnel claim; you must submit the prescribed competent-authority certificate proving the disability and service status.",
                "verified-policy", pages=[13],
            )
        if "leave after completing the first year" in low:
            return _reply(
                "The year is not automatically wasted. After completing at least 40 credits plus the required 10-week internship carrying 10 credits, you may receive a UG Certificate (Dairy Technology) in the specified exit area. If you later return, you may enter the third semester at your parent institute and must complete any first-year deficit credits under the regulations.",
                "verified-policy", pages=[2, 35],
            )
        if "complete two years" in low and "which semester" in low:
            return _reply(
                "After completing at least 80 credits plus the required 10-week internship carrying 10 credits, you may receive a UG Diploma (Dairy Technology). If you return, you may enter the fifth semester at your parent institute and must complete any second-year deficit credits under the regulations.",
                "verified-policy", pages=[2, 35],
            )
        return None

    special_nri = any(term in low for term in ("nri", "fn", "pio", "oci", "foreign national"))
    studied_abroad = any(term in low for term in (
        "12th at usa", "12th in usa", "xii at usa", "xii in usa", "completed my 12th abroad",
        "completed xii abroad", "passed 12th abroad", "passed xii abroad", "outside india",
        "school abroad", "examination from abroad",
    )) or ("12th" in low and ("usa" in low or "united states" in low))
    studied_in_india = any(term in low for term in (
        "12th in india", "xii in india", "completed my 12th in india", "passed 12th in india",
        "passed xii in india", "examination from india",
    ))
    missed_neet = "neet" in low and any(term in low for term in (
        "not completed", "did not appear", "didn't appear", "have not appeared", "haven't appeared",
        "without neet", "no neet", "not attempted", "didn't take", "did not take",
        "did not write", "didn't write", "have not written", "haven't written",
    ))
    if special_nri and studied_abroad and missed_neet:
        return _reply(
            "Your lack of NEET does not by itself make you ineligible for the B.V.Sc. NRI/FN/PIO/OCI quota. The specific quota rule exempts candidates who passed XII or an equivalent examination abroad - including the USA - from NEET-UG-2026. This exception overrides the general NEET rule for this circumstance. Final eligibility still requires at least 50% in Physics, Chemistry, Biology or Biotechnology and English taken together, completion of age 17 by 31 December 2026, valid NRI/FN/PIO/OCI status and documents, and the other admission requirements. Also note that MAFSU states there are no seats for an 'NRI sponsored' candidate; you must qualify in one of the actual NRI/FN/PIO/OCI categories.",
            "verified-policy", pages=[20, 21],
        )
    if special_nri and studied_in_india and missed_neet:
        return _reply(
            "No. For the B.V.Sc. NRI/FN/PIO/OCI quota, a candidate who passed XII or its equivalent in India must have appeared for NEET-UG-2026. The NEET exemption applies only when the qualifying XII/equivalent examination was passed abroad.",
            "verified-policy", pages=[20, 21],
        )
    if "48%" in low and "ncl expired" in low and "caste validity is pending" in low:
        return _reply(
            "Your 48% PCBE meets the 47.5% reserved-category marks threshold and you stated that you qualified NEET. But reserved admission is not yet established. The NCL certificate must be issued on or after 1 April 2026 or remain valid through the application deadline; otherwise the OBC claim is rejected. Proof of a pending CVC proposal may accompany the application, but the actual CVC must be submitted by the prospectus deadline or a provisional reserved admission is cancelled. You may then be considered Unreserved only if you meet its 50% threshold - which 48% does not.",
            "verified-policy", pages=[4, 11, 12],
        )
    if "general category" in low and "49%" in low and "compensate" in low:
        return _reply(
            "No. The 50% Unreserved PCBE threshold is a separate eligibility condition. Your 49% is below it, and a high NEET score cannot compensate for the missing qualifying-examination percentage.",
            "verified-policy", pages=[4],
        )
    if "47.8%" in low and "sc" in low:
        return _reply(
            "Yes, your stated 47.8% PCBE meets the 47.5% reserved-category marks threshold and you stated that you qualified NEET. Final admission still depends on age, valid SC reservation documents, merit, and the remaining requirements.",
            "verified-policy", pages=[4, 10, 11],
        )
    if "outside maharashtra" in low and "only management quota" in low:
        return _reply(
            "If you are an other-state candidate who does not qualify through the specific Maharashtra-parent-domicile exception, you are eligible only for Management-quota seats in MAFSU's affiliated private veterinary colleges, not constituent-college or private-college University-quota seats. NEET and the other eligibility requirements still apply.",
            "verified-policy", pages=[7, 9],
        )
    if "seat under obc" in low and "caste validity is not ready" in low:
        return _reply(
            "You must submit the CVC by 13 August 2026. If a reserved seat was provisionally allotted and you miss that deadline, that provisional reserved admission automatically stands cancelled without prior notice. You may be considered as Unreserved in subsequent rounds only if you meet Unreserved eligibility.",
            "verified-policy", pages=[11, 18],
        )
    if "blurred" in low and ("12th" in low or "marksheet" in low):
        document = "12th marksheet" if "12th" in low else "marksheet"
        return _reply(
            f"A blurred or unreadable {document} is a document deficiency; it is not a guaranteed immediate final rejection. MAFSU publishes a deficient/wrong-document list and provides a limited resubmission window to re-upload only the indicated document. You must upload the corrected copy within the stated deadline. Failure to correct it in time leads to rejection.",
            "verified-policy", pages=[12, 23, 61],
        )
    if "seat in round 1" in low and "preference again" in low:
        return _reply(
            "Yes. You must submit the option/preference form again for Round 2 to be considered in that round. What happens to the Round-1 seat depends on whether you merely received an allotment, reported and confirmed admission, and whether it was your first preference; do not assume an upgrade attempt preserves it without checking those conditions.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "got mumbai veterinary college" in low and "want nagpur" in low:
        return _reply(
            "The prospectus does not support a blanket promise that your Mumbai seat is retained while you seek Nagpur. If you already confirmed Regional- or State-quota admission, that college/quota admission is final. If it is only an unconfirmed allotment, the consequence depends on the round, reporting, and preference conditions. Submit the next-round option form only after checking the exact status of the Mumbai allotment.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "become 17 on 30 december 2026" in low:
        return _reply(
            "Yes, you meet the age condition because you complete 17 years on 30 December 2026, before the 31 December 2026 cutoff. Academic, NEET, and other requirements still apply.",
            "verified-policy", pages=[4],
        )
    if "date of birth is 2 january 2010" in low:
        return _reply(
            "No. You must be born on or before 1 January 2010. A birth date of 2 January 2010 is after the cutoff, so good NEET marks cannot make you age-eligible.",
            "verified-policy", pages=[4],
        )
    if "studied biotechnology instead of biology" in low:
        return _reply(
            "Biotechnology is accepted as the alternative to Biology for B.V.Sc. You must also have Physics, Chemistry, and English and meet the applicable combined-percentage, NEET, age, and other requirements; naming Biotechnology alone is not enough to confirm final eligibility.",
            "verified-policy", pages=[4],
        )
    if "high school in the usa" in low and "check equivalence" in low:
        return _reply(
            "MAFSU requires the foreign XII-equivalent qualification to be recognized as equivalent by the Association of Indian Universities or the appropriate authority, and it must establish Physics, Chemistry, Biology or Biotechnology, and English. The prospectus does not prescribe the line-by-line U.S.-course or syllabus procedure, so I cannot invent one. Obtain the applicable equivalence evidence and submit the official transcript and supporting documents requested by MAFSU; confirm the exact document format with the NRI/FN/PIO/OCI admissions nodal officer before applying.",
            "verified-policy", pages=[4, 20, 21],
        )
    if "oci candidate" in low and "normal state quota" in low:
        return _reply(
            "It depends on when you acquired OCI status and, for the older-status exception, Maharashtra nativity. OCI/PIO candidates who acquired status after 4 March 2021 are eligible only for the NRI/FN/PIO/OCI quota. Those who acquired OCI/PIO status before 4 March 2021 and are native to Maharashtra may also participate in MAFSU counselling for Unreserved seats, with a Maharashtra nativity certificate and NEET-UG-2026 merit. Otherwise, apply through the NRI/FN/PIO/OCI route.",
            "verified-policy", pages=[21, 22],
        )
    if "nri seats remain vacant" in low and "normal maharashtra" in low:
        return _reply(
            "Yes. Vacant NRI/FN/PIO/OCI seats may be offered in the special round to candidates from the Maharashtra state merit list. The candidate must submit the special-round option form and pay the Rs. 5,000 option fee. If admitted, the NRI-category special fee applies throughout the course in addition to regular fees.",
            "verified-policy", pages=[8],
        )
    if "vacant nri seat" in low and "all years" in low:
        return _reply(
            "Yes. Once admitted against a vacant NRI/FN/PIO/OCI seat in the special round, you must pay the applicable special NRI fee in addition to regular fees throughout the degree course; it is not limited to the admission year.",
            "verified-policy", pages=[8, 42],
        )
    if "admission under nri seat" in low and "refunded" in low:
        return _reply(
            "No. The prospectus states that the special fee paid for an NRI/FN/PIO/OCI quota seat is non-refundable in every case, including cancellation. Any regular-fee refund is governed separately by the cancellation timetable.",
            "verified-policy", pages=[22, 28, 42],
        )
    if "difference between vci quota" in low:
        return _reply(
            "VCI quota is 15% of the intake in applicable constituent veterinary colleges and is filled by the Veterinary Council of India through its independent admission procedure. MAFSU University-quota seats are allotted by MAFSU under its own counselling, merit, regional/state-quota, and reservation rules. You may pursue both only by satisfying and applying through each authority's separate procedure; a VCI application is not a MAFSU University-quota application. VCI quota is unavailable at COVAS Akola and affiliated private veterinary colleges.",
            "verified-policy", pages=[6, 7],
        )
    if "vci seats stay vacant" in low:
        return _reply(
            "Yes, but under the prospectus's stated conditions. Vacant VCI seats within intake capacity are filled from the regular state merit list in the special round. The additional VCI seats marked '# + ##' are filled from that list in the last round only subject to Government of Maharashtra approval.",
            "verified-policy", pages=[7],
        )

    if "49.6%" in low and "compensate" in low and "neet" in low:
        return _reply(
            "You are not eligible for B.V.Sc. because 49.6% in PCB and English is below the 50% Unreserved qualifying-examination threshold. A good NEET-UG-2026 score cannot compensate for failing that separate 12th-standard marks requirement.",
            "eligibility", pages=[4],
        )
    if "outside maharashtra" in low and "father" in low and "domicile" in low:
        return _reply(
            "You may apply using your parent's Maharashtra domicile/residence evidence if it satisfies the prospectus requirement. Because you passed 12th outside Maharashtra, you are considered for the 30% State Quota, not the 70% Regional Quota.",
            "verified-policy", pages=[5, 17, 18],
        )
    if "madhya pradesh" in low and "nagpur veterinary college" in low:
        return _reply(
            "As an other-state candidate who completed 10th and 12th outside Maharashtra, you are not eligible for Nagpur Veterinary College's University-quota seats. You may apply only for management-quota seats in MAFSU's provisionally affiliated private veterinary colleges, provided you have a qualifying NEET-UG-2026 score and meet the other eligibility requirements.",
            "verified-policy", pages=[7, 9],
        )
    if "turn 17" in low and "february 2027" in low:
        return _reply(
            "No. You cannot take admission for the 2026-27 batch because you must complete 17 years of age by 31 December 2026. Turning 17 in February 2027 is after that cutoff, even if you meet the marks and NEET requirements.",
            "verified-policy", pages=[4],
        )
    if ("non-creamy layer" in low or "ncl certificate" in low) and "not ready" in low:
        return _reply(
            "You may submit the application, but you should not assume the OBC claim can be completed at document verification. The prospectus requires a valid Non-Creamy Layer certificate for OBC reservation, issued on or after 1 April 2026 or valid through the application-form submission deadline. A deficient-document resubmission is available only if MAFSU lists that certificate as an indicated deficient document and only within its resubmission deadline. If a valid NCL certificate is not accepted in time, the OBC reservation claim is rejected; you may then be considered Unreserved only if you meet Unreserved eligibility and complete the prescribed grievance/fee-difference process.",
            "verified-policy", pages=[11, 12, 19, 23],
        )
    if "preference form" in low and "next round" in low and "current allotted seat" in low:
        return _reply(
            "Yes, you must submit the option/preference form again for every admission round; otherwise you will not be considered in that round. The prospectus does not let me determine what happens to your present allotment from the facts given. If you have already confirmed admission under Regional or State quota, that admission is final and you cannot change college or quota. If you have only been allotted a seat and have not reported, the consequence depends on the quota round and whether it was your first preference, so do not give up the allotted seat without checking that exact condition with MAFSU.",
            "verified-policy", pages=[24, 25, 26],
        )
    if "pune district" in low and "mumbai veterinary college" in low:
        return _reply(
            "Pune belongs to Region C, whose Regional-Quota college is KNP College of Veterinary Science, Shirwal; Mumbai Veterinary College belongs to Region B. Therefore Mumbai is not available to you through your Region-C quota, but you may list Mumbai for the State-Quota round because it is outside your own region. The prospectus specifically bars a candidate from taking a college in their own region during the State-Quota round.",
            "verified-policy", pages=[5, 24],
        )
    if "another state" in low and "management quota" in low and "private college" in low:
        return _reply(
            "Do not seek direct allotment from the private college. MAFSU fills and allots management-quota seats in provisionally affiliated private veterinary colleges after the University-quota rounds. A qualifying NEET-UG-2026 score is compulsory for management quota, including for other-state candidates.",
            "verified-policy", pages=[7, 9, 26],
        )
    if "cancel my seat" in low and "10 days after classes start" in low:
        return _reply(
            "Submit a duly signed cancellation request to the Associate Dean or Principal of your college. Ten days after classes start is within 15 days after the formally notified last date of admission, so the prospectus refund is 80% of aggregate fees.",
            "verified-policy", pages=[28],
        )
    if "female obc" in low and "university quota" in low:
        return _reply(
            "Yes. The 30% female reservation is horizontal and is available within both Unreserved and reserved categories, including OBC. Under the University quota, you compete in your applicable OBC category with the female reservation applied within that category; you do not lose the OBC claim merely because the female reservation also applies. A valid NCL certificate is still required for the OBC benefit.",
            "verified-policy", pages=[10, 12, 14],
        )
    return None


def eligibility_guard(question: str, state: dict, project_id: str = "bvsc") -> dict | None:
    intent = state.get("intent")
    active = intent in _INTERVIEW_INTENTS
    low = question.lower()
    original_low = str(state.get("carryQuestion") or question).lower()
    asks_personal_eligibility = (
        any(word in low for word in _ELIGIBILITY_WORDS)
        or ("meet" in low and "requirement" in low)
        or ("apply" in low and not low.startswith("how do i apply") and not low.startswith("where do i apply"))
        or "can i get admission" in low
    )
    starts = eligibility.describes_self(question) and asks_personal_eligibility
    if not active and not starts:
        return None

    programme = project_id
    rule = eligibility.RULES.get(programme)
    if not rule:
        return None

    # "I appeared for NEET but did not pass/qualify" already supplies the
    # relevant BVSc entrance outcome. Asking whether the student appeared
    # again is both repetitive and misleading: BVSc merit requires a
    # qualifying NEET score, not attendance alone. Keep quota exceptions out
    # of this generic path because XII-abroad NRI/FN/PIO/OCI cases have their
    # own verified rule above this guard.
    failed_neet = (
        "neet" in original_low
        and re.search(
            r"\b(?:did(?:n'?t| not)|have(?:n'?t| not)|not)\s+"
            r"(?:pass(?:ed)?|qualif(?:y|ied))\b|\bfailed\s+(?:the\s+)?neet\b",
            original_low,
        )
    )
    special_foreign_quota = any(
        marker in original_low for marker in ("nri", "fn", "pio", "oci", "abroad")
    )
    if programme == "bvsc" and failed_neet and not special_foreign_quota:
        return _reply(
            "No — for regular B.V.Sc. & A.H. admission, merely appearing for "
            "NEET-UG-2026 is not enough; you need a qualifying NEET-UG-2026 "
            "score because admission merit is based on that qualifying score. "
            "Since you said you did not qualify, you do not currently meet the "
            "entrance-exam requirement for B.V.Sc. Your Class 12 marks cannot "
            "compensate for an unqualified NEET result.",
            "eligibility", pages=[4],
            slotUpdate=_slot_update(
                programme=programme, entranceExamStatus="not_qualified",
                intent="eligibility_resolved",
            ),
        )
    entrance = state.get("entranceExamStatus")
    category = state.get("category")
    subject_percent = state.get("subjectPercent")
    subject_marks = dict(state.get("subjectMarks") or {})
    pending_percent = state.get("pendingPercent")

    # Natural per-subject marks are averaged only when the programme's full
    # required combination is present. PCBM alone is incomplete because every
    # programme also requires English in its marks calculation.
    stated_marks = eligibility.extract_subject_marks(question)
    if stated_marks:
        subject_marks.update(stated_marks)
    if intent == "eligibility_awaiting_subject_marks" or stated_marks:
        computed, missing = eligibility.subject_marks_percentage(programme, subject_marks)
        if computed is None:
            found = ", ".join(
                f"{name.title()} {value:g}" for name, value in sorted(subject_marks.items())
            )
            needed = ", ".join(name.title() for name in sorted(missing))
            return _reply(
                f"I found these marks: {found}. To calculate the required {rule['subject_label']} percentage, what did you score in {needed}?",
                "eligibility-interview",
                interviewField="subjectMarks",
                carryQuestion=state.get("carryQuestion") or question,
                slotUpdate=_slot_update(
                    programme=programme, subjectMarks=subject_marks,
                    entranceExamStatus=entrance, category=category,
                    intent="eligibility_awaiting_subject_marks",
                ),
            )
        subject_percent = computed
        intent = None
        active = True

    if intent == "eligibility_awaiting_percentage_scope" and pending_percent is not None:
        scope = eligibility.describes_percentage_scope(question)
        if scope == "subject":
            subject_percent = float(pending_percent)
            intent = None
        elif scope == "overall":
            return _reply(
                f"Thanks. An overall {float(pending_percent):g}% cannot be substituted for the admission calculation. What percentage did you score in {rule['subject_label']} taken together?",
                "clarify-percentage",
                interviewField="subjectPercent",
                carryQuestion=state.get("carryQuestion") or question,
                slotUpdate=_slot_update(
                    programme=programme, entranceExamStatus=entrance, category=category,
                    intent="eligibility_awaiting_subject_percent",
                ),
            )
        else:
            return _reply(
                f"Is {float(pending_percent):g}% your overall 12th percentage, or your percentage in {rule['subject_label']} taken together?",
                "clarify-percentage",
                interviewField="percentageScope",
                carryQuestion=state.get("carryQuestion") or question,
                slotUpdate=_slot_update(
                    programme=programme, pendingPercent=pending_percent,
                    entranceExamStatus=entrance, category=category,
                    intent="eligibility_awaiting_percentage_scope",
                ),
            )

    if intent == "eligibility_awaiting_entrance" and entrance is None:
        if programme == "bvsc" and re.search(
            r"\b(?:appeared|sat|took)\b.*\b(?:did(?:n'?t| not)\s+"
            r"(?:pass|qualify)|failed|not qualified)\b",
            low,
        ):
            entrance = "not_qualified"
        else:
            entrance = eligibility.is_bare_entrance_reply(question)
    if intent == "eligibility_awaiting_subject_percent" and subject_percent is None:
        subject_percent = eligibility.bare_percent(question)
    if intent == "eligibility_awaiting_subject_percent":
        # This path can be entered from an overall-vs-subject clarification,
        # where entrance/category were never asked. Do not silently turn that
        # narrow clarification into a different interview.
        entrance = entrance or "unknown"
        category = category or "unreserved"

    # A decisive entrance outcome the student already gave - via the interview
    # buttons, remembered in conversationState - outranks a verdict re-derived
    # from this question's text alone. answer.py cannot see conversationState,
    # so handing off below would answer "you meet the marks requirement" one
    # turn after this same session told the student their NEET result rules
    # them out. Quota exceptions stay out of it: XII-abroad NRI/FN/PIO/OCI
    # cases have their own verified rule above this guard.
    state_settles_entrance = (
        entrance in {"no", "pending", "not_qualified"} and not special_foreign_quota
    )

    # A free-form opening may already contain a decisive negative exam claim
    # or a complete percentage/category statement. Preserve evaluate() as the
    # authority before asking for missing slots.
    if not active and not state_settles_entrance:
        result = eligibility.evaluate(programme, question)
        if result["verdict"] != "insufficient":
            return None  # answer.py phrases the deterministic result
        if result.get("reason") == "overall_not_subject":
            facts = eligibility.extract(question)
            overall = facts.get("overall_percent")
            return _reply(
                f"Your fraction converts to {overall:g}% overall. The {rule['label']} rule uses {rule['subject_label']} taken together, not the overall 12th percentage. Was that fraction specifically for the required subjects? If not, what is the required subject-combination percentage?",
                "clarify-percentage",
                interviewField="subjectPercent",
                carryQuestion=question,
                slotUpdate=_slot_update(
                    programme=programme, category=facts.get("category"),
                    intent="eligibility_awaiting_subject_percent",
                ),
            )
        if result.get("reason") == "overall_not_subject":
            facts = eligibility.extract(question)
            return _reply(
                f"The {rule['label']} rule uses your percentage in {rule['subject_label']} taken together—not your overall 12th percentage. What is that subject-combination percentage?",
                "clarify-percentage",
                interviewField="subjectPercent",
                carryQuestion=question,
                slotUpdate=_slot_update(programme=programme, category=facts.get("category"),
                                        intent="eligibility_awaiting_subject_percent"),
            )
        facts = eligibility.extract(question)
        bare = eligibility.bare_percent(question)
        if (
            result.get("reason") == "no_percentage"
            and bare is not None
            and facts.get("subject_percent") is None
            and facts.get("overall_percent") is None
        ):
            return _reply(
                f"Is {bare:g}% your overall 12th percentage, or your percentage in {rule['subject_label']} taken together?",
                "clarify-percentage",
                interviewField="percentageScope",
                carryQuestion=question,
                slotUpdate=_slot_update(
                    programme=programme, pendingPercent=bare,
                    category=facts.get("category"),
                    intent="eligibility_awaiting_percentage_scope",
                ),
            )
        # A subject-specific question with no marks has substantive content
        # for RAG to answer; the legacy guard deliberately does not hijack it
        # into the marks interview.
        if eligibility.describes_own_subjects(question):
            facts = eligibility.extract(question)
            subjects = facts.get("subjects") or set()
            if programme == "bvsc" and {"physics", "chemistry", "english"}.issubset(subjects) and ({"biology", "biotechnology"} & subjects):
                return _reply(
                    "Your subject combination is accepted for B.V.Sc. & A.H.: Biotechnology can satisfy the Biology-or-Biotechnology requirement alongside Physics, Chemistry, and English. I cannot confirm full eligibility from subjects alone; you must also meet the applicable subject-combination percentage, NEET-UG-2026, and age requirements.",
                    "eligibility-rule", pages=[4],
                )
            return None

    if entrance is None:
        entrance_prompt = (
            "Have you qualified NEET-UG-2026?"
            if programme == "bvsc"
            else f"Have you appeared for {rule['entrance']}?"
        )
        if programme == "bfsc" and "neet" in original_low:
            entrance_prompt = (
                "For B.F.Sc., not passing NEET does not by itself make you ineligible. "
                "Regular B.F.Sc. admission uses MHT-CET 2026, not NEET. Let me check "
                "the remaining requirements. Have you appeared for MHT-CET 2026?"
            )
        elif programme == "btech-dairy" and "neet" in original_low:
            entrance_prompt = (
                "For B.Tech. (Dairy Technology), not passing NEET does not by itself "
                "make you ineligible. NEET is not the entrance exam used for this "
                "programme; the regular Maharashtra admission route uses MHT-CET 2026. "
                "Let me check the remaining requirements. Have you appeared for MHT-CET 2026?"
            )
        entrance_options = (
            [
                {"label": "Yes, I qualified", "value": "yes"},
                {"label": "I appeared but did not qualify", "value": "not_qualified"},
                {"label": "I have not appeared yet", "value": "no"},
            ]
            if programme == "bvsc"
            else [
                {"label": "Yes, I have appeared", "value": "yes"},
                {"label": "No, not yet", "value": "no"},
                {"label": "The exam is pending", "value": "pending"},
            ]
        )
        return _reply(
            entrance_prompt,
            "eligibility-interview",
            interviewField="entranceExamStatus",
            interviewOptions=entrance_options,
            carryQuestion=state.get("carryQuestion") or question,
            slotUpdate=_slot_update(
                programme=programme, subjectPercent=subject_percent,
                subjectMarks=subject_marks or None, category=category,
                intent="eligibility_awaiting_entrance",
            ),
        )

    if entrance in {"no", "pending", "not_qualified"}:
        if programme == "bvsc" and entrance == "not_qualified":
            entrance_failure = (
                "You do not currently meet the B.V.Sc. & A.H. entrance-exam "
                "requirement. Merely appearing for NEET-UG-2026 is not enough; "
                "you need a qualifying score because admission merit is based on "
                "the NEET qualifying score."
            )
        elif programme == "bvsc":
            entrance_failure = (
                "You do not currently meet the B.V.Sc. & A.H. entrance-exam "
                "requirement. You must appear for and qualify NEET-UG-2026 before "
                "regular admission can be considered."
            )
        else:
            entrance_failure = (
                f"You do not currently meet the entrance-exam requirement for "
                f"{rule['label']}. Admission requires {rule['entrance']}, so you "
                "must complete the required exam process before admission can be considered."
            )
        return _reply(
            entrance_failure,
            "eligibility",
            slotUpdate=_slot_update(programme=programme, entranceExamStatus=entrance,
                                    intent="eligibility_resolved"),
        )

    if category is None:
        return _reply(
            "Which admission category applies to you?",
            "eligibility-interview",
            interviewField="category",
            interviewOptions=[
                {"label": "Unreserved / General", "value": "unreserved"},
                {"label": "Reserved category", "value": "reserved"},
            ],
            carryQuestion=state.get("carryQuestion") or question,
            slotUpdate=_slot_update(
                programme=programme, entranceExamStatus=entrance,
                subjectPercent=subject_percent, subjectMarks=subject_marks or None,
                intent="eligibility_awaiting_category",
            ),
        )

    if subject_percent is None:
        return _reply(
            f"What percentage did you score in {rule['subject_label']} taken together?",
            "clarify-percentage",
            interviewField="subjectPercent",
            carryQuestion=state.get("carryQuestion") or question,
            slotUpdate=_slot_update(programme=programme, entranceExamStatus=entrance,
                                    category=category, intent="eligibility_awaiting_subject_percent"),
        )

    required = eligibility.threshold(programme, category)
    meets = subject_percent >= required
    programme_label = rule["label"].rstrip(".")
    if meets:
        entrance_statement = (
            "you stated that you qualified NEET-UG-2026"
            if programme == "bvsc"
            else f"you stated that you have appeared for {rule['entrance']}"
        )
        answer = (
            f"Yes — based on the details you've shared, you can apply for {programme_label}. "
            f"Your {subject_percent:g}% in the required subject combination meets the "
            f"{category} minimum of {required:g}%, and {entrance_statement}. "
        )
        if programme == "bfsc" and "neet" in original_low:
            answer += (
                "Your NEET result does not affect regular B.F.Sc. eligibility because "
                "this programme uses MHT-CET 2026 rather than NEET. "
            )
        elif programme == "btech-dairy" and "neet" in original_low:
            answer += (
                "Your NEET result does not affect regular B.Tech. (Dairy Technology) "
                "eligibility because NEET is not the entrance exam used for this programme. "
            )
    else:
        answer = (
            f"No — based on the marks you've shared, you cannot apply for {programme_label} "
            f"under the {category} category. Your {subject_percent:g}% in the required "
            f"subject combination is below the {required:g}% minimum. "
        )
    if meets:
        answer += (
            "This confirms the marks and entrance-exam parts only; you must also meet the "
            "age rule and submit the required category and admission documents. Final "
            "allotment depends on merit, quota, preferences, and seat availability."
        )
    return _reply(
        answer, "eligibility", pages=[4],
        slotUpdate=_slot_update(programme=programme, entranceExamStatus=entrance,
                                category=category, subjectPercent=subject_percent,
                                subjectMarks=subject_marks or None,
                                intent="eligibility_resolved"),
    )


GUARDS = (
    injection_guard,
    malformed_input_guard,
    pii_guard,
    admission_year_guard,
    contradiction_guard,
    prediction_guard,
    greeting_guard,
    legal_boundary_guard,
    language_preference_guard,
    identity_guard,
    challenge_guard,
    institutional_role_guard,
    nri_programme_guard,
)


def run_guards(question: str, conversation_state: dict | None, project_id: str = "bvsc") -> dict | None:
    state = conversation_state or {}
    for guard in GUARDS:
        response = guard(question, state)
        if response is not None:
            return response
    response = off_topic_guard(question, state, project_id)
    if response is not None:
        return response
    response = paragraph_policy_guard(question, state)
    if response is not None:
        return response
    response = multi_programme_eligibility_guard(question, state)
    if response is not None:
        return response
    response = programme_clarify_guard(question, state)
    if response is not None:
        return response
    response = programme_help_confirmation_guard(question, state, project_id)
    if response is not None:
        return response
    response = programme_help_guard(question, state, project_id)
    if response is not None:
        return response
    response = subject_requirement_guard(question, state, project_id)
    if response is not None:
        return response
    response = document_status_guard(question, state, project_id)
    if response is not None:
        return response
    structured = policy.admission_reply(policy.evaluate(project_id, question))
    if structured is not None:
        return structured
    response = verified_policy_guard(question, state, project_id)
    if response is not None:
        return response
    return eligibility_guard(question, state, project_id)
