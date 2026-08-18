"""Deterministic eligibility verdicts: code decides, the model only phrases it.

Why this is not left to the model
---------------------------------
The 2026-08-14 80-question evaluation failed four questions in the same way,
and every one of them was an arithmetic or threshold slip inside otherwise
fluent prose:

  Q25  "51% overall but only 45% in PCB and English" -> answered ELIGIBLE,
       by comparing the 51% aggregate against a rule that is explicitly on
       the subject combination. The student is not eligible.
  Q19  "I didn't appear for MHT-CET, can I still get admission?" -> "Yes,
       you can" followed by "you also need to have appeared for MHT-CET".
  Q13  reserved B.V.Sc. threshold given as 40% (it is 47.50%).
  Q28  the same 40%-for-B.V.Sc. slip.

None of those are retrieval failures - the right text was in front of the
model. They are what happens when a language model performs a comparison
mid-sentence. So the comparison moves here, where it is testable and a wrong
answer is a fixable rule rather than a change of mood, and the model is left
to do what it is good at: saying the result in plain language.

Thresholds are transcribed from the prospectus PDFs, NOT from the assistant's
own answers - checking the bot against its own prior output would only prove
it is self-consistent. Each carries the page it came from.
"""

import re

# Verbatim from the 2026-27 prospectuses. The exact phrase in all three is
# "...taken together for Unreserved category and N% marks in case of Reserved
# category candidate", which is the whole point: the requirement is on the
# SUBJECT COMBINATION, never on the overall aggregate. Conflating the two is
# what made Q25 tell an ineligible student to apply.
RULES = {
    "bvsc": {
        "label": "B.V.Sc. & A.H.",
        "unreserved": 50.0,
        "reserved": 47.50,
        "subjects": {"physics", "chemistry", "english"},
        # Biology OR Biotechnology satisfies the same slot.
        "either": {"biology", "biotechnology"},
        "subject_label": "Physics, Chemistry, Biology or Biotechnology and English",
        "entrance": "NEET-UG-2026",
        "entrance_key": "neet",
        "page": 4,
        # Verified 2026-08-18, THE ELIGIBILITY/SELECTION CRITERIA section
        # itself (item 3, same list as marks/NEET/medium-of-instruction, not
        # a footnote): "Candidates should fulfill the eligibility condition
        # of 17 years of age on 31/12/2026 i.e. the candidate born on or
        # before 1st January, 2010 shall only be considered for admission."
        # Live report: an "eligible" verdict was overclaiming - it mentioned
        # NEET as an outstanding condition but never age, even though the
        # source states it with equal standing. Not added for bfsc/btech-
        # dairy at the time this was first written - that assumption was
        # WRONG, corrected 2026-08-18 (see their own entries below): both
        # DO state the identical rule in their own general eligibility
        # section too, not only the NRI one. No interview step or birthdate
        # extraction exists to CHECK this against a stated date - it is
        # stated as an outstanding condition in the verdict, exactly like
        # the entrance exam already is, not a computed pass/fail.
        "age_requirement": "17 years of age by 31 December 2026 (born on or before 1 January 2010)",
    },
    "bfsc": {
        "label": "B.F.Sc.",
        "unreserved": 50.0,
        "reserved": 40.0,
        "subjects": {"physics", "chemistry", "biology", "english"},
        "either": set(),
        "subject_label": "Physics, Chemistry, Biology and English",
        "entrance": "MHT-CET 2026",
        "entrance_key": "cet",
        "page": 10,
        # Verified 2026-08-18 directly against the OCR'd prospectus text
        # (data/projects/bfsc/vector-store.json, page 10): item 4 of "5. THE
        # ELIGIBILITY / SELECTION CRITERIA FOR ADMISSION" - the SAME general
        # section and list position as bvsc's, not a footnote - states this
        # verbatim: "Candidates should fulfill the eligibility condition of
        # 17 years of age on 31/12/2026 i.e. the candidate born on or before
        # 1st January, 2010 shall only be considered for admission on merit
        # basis." Also independently restated in the NRI/FN/PIO/OCI section
        # (page 23, item 11.ii) - corrects the earlier assumption above that
        # this was NRI-only for bfsc/btech-dairy; it was never actually
        # checked against the source text until now.
        "age_requirement": "17 years of age by 31 December 2026 (born on or before 1 January 2010)",
    },
    "btech-dairy": {
        "label": "B.Tech. (Dairy Technology)",
        "unreserved": 50.0,
        "reserved": 40.0,
        "subjects": {"physics", "chemistry", "mathematics", "english"},
        "either": set(),
        "subject_label": "Physics, Chemistry, Mathematics and English",
        "entrance": "MHT-CET 2026",
        "entrance_key": "cet",
        "page": 5,
        # Verified 2026-08-18, same method as bfsc above
        # (data/projects/btech-dairy/vector-store.json, page 5): item 4 of
        # "5. THE ELIGIBILITY / SELECTION CRITERIA FOR ADMISSION" states the
        # identical sentence verbatim (down to the punctuation).
        "age_requirement": "17 years of age by 31 December 2026 (born on or before 1 January 2010)",
    },
}

