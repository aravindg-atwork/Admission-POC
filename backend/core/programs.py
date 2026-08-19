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
    "bvsc": "B.V.Sc. & A.H.",
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
    "bvsc": ("bvsc", "animalhusbandry", "veterinary", "vet",
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


# The single core abbreviation per programme, used ONLY by
# _typo_matched_projects below - never the full alias tuple. The descriptive
# aliases (veterinary, fishery, dairy, vet...) stay exact-substring-only on
# purpose: "vet" is a common enough word that fuzzing it would misfire
# ("vet appointment"), and "dairy" is edit-distance-1 from the real word
# "daily" ("daily fee schedule" must not route to btech-dairy). The three
# short abbreviations don't have that problem - they aren't dictionary
# words - which is exactly what makes a typo in one of THEM worth catching.
_CORE_ABBREVIATIONS = {
    "bvsc": "bvsc",
    "bfsc": "bfsc",
    "btech-dairy": "btech",
}

# Real, common, unrelated words that happen to sit edit-distance-1 (or one
# adjacent transposition) from a core abbreviation above and must never be
# treated as a typo of it - see _typo_matched_projects's docstring for how
# "tech" (one letter from "btech") was found and why a per-word exclusion,
# not a length change, is the right fix.
_TYPO_EXCLUDED_WORDS = {"tech"}


def _is_adjacent_transposition(a, b):
    """True if `a` is `b` with exactly one pair of ADJACENT characters
    swapped ("bvcs" vs "bvsc") - plain Levenshtein counts a transposition
    as distance 2 (two substitutions), not 1, so _levenshtein_le(a, b, 1)
    misses this extremely common typo shape entirely. Only ever called
    alongside that check, never instead of it - see _typo_matched_projects.
    """
    if len(a) != len(b):
        return False
    diffs = [i for i in range(len(a)) if a[i] != b[i]]
    return (len(diffs) == 2 and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]])


def _typo_matched_projects(text):
    """Single-edit typo tolerance for the three core programme
    abbreviations - "bfsv" for "bfsc", "bvcs" for "bvsc" - as
    {project_id: matched_word}.

    core/programs.py's existing typo tolerance (_matches, used for topic
    markers like "eligibility") is gated to markers >=6 characters for
    exactly the reason these abbreviations were left out of it entirely: at
    4-5 characters, a blind edit-distance-1 net is wide enough to catch
    other words by accident. Worse than an unrelated word here specifically:
    "bvsc" and "bfsc" are mutually edit-distance-1 of EACH OTHER (the
    v/f substitution), so a naive per-abbreviation check would let a typo of
    ONE programme's name "correct" into a DIFFERENT, wrong programme -
    silently answering from the wrong corpus, worse than not catching the
    typo at all. This is the concrete shape of the risk that kept typo
    tolerance off the programme aliases in the first place.

    Fixed by requiring the match be unique: a word is only accepted as a
    typo of an abbreviation when it is within edit-distance 1 of that ONE
    abbreviation and no other. "bfsv" is distance 1 from "bfsc" but distance
    2 from "bvsc" - unambiguous, accepted. A word equidistant from (or
    within edit-distance 1 of) two abbreviations at once is left undetected
    rather than guessed either way.

    _TYPO_EXCLUDED_WORDS closes a second gap the uniqueness rule above
    cannot: a word can be unambiguously distance-1 from exactly one
    abbreviation and STILL be a real, common, unrelated word - "tech" is
    distance 1 from "btech" (drop the leading "b") and appears constantly in
    completely unrelated contexts ("hi-tech", "tech support", "EdTech"), not
    just as a typo of the abbreviation. Found by sweeping every question in
    tools/eval_admissions.py's CASES plus a broad list of common short
    English words before trusting this function; "tech" was the only
    collision either turned up. Extend this set the same way
    programs.mentions_foreign_course's management/quota gate is extended -
    add the word, do not redesign the check - if a new one is found.
    """
    found = {}
    for word in _words(text):
        if len(word) < 4 or word in _TYPO_EXCLUDED_WORDS:
            continue
        near = [pid for pid, abbr in _CORE_ABBREVIATIONS.items()
                if _levenshtein_le(word, abbr, 1) or _is_adjacent_transposition(word, abbr)]
        if len(near) == 1:
            found[near[0]] = word
    return found


