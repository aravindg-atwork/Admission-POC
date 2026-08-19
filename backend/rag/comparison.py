"""Cross-program comparison answers - _answer_comparison, moved unchanged
from rag.py during the 2026-08-13 re-architecture (see rag/guards.py's
_comparison_guard, the only caller). Fans retrieval out across several
programs' own projects and answers all of them in one labeled generation
call rather than one call per program - see the module-level comment on
_COMPARISON_TOP_K_PER_PROGRAM and _answer_comparison's own docstring for
why.
"""

import itertools
import re

from .. import config
from ..core import textclean
from ..prompts.system import _COMPARISON_SYSTEM_PROMPT
from ..generation import embeddings, llm
from ..storage import faq, projects, reviewlog, vectorstore
from . import provenance, validate
from .helpers import (_add_nri_scope_caveat, _apply_script_pref, _build_retrieval_text,
                       _compact_readings, _program_name)


# Retrieval chunks per program in a comparison answer, smaller than
# config.TOP_K (15): that number was tuned for ONE program's context filling
# the whole prompt, but a comparison question pulls from several programs at
# once, and 15 chunks x 3 programs would both blow up prompt size and drown
# the model in cross-program noise right in the one answer path where
# staying on the correct program per fact matters most. Started at 6, raised
# to 10 after live-testing found 6 missed B.V.Sc.'s own eligibility page
# (page 3) on "which courses can I apply for" - confirmed directly against
# vectorstore.search that K=6 excluded it while K=10 included it, for the
# exact same query.
#
# Raised 10 -> 14 on 2026-08-17, alongside _dedupe_chunks above (not instead
# of it - the two fix different things). Dedup solved a program whose top-10
# was mostly near-identical repeats of ONE fact; it does not help a program
# whose data is genuinely WIDE rather than repetitive - confirmed directly
# that even the deduped top-10 for B.Tech Dairy's hostel fees, which spans
# five distinct college/room-type combinations, still didn't include a
# single one of them for "What are the hostel fees?", while the same
# programme's own single-project TOP_K=15 query found all five. 14 (not the
# full 15) keeps a little headroom below the single-program budget, since a
# comparison prompt is already three programs' worth of context in one call.
_COMPARISON_TOP_K_PER_PROGRAM = 14

# Found 2026-08-12: "I studied PCM. Which MAFSU courses can I apply for?"
# against B.V.Sc.'s own store never surfaced its eligibility chunk ("minimum
# 50% marks in Physics, Chemistry, Biology...") even at K=25 - confirmed
# directly via vectorstore.search - because that chunk's actual wording has
# almost no term/semantic overlap with "PCM" (B.V.Sc. requires Biology, not
# Math, so a PCM query is nearly the opposite of what the chunk says). The
# model then truthfully reported "the document doesn't specify" from a
# context that genuinely never contained the fact - not a hallucination, a
# retrieval miss. Raising K further doesn't fix it (this is a term-overlap
# problem, not a rank-cutoff problem); appending generic eligibility
# vocabulary to the retrieval query does - confirmed live: the same chunk
# jumped to rank 2 once "eligibility criteria required subjects Physics
# Chemistry Biology Mathematics English percentage marks" was appended.
# Gated narrowly (only when the question already looks eligibility/subject-
# stream-shaped) so an unrelated comparison question (fees, hostels) isn't
# diluted with irrelevant boost terms it doesn't need.
_SUBJECT_STREAM_MARKERS = {
    "pcb", "pcm", "pcmb", "pcbm", "biology", "mathematics", "physics",
    "chemistry", "stream", "eligible", "eligibility", "criteria", "marks",
    "neet", "aieea", "cgpa",
}
# "difference in admission process" (E22) is broad enough to touch subjects
# without naming any - the answer for that exact phrasing swapped B.F.Sc.'s
# real requirement (Biology) for B.Tech Dairy's (Mathematics) and then
# self-contradicted two sentences later, because the actual eligibility
# chunk ranked outside the top 10 with no boost. A literal phrase check
# rather than adding "admission"/"process" to the marker set above - both
# words alone are too generic (appear in plenty of comparison questions
# that genuinely have nothing to do with subject eligibility, e.g. a fee or
# date comparison) and would dilute retrieval there for no benefit.
_ADMISSION_PROCESS_PHRASE = "admission process"
_ELIGIBILITY_RETRIEVAL_BOOST = (
    " eligibility criteria required subjects Physics Chemistry Biology "
    "Biotechnology Mathematics English percentage marks qualifying examination"
)

