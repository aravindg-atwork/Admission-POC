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
    "default": {
        "label": "B.V.Sc. & A.H.",
        "unreserved": 50.0,
        "reserved": 47.50,
        "subjects": {"physics", "chemistry", "english"},
        # Biology OR Biotechnology satisfies the same slot.
        "either": {"biology", "biotechnology"},
        "subject_label": "Physics, Chemistry, Biology or Biotechnology and English",
        "entrance": "NEET-UG-2026",
        "page": 4,
    },
    "bfsc": {
        "label": "B.F.Sc.",
        "unreserved": 50.0,
        "reserved": 40.0,
        "subjects": {"physics", "chemistry", "biology", "english"},
        "either": set(),
        "subject_label": "Physics, Chemistry, Biology and English",
        "entrance": "MHT-CET 2026",
        "page": 10,
    },
    "btech-dairy": {
        "label": "B.Tech. (Dairy Technology)",
        "unreserved": 50.0,
        "reserved": 40.0,
        "subjects": {"physics", "chemistry", "mathematics", "english"},
        "either": set(),
        "subject_label": "Physics, Chemistry, Mathematics and English",
        "entrance": "MHT-CET 2026",
        "page": 5,
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


def threshold(project_id, category):
    rule = RULES.get(project_id)
    if not rule:
        return None
    return rule["reserved"] if category == "reserved" else rule["unreserved"]


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


def evaluate(project_id, text):
    """Verdict for a self-situation question, or a reason it cannot be given.

    Returns a dict the caller can hand to the model as facts to phrase:
      {verdict: eligible | not_eligible | insufficient, ...}
    """
    rule = RULES.get(project_id)
    if not rule:
        return {"verdict": "insufficient", "reason": "unknown_programme"}

    facts = extract(text)
    category = facts["category"]
    required = threshold(project_id, category or "unreserved")

    subjects_ok, missing = subject_verdict(project_id, facts["subjects"])
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
            "entrance": rule["entrance"], "page": rule["page"]}