# Real-world phrases that contain a programme alias as a SUBSTRING but name
# something else entirely - stripped from the normalized text before alias
# matching runs, so the alias inside them never counts as naming that
# programme. "Indian Dairy Diploma" (IDD) is a real, named vocational
# qualification some applicants already hold - it appears in bvsc's OWN
# prospectus ("Indian Dairy Diploma shall not be considered equivalent to
# XII (HSSC)"), and a student asking about ITS equivalence on the
# B.V.Sc.-scoped widget got silently redirected to B.Tech (Dairy
# Technology)'s own admission requirements instead of an answer about their
# own diploma (_program_redirect_guard fires on ANY project, not just
# `default`, whenever detect_program finds a different programme's alias in
# the text - "dairy" being a deliberately bare alias for btech-dairy is
# exactly what makes it collide here). Reproduced directly, live,
# 2026-08-19. Same "extend the gate, don't redesign it" pattern as
# _TYPO_EXCLUDED_WORDS above and mentions_foreign_course's management/quota
# gate: add a phrase here if a new collision turns up.
_NON_PROGRAMME_PHRASES = ("dairydiploma",)


def _strip_non_programme_phrases(norm):
    for phrase in _NON_PROGRAMME_PHRASES:
        norm = norm.replace(phrase, "")
    return norm


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
    norm = _strip_non_programme_phrases(_normalize(text))
    self_credential = _self_credential_programs(text)
    found = []
    matched_ids = set()
    for project_id, aliases in _PROGRAM_ALIASES.items():
        if project_id in self_credential:
            continue
        positions = [norm.find(alias) for alias in aliases if alias in norm]
        if positions:
            found.append((min(positions), project_id))
            matched_ids.add(project_id)
    # Typo fallback: only for a programme no EXACT alias already found (a
    # question can misspell one programme while naming another correctly -
    # each is judged on its own). Position comes from the lowered original
    # text rather than `norm` (the exact-match coordinate space, fully
    # despaced) - a minor mismatch, acceptable since a question mixing an
    # exact mention of one programme with a typo'd mention of another is a
    # vanishingly rare case to begin with.
    lowered = text.lower()
    for project_id, word in _typo_matched_projects(text).items():
        if project_id in self_credential or project_id in matched_ids:
            continue
        found.append((lowered.find(word), project_id))
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
    # Topics whose ANSWER genuinely differs between the three programmes, and
    # where answering from all three is worse than asking which one. Narrowed
    # 2026-08-17 after measuring both alternatives.
    #
    # Removed: "admission", "documents", "certificate(s)", "deadline",
    # "merit", "grievance", "refund", "course", "degree", "internship". Those
    # are shared - one application portal, one document list, one merit
    # process - and having them here meant "what documents are required?" and
    # "how do I apply?" were answered with "which programme are you asking
    # about?". Section D scored 6/12 that way against 12/12 without them.
    #
    # "fee" stays, and that is not arbitrary: a bare "what is the fee?" fanned
    # out across all three programmes came back with every figure redacted by
    # the provenance check, because no single retrieval could source three
    # programmes' fee tables cleanly. A clarification is a better answer than
    # three apologies.
    # "hostel" moved to _SHARED_PORTAL_MARKERS 2026-08-18: the prospectuses
    # don't actually state a differing per-programme hostel fee at all - the
    # FEE STRUCTURE annexures only say it is "payable at the respective
    # college at the time of confirmation of admission", the same sentence in
    # every corpus. There was never a number here to disambiguate; "hostel"
    # only ever looked programme-specific by analogy with "fee".
    "fee", "fees", "tuition", "eligibility", "eligible", "criteria",
    "marks", "cutoff", "percentage", "seat", "seats", "intake", "vacancy",
    "vacancies", "quota", "reservation", "reserved", "unreserved",
    "syllabus", "curriculum", "duration", "neet", "aieea", "cgpa",
    # Hindi / Marathi
    "शुल्क", "फी", "फीस", "पात्रता", "जागा",
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
    # Added 2026-08-17. A question can MENTION a programme-specific topic
    # without asking for its value, and the word list alone cannot tell the
    # difference: "how do I PAY the application fee?" is one payment process
    # for all three programmes, and "does qualifying for NEET GUARANTEE
    # admission?" is one answer for all three, yet both were bounced with
    # "which programme are you asking about?" purely because "fee" and "neet"
    # appear in them. These verbs mark the question as being about the
    # PROCESS, which is shared, rather than the figure, which is not.
    "pay", "paying", "payment", "guarantee", "guarantees", "guaranteed",
    # Added 2026-08-18, same shape: "does MAFSU CONSIDER 12th marks or
    # entrance-exam marks?" asks about the merit-calculation PROCESS (the
    # weightage system is described the same way across every programme's
    # prospectus), not a differing figure, yet "marks" alone got it bounced
    # with "which programme?".
    "consider", "considers", "considered",
    # See _PROGRAM_SPECIFIC_MARKERS's comment on "hostel" - moved here
    # entirely, not just excluded from the strong/force-ask set, because
    # there is no differing per-programme figure to disambiguate in the
    # first place.
    "hostel", "वसतिगृह",
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