_RESERVED_WORDS = {
    "reserved", "sc", "st", "obc", "nt", "vjnt", "vj", "sbc", "ews", "dt",
    "backward", "scheduled",
}
_UNRESERVED_WORDS = {"unreserved", "open", "general", "ur"}

# A percentage is "subject-scoped" when the sentence around it names the
# subject combination, and "overall" when it names the aggregate. Q25 stated
# BOTH in one sentence, so which one attaches to which number decides the
# verdict - hence matching on the words immediately around each figure rather
# than taking the first percentage in the message.
_SUBJECT_CUES = ("pcb", "pcm", "pcbe", "pcme", "physics", "chemistry", "biolog",
                 "mathemat", "maths", "math", "english", "those subjects",
                 "these subjects", "subject")
_OVERALL_CUES = ("overall", "aggregate", "total", "in 12th", "in 12", "hsc",
                 "boards", "board exam", "percentage in 12")

_PERCENT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent)", re.I)

_SUBJECT_ALIASES = {
    "physics": "physics", "chemistry": "chemistry", "english": "english",
    "biology": "biology", "bio": "biology", "biotechnology": "biotechnology",
    "biotech": "biotechnology", "mathematics": "mathematics",
    "maths": "mathematics", "math": "mathematics",
}


# Programme names contain their own category false-positives: "B.V.Sc." and
# "B.F.Sc." both tokenize to "sc", which is also the Scheduled Caste marker,
# so every question naming a programme looked like a reserved-category
# question. Stripped before any category matching.
_PROGRAMME_NOISE_RE = re.compile(
    r"\b[bm]\.?\s?[vf]?\.?\s?sc\.?\b|\bb\.?\s?tech\b|\bbvsc\b|\bbfsc\b|\bmvsc\b",
    re.I)

# "instead of Mathematics", "didn't have Maths", "without Biology" - a subject
# named only to say it is ABSENT. Counting it as studied is how "can I apply
# with Biology instead of Mathematics?" came out as satisfying a Mathematics
# requirement.
_NEGATED_SUBJECT_RE = re.compile(
    r"(?:instead\s+of|without|didn'?t\s+have|did\s+not\s+have|don'?t\s+have|"
    r"no|not|lack(?:ing)?|missing)\s+(?:a\s+|any\s+)?"
    r"(physics|chemistry|english|biology|bio|biotechnology|biotech|"
    r"mathematics|maths|math)\b", re.I)


def _nearest_cue(text, start, end, width=30):
    """Which cue sits closest to this percentage - subject, overall, neither.

    Looks at a tight window on each side rather than a wide one, because Q25
    put both readings in a single sentence ("51% overall in 12th but only 45%
    in PCB and English"). A wide window saw "PCB" next to the 51% too and
    scored an aggregate as a subject mark, which flips the verdict.
    """
    after = text[end:end + width].lower()
    before = text[max(0, start - width):start].lower()
    for scope, cues in (("overall", _OVERALL_CUES), ("subject", _SUBJECT_CUES)):
        for cue in cues:
            if cue in after:
                return scope, after.index(cue)
    best = None
    for scope, cues in (("overall", _OVERALL_CUES), ("subject", _SUBJECT_CUES)):
        for cue in cues:
            if cue in before:
                distance = len(before) - before.rindex(cue)
                if best is None or distance < best[1]:
                    best = (scope, distance)
    return best if best else (None, 0)


