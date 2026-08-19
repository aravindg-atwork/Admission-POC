"""Deterministic, non-LLM canned text - never sent to any model, returned
directly by a guard short-circuit (see rag/guards.py). Kept separate from
system.py's LLM-directed prompts since these are the actual user-facing
strings, not instructions to a model.
"""

# The institution, in one place. Every prompt that can produce a
# self-descriptive sentence must state it, because a model asked "who are
# you?" with no institution in its prompt will supply one - and it supplies a
# REAL one, which is what makes the failure so hard to catch. Observed twice:
# "College of Veterinary Science, Osmania University" from the greeting
# prompt, then "Tamil Nadu Veterinary and Animal Sciences University" from
# the off-topic prompt after only the greeting had been fixed. Both are real
# universities. Neither is this one.
#
# Neither answer involved retrieval at all - these are guard paths with no
# chunks - so no amount of re-ingesting or better OCR could have prevented
# them. The fix is grounding the prompts, not the corpus.
INSTITUTION = "Maharashtra Animal & Fishery Sciences University (MAFSU), Nagpur"

# Appended to every guard prompt that speaks in the assistant's own voice.
IDENTITY_RULE = (
    " You are the admissions assistant for the {program} programme at "
    + INSTITUTION + ". If asked who or what you are, say exactly that. "
    "NEVER name any other university, college or city - you have no "
    "prospectus in front of you on this turn, so any institution you add "
    "would be invented."
)

# Fixed replies for instruction-override attempts (see intent.is_prompt_injection).
# Written out per language rather than generated: the entire point is that no
# model runs on this path, so there is nothing that can be talked into a
# different answer. Kept polite and short - most people typing this are testing
# the system, not attacking it, and a curt refusal reads worse in a demo than a
# calm one.
# {program} filled in per-project (see _program_name) - was a fixed
# "B.V.Sc. & A.H." constant, wrong for the 5 other programs same as the
# system/greeting prompts above.
_INJECTION_REFUSAL_TEMPLATES = {
    "en": "I can only help with admission questions about the {program} "
          "program - things like eligibility, dates, fees, documents or hostel. "
          "Ask me one of those and I'll answer from the prospectus.",
    "hi": "मैं केवल {program} कार्यक्रम के प्रवेश से जुड़े सवालों में मदद कर सकता हूँ - "
          "जैसे पात्रता, तारीखें, शुल्क, दस्तावेज़ या छात्रावास। इनमें से कुछ पूछिए, मैं "
          "प्रॉस्पेक्टस से जवाब दूँगा।",
    "mr": "मी फक्त {program} कार्यक्रमाच्या प्रवेशाशी संबंधित प्रश्नांमध्ये मदत करू शकतो - "
          "जसे की पात्रता, तारखा, शुल्क, कागदपत्रे किंवा वसतिगृह. यापैकी काही विचारा, मी "
          "प्रॉस्पेक्टसमधून उत्तर देईन.",
    "ta": "நான் {program} திட்டத்தின் சேர்க்கை தொடர்பான கேள்விகளுக்கு மட்டுமே "
          "உதவ முடியும் - தகுதி, தேதிகள், கட்டணம், ஆவணங்கள் அல்லது விடுதி போன்றவை. "
          "அவற்றில் ஒன்றைக் கேளுங்கள், ப்ராஸ்பெக்டஸிலிருந்து பதிலளிக்கிறேன்.",
}


# Deterministic, not generated - same reasoning as _INJECTION_REFUSALS: this
# fires before any retrieval or LLM call, so there is nothing to get wrong.
# Picked by the SAME resolved language as the generation-side hint
# (hint_language, computed above in _answer - see its own comment for why
# that beats raw ui_language), not just the UI selector, so a Marathi-script
# ambiguous question gets a Marathi clarification even if the picker is still
# on English.
_PROGRAM_CLARIFY_TEXT = {
    "en": "Which program are you asking about? Please pick one, or ask again "
          "naming the program:",
    "hi": "आप किस कार्यक्रम के बारे में पूछ रहे हैं? कृपया एक चुनें, या कार्यक्रम "
          "का नाम लेकर फिर से पूछें:",
    "mr": "तुम्ही कोणत्या अभ्यासक्रमाबद्दल विचारत आहात? कृपया एक निवडा, किंवा "
          "अभ्यासक्रमाचे नाव घेऊन पुन्हा विचारा:",
    "ta": "நீங்கள் எந்தத் திட்டத்தைப் பற்றி கேட்கிறீர்கள்? ஒன்றைத் தேர்ந்தெடுக்கவும், "
          "அல்லது திட்டத்தின் பெயருடன் மீண்டும் கேளுங்கள்:",
}


