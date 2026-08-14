"""Deterministic, non-LLM canned text - never sent to any model, returned
directly by a guard short-circuit (see rag/guards.py). Kept separate from
system.py's LLM-directed prompts since these are the actual user-facing
strings, not instructions to a model.
"""

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
)
_OFF_TOPIC_TASK_PROMPT = (
    "You are the admissions assistant for the {program} program. The student "
    "has asked you to perform a task unrelated to admissions (writing code, "
    "translating, drafting something). Warmly decline WITHOUT attempting any "
    "part of it - no partial, simplified or example version - and invite them "
    "to ask about eligibility, fees, dates or documents instead. Stay friendly; "
    "this is a redirect, not a telling-off. Two sentences maximum. Plain prose, "
    "no markdown."
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
)


# Answer to "what programmes do you offer?" - see guards.py's
# _program_list_guard. The list itself comes from programs.PROGRAM_NAMES, so
# it cannot drift out of step with the projects that actually exist.
_PROGRAM_LIST_TEXT = {
    "en": "We offer six programmes. Tell me which one you're interested in "
          "and I'll answer anything about it - eligibility, fees, dates or "
          "documents.",
    "hi": "हम छह कार्यक्रम प्रदान करते हैं। मुझे बताइए आप किसमें रुचि रखते हैं, "
          "और मैं उसके बारे में कुछ भी बता सकता हूँ - पात्रता, शुल्क, तारीखें "
          "या दस्तावेज़।",
    "mr": "आम्ही सहा अभ्यासक्रम देतो. तुम्हाला कोणत्यात रस आहे ते सांगा, आणि मी "
          "त्याबद्दल काहीही सांगू शकतो - पात्रता, शुल्क, तारखा किंवा कागदपत्रे.",
}