def is_shared_topic(text):
    """True when the question hits a portal-mechanics/process marker that has
    exactly one correct answer regardless of programme (see
    _SHARED_PORTAL_MARKERS). Exposed separately from needs_program_clarification
    so guards.py can use it as a veto over a ROUTER opinion too, not just as
    an early-return inside the deterministic marker check - see
    _program_clarify_guard's use of this for why: the router's own
    "needs_program_clarification" verdict used to win unconditionally
    whenever it had one, with no way for a proven-shared topic to override a
    router false positive back to "just answer it". Reproduced directly -
    "Does MAFSU consider 12th marks or entrance-exam marks for admission?"
    and "What is the hostel fee at MAFSU?" both have one shared answer (the
    weightage process is described the same way for every programme; hostel
    fees are stated as "payable at the respective college", not a differing
    figure - see the FEE STRUCTURE annexures), yet both got bounced with
    "which programme?" because the router said yes and nothing could say
    otherwise.
    """
    return _matches(_words(text), _SHARED_PORTAL_MARKERS)


def needs_program_clarification(text):
    """True when a question is about something that varies per program,
    names no specific program, and isn't one of the shared portal-mechanics
    questions that already has one correct answer regardless of program.
    """
    if detect_program(text):
        return False
    if is_shared_topic(text):
        return False
    words = _words(text)
    return _matches(words, _PROGRAM_SPECIFIC_MARKERS)


# Narrower than _PROGRAM_SPECIFIC_MARKERS - excludes "reservation", "reserved",
# "unreserved", "quota". Added 2026-08-17 for guards.py's _program_clarify_guard,
# which now ORs a deterministic signal in alongside the router instead of only
# using it as a fallback (see that guard's comment for why: the router
# occasionally misclassifies "What are the eligibility criteria?" and used to
# skip a clarification the full marker set already knew to ask for).
#
# The four words excluded here are exactly the ones this codebase already
# measured as unsafe for that job: "what is the reservation POLICY?" (one
# shared answer, same for all three programmes) and "what percentage do
# RESERVED candidates need?" (differs per programme) both contain a reservation
# word, and only reading the sentence - which only the router does - tells
# them apart. OR-ing the full marker set back in reproduced the exact
# regression HANDOFF.md documents for the deterministic-only attempt: Section
# E 9/9 -> 5/9, the same four questions (reservation policy, documents to
# claim it, cross-state reservation, EWS seats) wrongly asking "which
# programme?" instead of answering. Excluding just these four here keeps the
# broader OR-fix (eligibility, fee, marks, seats, hostel, duration, etc. all
# still force a clarification even on a router "no") without reopening that
# specific, already-measured collision.
#
# "hostel" added to the exclusion 2026-08-17, same day, confirmed live:
# _program_clarify_guard's OWN pre-existing comment already named this exact
# collision before this module even had a strong/weak split - "'is hostel
# accommodation compulsory?' (shared) [vs] 'what is the hostel fee?'
# (differs). Both questions contain the same marker word; only reading them
# apart works." Missed it when first narrowing this set; force-asking
# reproduced it immediately - "Is hostel accommodation compulsory?" (one
# shared answer) started wrongly asking "which programme?" the same way the
# reservation words did.
#
# "seat"/"seats"/"intake"/"vacancy"/"vacancies" excluded too, same day: "Are
# there seats reserved for EWS candidates?" hit the identical shape - the
# EWS reservation PERCENTAGE is a shared, state-mandated figure (like the
# reservation words above), but total seat COUNT genuinely does vary per
# programme, and "seats" alone can't tell which question this is. Not part
# of the original ask (eligibility/fee) either, so excluding the whole
# family rather than special-casing just EWS.
_FORCE_ASK_MARKERS = _PROGRAM_SPECIFIC_MARKERS - {
    "reservation", "reserved", "unreserved", "quota", "hostel",
    "seat", "seats", "intake", "vacancy", "vacancies",
}


