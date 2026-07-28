"""Deterministic Hindi/Marathi -> English domain terms for retrieval.

The retrieval path translates a Devanagari question to English (see
llm.translate_to_english) because the prospectus is English and the embedding
model does not align the scripts well enough. That translation is done by a 2B
local model, and at that size it is unreliable on exactly the vocabulary that
matters most here - measured on the retrieval harness:

    "शेतकरी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?"
      -> "What are the FEES for agricultural students' seats?"
    "प्रकल्पग्रस्त व्यक्तींसाठी किती टक्के जागा राखीव आहेत?"
      -> "How many seats are available for project-based students?"

Both are reservation-percentage questions that the mistranslation turned into
something else, and both then retrieved fee pages instead of the reservation
table. A wrong translation does not merely blur retrieval, it aims it at the
wrong part of the document.

So the domain nouns are mapped here in code instead. This does NOT replace the
translation - it is appended to it, so the sentence structure still comes from
the model while the load-bearing terms are guaranteed present regardless of what
the model did with them. Same reasoning as transliterate.py and tablelookup.py:
where a mapping is mechanical, do it mechanically rather than hoping.

Matched as stems, because Hindi and Marathi agglutinate case endings onto the
noun ("शेतकरी" -> "शेतकऱ्यांसाठी", "प्रवेश" -> "प्रवेशासाठी"). Only Devanagari keys
are stem-matched; there is nothing to gain from prefix-matching Latin here.
"""

import unicodedata

# Devanagari stem -> English terms to append. Deliberately domain nouns only:
# verbs and question words are what the model translates reliably, and adding
# them would dilute the lexical overlap score without adding signal.
_TERMS = {
    # reservation categories
    "शेतकर": "agriculturist agricultural land",
    "शेतकऱ": "agriculturist agricultural land",
    "कृषक": "agriculturist agricultural land",
    "प्रकल्पग्रस्त": "project affected person",
    "प्रकल्पबाधित": "project affected person",
    "संरक्षण": "defence personnel",
    "सैनिक": "defence personnel",
    "स्वातंत्र्यसैनिक": "freedom fighter",
    "स्वतंत्रता": "freedom fighter",
    "अनाथ": "orphan candidate",
    "दिव्यांग": "physically handicapped disability",
    "अपंग": "physically handicapped disability",
    "विकलांग": "physically handicapped disability",
    "आर्थिक": "economically weaker section",
    "दुर्बल": "economically weaker section",
    "राखीव": "reserved reservation",
    "आरक्ष": "reserved reservation",
    "अनारक्षित": "unreserved open category",
    "खुल": "open category unreserved",
    "प्रवर्ग": "category",
    "मागास": "backward class",
    # quantities
    "टक्के": "percentage percent",
    "टक्का": "percentage percent",
    "प्रतिशत": "percentage percent",
    "जाग": "seats intake capacity",
    "सीट": "seats intake capacity",
    # fees
    "शुल्क": "fee fees",
    "फीस": "fee fees",
    "ट्यूशन": "tuition fee",
    "परीक्ष": "examination fee exam",
    "नोंदणी": "registration fee",
    "पंजीकरण": "registration fee",
    "वसतिगृह": "hostel fees",
    "छात्रावास": "hostel fees",
    "हॉस्टेल": "hostel fees",
    "इंटर्नशिप": "internship",
    "कॉशन": "caution money deposit",
    "अनामत": "caution money deposit",
    "परतावा": "refund",
    "वापसी": "refund",
    # process and documents
    "प्रवेश": "admission",
    "पात्रत": "eligibility criteria",
    "अर्ज": "application form",
    "आवेदन": "application form",
    "कागदपत्र": "certificates documents",
    "दस्तावेज": "certificates documents",
    "अधिवास": "domicile residence certificate",
    "वास्तव्य": "domicile residence certificate",
    "निवास": "domicile residence certificate",
    "वैधता": "caste validity certificate",
    "जात": "caste certificate",
    "जाति": "caste certificate",
    "गुणवत्ता": "merit list",
    "मेरिट": "merit list",
    "तक्रार": "grievance",
    "शिकायत": "grievance",
    "तारीख": "date last date",
    "तिथि": "date last date",
    "उपस्थित": "attendance",
    "माध्यम": "medium of instruction",
    "बदली": "transfer",
    "स्थानांतरण": "transfer",
    "अभ्यासक्रम": "course degree",
    "पाठ्यक्रम": "course degree",
}


def _is_word_char(ch):
    # Same rule as faq._is_word_char: Indic vowel signs and the virama are
    # combining marks, not alnum, so an alnum-only split shatters every word.
    return ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc")


def _words(text):
    out, current = [], []
    for ch in text.lower():
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def english_terms(text):
    """English domain terms implied by the Devanagari words in `text`.

    Returns a space-joined string (empty when nothing matches, e.g. for a
    question that was already in English). Order follows the question, and
    duplicates are dropped so one repeated noun does not skew lexical scoring.
    """
    seen, out = set(), []
    for word in _words(text):
        for stem, english in _TERMS.items():
            if word == stem or (len(stem) >= 3 and word.startswith(stem)):
                for term in english.split():
                    if term not in seen:
                        seen.add(term)
                        out.append(term)
                break
    return " ".join(out)
