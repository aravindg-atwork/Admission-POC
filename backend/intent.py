"""Intent classification: lightweight, deterministic routing for conversation
patterns that need different handling than generic prospectus RAG.

Keyword-based, not a model call - same design philosophy as lang.py's script/
romanized-Indic detection: fast, free, predictable, and easy to audit or extend
by adding words as real conversations reveal gaps. Greeting detection already
lived in rag.py (exact-match GREETINGS set) before this module existed; payment-
issue detection is the first addition here, more categories can follow the same
pattern (require a domain-context word AND a problem word, to avoid false
positives on a plain factual question).
"""

import unicodedata

# A payment-domain word alone ("What is the fee?") is a completely normal
# question and must NOT trigger this - only domain + problem word together
# should. Kept token-based (not phrase/regex) to match lang.py's approach.
#
# Both sets carry Devanagari forms because English-only sets meant no Hindi or
# Marathi payment problem ever reached the de-escalation prompt: the context set
# had no Devanagari at all, and both sets must hit. A student writing "मेरा पेमेंट
# फेल हो गया लेकिन पैसे कट गए" was answered by the generic counselor prompt with a
# fee figure - the exact case PAYMENT_SYSTEM_PROMPT exists to handle, and the one
# where getting it wrong costs the student a real grievance fee.
_PAYMENT_CONTEXT = {
    "payment", "pay", "paid", "paying", "transaction", "fee", "fees", "amount",
    "money", "gateway", "upi", "card", "netbanking", "razorpay", "paytm",
    "refund", "refunded", "paisa", "paise", "rupees", "rs",
    # Hindi / Marathi
    "पेमेंट", "पैसे", "पैसा", "पेसे", "शुल्क", "फीस", "फी", "भुगतान", "रक्कम",
    "रुपये", "व्यवहार", "ट्रांजैक्शन", "पावती", "रसीद", "परतावा", "रिफंड",
    "गेटवे", "कार्ड", "यूपीआय", "यूपीआई",
}
_PROBLEM_MARKERS = {
    "failed", "fail", "failure", "error", "issue", "issues", "problem",
    "problems", "stuck", "pending", "deducted", "debited", "twice", "double",
    "wrong", "missing", "not", "didnt", "didn't", "havent", "haven't",
    "complaint", "complain", "help", "chargeback", "reversed", "bounced",
    "cut", "katgaya", "kata", "wapas", "nahi", "nahin",
    # Hindi / Marathi. "नाही"/"नहीं" are deliberately included (a payment context
    # word plus a negation is nearly always a complaint), matching the romanized
    # "nahi"/"nahin" already in this set.
    "फेल", "एरर", "त्रुटि", "समस्या", "अडचण", "कट", "कटे", "कापले", "कपात",
    "अटक", "अडकले", "प्रलंबित", "दुप्पट", "दोनदा", "चुकीचे", "गलत", "तक्रार",
    "शिकायत", "नाही", "नहीं", "मिळाली", "मिळाले", "अयशस्वी",
}

# Devanagari matras and virama are combining marks, so they are not isalnum() and
# a naive whitespace split leaves punctuation attached ("फेल," never matching
# "फेल"). Splitting on anything that is neither alphanumeric nor a combining mark
# keeps Indic words intact while stripping the punctuation around them.
def _words(text):
    out, current = [], []
    for ch in text.lower():
        if ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc"):
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return set(out)


def is_payment_issue(text):
    """True when the question reads as a payment PROBLEM, not just a payment
    question - requires at least one word from each set, e.g. "payment" +
    "failed", "fee" + "deducted", "amount" + "wrong".
    """
    words = _words(text)
    return bool(words & _PAYMENT_CONTEXT) and bool(words & _PROBLEM_MARKERS)
