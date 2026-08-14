"""Program-name detection: lightweight, deterministic routing across the
university's several separate degree-program projects (see projects.py).

Same design philosophy as lang.py's script detection and intent.py's payment-
issue check: keyword/substring matching, no model call, fast and auditable.
Each program lives in its own project with its own vector store and FAQ cache
(kept isolated on purpose - see the 2026-08-12 session that added the other
five programs, to avoid exactly the cross-program contamination that today's
B.V.Sc.-only retrieval bugs were about). This module exists for the one thing
that isolation doesn't solve by itself: a query arriving at the general/
default entry point that never says which program it means ("how much is the
fee?"), where answering from B.V.Sc. data by default would just be a silent
wrong guess for a B.Tech. or M.V.Sc. applicant.
"""

import re
import unicodedata

# Canonical display names, also used to label the disambiguation options
# shown to the student (see server.py's clarification response and app.js).
# Undergraduate only, from 2026-27. The postgraduate and doctoral projects
# (M.V.Sc., Ph.D., M.Tech. Dairy) were retired 2026-08-14 - the assistant is
# scoped to UG admissions. Their aliases are gone too: leaving them would let
# a question naming a retired programme route to a project that no longer
# exists, which fails far less clearly than not recognising the name at all.
PROGRAM_NAMES = {
    "default": "B.V.Sc. & A.H.",
    "bfsc": "B.F.Sc.",
    "btech-dairy": "B.Tech. (Dairy Technology)",
}


def _normalize(text):
    """Lowercase, letters/digits only - collapses 'B.V.Sc.', 'BVSc', 'B V Sc'
    and 'bvsc' to the same comparable form, and 'Dairy Technology' to
    'dairytechnology' regardless of the student's spacing/punctuation.
    """
    return "".join(ch for ch in text.lower() if ch.isalnum())


# Substring-matched against the normalized question. Deliberately conservative
# on the two dairy programs: bare "dairy" is genuinely ambiguous between them
# (Bachelor's vs Master's) and is left OUT on purpose, so a bare "dairy fee"
# question correctly falls through to needs_clarification rather than
# guessing which one. "btech"/"mtech" alone are safe and specific because,
# among these six programs, each belongs to exactly one.
#
# "dairytechnology" was removed from btech-dairy's aliases 2026-08-12: it's
# just as ambiguous as bare "dairy" (both programs' full names end in "Dairy
# Technology"), and having it here silently contradicted the comment above -
# "M.Tech. Dairy Technology" matched BOTH btech-dairy (via "dairytechnology")
# and mtech-dairy (via "mtech"), so a plain single-program M.Tech question got
# routed through the cross-program comparison path and answered with an
# unnecessary "the B.Tech document doesn't specify..." aside about a program
# nobody asked about. Before needs_comparison existed to check for 2+ matches,
# this silently misrouted the same questions to btech-dairy outright (it
# happened to sort first in this dict) - a latent bug this surfaced rather
# than introduced.
#
# "veterinary" was removed from default's aliases the same day, same bug
# shape: M.V.Sc. IS "Master of VETERINARY Science", so any question
# mentioning "my veterinary degree" (without naming B.V.Sc. specifically)
# matched BOTH default (via "veterinary") and mvsc (via "mvsc") - a plain
# M.V.Sc. question about the applicant's own prior degree got routed through
# the comparison path and picked up an irrelevant "For B.V.Sc. & A.H.
# program... not directly relevant to your question" aside. "bvsc" alone is
# specific enough - unlike "veterinary", which describes the whole field.
# The Devanagari entries are POST-_normalize skeletons, not readable words:
# _normalize keeps only alnum characters, and Devanagari matras/viramas are
# combining marks (category Mn), so "बी.व्ही.एस्सी." and "बीव्हीएससी" both
# reduce to "बवहएसस". Added 2026-08-13 after a Hindi question naming its
# programme in Devanagari was still asked "which programme did you mean?" -
# only the Latin spellings were listed, so a student writing in their own
# script could never satisfy the check. The intent router usually catches
# this, but it is rate-limited/unavailable often enough (observed: Groq
# HTTP 429) that the deterministic floor has to handle it too.
# Tamil added alongside Devanagari 2026-08-13 - fixing only one of the
# two Indic scripts the app supports would have left the identical bug
# open for every Tamil-speaking student.
_PROGRAM_ALIASES = {
    # "veterinary"/"vet" added 2026-08-14: detect_program("veterinary")
    # returned None, so "Can I apply for veterinary at MAFSU?" named no
    # programme as far as the deterministic matcher was concerned, and the
    # eligibility guard fell through to the router - which answered about
    # B.Tech. (Dairy Technology). It is the word a student is most likely to
    # use for this course, and now that M.V.Sc. is retired it is unambiguous.
    "default": ("bvsc", "animalhusbandry", "veterinary", "vet",
                "veterinaryscience", "बवहएसस", "बवएसस", "पशवदयकय",
                "பவஎஸச", "கலநட"),
    "bfsc": ("bfsc", "fishery", "fisheries", "बएफएसस", "मतसय",
             "பஎஃபஎஸச", "மனவளம"),
    # "dairy"/"dairytechnology" are unambiguous again now that M.Tech.
    # (Dairy) is retired - they were excluded only because two dairy
    # programmes existed and a bare "dairy" could not choose between them.
    "btech-dairy": ("btech", "dairy", "dairytechnology", "बटक", "படக"),
}