# Deterministic, same reasoning as _PROGRAM_CLARIFY_TEXT above - see
# intent.needs_percentage_clarification's docstring for why this exists as a
# hard short-circuit rather than a prompt rule (an inconsistent per-program
# LLM guess on the exact same ambiguous number is the reported failure).
# Extended to Hindi/Marathi 2026-08-13 alongside the detector itself - a
# Hindi/Marathi question that trips the guard must not get an English
# clarification back, same "picked by hint_language, not just the raw UI
# selector" rule as _PROGRAM_CLARIFY_TEXT above. No Tamil key yet, matching
# the detector's own scope (see intent.needs_percentage_clarification).
_PERCENTAGE_CLARIFY_TEXT = {
    "en": "Eligibility for these programs is based on your percentage in the "
          "required subject combination (Physics, Chemistry, Biology/Mathematics "
          "and English) - not your overall 12th aggregate, which is often a "
          "different number. Is the percentage you mentioned your overall score, "
          "or specifically in those subjects? Let me know which one it is and "
          "I'll give you an exact answer.",
    "hi": "इन कार्यक्रमों के लिए पात्रता आपके आवश्यक विषय-संयोजन (भौतिकी, रसायन "
          "विज्ञान, जीव विज्ञान/गणित और अंग्रेज़ी) में प्रतिशत पर आधारित है - न कि "
          "आपके 12वीं के कुल प्रतिशत पर, जो अक्सर एक अलग संख्या होती है। आपने जो "
          "प्रतिशत बताया है, क्या वह आपका कुल स्कोर है, या विशेष रूप से इन्हीं "
          "विषयों में? मुझे बताइए कि यह कौन सा है, और मैं आपको सटीक जवाब दूँगा।",
    "mr": "या अभ्यासक्रमांसाठी पात्रता तुमच्या आवश्यक विषय-संयोजनातील (भौतिकशास्त्र, "
          "रसायनशास्त्र, जीवशास्त्र/गणित आणि इंग्रजी) टक्केवारीवर आधारित आहे - "
          "तुमच्या 12वीच्या एकूण टक्केवारीवर नाही, जी सहसा वेगळी संख्या असते. तुम्ही "
          "सांगितलेली टक्केवारी तुमचा एकूण स्कोअर आहे, की विशेषतः याच विषयांमधील? "
          "मला सांगा कोणती आहे, म्हणजे मी तुम्हाला अचूक उत्तर देईन.",
}

# For the SAME missing-information gap as _PERCENTAGE_CLARIFY_TEXT above
# (evaluate()'s overall_not_subject reason - see guards.py's
# _eligibility_percent_ask) but reached the SECOND time round, once the
# student has already answered "overall or subject?" and said "overall".
# Reusing _PERCENTAGE_CLARIFY_TEXT there re-asks "is it your overall score,
# or specifically in those subjects?" to someone who just said it was their
# overall score - reproduced live: a student who typed "its overall score"
# in reply got the identical question back, verbatim, and reasonably read
# that as the assistant not having listened, even though a NEW piece of
# information (their subject-specific percentage) was genuinely still
# missing. This text names that gap directly - asks for the number, not the
# scope - instead of repeating a question already answered.
_SUBJECT_PERCENT_ASK_TEXT = {
    "en": "Thanks - since that's your overall aggregate, I still need your "
          "percentage specifically in the required subject combination "
          "(Physics, Chemistry, Biology/Mathematics and English) to give you "
          "an exact answer - the two are usually different numbers. What was "
          "your percentage in just those subjects?",
    "hi": "धन्यवाद - चूँकि यह आपका कुल प्रतिशत है, मुझे सटीक जवाब देने के लिए अब भी "
          "आपके आवश्यक विषय-संयोजन (भौतिकी, रसायन विज्ञान, जीव विज्ञान/गणित और "
          "अंग्रेज़ी) में आपका प्रतिशत चाहिए - ये दोनों आमतौर पर अलग संख्याएँ होती हैं। "
          "सिर्फ़ इन्हीं विषयों में आपका प्रतिशत कितना था?",
    "mr": "धन्यवाद - हे तुमचे एकूण प्रतिशत असल्यामुळे, अचूक उत्तर देण्यासाठी मला अजूनही "
          "तुमच्या आवश्यक विषय-संयोजनातील (भौतिकशास्त्र, रसायनशास्त्र, जीवशास्त्र/गणित "
          "आणि इंग्रजी) टक्केवारी हवी आहे - या सहसा वेगळ्या संख्या असतात. फक्त याच "
          "विषयांमधील तुमची टक्केवारी किती होती?",
}