def extract(text):
    """Pull the student's own stated facts out of their message.

    Returns {subject_percent, overall_percent, category, subjects}, any of
    which may be None/empty - "insufficient information" is a first-class
    result here, not a failure. Guessing is what this module exists to stop.
    """
    raw = text or ""
    low = raw.lower()
    subject_percent = overall_percent = None
    for match in _PERCENT_RE.finditer(raw):
        value = float(match.group(1))
        if value > 100:
            continue
        scope, _ = _nearest_cue(raw, match.start(), match.end())
        if scope == "subject" and subject_percent is None:
            subject_percent = value
        elif scope == "overall" and overall_percent is None:
            overall_percent = value
        # A bare "I got 48%" with no qualifier either side stays unassigned -
        # genuinely ambiguous, and the caller asks rather than assuming.

    words = set(re.findall(r"[a-z]+", _PROGRAMME_NOISE_RE.sub(" ", low)))
    category = None
    if words & _RESERVED_WORDS:
        category = "reserved"
    elif words & _UNRESERVED_WORDS:
        category = "unreserved"

    negated = {_SUBJECT_ALIASES[m.group(1).lower()]
               for m in _NEGATED_SUBJECT_RE.finditer(raw)}
    subjects = set()
    for token, canonical in _SUBJECT_ALIASES.items():
        if re.search(rf"\b{token}\b", low):
            subjects.add(canonical)
    # Shorthand: PCB/PCM expand to their subject sets.
    if re.search(r"\bpcb\w*\b", low):
        subjects |= {"physics", "chemistry", "biology"}
    if re.search(r"\bpcm\w*\b", low):
        subjects |= {"physics", "chemistry", "mathematics"}
    subjects -= negated

    return {"subject_percent": subject_percent, "overall_percent": overall_percent,
            "category": category, "subjects": subjects}


# The entrance exam is not a soft preference: every prospectus makes admission
# itself depend on it. B.F.Sc. p10 and B.Tech. (D.T.) p5 both say the candidate
# "should have also appeared for Common Entrance Test (MHT-CET 2026)", and
# B.V.Sc. p4 says admission "shall be made on the basis of his/her inter-se
# merit in the NEET-UG-2026 qualifying score". Without the exam there is no
# merit score to admit on.
#
# Q19 is what the absence of this check cost: "I didn't appear for MHT-CET. Can
# I still get admission to B.F.Sc.?" was answered "Yes, you can still get
# admission..." and then, in the same reply, "you must also appear for
# MHT-CET". This module's docstring has listed that failure since it was
# written, but nothing here ever read the "entrance" field, so the question
# went to plain RAG with nothing constraining it - and a model asked to weigh
# strong marks against a missed exam leads with the marks.
#
# Only NEGATED mentions count, and only for the exam THIS programme admits on.
# Both halves matter: "Do I need to appear for MHT-CET?" is a question about
# the rule rather than a claim to have skipped it, and a B.F.Sc. applicant who
# missed NEET has missed an exam B.F.Sc. does not use.
#
# Bare "no" is deliberately NOT a negation marker here. "There is no exemption
# from MHT-CET" and "No candidate is admitted without MHT-CET" both contain a
# negation next to the exam name while asserting the exact opposite of what
# this function is looking for.
_ENTRANCE_NEGATION = (
    r"(?:did|do|does|have|has|had|am|is|are|was|were|will|would|can|could|"
    r"shall|should)\s*n[o']?t|never|without|missed|skipped"
)
_NOT_APPEARED_RE = re.compile(
    r"\b(?:" + _ENTRANCE_NEGATION + r")\b"
    r"(?:\W+\w+){0,3}?\W+"
    r"(neet|mht[\s.\-]*cet|mh[\s.\-]*cet|cet)\b",
    re.I,
)
# Sentences that negate an EXEMPTION rather than the student's attendance.
# Checked before the negation scan because "no exemption from MHT-CET" matches
# the shape above exactly - the negation attaches to the waiver, not the exam.
_EXEMPTION_RE = re.compile(
    r"\b(exemption|exempt|waiver|waived|relaxation|excused)\b", re.I)

