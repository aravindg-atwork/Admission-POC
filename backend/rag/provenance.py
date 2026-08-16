"""Cross-program provenance check for comparison answers.

The gap this closes
-------------------
validate.deterministic_checks already catches a number that appears nowhere
in the retrieved context. That check is whole-context: for a single-program
answer the context IS that program's excerpts, so it works. For a comparison
answer the context is every target program's excerpts concatenated, so a
figure lifted from ONE program and stated under ANOTHER's heading passes
cleanly - the number really is "in the context", just not in the part that
was cited.

Found in production on 2026-08-13, exactly this shape. Asked for the
admission fee across all six programs, the answer reported:

    Ph.D. - unreserved Rs. 30,310, reservation Rs. 25,110

The Ph.D. prospectus (p.34) actually says unreserved Rs. 68,860, reservation
Rs. 30,310. So 30,310 was the RESERVATION figure promoted into the
unreserved slot, and 25,110 does not occur anywhere in the Ph.D. document at
all - it is M.V.Sc./M.Tech's reservation figure, which was sitting in the
same combined context. Five of the six programs were correct, which is what
makes this class of error dangerous: nothing about the answer looks wrong,
and a Ph.D. applicant was told their fee was 38,550 rupees lower than it is.

How it works
------------
Split the answer into per-program segments (the comparison prompt already
requires each program's part to be labeled with its name and put on its own
line), then check each segment's numbers against ONLY that program's own
excerpts. A number attributed to a program whose own document never mentions
it is unsupported, regardless of which sibling program it was borrowed from.

Deliberately deterministic - no model call. This is a containment check on a
model that has already demonstrated it will produce a fluent, plausible,
wrong figure; asking another model whether the first one was right would
reintroduce the same failure mode one level up.
"""

import re

from .validate import _extract_numbers


def _segment_by_program(reply, program_names):
    """Split `reply` into {project_id: text_about_that_program}.

    program_names is {project_id: display name}. Matching is on the display
    name's distinctive head (e.g. "B.V.Sc." from "B.V.Sc. & A.H.") because
    the model routinely shortens the full label in prose. Text before the
    first recognized program heading is dropped - it belongs to no program
    and is usually a lead-in sentence with no figures to attribute.
    """
    marks = []
    for pid, name in program_names.items():
        # First whitespace-delimited token is the discriminating part of
        # every program name here ("B.V.Sc.", "B.F.Sc.", "B.Tech.", "M.V.Sc.",
        # "Ph.D.", "M.Tech.") - the trailing qualifiers are what vary.
        head = name.split()[0]
        for match in re.finditer(re.escape(head), reply):
            marks.append((match.start(), pid))
    if not marks:
        return {}
    marks.sort()

    segments = {}
    for index, (start, pid) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(reply)
        segments[pid] = segments.get(pid, "") + " " + reply[start:end]
    return segments


def check(reply, program_contexts, program_names):
    """Numbers stated under a program that its OWN excerpts never mention.

    `program_contexts` is {project_id: that program's excerpt text}. Returns
    {project_id: sorted list of unsupported numbers}, empty when everything
    checks out. Programs with no retrieved context are skipped rather than
    reported - "we retrieved nothing for this program" is a different
    problem, already handled upstream, and flagging it here would bury the
    real cross-contamination signal in noise.
    """
    segments = _segment_by_program(reply, program_names)
    offenders = {}
    for pid, segment in segments.items():
        context = program_contexts.get(pid)
        if not context:
            continue
        unsupported = _extract_numbers(segment) - _extract_numbers(context)
        if unsupported:
            offenders[pid] = sorted(unsupported)
    return offenders


_STOP = frozenset("""
the a an is are was were for of to in on at by and or with from as it its this that
rs rupees fee fees category candidates candidate per each all both other others
you your they their there here about which what when where who how
""".split())
_WORD_RE = re.compile(r"[a-z]+")
# Tight on purpose. These labels sit right next to their number in both the
# answer and the document ("for reservation category Rs. 30310/-"), and a
# wider window simply swallows the NEIGHBOURING label too - measured: at 160
# chars the Ph.D. excerpt's "unreserved" and "reservation" both fell inside
# the same span, so a mislabelled figure looked correctly labelled.
_ANSWER_WINDOW = 50
_CONTEXT_WINDOW = 50