def needs_program_clarification_strong(text):
    """Same as needs_program_clarification, but only the markers proven safe
    to OR in against a router "no" (see _FORCE_ASK_MARKERS above). Used to
    FORCE a clarification even when the router disagrees; the router is still
    trusted alone (no override) on the excluded reservation/quota words.
    """
    if detect_program(text):
        return False
    if is_shared_topic(text):
        return False
    words = _words(text)
    return _matches(words, _FORCE_ASK_MARKERS)


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
# Project ids, and "default" is deliberately NOT among them: it is the
# general entry point with no corpus of its own since the 2026-08-16
# split. Leaving it here would reintroduce exactly the bug the split
# removed - a question naming no programme answering from B.V.Sc.
_UG_PROGRAMS = ("bvsc", "bfsc", "btech-dairy")

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
#
# "be" (Bachelor of Engineering) removed 2026-08-18: it is also the single
# most common auxiliary verb in English, and _words() tokenizes on word
# boundaries alone with no part-of-speech awareness - "which NEET score
# will BE considered for 2026 admission?", an entirely ordinary admission
# question, collided on that one word and got refused outright with "I
# only cover admissions for...". "engineering" (already in this set) plus
# _DEGREE_SHAPE_RE's fallback (which matches "B.E." - the form people
# actually write to distinguish it from the word "be") already cover a
# genuine Bachelor of Engineering mention without this bare two-letter
# token's blast radius.
_FOREIGN_COURSE_WORDS = {
    "mba", "mbbs", "bds", "bams", "bhms", "bums", "bpt", "bsc", "msc", "ba",
    "bcom", "mcom", "llb", "llm", "bca", "mca", "bba", "bpharm", "dpharm",
    "bed", "med", "phd", "mvsc", "mtech", "btech",
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
    # "management" alone is in _FOREIGN_COURSE_WORDS for a business-management
    # degree ("do you offer a management course?"), but "Management Quota" is
    # this university's OWN admission-category term - every one of the three
    # programmes' own prospectuses uses it constantly (private-college seats
    # filled outside the state merit list, as opposed to "University Quota").
    # Reproduced live, twice, with two different disambiguating words: "Do I
    # need NEET even if I'm taking management quota?" and "I have low NEET
    # marks, can I take management seat?" - both squarely in-scope MAFSU
    # admission questions, both refused with "I only cover admissions for...
    # " because "management" alone was enough to trigger the foreign-course
    # match. First fix only checked for "quota"; a student is at least as
    # likely to say "seat"/"seats" for the exact same concept, so any of this
    # admission-vocabulary set nearby is enough to disambiguate - nobody asks
    # about a "management seat" or "management quota" wanting a business
    # degree.
    _MGMT_QUOTA_DISAMBIGUATORS = {"quota", "seat", "seats"}
    foreign_words = (_FOREIGN_COURSE_WORDS - {"management"}
                      if words & _MGMT_QUOTA_DISAMBIGUATORS else _FOREIGN_COURSE_WORDS)
    if words & foreign_words:
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