# Quick-reply chips for the prompt above, added 2026-08-17 alongside the
# widget UI change: two clickable answers next to the same free-text box
# that already worked (see app.js's composer, never disabled by a
# clarification), rather than clicking being the ONLY way to answer. `value`
# is the exact literal text a click sends, matched back against
# core.eligibility.is_bare_scope_reply - see that docstring for why a click
# is deliberately routed through the same path a typed reply takes instead
# of a separate code path, so the two stay behaviourally identical by
# construction rather than by two implementations agreeing.
_PERCENTAGE_SCOPE_OPTIONS = {
    "en": [{"value": "It's my overall percentage", "label": "My overall percentage"},
           {"value": "It's in the specific subject combination",
            "label": "My subject-combination score"}],
    "hi": [{"value": "यह मेरा कुल प्रतिशत है", "label": "मेरा कुल प्रतिशत"},
           {"value": "यह विशेष विषय-संयोजन में है", "label": "मेरा विषय-संयोजन स्कोर"}],
    "mr": [{"value": "ही माझी एकूण टक्केवारी आहे", "label": "माझी एकूण टक्केवारी"},
           {"value": "ही विशिष्ट विषय-संयोजनातील आहे", "label": "माझा विषय-संयोजन स्कोअर"}],
}



# Deterministic acknowledgement for a message about the CONVERSATION rather
# than about admissions - see guards.py's _meta_correction_guard. Fixed text,
# no model call: there is nothing in the prospectus to look up, and the whole
# failure being fixed here is the assistant confidently guessing what the
# student meant a second time. Reported case: "I didn't say I want to get in
# bfsc?" answered with a B.F.Sc. program overview, because the string "bfsc"
# occurs in a sentence denying it. Handing the next move back to the student
# is the honest response.
#
# Same per-language keying and hint_language selection rule as
# _PROGRAM_CLARIFY_TEXT/_PERCENTAGE_CLARIFY_TEXT above. No Tamil key yet,
# matching their scope.
#
# Worded to fit BOTH meta cases this guard catches: the student correcting a
# wrong assumption ("I didn't say I want bfsc") and the student saying
# they're lost ("i dont understand"). An earlier draft opened with "You're
# right - I got that wrong", which reads as a non-sequitur in the second
# case, where nobody claimed anything was wrong, only that it wasn't clear.
_META_ACKNOWLEDGE_TEXT = {
    "en": "Sorry - let me get this right instead of guessing again. Tell me "
          "what you'd like to know and which program it's about, and I'll "
          "answer that directly.",
    "hi": "क्षमा करें - मैं दोबारा अंदाज़ा लगाने के बजाय इसे सही ढंग से समझना चाहता "
          "हूँ। आप क्या जानना चाहते हैं और वह किस कार्यक्रम के बारे में है, यह मुझे "
          "बताइए, और मैं उसी का सीधा उत्तर दूँगा।",
    "mr": "माफ करा - पुन्हा अंदाज लावण्याऐवजी मला हे नीट समजून घ्यायचं आहे. "
          "तुम्हाला काय जाणून घ्यायचं आहे आणि ते कोणत्या अभ्यासक्रमाबद्दल आहे हे "
          "मला सांगा, म्हणजे मी त्याचंच थेट उत्तर देईन.",
}