# The student has to be talking about THEMSELVES. Same discipline
# describes_own_subjects already applies to subjects, and for the same reason:
# "No candidate is admitted without MHT-CET" contains a negation next to the
# exam name but states the rule rather than a personal circumstance, and
# answering it with "you are not eligible" is the same class of error as
# delivering a personal verdict on a general subject question.
_FIRST_PERSON_RE = re.compile(r"\b(i|i'?m|i'?ve|my|me|mine)\b", re.I)


def _named_entrance_key(token):
    """Which exam a matched token names: 'neet', 'cet', or None."""
    squashed = re.sub(r"[^a-z]", "", token.lower())
    if "neet" in squashed:
        return "neet"
    if "cet" in squashed:
        return "cet"
    return None


def missing_entrance_exam(project_id, text):
    """The exam this programme admits on, when the student says they did not
    sit it. None otherwise - including when they missed a DIFFERENT exam.

    Returns the display name ("MHT-CET 2026") so the caller can name it back.
    """
    rule = RULES.get(project_id)
    if not rule or not text:
        return None
    if _EXEMPTION_RE.search(text) or not _FIRST_PERSON_RE.search(text):
        return None
    for match in _NOT_APPEARED_RE.finditer(text):
        if _named_entrance_key(match.group(1)) == rule["entrance_key"]:
            return rule["entrance"]
    return None


def threshold(project_id, category):
    rule = RULES.get(project_id)
    if not rule:
        return None
    return rule["reserved"] if category == "reserved" else rule["unreserved"]


# A subject only counts as the STUDENT'S when they say it is theirs. Without
# this, "Is Mathematics compulsory for B.Tech. Dairy Technology?" was read as
# a student who had studied Mathematics and nothing else, and answered "You
# are not eligible for B.Tech. (Dairy Technology)" - a personal verdict on a
# general question, delivered to someone who never described their subjects.
_OWN_SUBJECTS_RE = re.compile(
    r"\b(i\s+(?:have|had|studied|took|did|am|completed|passed)|my\s+\w+|i'?ve|"
    r"i\s+didn'?t|i\s+do\s+not|with\s+p\.?c\.?[bm]|instead\s+of)\b", re.I)


def describes_own_subjects(text):
    """Whether the student is telling us what THEY studied."""
    return bool(_OWN_SUBJECTS_RE.search(text or ""))


# Added 2026-08-17 to close a gap found live: a student who answers
# _percentage_clarify_guard's "is that your overall score or those
# subjects?" was being handled as a brand-new, context-free message - the
# router's history-based follow-up resolution does not reliably reattach the
# scope word to the ORIGINAL question's percentage, and one live test fanned
# out across all three programmes instead of answering the specific one
# actually asked about. http/chat_routes.py uses these the same way it
# already uses programs.is_bare_program_reply for the program-clarify
# prompt: recognise a short, topic-free reply to OUR OWN question and
# recombine it with the question that is still pending, rather than trust
# free-form multi-turn resolution for something this narrow.
_SCOPE_REPLY_OVERALL = ("overall", "aggregate", "total", "12th percentage", "12th score")
_SCOPE_REPLY_SUBJECT = ("subject", "pcb", "pcm", "combination", "those subjects", "these subjects")


def describes_percentage_scope(text):
    """Which scope a reply names ("overall" or "subject"), or None if it
    names neither. Does not by itself mean the message is a BARE reply -
    see is_bare_scope_reply, which adds the "carries no question of its
    own" check before a caller treats this as answering the clarification.
    """
    low = (text or "").lower()
    if any(cue in low for cue in _SCOPE_REPLY_OVERALL):
        return "overall"
    if any(cue in low for cue in _SCOPE_REPLY_SUBJECT):
        return "subject"
    return None