# Found 2026-08-12: "I completed my B.V.Sc. abroad. Do I need to appear for
# AIEEA for M.V.Sc. admission?" named two programs (bvsc, mvsc) and wrongly
# triggered the cross-program comparison path against B.V.Sc., even though
# B.V.Sc. here is pure background about the student's own prior degree, not
# something to compare against M.V.Sc. - the resulting answer led with a
# flat, unhedged claim and buried its NRI-scope caveat under the unrelated
# B.V.Sc. paragraph. Program-name detection itself was correct (both names
# genuinely appear); the bug was treating "student's own already-completed
# degree, named only as background" the same as "program the student wants
# information about" - same bug SHAPE as the "veterinary"-alias fix above,
# but that fix can't catch this: "bvsc" is a legitimate, specific alias, and
# removing it would just break every real B.V.Sc. question.
_SELF_CREDENTIAL_RE = re.compile(
    r"\b(?:i\s+(?:have\s+)?(?:completed|did|done|passed|finished|hold|holds|"
    r"obtained|got|graduated)|already\s+have|my\s+own|i\s+am\s+a\s+graduate\s+of)\b",
    re.IGNORECASE,
)
_SELF_CREDENTIAL_WINDOW = 40  # chars after the marker to look for the named program
# Bounds the window to the credential's own clause so a SECOND, unrelated
# program named right after ("...B.Tech Dairy degree, is M.Tech Dairy
# eligibility different?") isn't swept in too - "." is deliberately excluded
# from this boundary set even though it usually ends a clause, because every
# program abbreviation here IS internal periods ("B.V.Sc.", "Ph.D."); cutting
# on "." would truncate the window before the abbreviation it needs to match.
_CLAUSE_BOUNDARY_RE = re.compile(
    r"[,;?!]|\b(?:is|are|do|does|am|was|were|can|could|will|would|should|and|but|so)\b",
    re.IGNORECASE,
)


def _self_credential_programs(text):
    """Project ids named only as the student's OWN prior/completed degree,
    not the program being asked about - see _SELF_CREDENTIAL_RE above.
    """
    found = set()
    for match in _SELF_CREDENTIAL_RE.finditer(text):
        rest = text[match.end():match.end() + _SELF_CREDENTIAL_WINDOW]
        boundary = _CLAUSE_BOUNDARY_RE.search(rest)
        span = rest[:boundary.start()] if boundary else rest
        window = _normalize(span)
        for project_id, aliases in _PROGRAM_ALIASES.items():
            if any(alias in window for alias in aliases):
                found.add(project_id)
    return found


def detect_programs_multi(text):
    """Return every project id a question explicitly names, ordered by where
    its first alias appears in the text - not just one (see detect_program).

    Added 2026-08-12 to tell "what is the B.Tech Dairy fee" (exactly one
    program - route/redirect there, see rag.py) apart from "compare B.V.Sc.
    and B.F.Sc." or "which courses require NEET vs MHT-CET" (two or more
    programs, or none at all with comparison language - see
    needs_comparison), which need a genuine cross-project synthesized answer
    instead of a single redirect. Text order rather than the dict's key
    order so a mixed mention ("B.F.Sc. or B.V.Sc.?") lists the programs the
    way the student actually asked about them. Programs named only as the
    student's own prior/completed degree are excluded entirely (see
    _self_credential_programs) - never counted for comparison, redirect, or
    clarification decisions.
    """
    norm = _normalize(text)
    self_credential = _self_credential_programs(text)
    found = []
    for project_id, aliases in _PROGRAM_ALIASES.items():
        if project_id in self_credential:
            continue
        positions = [norm.find(alias) for alias in aliases if alias in norm]
        if positions:
            found.append((min(positions), project_id))
    found.sort()
    return [project_id for _, project_id in found]