# Off-topic replies (see guards.py's _off_topic_guard). Two separate prompts
# because the right response genuinely differs: a stray trivia fact can be
# answered in a clause and waved off, while a request to PERFORM an unrelated
# task must not be attempted at all, not even partially. These mirror the
# rules already stated in SYSTEM_PROMPT_BASE - kept as their own small prompts
# so the off-topic path never has to carry the full RAG system prompt (and its
# excerpt-handling rules) for a question with no excerpts.
_OFF_TOPIC_TRIVIA_PROMPT = (
    "You are the admissions assistant for the {program} program. The student "
    "has asked something with nothing to do with admissions. Answer the "
    "trivial fact in AT MOST one short clause, then warmly steer them back to "
    "admissions - mention they can ask about eligibility, fees, dates or "
    "documents. Never explain or elaborate on the off-topic fact. Never say "
    "anything like 'the prospectus doesn't specify' about it - it was never a "
    "prospectus question. Two sentences maximum. Plain prose, no markdown."
    + IDENTITY_RULE
)
_OFF_TOPIC_TASK_PROMPT = (
    "You are the admissions assistant for the {program} program. The student "
    "has asked you to perform a task unrelated to admissions (writing code, "
    "translating, drafting something). Warmly decline WITHOUT attempting any "
    "part of it - no partial, simplified or example version - and invite them "
    "to ask about eligibility, fees, dates or documents instead. Stay friendly; "
    "this is a redirect, not a telling-off. Two sentences maximum. Plain prose, "
    "no markdown."
    + IDENTITY_RULE
)


# Reply when a student disputes a fact we already gave (see guards.py's
# _dispute_guard). The exact page/line citation is appended in CODE, never
# generated - a hallucinated citation would defeat the whole purpose - so
# this prompt is told the lines exist and must not restate them itself.
_DISPUTE_PROMPT = (
    "You are the admissions assistant for the {program} program. The student "
    "is disputing a fact you gave them, and you have the exact prospectus "
    "lines in front of you.\n\n"
    "RULES:\n"
    "- If the lines support what you said, hold your ground politely and "
    "clearly. Say plainly that you've double-checked and the figure stands. "
    "Do not apologise for being right, do not hedge with 'you may be right', "
    "and do not soften a correct fact into a maybe.\n"
    "- If the lines actually show you were WRONG, say so directly and give "
    "the correct fact. No excuses.\n"
    "- If the student may be thinking of a genuinely different thing (a "
    "different category, a different year, another program's figure), name "
    "that possibility in one sentence - it is usually the real source of the "
    "disagreement.\n"
    "- Two or three sentences, plain spoken English, no markdown. Explain the "
    "fact in your own words - do NOT quote or restate the prospectus lines, "
    "and do NOT mention page or line numbers. Those are attached separately "
    "below your reply, automatically.\n"
    + IDENTITY_RULE
)


# Answer to "what programmes do you offer?" - see guards.py's
# _program_list_guard. The list itself comes from programs.PROGRAM_NAMES, so
# it cannot drift out of step with the projects that actually exist.
# {count} is filled from programs.PROGRAM_NAMES at call time, never written
# out as a word. It said "six programmes" for a fortnight after the three
# postgraduate projects were retired, because the number was baked into the
# sentence while the list beneath it came from the registry - the reply
# contradicted itself in the same breath.
_PROGRAM_LIST_TEXT = {
    "en": "We offer {count} programmes. Tell me which one you're interested "
          "in and I'll answer anything about it - eligibility, fees, dates "
          "or documents.",
    "hi": "हम {count} कार्यक्रम प्रदान करते हैं। मुझे बताइए आप किसमें रुचि रखते "
          "हैं, और मैं उसके बारे में कुछ भी बता सकता हूँ - पात्रता, शुल्क, "
          "तारीखें या दस्तावेज़।",
    "mr": "आम्ही {count} अभ्यासक्रम देतो. तुम्हाला कोणत्यात रस आहे ते सांगा, आणि "
          "मी त्याबद्दल काहीही सांगू शकतो - पात्रता, शुल्क, तारखा किंवा कागदपत्रे.",
}