# A compound question ("what is the fee, and also am I eligible with 55% in
# PCM, and also is hostel compulsory?") embedded as ONE blended query
# dilutes similarity for each sub-topic individually - reproduced live
# 2026-08-19: that exact question never surfaced B.V.Sc.'s own fee chunk at
# all under a single blended embedding, even though the identical fee
# question asked alone retrieves it cleanly. Deliberately narrow - matches
# the connective phrases a compound admission question actually uses in
# practice, not a general clause-boundary parser (this codebase's
# established style throughout, see programs.py's alias-collision
# comments for the same "narrow pattern, extend later if a new case turns
# up" reasoning).
_COMPOUND_CONNECTIVE_RE = re.compile(r"\band\s+also\b|\bas\s+well\s+as\b", re.I)


def _split_compound_query(text):
    """Split a compound, multi-topic question into its component
    sub-questions for RETRIEVAL purposes only - the generation prompt
    still receives the original, unmodified question text; only WHICH
    chunks get retrieved changes. Returns [text] unchanged (a single
    "sub-question") when no connective is found, so every caller can
    treat the single- and multi-topic cases identically.
    """
    parts = [p.strip() for p in _COMPOUND_CONNECTIVE_RE.split(text) if p and p.strip()]
    return parts if len(parts) > 1 else [text]

# Found 2026-08-17: "whats the admission fees" against B.Tech. (Dairy
# Technology)'s own store filled 8 of the 10 slots with near-identical
# repeats of the SAME unreserved-fee sentence (OCR-chunked with overlapping
# windows across pages 40/43), crowding out the DIFFERENT reserved-category
# figure sitting at rank 14 - confirmed directly via vectorstore.search.
# The model then stated the reserved figure without it being in context,
# provenance.check flagged it unsourced, and redact() removed the WHOLE
# B.Tech Dairy segment - including the correctly-grounded unreserved figure,
# which WAS in the 10 chunks the whole time. Not a rank-cutoff problem
# (raising K just adds more of the same repeated sentence) and not a
# term-overlap problem (unlike the PCM case above) - it's wasted slots.
# Pulls a wider candidate pool and drops near-duplicates before trimming to
# _COMPARISON_TOP_K_PER_PROGRAM, so repeats stop crowding out genuinely
# different content without raising the prompt size any query pays for.
#
# Similarity, not exact match: confirmed directly that the repeated chunks
# above are NOT byte-identical - OCR rendered the same header two ways
# ("matsu" vs "matsui", a one-character site-name difference, plus varying
# leading whitespace) ahead of the otherwise-identical fee sentence, which
# shifts everything after it far enough that a prefix or exact-string key
# missed every single one of them. Token-set overlap (Jaccard) shrugs off a
# one-word header difference the way an exact-match key cannot.
_DEDUPE_POOL_MULTIPLIER = 3
_DEDUPE_SIMILARITY = 0.8


