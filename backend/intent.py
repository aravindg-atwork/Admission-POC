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

# A payment-domain word alone ("What is the fee?") is a completely normal
# question and must NOT trigger this - only domain + problem word together
# should. Kept token-based (not phrase/regex) to match lang.py's approach.
_PAYMENT_CONTEXT = {
    "payment", "pay", "paid", "paying", "transaction", "fee", "fees", "amount",
    "money", "gateway", "upi", "card", "netbanking", "razorpay", "paytm",
    "refund", "refunded", "paisa", "paise", "rupees", "rs",
}
_PROBLEM_MARKERS = {
    "failed", "fail", "failure", "error", "issue", "issues", "problem",
    "problems", "stuck", "pending", "deducted", "debited", "twice", "double",
    "wrong", "missing", "not", "didnt", "didn't", "havent", "haven't",
    "complaint", "complain", "help", "chargeback", "reversed", "bounced",
    "cut", "katgaya", "kata", "wapas", "nahi", "nahin",
}


def is_payment_issue(text):
    """True when the question reads as a payment PROBLEM, not just a payment
    question - requires at least one word from each set, e.g. "payment" +
    "failed", "fee" + "deducted", "amount" + "wrong".
    """
    words = set(text.lower().split())
    return bool(words & _PAYMENT_CONTEXT) and bool(words & _PROBLEM_MARKERS)