# "Which is easier to get into?" - no factual "easier" exists (see
# guards.py's _subjective_comparison_guard), so this is honest about that
# rather than inventing a ranking, and redirects to something genuinely
# checkable instead.
_SUBJECTIVE_COMPARISON_TEXT = {
    "en": "There's no single \"easier\" answer - each programme has its own "
          "marks and subject requirements, and which one is easier for you "
          "depends on your own percentage and subjects. Tell me your marks "
          "and I can check your eligibility for both directly.",
    "hi": "इसका कोई एक \"आसान\" जवाब नहीं है - हर कार्यक्रम की अपनी अलग अंक और "
          "विषय आवश्यकताएँ हैं, और आपके लिए कौन-सा आसान है यह आपके प्रतिशत और "
          "विषयों पर निर्भर करता है। अपने अंक बताइए, मैं दोनों के लिए आपकी "
          "पात्रता सीधे जाँच सकता हूँ।",
    "mr": "याचे एकच \"सोपे\" उत्तर नाही - प्रत्येक अभ्यासक्रमाच्या स्वतःच्या "
          "गुण आणि विषय आवश्यकता आहेत, आणि तुमच्यासाठी कोणता सोपा आहे हे "
          "तुमच्या टक्केवारी आणि विषयांवर अवलंबून आहे. तुमचे गुण सांगा, मी "
          "दोन्हीसाठी तुमची पात्रता थेट तपासू शकतो.",
}


# Reply when a student names a course this university does not run - see
# guards.py's _unknown_programme_guard. Fixed text, no retrieval, no model:
# the whole failure is the assistant answering anyway, and retrieval's best
# match is never empty, so a question about an absent course comes back
# looking just like one about a present course.
_UNKNOWN_PROGRAMME_TEXT = {
    "en": "I only cover admissions for {programmes}, so I can't help with "
          "that course. If you meant one of these, tell me which and I'll "
          "answer straight away.",
    "hi": "मैं केवल {programmes} के प्रवेश के बारे में बता सकता हूँ, इसलिए उस "
          "पाठ्यक्रम में मदद नहीं कर पाऊँगा। अगर आपका मतलब इनमें से किसी एक से "
          "है, तो बताइए और मैं तुरंत जवाब दूँगा।",
    "mr": "मी फक्त {programmes} च्या प्रवेशाबद्दल सांगू शकतो, त्यामुळे त्या "
          "अभ्यासक्रमात मदत करू शकणार नाही. यापैकी एखादा अभिप्रेत असल्यास सांगा, "
          "मी लगेच उत्तर देईन.",
}


# ---------------------------------------------------------------------------
# P1: guided eligibility interview (see rag/guards.py's _eligibility_guard
# and _eligibility_interview_ask). Asks for ONE missing field at a time -
# entrance-exam status, then category - instead of either silently assuming
# "unreserved" (evaluate()'s pre-existing category_assumed fallback, still
# used when the student never engages the interview at all, e.g. an API
# caller with no chip UI) or falling through to plain RAG generation, which
# is what a bare "am I eligible for B.V.Sc.?" did before this existed - the
# same "guessing where the deterministic engine could instead ask" failure
# eligibility.py's own module docstring already documents for the
# percentage-vs-threshold comparison, one turn earlier in the conversation.
#
# Same per-language keying / hint_language selection as
# _PROGRAM_CLARIFY_TEXT above. No Tamil key yet - eligibility.py's own
# category/entrance-exam detectors don't cover Tamil either (see
# extract()'s _RESERVED_WORDS/_UNRESERVED_WORDS and
# missing_entrance_exam's regexes), so there is nothing yet to ask FOR in
# that language.
_ELIGIBILITY_ENTRANCE_TEXT = {
    "en": "One more thing before I can give you a straight answer - have "
          "you appeared for {entrance}? Admission is decided on that exam, "
          "so it changes what I can tell you.",
    "hi": "सीधा जवाब देने से पहले एक और बात - क्या आपने {entrance} की परीक्षा दी "
          "है? प्रवेश इसी परीक्षा के आधार पर तय होता है, इसलिए इससे जवाब बदल "
          "सकता है।",
    "mr": "थेट उत्तर देण्याआधी आणखी एक गोष्ट - तुम्ही {entrance} परीक्षा दिली आहे "
          "का? प्रवेश याच परीक्षेवर आधारित ठरतो, त्यामुळे याने उत्तर बदलू शकते.",
}
# `value` is what a click sends when it resubmits the carried question (see
# app.js's pickInterview) - a short semantic tag stored straight into
# conversationState.entranceExamStatus, not prose - unlike
# _PERCENTAGE_SCOPE_OPTIONS.value, which IS the literal text a click sends as
# a new chat message. The interview answers a STRUCTURED slot instead of
# splicing text, so there is nothing here for is_bare_scope_reply's approach
# to matching against; see guards.py's merge logic instead.
_ELIGIBILITY_ENTRANCE_OPTIONS = {
    "en": [{"value": "yes", "label": "Yes, I've appeared"},
           {"value": "no", "label": "No, not yet"},
           {"value": "pending", "label": "It's scheduled / pending"}],
    "hi": [{"value": "yes", "label": "हाँ, दे दी है"},
           {"value": "no", "label": "नहीं, अभी नहीं"},
           {"value": "pending", "label": "अभी बाकी है"}],
    "mr": [{"value": "yes", "label": "हो, दिली आहे"},
           {"value": "no", "label": "नाही, अजून नाही"},
           {"value": "pending", "label": "अजून बाकी आहे"}],
}