def is_bare_scope_reply(text):
    """True when a message is JUST answering "overall or subject?" and asks
    nothing of its own - "overall", "it's my subject combination score".

    Mirrors programs.is_bare_program_reply's reasoning exactly: "which
    subjects are compulsory?" contains the word "subject" too, but is a
    complete, self-sufficient new question, not an answer to the
    clarification, and must not be swallowed into the pending one. A
    genuinely bare reply is short and asks nothing - gated on both a
    question mark (a real question almost always has one) and a word-count
    ceiling generous enough for "It's in my specific subject combination,
    not my overall aggregate" but not for an ordinary follow-up question.

    Also false if the reply carries its OWN percentage ("55% in PCB") -
    apply_percentage_scope would silently splice the scope onto the STALE
    number from the original pending question and discard this new one,
    answering confidently on the wrong figure instead of the one just given.
    Falling through to the normal pipeline here is the safe direction: worst
    case it asks again, which beats a wrong verdict.
    """
    if _PERCENT_RE.search(text or ""):
        return None
    scope = describes_percentage_scope(text)
    if not scope:
        return None
    if "?" in text or len((text or "").split()) > 10:
        return None
    return scope


def apply_percentage_scope(text, scope):
    """Splice an explicit scope cue next to the first percentage figure in
    `text`, so extract()'s _nearest_cue (a tight +/-30 char window - see its
    docstring) attributes it correctly. Used to recombine a bare
    clarify-percentage reply with the ORIGINAL question, which is the one
    that actually carries the number; the reply itself never repeats it.
    """
    m = _PERCENT_RE.search(text or "")
    if not m:
        return text
    cue = " overall" if scope == "overall" else " in the specific subject combination"
    return text[:m.end()] + cue + text[m.end():]


def subject_verdict(project_id, subjects):
    """Whether the subjects the student studied satisfy this programme.

    None when they named no subjects at all. Returns (ok, missing).
    """
    rule = RULES.get(project_id)
    if not rule or not subjects:
        return None, set()
    missing = rule["subjects"] - subjects
    if rule["either"] and not (rule["either"] & subjects):
        missing = missing | {" or ".join(sorted(rule["either"]))}
    # English is very often simply not mentioned by a student listing their
    # science subjects, so its absence is not treated as disqualifying - only
    # a subject they'd have had to actively choose (Biology vs Mathematics)
    # counts as missing.
    missing.discard("english")
    return (not missing), missing


def eligible_programmes(subjects):
    """Every programme whose subject requirement the student satisfies.

    Exists because "which courses can I apply for?" was answered with one
    programme twice in the evaluation - Q32 said B.V.Sc. was the only option
    for a PCB student (B.F.Sc. also takes PCB), and Q33 sent a PCM student to
    B.V.Sc., which requires Biology and which they cannot enter.
    """
    if not subjects:
        return []
    return [pid for pid in RULES if subject_verdict(pid, subjects)[0]]


_ASKS_THRESHOLD_RE = re.compile(
    r"\b(what|how much|how many|minimum|min|required|require|need|needed|"
    r"cut ?off|cutoff|criteria|eligibility)\b", re.I)
_THRESHOLD_SUBJECT_RE = re.compile(
    r"\b(percent|percentage|%|marks|score|aggregate|cut ?off|cutoff)\b", re.I)


def is_threshold_question(text):
    """Asking what the requirement IS, rather than whether they meet it.

    Separated from evaluate() because these carry no marks of their own, so
    evaluate() correctly reports "insufficient" and they fall through to
    retrieval - which is where Q50 went wrong. Asked "what percentage is
    required for SC/ST/OBC candidates?", the pipeline answered "50%... the
    guidelines do not list a separate lower threshold for these categories",
    four questions before stating the real 47.50% correctly elsewhere. That
    is a false rule stated with confidence, and it turns eligible students
    away.
    """
    if not text:
        return False
    facts = extract(text)
    if facts["subject_percent"] is not None or facts["overall_percent"] is not None:
        return False          # they cited their own marks - that is a verdict
    return bool(_ASKS_THRESHOLD_RE.search(text)
                and _THRESHOLD_SUBJECT_RE.search(text))