def detect_program(text):
    """Return the project id a question explicitly names, or None.

    Not exhaustive - tune by adding aliases as real misses turn up, same as
    lang.py's marker sets. The alias sets above don't overlap by
    construction (each token/phrase names exactly one program), so which one
    "wins" only matters when a question names several - see
    detect_programs_multi, which this delegates to.
    """
    multi = detect_programs_multi(text)
    return multi[0] if multi else None


# Devanagari vowel signs (matras) and the virama are combining marks, not
# alnum, so a naive isalnum() split shatters every Devanagari word mid-token
# ("फी" -> "फ", silently dropping the "ी" - reproduced directly: needed
# needs_program_clarification's own _PROGRAM_SPECIFIC_MARKERS check for "फी"
# to actually fire on "फी किती आहे?"). Same fix as intent.py's _words() and
# faq.py's _is_word_char - duplicated here rather than imported because each
# of those has its own slightly different normalization needs, matching this
# codebase's existing convention of small per-module tokenizers over a shared
# one (see faq.py's docstring on this point).
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


# Topics whose answer genuinely varies per program - fees, eligibility, seats,
# dates and the like. A question hitting one of these, with no program named,
# is the case that actually needs disambiguating.
_PROGRAM_SPECIFIC_MARKERS = {
    "fee", "fees", "eligibility", "eligible", "criteria", "admission",
    "seat", "seats", "hostel", "tuition", "marks", "quota", "reservation",
    "reserved", "unreserved", "syllabus", "course", "degree", "intake",
    "neet", "aieea", "cgpa", "documents", "certificate", "certificates",
    "deadline", "merit", "grievance", "refund", "internship", "vacancy",
    "vacancies", "cutoff", "duration", "curriculum",
    # Hindi / Marathi
    "शुल्क", "फी", "फीस", "पात्रता", "जागा", "वसतिगृह", "प्रवेश",
}
# Portal-mechanics topics that have exactly one correct answer regardless of
# which program - matches tools/seed_faq_portal.py's shared content. A
# question hitting one of these must NOT be treated as needing program
# disambiguation, or it would fight the existing "How to Register?" answer
# (see rag.py/faq cache), which already disambiguates portal-signup from
# academic-registration on its own, a completely different axis.
_SHARED_PORTAL_MARKERS = {
    "register", "registration", "password", "login", "log", "upload",
    "print", "resubmission", "resubmit", "account", "forgot",
}


def _is_devanagari(s):
    return any(0x0900 <= ord(c) <= 0x097F for c in s)


def _levenshtein_le(a, b, max_dist):
    """True if a and b are within max_dist single-character edits - no
    external dependency (this backend stays stdlib-only, see config.py's
    module docstring), so a plain bounded DP instead of a library.
    """
    if abs(len(a) - len(b)) > max_dist:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] <= max_dist


def _matches(words, markers):
    """Exact match for English; stem/prefix match for Devanagari markers,
    since Hindi/Marathi agglutinate case endings onto the noun the same way
    glossary.py's stems do ("वसतिगृह" -> "वसतिगृहाची") - an exact-set check
    silently missed every inflected form, reproduced directly: "वसतिगृहाची
    सोय उपलब्ध आहे का?" (is hostel available) never matched the bare
    "वसतिगृह" marker. `len(marker) >= 3` guards against a short marker
    stem-matching words it has no business matching.

    English markers additionally get a single-edit typo tolerance, gated to
    `len(marker) >= 6` for the same false-positive reason - reproduced
    directly: "what the eligbility" (one missing letter) exact-matched
    nothing in _PROGRAM_SPECIFIC_MARKERS, so needs_program_clarification
    returned False and the question silently answered from whichever
    program the request happened to be scoped to instead of asking which
    course - the exact "ask, don't guess" guarantee this module exists to
    give. A short marker like "fee"/"seat" is left exact-match-only: at
    3-4 characters, an edit-distance-1 net is wide enough to catch
    unrelated real words ("see", "fed"), which a typo fix must not do.
    """
    for word in words:
        for marker in markers:
            if word == marker:
                return True
            if _is_devanagari(marker) and len(marker) >= 3 and word.startswith(marker):
                return True
            if not _is_devanagari(marker) and len(marker) >= 6 and _levenshtein_le(word, marker, 1):
                return True
    return False