_ELIGIBILITY_CATEGORY_TEXT = {
    "en": "And which category are you applying under - Unreserved (General) "
          "or Reserved (SC/ST/OBC/NT/VJNT/SBC/EWS)? The required percentage "
          "differs between the two.",
    "hi": "और आप किस श्रेणी में आवेदन कर रहे हैं - अनारक्षित (जनरल) या आरक्षित "
          "(SC/ST/OBC/NT/VJNT/SBC/EWS)? दोनों के लिए आवश्यक प्रतिशत अलग-अलग है।",
    "mr": "आणि तुम्ही कोणत्या प्रवर्गातून अर्ज करत आहात - अराखीव (जनरल) की राखीव "
          "(SC/ST/OBC/NT/VJNT/SBC/EWS)? दोन्हीसाठी आवश्यक टक्केवारी वेगळी आहे.",
}
_ELIGIBILITY_CATEGORY_OPTIONS = {
    "en": [{"value": "unreserved", "label": "Unreserved / General"},
           {"value": "reserved", "label": "Reserved (SC/ST/OBC/...)"}],
    "hi": [{"value": "unreserved", "label": "अनारक्षित / जनरल"},
           {"value": "reserved", "label": "आरक्षित (SC/ST/OBC/...)"}],
    "mr": [{"value": "unreserved", "label": "अराखीव / जनरल"},
           {"value": "reserved", "label": "राखीव (SC/ST/OBC/...)"}],
}


# Lead text for the P2 topic/capability menu - see guards.py's
# _topic_menu_guard. Two variants, not one: "tell me about admission" is the
# student asking about the PROCESS, "what can you help with?" is asking about
# THE ASSISTANT, and answering the second with "what would you like to know
# about admission?" reads as not having heard the actual question even though
# the menu that follows is identical either way. Deliberately plain
# admissions-counselor language, no mention of "topics", "categories",
# "options" or anything that reads as internal system vocabulary (see
# agent-qustioning system.md section 11 - "do not expose internal RAG
# terminology").
_TOPIC_MENU_LEAD_TEXT = {
    "broad": {
        "en": "Sure - what would you like to know about admission? Pick one "
              "below, or just ask in your own words:",
        "hi": "ज़रूर - आप प्रवेश के बारे में क्या जानना चाहेंगे? नीचे से एक चुनें, "
              "या अपने शब्दों में पूछें:",
        "mr": "नक्कीच - तुम्हाला प्रवेशाबद्दल काय जाणून घ्यायचं आहे? खालीलपैकी एक "
              "निवडा, किंवा तुमच्या स्वतःच्या शब्दांत विचारा:",
    },
    "capability": {
        "en": "I can help with quite a bit around admission. What would you "
              "like to check?",
        "hi": "मैं प्रवेश से जुड़ी कई चीज़ों में मदद कर सकता हूँ। आप क्या जांचना "
              "चाहेंगे?",
        "mr": "मी प्रवेशाशी संबंधित बऱ्याच गोष्टींमध्ये मदत करू शकतो. तुम्हाला काय "
              "तपासायचं आहे?",
    },
}