def thresholds_for(text, project_id=None):
    """The requirement(s) this question is actually asking about.

    Returns a list of (label, category, percent, subject_label, page). When no
    programme is pinned down, every programme is returned rather than one
    picked - the reserved threshold genuinely differs (47.50% for B.V.Sc.,
    40% for the other two), so answering with a single figure is wrong however
    it is phrased.
    """
    facts = extract(text)
    category = facts["category"] or "both"
    ids = [project_id] if project_id in RULES else list(RULES)
    out = []
    for pid in ids:
        rule = RULES[pid]
        for name in (("unreserved", "reserved") if category == "both" else (category,)):
            out.append((rule["label"], name, rule[name],
                        rule["subject_label"], rule["page"]))
    return out


_WHICH_PROGRAMMES_RE = re.compile(
    r"\b(which|what|all)\b[^?]{0,60}\b(courses?|programmes?|programs?|degrees?|"
    r"options?)\b", re.I)
_APPLY_RE = re.compile(
    r"\b(apply|eligible|eligibility|qualify|can i (do|join|take)|opt for)\b", re.I)


def describes_self(text):
    """Whether `text` speaks in the first person at all - "I", "my", "I've".

    Used by the guided-interview gate (rag/guards.py's
    _looks_like_eligibility_question) to tell "what is the eligibility
    criteria for B.V.Sc.?" (a question about the RULE) apart from "am I
    eligible for B.V.Sc.?" (a question about the STUDENT). Both reach
    evaluate()'s "insufficient"/"no_percentage" outcome identically - neither
    states a percentage - but only the second should ever prompt the
    interview; the first must keep falling through to a normal descriptive
    RAG answer exactly as it always has. Reproduced directly: without this
    check, A1 ("What is the eligibility criteria for B.V.Sc. & A.H. at
    MAFSU?" - a general, answerable-from-the-prospectus question) got
    intercepted with "have you appeared for the entrance exam?" instead of
    its real answer.
    """
    return bool(_FIRST_PERSON_RE.search(text or ""))


_BARE_NUMBER_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*$")


def bare_percent(text):
    """The percentage figure in `text`, regardless of any scope cue - used by
    the guided-interview flow (rag/guards.py's _eligibility_guard) to accept
    a lone number ("48", "48%") as the answer to a question that has ALREADY
    narrowed the scope unambiguously by asking for it specifically ("what is
    your percentage in the required subject combination?"). extract()'s
    cue-based disambiguation exists for the freeform case, where a bare
    number's scope is genuinely unclear - it is the wrong tool once the
    assistant itself is the one that asked, and the only thing left to
    interpret is the number.

    Tries _PERCENT_RE first (needs a "%"/"percent" marker) so a number
    embedded in a longer sentence is still read correctly, then falls back
    to a whole-message bare number with no marker at all ("48") - the most
    natural reply to a question that already told the student it wants a
    percentage, and the ONLY thing _PERCENT_RE cannot match, since it
    requires the marker. The whole-message anchor (^...$) keeps this
    fallback narrow: it must be the entire reply, not a number sitting
    inside a longer, differently-shaped message.
    """
    m = _PERCENT_RE.search(text or "")
    if not m:
        m = _BARE_NUMBER_RE.match(text or "")
    if not m:
        return None
    value = float(m.group(1))
    return value if value <= 100 else None


# Bare yes/no/pending replies to the interview's "have you appeared for the
# entrance exam?" question (see rag/guards.py's _eligibility_interview_ask).
# missing_entrance_exam requires a first-person negation NEXT TO the exam's
# own name (see its docstring) - deliberately narrow so an unrelated sentence
# mentioning the exam isn't misread as a personal claim. A one-word "no"
# typed in reply to OUR OWN question has neither, so it needs its own,
# equally narrow, classifier - mirrors is_bare_scope_reply's shape exactly:
# short, and not a substantial question of its own, so a genuine new
# question typed at this moment still falls through instead of being
# swallowed as an answer to a stale prompt.
_ENTRANCE_BARE_NO_RE = re.compile(r"^(no|nope|nah|haven'?t|didn'?t|not\s+appeared)\b", re.I)
_ENTRANCE_BARE_YES_RE = re.compile(r"^(yes|yeah|yep|already|done|appeared)\b", re.I)
_ENTRANCE_BARE_PENDING_RE = re.compile(r"pending|upcoming|scheduled|not\s+yet", re.I)