def _labels_near(text, number, window):
    """Significant words surrounding every occurrence of `number` in `text`."""
    words = set()
    flat = text.replace(",", "")
    for match in re.finditer(r"(?<!\d)" + re.escape(number) + r"(?!\d)", flat):
        span = flat[max(0, match.start() - window): match.end() + window].lower()
        words |= {w for w in _WORD_RE.findall(span) if w not in _STOP and len(w) > 3}
    return words


def check_labels(reply, program_contexts, program_names):
    """Numbers stated under a label their own source never associates them with.

    Catches the half of this failure that check() above cannot: a figure that
    IS in the right program's document but is being described as something
    else. Real case - the Ph.D. answer reported "Rs. 30,310 for the
    unreserved category" when 30,310 is that program's RESERVATION fee
    (unreserved is 68,860). check() passes it, because 30,310 genuinely
    occurs in the Ph.D. material; only the label is wrong, and a wrong label
    on a right number is just as expensive to a student.

    Method: take the descriptive words the ANSWER puts next to a number, and
    require at least one of them to appear next to that same number in the
    program's own excerpts. Deliberately conservative in two ways, because a
    false alarm here costs a correct answer:
      - a label word the document never uses ANYWHERE is ignored rather than
        counted as a mismatch, since the model may simply be paraphrasing
        ("marks" for "score") and this check cannot tell paraphrase from
        error;
      - a number the excerpts never contain at all is left to check(), which
        reports it more precisely.
    """
    segments = _segment_by_program(reply, program_names)
    offenders = {}
    for pid, segment in segments.items():
        context = program_contexts.get(pid)
        if not context:
            continue
        context_words = {w for w in _WORD_RE.findall(context.lower()) if w not in _STOP}
        flat_context = context.replace(",", "")
        mismatched = []
        for number in _extract_numbers(segment):
            if number not in flat_context.replace(" ", "") and number not in flat_context:
                continue  # not sourced at all - check() owns this case
            answer_labels = _labels_near(segment, number, _ANSWER_WINDOW)
            # Only judge against vocabulary the document actually uses.
            answer_labels &= context_words
            if not answer_labels:
                continue
            context_labels = _labels_near(context, number, _CONTEXT_WINDOW)
            if context_labels and not (answer_labels & context_labels):
                mismatched.append(number)
        if mismatched:
            offenders[pid] = sorted(mismatched)
    return offenders


def label_instruction(offenders, program_names):
    """Correction naming figures that are real but described wrongly."""
    lines = []
    for pid, numbers in offenders.items():
        lines.append(f"- {program_names.get(pid, pid)}: {', '.join(numbers)}")
    return (
        "\n\nSTOP. These figures appear in the right program's excerpts, but "
        "you have described them as something they are not:\n" + "\n".join(lines) + "\n"
        "Re-read the excerpt around each of those numbers and state it under "
        "the label the document itself gives it. If the excerpts do not "
        "actually say which category or which year a figure belongs to, do "
        "NOT assign it one - say plainly that the prospectus excerpt doesn't "
        "specify that figure for this program. An unlabelled gap is fine; a "
        "confident wrong label is not."
    )


# Starts with the program name, NOT "For {name}" - a segment begins AT the
# program name, so whatever introduced it ("For ", "\n- ") is still sitting
# in the reply and would be duplicated ("For For Ph.D., ...").
_REDACTION = ("{name}, this isn't clearly stated in the prospectus excerpts - "
              "please confirm it directly with the MAFSU admissions office "
              "rather than relying on a figure here.")
# A segment runs to the START of the next program's name, so it swallows that
# program's own lead-in ("... 69410. For " before "M.Tech."). Trimming back to
# the last sentence end leaves that lead-in where it belongs - without this,
# redacting one program silently decapitated the next one's sentence.
# A redacted span runs up to the NEXT programme's name, so it also swallows
# that programme's lead-in ("... Rs. 69,410.\n\nFor " before "M.Tech."). Only
# that tail is trimmed back. Sentence-boundary matching was tried first and
# was wrong here: "Rs." ends in a period, so a greedy [.!?] match stopped
# inside "Other state: Rs. 69,410" and left a bare "69,410" stranded in the
# reply - the exact artifact this is meant to remove.
_TRAILING_LEADIN_RE = re.compile(r"(?i)\s*(?:for|and|note:?)?\s*$")