def needs_program_clarification(text):
    """True when a question is about something that varies per program,
    names no specific program, and isn't one of the shared portal-mechanics
    questions that already has one correct answer regardless of program.
    """
    if detect_program(text):
        return False
    words = _words(text)
    if _matches(words, _SHARED_PORTAL_MARKERS):
        return False
    return _matches(words, _PROGRAM_SPECIFIC_MARKERS)


def is_bare_program_reply(text):
    """True when a message is JUST a program name, carrying no question of
    its own - "btech", "B.F.Sc.", "the dairy one".

    Used by http/chat_routes.py to tell a student ANSWERING the program-
    clarification question ("which program did you mean?") apart from one
    asking a genuinely new question that happens to name a program. The
    distinction matters because the first case has to be answered using the
    EARLIER question's text (the student already said what they wanted to
    know), while the second must be answered on its own terms.

    Deliberately keyed on "carries no topic marker of its own" rather than a
    word count: "btech dairy fees" is only three words but is a complete,
    self-sufficient question that must NOT be rewritten into whatever was
    asked before it, while "the btech one please" is four words and is
    purely an answer to the clarification.
    """
    if not detect_program(text):
        return False
    words = _words(text)
    return not _matches(words, _PROGRAM_SPECIFIC_MARKERS | _SHARED_PORTAL_MARKERS)


# The three undergraduate programs - the sensible default set for a generic
# "which/all courses" comparison with no program named (see comparison_targets
# below). A 12th-marks eligibility question has no bearing on the three
# postgraduate/doctoral programs, so defaulting to all six would only add
# noise to the answer, not real coverage.
# Every programme is undergraduate now, so this and PROGRAM_NAMES are the
# same set - kept as its own name because comparison_targets' intent ("the
# sensible default set for a generic question") is not the same statement as
# "all programmes", and they will diverge again if a PG programme returns.
_UG_PROGRAMS = ("default", "bfsc", "btech-dairy")

# Word-level co-occurrence, not phrase matching: a trigger word ("which",
# "all", "compare"...) AND a course/program noun must both appear SOMEWHERE
# in the question, not adjacently - real phrasing puts modifiers between them
# ("which MAFSU UNDERGRADUATE courses", "all the MAFSU undergraduate
# courses"), which an adjacent-phrase check misses. Neither set is broad
# enough to misfire alone: "which documents are required" has a trigger but
# no course/program noun; "what is the duration of the course" has the noun
# but no trigger. Tuned against the exact generic no-program-named
# cross-program questions found in the 2026-08-12 benchmark run.
_COMPARISON_TRIGGER_WORDS = {"which", "all", "compare", "comparison", "difference", "differ"}
_COMPARISON_NOUN_WORDS = {"course", "courses", "program", "programs"}


def needs_comparison(text):
    """True when a question genuinely spans multiple programs and needs a
    synthesized cross-project answer (see rag.py's comparison answer path) -
    either by naming two or more programs explicitly, or by asking a generic
    "which/all courses" question with comparison language and no single
    program named. A question naming exactly one program is never a
    comparison, regardless of phrasing - that's an ordinary single-program
    question (see detect_program/needs_program_clarification instead).
    """
    named = detect_programs_multi(text)
    if len(named) >= 2:
        return True
    if named:
        return False
    words = _words(text)
    # _matches, not a raw set intersection: the same single-character typo
    # tolerance needs_program_clarification already gets (see _matches).
    # Reproduced directly - "what all couse i can apply for if my score is
    # 60%" (one missing letter in "course") failed the noun check, so this
    # returned False, the question fell through to the program-clarify guard,
    # and a student asking the genuinely cross-program question this path
    # exists to answer got "which program did you mean?" instead. The
    # trigger words are mostly under the 6-character floor _matches applies
    # ("all", "which"), so they stay exact-match in practice; the nouns
    # ("course"/"courses"/"program"/"programs") are all over it, which is
    # exactly where the real typos land.
    return _matches(words, _COMPARISON_TRIGGER_WORDS) and _matches(words, _COMPARISON_NOUN_WORDS)


# Said explicitly, "all" means all six - not the UG default. Asked "for all
# course is this fee same?" the answer covered three programmes and closed
# with "the same across all three", which is not what was asked and quietly
# leaves the postgraduate programmes unanswered.
_ALL_PROGRAMS_WORDS = {"all", "every", "each", "सर्व", "सभी", "प्रत्येक"}