def is_bare_entrance_reply(text):
    """Which way a short, question-free reply answers "have you appeared for
    the entrance exam?" - "yes" | "no" | "pending" | None. None both for a
    genuine new question ("do I need to appear for MHT-CET?" - has a "?" and
    is really about the RULE, not a personal claim - describes_own_subjects'
    docstring covers the identical trap for subjects) and for anything that
    isn't recognisably an answer at all.
    """
    stripped = (text or "").strip()
    if not stripped or "?" in stripped or len(stripped.split()) > 6:
        return None
    if _ENTRANCE_BARE_PENDING_RE.search(stripped):
        return "pending"
    if _ENTRANCE_BARE_NO_RE.match(stripped):
        return "no"
    if _ENTRANCE_BARE_YES_RE.match(stripped):
        return "yes"
    return None


def is_which_programmes_question(text):
    """"Which courses can I apply for?" - answerable from subjects alone.

    A whole family the assistant kept getting wrong by answering with ONE
    programme: a PCB student was told B.V.Sc. was "the only undergraduate
    course" they were eligible for (B.F.Sc. also takes PCB), and a PCM student
    was sent to B.V.Sc., which requires Biology and which they cannot enter.
    eligible_programmes() has always computed this correctly; nothing asked it.

    Requires the student to have described their OWN subjects - otherwise
    there is nothing to match against and clarification is the right response.
    """
    if not text or not describes_own_subjects(text):
        return False
    return bool(_WHICH_PROGRAMMES_RE.search(text) and _APPLY_RE.search(text))


def evaluate(project_id, text):
    """Verdict for a self-situation question, or a reason it cannot be given.

    Returns a dict the caller can hand to the model as facts to phrase:
      {verdict: eligible | not_eligible | insufficient, ...}
    """
    rule = RULES.get(project_id)
    if not rule:
        return {"verdict": "insufficient", "reason": "unknown_programme"}

    # Before anything to do with marks. A missed entrance exam is disqualifying
    # on its own, and checking it first is what stops strong marks from leading
    # the answer - the Q19 failure was an opening "Yes, you can still get
    # admission" with the exam requirement appended as a contradiction.
    missed = missing_entrance_exam(project_id, text)
    if missed:
        return {"verdict": "not_eligible", "reason": "entrance_exam",
                "entrance": missed, "programme": rule["label"],
                "page": rule["page"]}

    facts = extract(text)
    category = facts["category"]
    required = threshold(project_id, category or "unreserved")

    # Only judge subjects the student claims as their own - see
    # describes_own_subjects. A question that merely NAMES a subject is asking
    # what the rule is, not asking to be assessed against it.
    own = facts["subjects"] if describes_own_subjects(text) else set()
    subjects_ok, missing = subject_verdict(project_id, own)
    if subjects_ok is False:
        return {"verdict": "not_eligible", "reason": "subjects",
                "missing": sorted(missing), "programme": rule["label"],
                "required_subjects": rule["subject_label"], "page": rule["page"]}

    percent = facts["subject_percent"]
    if percent is None and facts["overall_percent"] is not None:
        # The rule is explicitly on the subject combination, so an aggregate
        # cannot answer it - and silently substituting one for the other is
        # exactly the Q25 failure. Ask instead.
        return {"verdict": "insufficient", "reason": "overall_not_subject",
                "overall": facts["overall_percent"], "programme": rule["label"],
                "required_subjects": rule["subject_label"],
                "required": required, "page": rule["page"]}
    if percent is None:
        return {"verdict": "insufficient", "reason": "no_percentage",
                "programme": rule["label"], "required": required,
                "required_subjects": rule["subject_label"], "page": rule["page"]}

    return {"verdict": "eligible" if percent >= required else "not_eligible",
            "reason": "percentage", "stated": percent, "required": required,
            "category": category or "unreserved",
            "category_assumed": category is None,
            "programme": rule["label"], "required_subjects": rule["subject_label"],
            "entrance": rule["entrance"], "page": rule["page"],
            # .get(), not rule[...]: only bvsc's RULES entry currently has
            # this key (see its own comment on why bfsc/btech-dairy are
            # deliberately left out) - None here for the other two, which
            # _eligibility_facts reads as "nothing to mention".
            "age_requirement": rule.get("age_requirement")}