def redact(reply, bad_pids, program_names):
    """Replace each named program's segment with an honest "not stated" line.

    The last resort, after a targeted regeneration has already failed to
    source or correctly label a figure. Serving the number anyway - which is
    what happened before this existed, and was observed serving a Ph.D.
    admission fee of Rs. 30,310 against a real Rs. 68,860 - is the single
    worst outcome available: the student acts on it, and nothing in the reply
    signals any doubt. Removing the whole segment rather than surgically
    deleting the number keeps the remaining sentence grammatical and, more
    importantly, avoids leaving a half-claim that reads as if it were still
    verified.

    Other programs' segments are untouched: in the real case five of six were
    correct, and throwing those away would punish the student for the
    model's failure on one.
    """
    # Span-based, not string-replace. _segment_by_program CONCATENATES every
    # occurrence of a program name into one string, so when a name appears
    # more than once (a heading plus a mention in a closing note) that
    # concatenation matches nothing in the reply and the replace either
    # no-ops or clips a fragment, stranding the rest of the figures -
    # observed as a bare "69,410" left floating after a redaction line.
    # Editing by character span, back to front so earlier offsets stay
    # valid, removes exactly the text that was measured and nothing else.
    marks = []
    for pid, name in program_names.items():
        head = name.split()[0]
        for match in re.finditer(re.escape(head), reply):
            marks.append((match.start(), pid))
    if not marks:
        return reply
    marks.sort()

    # A programme's "segment" has to actually be a segment. When a reply names
    # every programme in ONE sentence - "you can apply for B.V.Sc. & A.H.,
    # B.F.Sc. and B.Tech. (Dairy Technology)" - consecutive names sit a comma
    # apart, and replacing that span splices the caveat into the middle of the
    # list: "...for B.V.Sc. & A.H., B.F.Sc., this isn't clearly stated in the
    # prospectus excerpts - please confirm... and B.Tech. (Dairy Technology)."
    # Observed the moment general questions started fanning out across all
    # three programmes rather than arriving as per-programme comparisons.
    #
    # Below this width the text between two programme names is punctuation,
    # not a claim, so there is nothing to redact there - the caveat goes at the
    # end of the reply instead, where it still reaches the student and still
    # reads as a sentence.
    _MIN_SEGMENT_CHARS = 60

    spans = []
    trailing = []
    for index, (start, pid) in enumerate(marks):
        if pid not in bad_pids:
            continue
        end = marks[index + 1][0] if index + 1 < len(marks) else len(reply)
        if end - start < _MIN_SEGMENT_CHARS:
            name = program_names.get(pid, pid)
            if name not in trailing:
                trailing.append(name)
            continue
        # Hand back this span's tail (the next program's own lead-in, e.g.
        # "\n\nFor ") by cutting at the last sentence end or line break.
        chunk = reply[start:end]
        end = start + len(_TRAILING_LEADIN_RE.sub("", chunk))
        spans.append((start, end, pid))

    out = reply
    for start, end, pid in reversed(spans):
        out = out[:start] + _REDACTION.format(name=program_names.get(pid, pid)) + out[end:]
    for name in trailing:
        # "For " supplies the lead-in the segmented form gets from the reply
        # itself - without it the appended caveat starts mid-clause ("B.F.Sc.,
        # this isn't clearly stated...") and reads as a fragment.
        out = out.rstrip() + " For " + _REDACTION.format(name=name).strip()
    return out


def instruction(offenders, program_names):
    """A targeted correction to append to the prompt on a regeneration pass.

    Names the exact figures and the exact program each was wrongly attributed
    to, rather than repeating a general "be accurate" rule - the general rule
    was already in the prompt and did not prevent this.
    """
    lines = []
    for pid, numbers in offenders.items():
        name = program_names.get(pid, pid)
        lines.append(f"- {name}: {', '.join(numbers)}")
    return (
        "\n\nSTOP. Your previous answer stated these figures under a program "
        "whose own excerpts do not contain them:\n" + "\n".join(lines) + "\n"
        "Each of those numbers was taken from a DIFFERENT program's section. "
        "Rewrite the answer using, for each program, ONLY the numbers that "
        "appear under that program's own '===' heading. If a program's "
        "excerpts genuinely do not give the figure asked for, say plainly "
        "that its prospectus doesn't state it - never substitute another "
        "program's number, and never guess."
    )