def comparison_targets(text):
    """Which projects a comparison answer should pull from: the programmes
    explicitly named (2+), every programme when the question says "all", or
    the three undergraduate programmes by default. Only meaningful when
    needs_comparison(text) is already True.

    The UG default exists because a 12th-marks eligibility question has no
    bearing on the postgraduate and doctoral programmes, so including them
    adds noise rather than coverage. That reasoning does not survive the
    word "all", which is a direct request for the full set.
    """
    named = detect_programs_multi(text)
    if len(named) >= 2:
        return named
    if _words(text) & _ALL_PROGRAMS_WORDS:
        return list(PROGRAM_NAMES)
    return list(_UG_PROGRAMS)


# Courses this university does not run, plus the shapes an unfamiliar degree
# usually takes. Deliberately a list of COURSES: the refusal it gates must
# never trigger on the institution's own name.
_FOREIGN_COURSE_WORDS = {
    "mba", "mbbs", "bds", "bams", "bhms", "bums", "bpt", "bsc", "msc", "ba",
    "bcom", "mcom", "llb", "llm", "bca", "mca", "bba", "bpharm", "dpharm",
    "bed", "med", "phd", "mvsc", "mtech", "be", "btech",
    "engineering", "medicine", "medical", "nursing", "pharmacy", "law",
    "agriculture", "horticulture", "forestry", "commerce", "arts", "management",
}

# Degree-shaped tokens: B.Arch, M.Plan, and anything else of that form we
# have not enumerated. Matched only as a fallback, so an unlisted course is
# still caught rather than silently answered from the wrong corpus.
# Postgraduate/doctoral programmes, all retired from this deployment on
# 2026-08-14. Written to tolerate the dots and spacing students actually type
# (Ph.D., PhD, Ph D, M.V.Sc., MVSc, M.Tech, M Tech).
_PG_MARKER_RE = re.compile(
    r"\b(ph\.?\s?d\.?|m\.?\s?v\.?\s?sc\.?|m\.?\s?tech\.?|m\.?\s?sc\.?|"
    r"m\.?\s?f\.?\s?sc\.?|post[\s-]?graduate|masters?\s+(?:degree|programme|program)|"
    r"doctoral|doctorate)\b", re.I)

_DEGREE_SHAPE_RE = re.compile(r"\b[bm]\.\s?[a-z]{1,6}\.?\b", re.I)


def mentions_foreign_course(text):
    """Whether the text actually names a course, other than one of ours.

    Corroboration for the unknown-programme refusal, which used to fire on
    the router's say-so alone. The router is instructed to report False when
    a message names no degree at all, but it read the UNIVERSITY's name as a
    course and refused two of the most ordinary questions there are - "How do
    I apply for MAFSU admission?" and "Where can I find the MAFSU
    prospectus?" - with "I can't help with that course".

    Refusing a question that is squarely in scope is a worse failure than the
    one the refusal was built to prevent, and it hits far more students, so
    the refusal now needs evidence in the student's own words.
    """
    # Postgraduate markers decide FIRST, before the "is it one of ours?"
    # check, because two of them collide with our own aliases: "M.Tech. Dairy
    # Technology" contains "dairy" and so read as the B.Tech. programme, and
    # "M.V.Sc." shares its tail with "B.V.Sc.". Matched by regex rather than
    # word tokens because _words() splits "Ph.D." into "ph" and "d", so the
    # plain word list never saw a Ph.D. question at all - which is how a
    # Ph.D. question came back quoting B.V.Sc.'s 47.5%.
    if _PG_MARKER_RE.search(text or ""):
        return True
    if detect_programs_multi(text):
        return False
    words = _words(text)
    if words & _FOREIGN_COURSE_WORDS:
        return True
    stripped = re.sub(r"\b(mafsu|maharashtra|university|college|institute)\b", " ",
                      text or "", flags=re.I)
    return bool(_DEGREE_SHAPE_RE.search(stripped))


def comparison_is_explicit(text):
    """True when the text itself names the set to compare.

    comparison_targets() falls back to the three UG programmes when a question
    reads as a comparison but names nothing. That default is right on the
    general widget and wrong on a programme-scoped one: a student already
    inside the B.Tech widget asking "can I apply if I took Biology instead of
    Maths?" is asking about B.Tech, but needs_comparison sees the contrast and
    comparison_targets then supplies all three, so the reply opens on B.V.Sc.

    Same discipline the redirect path already follows - act on a programme the
    student actually named, never on one merely inferred.
    """
    return (len(detect_programs_multi(text)) >= 2
            or bool(_words(text) & _ALL_PROGRAMS_WORDS))