def _token_set(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _dedupe_chunks(chunks, keep):
    """First `keep` chunks, skipping any whose text is a near-duplicate
    (Jaccard token overlap above _DEDUPE_SIMILARITY) of one already kept -
    see the comment above. Preserves the incoming score-sorted order -
    vectorstore.search already returns highest first. O(keep * pool), fine
    at these sizes (a few dozen chunks at most per program).
    """
    kept_tokens = []
    out = []
    for entry in chunks:
        tokens = _token_set(entry.get("text", ""))
        if tokens and any(
            len(tokens & prior) / len(tokens | prior) >= _DEDUPE_SIMILARITY
            for prior in kept_tokens
        ):
            continue
        kept_tokens.append(tokens)
        out.append(entry)
        if len(out) >= keep:
            break
    return out


def _retrieve_top(store, query_vector, retrieval_text, k):
    """Wider pool than the final k, deduped down - the single-query-vector
    half of what _answer_comparison's per-programme retrieval loop already
    did, extracted so _split_compound_query's multi-sub-query case can call
    it once per sub-query and merge (see that call site).
    """
    pool = vectorstore.search(store, query_vector, k * _DEDUPE_POOL_MULTIPLIER, retrieval_text)
    return _dedupe_chunks(pool, k)


def _retrieve_top_multi(store, sub_queries, k):
    """Retrieve for EACH sub-query separately (own embedding, own pool),
    then merge round-robin - one chunk from sub-query 1, one from sub-query
    2, and so on - rather than concatenating and re-ranking by raw
    similarity to any single sub-query. Round-robin guarantees every
    sub-topic gets SOME representation; a merge-then-rank-by-score would
    let whichever sub-topic's chunks happen to score highest overall crowd
    out the others, which is exactly the dilution problem this exists to
    fix, just moved one step later. A per-sub-query share of k (never
    below 4) keeps the total prompt size close to what a single-query
    comparison already pays, rather than growing with the number of
    sub-questions asked.

    The final _dedupe_chunks pass (content/Jaccard-based, not identity-
    based) is what actually removes a chunk two sub-queries both surfaced -
    vectorstore.search returns a fresh COPY of each entry on every call
    (see its own comment - attached scores must never mutate the shared
    cached store), so two calls never return the SAME object even for the
    identical underlying chunk; only a content comparison catches that.

    `sub_queries` is [(query_vector, retrieval_text), ...].
    """
    share = max(4, k // len(sub_queries))
    per_query_lists = [_retrieve_top(store, qv, rt, share) for qv, rt in sub_queries]
    merged = [entry for group in itertools.zip_longest(*per_query_lists)
              for entry in group if entry is not None]
    return _dedupe_chunks(merged, k)


# Found 2026-08-18 via direct trace inspection: a "compare NRI fees" question
# retrieved THREE separate, structurally near-identical fee tables for B.V.Sc.
# alone - Annexure-IV "FEE STRUCTURE (Constituent Veterinary Colleges)",
# Annexure-V "FEE STRUCTURE: University Quota (...Private Veterinary
# Colleges)", Annexure-VI "FEE STRUCTURE: Management Quota (...Private
# Veterinary Colleges)" - each with its OWN, DIFFERENT figures (private
# college fees run higher than constituent/government college fees). The
# model quoted the SAME numbers under all three category labels instead of
# reading each table separately; provenance.check_labels correctly caught it
# (see _answer_comparison's provenance block) and it was redacted rather than
# served wrong - but redaction is cleanup, not prevention. B.F.Sc. and
# B.Tech. Dairy each have only ONE fee table, so this is a B.V.Sc.-shaped
# problem specifically, not something to special-case broadly.
# Anchored to a markdown heading LINE (optional #/* markers at line start),
# not a bare substring match - "FEE STRUCTURE" also appears mid-sentence in
# ordinary prose ("the University reserves the right to increase the fee
# structure at any time..."), which a substring match wrongly counted as a
# distinct table category. A real table heading is on its own line.
_FEE_STRUCTURE_RE = re.compile(
    r"(?im)^[#*\s]{0,8}FEE STRUCTURE\s*[:\-–]?\s*\(?([A-Za-z][A-Za-z /\-]{3,60})")


def _fee_table_categories(chunks):
    """Distinct fee-table category labels found across one programme's own
    retrieved chunks - empty or a single label means nothing to warn about;
    two or more means the prompt should tell the model explicitly that these
    are separate tables with separate figures, rather than leaving it to
    notice three near-identically-formatted tables on its own.
    """
    labels = set()
    for chunk in chunks:
        for match in _FEE_STRUCTURE_RE.finditer(chunk.get("text", "")):
            label = match.group(1).strip().rstrip(")").strip()
            if label:
                labels.add(label)
    return labels


def _flagged_problems(unsourced, mislabelled):
    """Flatten provenance.check()/check_labels()'s {pid: [numbers]} results
    into the actual set of flagged (kind, pid, number) problems - used by
    _answer_comparison's retry-acceptance check below, hoisted to module
    level (rather than left as a local closure) so it can be unit-tested
    directly - see tools/test_comparison_retry.py.

    Module level, not a method: comparing dicts by `len()` counts
    programme-KEYS with at least one problem, not the number of actual
    flagged numbers - see the call site's comment for the bug this exists
    to fix. The right unit to compare on is the individual problem, which
    this makes an actual Python set so `<` (strict subset) does the
    comparison correctly.
    """
    return ({("unsourced", pid, n) for pid, nums in unsourced.items() for n in nums}
            | {("mislabel", pid, n) for pid, nums in mislabelled.items() for n in nums})


def _answer_comparison(target_programs, question, script_pref, ui_language,
                        language, hint_language, hint, typed_romanized, cloud_ok, trace=None):
    """Answer a question that spans several programs by retrieving from each
    one's own project and handing the model all of them at once, clearly
    labeled, in a single generation call - see programs.needs_comparison and
    _COMPARISON_SYSTEM_PROMPT for why this exists and what it guards against.

    Deliberately NOT FAQ-cached: a cached comparison entry would need a cache
    keyed on the exact SET of target programs (not just the question text),
    which the existing per-project faq.py has no notion of - out of scope for
    now, so every comparison question pays a fresh generation call. Worth
    revisiting if comparison questions turn out to be common enough that the
    quota cost matters.
    """
    trace = trace or (lambda *a, **k: None)  # optional: callers outside the guard-stage need no trace
    # See _ELIGIBILITY_RETRIEVAL_BOOST's comment above _COMPARISON_TOP_K_PER_PROGRAM:
    # re-embeds the boosted text (not just a keyword hint) because cosine
    # similarity against query_vector is the dominant ranking signal here -
    # a query_text-only nudge is far too weak to pull a near-zero-overlap
    # chunk (a program's OWN required subjects, when the student named a
    # DIFFERENT combination) into the top-K.
    #
    # One (query_vector, retrieval_text) pair per detected sub-question
    # (see _split_compound_query) - each gets its OWN eligibility boost
    # check rather than one applied to the whole compound text, so a
    # boost relevant to sub-question 2 doesn't get diluted across
    # sub-question 1's genuinely different embedding.
    sub_queries = []
    for sub_text in _split_compound_query(question):
        embed_text = sub_text
        if (set(faq._words(sub_text)) & _SUBJECT_STREAM_MARKERS
                or _ADMISSION_PROCESS_PHRASE in sub_text.lower()):
            embed_text = sub_text + _ELIGIBILITY_RETRIEVAL_BOOST
        sub_queries.append((embeddings.embed_query(embed_text),
                             _build_retrieval_text(embed_text, language, hint_language, ui_language)))

    sections = []
    included = []
    all_pages = set()
    all_chunks = []
    # Kept per-program, not just concatenated into `context` below, so the
    # provenance check after generation can verify each figure against the
    # program it was actually attributed to - see provenance.py for the
    # cross-program fee leak this exists to catch.
    program_contexts = {}
    for pid in target_programs:
        store = vectorstore.load(projects.store_path(pid))
        if not store:
            continue
        # A single sub-query takes the plain path (identical behaviour to
        # before _split_compound_query existed); 2+ sub-queries merge
        # round-robin - see _retrieve_top_multi.
        if len(sub_queries) > 1:
            top = _retrieve_top_multi(store, sub_queries, _COMPARISON_TOP_K_PER_PROGRAM)
        else:
            qv, rt = sub_queries[0]
            top = _retrieve_top(store, qv, rt, _COMPARISON_TOP_K_PER_PROGRAM)
        if not top:
            continue
        included.append(pid)
        all_pages.update(e["page"] for e in top)
        all_chunks.extend(top)
        excerpt_text = "\n\n".join(_compact_readings(e["text"]) for e in top)
        categories = _fee_table_categories(top)
        if len(categories) > 1:
            excerpt_text = (
                f"(NOTE: the excerpts below contain {len(categories)} SEPARATE fee-structure "
                f"tables for {_program_name(pid)} - {', '.join(sorted(categories))}. Each has "
                "its OWN figures; do not reuse one table's numbers for a different category. "
                "State each fee under the specific category its own table names, and if the "
                "excerpts don't give a figure for a category, say so rather than guessing.)\n\n"
            ) + excerpt_text
        sections.append(f"=== {_program_name(pid)} ===\n{excerpt_text}")
        program_contexts[pid] = excerpt_text

    trace("retrieval", topK=_COMPARISON_TOP_K_PER_PROGRAM, includedPrograms=included,
          chunks=[{"page": e.get("page"), "score": e.get("score"), "snippet": e["text"][:160]}
                  for e in all_chunks])

    if not sections:
        # None of the target programs have a prospectus ingested yet - same
        # honest "nothing to answer from" handling as _answer's no-context
        # case, just phrased for a comparison question.
        no_data_prompt = (
            "There are NO prospectus excerpts available for any of the programs "
            "this question is about - none have been uploaded yet. Do not answer "
            "using any outside knowledge or make up specifics. Instead, warmly "
            "and briefly tell the student the prospectuses aren't loaded yet.\n\n"
            "Question: " + question + hint
        )
        reply, model = llm.generate(_COMPARISON_SYSTEM_PROMPT, no_data_prompt, question, allow_cloud=cloud_ok)
        reply = textclean.clean_for_display(reply)
        display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
        trace("final_answer", answer=display, source="no-context", model=model,
              pages=[], speakable=speakable, language=language)
        return {"answer": display, "pages": [], "model": model, "language": language,
                "source": "no-context", "speakable": speakable, "comparedPrograms": []}

    context = "\n\n".join(sections)
    page_reminder = (
        "\n\n(Reminder: answer this fully yourself using the excerpts above for "
        "each program - do NOT tell the student to go check a page number "
        "themselves, and do not mention page numbers at all.)"
    )
    user_prompt = "Prospectus excerpts:\n" + context + "\n\nQuestion: " + question + hint + page_reminder
    reply, model = llm.generate(_COMPARISON_SYSTEM_PROMPT, user_prompt, question, allow_cloud=cloud_ok)
    trace("generation", model=model, promptId="comparison_system_prompt")
    reply = textclean.clean_for_display(reply)
    reply = validate.autofix(reply)

    # Cross-program provenance: every figure stated under a program must come
    # from THAT program's own excerpts. validate's own number check runs
    # against the whole combined context, so a figure borrowed from a sibling
    # program passes it - see provenance.py for the real Ph.D. fee case this
    # was built for. One targeted regeneration naming the exact offending
    # numbers; if the retry still can't source them, the honest fallback is
    # to say so per program rather than serve a confident wrong figure.
    program_names = {pid: _program_name(pid) for pid in included}
    offenders = provenance.check(reply, program_contexts, program_names)
    # Two distinct failures, checked together: a figure borrowed from another
    # program (check) and a figure that is this program's own but described
    # as the wrong thing (check_labels). The real Ph.D. answer had one of
    # each - 25,110 borrowed from M.V.Sc., and 30,310 (its reservation fee)
    # reported as its unreserved fee. Catching only the first would still
    # have left a student with a fee understated by 38,550 rupees.
    label_offenders = provenance.check_labels(reply, program_contexts, program_names)
    if offenders or label_offenders:
        trace("provenance", stage="first_pass", offenders=offenders,
              labelOffenders=label_offenders)
        retry_prompt = user_prompt
        if offenders:
            retry_prompt += provenance.instruction(offenders, program_names)
        if label_offenders:
            retry_prompt += provenance.label_instruction(label_offenders, program_names)
        retried = llm.generate(_COMPARISON_SYSTEM_PROMPT, retry_prompt, question,
                               allow_cloud=cloud_ok)
        if retried:
            candidate = validate.autofix(textclean.clean_for_display(retried[0]))
            still = provenance.check(candidate, program_contexts, program_names)
            still_labels = provenance.check_labels(candidate, program_contexts, program_names)
            trace("provenance", stage="after_regeneration", offenders=still,
                  labelOffenders=still_labels)
            # Only accept the retry if it is strictly better - a
            # regeneration that fixes a borrowed figure by mislabelling a
            # real one has not improved anything, and the original at least
            # was not generated with a correction bolted onto its prompt.
            # "Strictly better" means the AFTER set of flagged problems is a
            # strict subset of the BEFORE set (see _flagged_problems): every
            # problem still present already existed (no new one introduced -
            # the "not a lateral trade" guarantee this always had), and at
            # least one original problem is now actually gone. Comparing
            # dict LENGTHS instead (as this used to) undercounts by
            # programme rather than by number - a programme with 3
            # unsourced numbers reduced to 1 by the retry still reads as
            # "1" before and "1" after, so an objectively-fixed problem got
            # rejected as "no improvement". Reproduced directly.
            before_flagged = _flagged_problems(offenders, label_offenders)
            after_flagged = _flagged_problems(still, still_labels)
            if after_flagged < before_flagged:
                reply, model = candidate, retried[1]
                offenders, label_offenders = still, still_labels
        if offenders or label_offenders:
            reasons = [f"{program_names.get(pid, pid)}: unsourced {', '.join(nums)}"
                       for pid, nums in offenders.items()]
            reasons += [f"{program_names.get(pid, pid)}: mislabelled {', '.join(nums)}"
                        for pid, nums in label_offenders.items()]
            reviewlog.append(projects.review_log_path(target_programs[0]), {
                "kind": "provenance_unsourced_number",
                "reasons": reasons,
                "source": "comparison",
            })
            # Detection alone is not a fix. Before this, a figure the check
            # had ALREADY identified as unsourced was still served whenever
            # the regeneration failed to improve on it - observed serving a
            # Ph.D. admission fee of Rs. 30,310 against a real Rs. 68,860,
            # with the offence dutifully written to the review log nobody
            # reads in time. The only safe end state for a number we cannot
            # source is not to state it.
            bad_pids = set(offenders) | set(label_offenders)
            reply = provenance.redact(reply, bad_pids, program_names)
            trace("provenance", stage="redacted", programs=sorted(bad_pids))

    reply = _add_nri_scope_caveat(question, all_chunks, reply)

    if config.VALIDATION_ENABLED:
        if language == "latin" and not typed_romanized:
            nri_postprocess = lambda r: _add_nri_scope_caveat(question, all_chunks, r)  # noqa: E731
            reply, model, reasons, regenerated = validate.check_and_regenerate(
                question, context, reply, model, _COMPARISON_SYSTEM_PROMPT, user_prompt,
                postprocess=nri_postprocess)
        else:
            reasons = validate.deterministic_checks(question, context, reply)
            regenerated = False
        trace("validation", reasons=reasons, regenerated=regenerated)
        if reasons:
            # A comparison spans several projects at once - log against each
            # one included, since the same reviewer/admin bar applies to any
            # of them the flagged answer touched.
            for pid in included:
                reviewlog.append(projects.review_log_path(pid), {
                    "kind": "validation_regenerated" if regenerated else "validation_flag",
                    "reasons": reasons, "source": "comparison",
                })

    display, speakable = _apply_script_pref(reply, language, script_pref, typed_romanized)
    trace("final_answer", answer=display, source="comparison", model=model,
          pages=sorted(all_pages), speakable=speakable, language=language)
    return {"answer": display, "pages": sorted(all_pages), "model": model, "language": language,
            "source": "comparison", "speakable": speakable,
            "comparedPrograms": [{"projectId": pid, "label": _program_name(pid)} for pid in included]}

