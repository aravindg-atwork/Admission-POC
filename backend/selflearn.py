"""Pattern detection over data already on disk (flagged dislikes,
review-log validation events) - no ML weight-learning, no fine-tuning,
genuinely out of scope for a pure-Python, no-training-infra system. What's
achievable: the same deterministic-keyword-rule philosophy every other
module in this codebase already uses (programs.py, intent.py, faq.py's
discriminators), applied to counting rather than routing.

Two tiers, deliberately unequal in how much trust they get:

  SAFE_TO_AUTOMATE - exactly one category: adding a synonym WORD to an
  EXISTING faq.py discriminator canonical (see faq.add_learned_discriminator's
  own docstring for the full one-directional-error argument). Even here,
  this module surfaces the PATTERN (which groups collided, how often) - it
  deliberately does NOT auto-extract which specific word to add via a
  guessing heuristic, since a wrong-but-plausible-looking word is exactly
  the kind of subtle error this whole codebase tries to design out. A human
  (or a future dedicated tool) reads the surfaced evidence and supplies the
  actual word to faq.add_learned_discriminator.

  PROPOSE_ONLY - everything else: new discriminator groups, program aliases,
  comparison/complexity triggers, NRI-caveat signals, any system-prompt
  wording. Misrouting a PROGRAM risks answering confidently from the wrong
  prospectus entirely - categorically higher-stakes than an FAQ-cache miss,
  and not an asymmetry that favors caution the way the discriminator case
  does. These are templated (not LLM-phrased - no reason to spend a call on
  text only an admin reads) and written to a project's suggestions.json for
  manual review; nothing here ever auto-edits a .py file.
"""

import time

from .faq import _discriminators

SAFE_TO_AUTOMATE = "safe_to_automate"
PROPOSE_ONLY = "propose_only"


def detect_recurring_patterns(flagged_entries, window_days=None, min_occurrences=None):
    """Groups flagged entries by their discriminator-group SIGNATURE (which
    groups/canonicals their question touched) within a rolling window, and
    surfaces any signature repeating at least min_occurrences times. Pure
    counting - zero LLM calls, zero network calls.

    Returns a list of {signature, count, entries} - `entries` keeps the
    original flagged records (question/answer text and all) so a human
    reviewing the pattern has real evidence to look at, not just a count.
    """
    from . import config

    window_days = window_days if window_days is not None else config.PATTERN_WINDOW_DAYS
    min_occurrences = min_occurrences if min_occurrences is not None else config.PATTERN_MIN_OCCURRENCES
    cutoff = time.time() - window_days * 86400

    buckets = {}
    for entry in flagged_entries:
        if entry.get("flagged_at", 0) < cutoff:
            continue
        _, groups = _discriminators(entry.get("question", ""))
        if not groups:
            continue
        # A tuple of (group, sorted canonicals) pairs - stable, hashable,
        # and readable directly in the admin UI without decoding anything.
        signature = tuple(sorted((g, tuple(sorted(v))) for g, v in groups.items()))
        buckets.setdefault(signature, []).append(entry)

    patterns = []
    for signature, entries in buckets.items():
        if len(entries) >= min_occurrences:
            patterns.append({"signature": signature, "count": len(entries), "entries": entries})
    patterns.sort(key=lambda p: -p["count"])
    return patterns


def classify(pattern):
    """SAFE_TO_AUTOMATE when every group in the pattern's signature is
    already a key in faq._CONTRAST_FORMS (an EXISTING discriminator group -
    "feetype", "category", "when", "bound", "asks_about", "necessity", or
    any future one) - meaning the fix this pattern points at is "this
    EXISTING group needs one more synonym word", which
    faq.add_learned_discriminator is scoped to and which can only ever
    make the cache MORE conservative regardless of which group it is (see
    that function's own docstring for the full one-directional argument -
    the safety property is uniform across groups, not specific to any one
    of them).

    detect_recurring_patterns above can only ever produce signatures built
    from faq._discriminators()'s own output, which by construction can
    only ever reference a group/canonical that already exists in
    _CONTRAST_FORMS - there is no code path today that surfaces "this
    should be a brand-new group" as a pattern. So this branch is currently
    always taken for patterns from THIS detector; the PROPOSE_ONLY branch
    exists for forward-compatibility with a different kind of detector
    (e.g. one surfacing program-level misrouting patterns from
    programs.py/reviewlog data instead of faq.py's discriminators), which
    is genuinely higher-stakes (see the module docstring) and does not
    exist yet.
    """
    from .faq import _CONTRAST_FORMS

    known_groups = set(_CONTRAST_FORMS)
    groups_touched = {g for g, _ in pattern["signature"]}
    if groups_touched and groups_touched <= known_groups:
        return SAFE_TO_AUTOMATE
    return PROPOSE_ONLY


def propose(pattern):
    """A templated (not LLM-generated), human-readable suggestion plus the
    evidence behind it - written by the caller to a project's
    suggestions.json (see projects.suggestions_path). Never auto-applied;
    "Apply" in the admin console means an admin edits the named source file
    by hand.
    """
    groups_desc = ", ".join(f"{g}={list(v)}" for g, v in pattern["signature"])
    return {
        "kind": "recurring_flag_pattern",
        "summary": (f"{pattern['count']} flagged answers in the last window share the "
                    f"discriminator signature [{groups_desc}] - worth checking whether "
                    "this is a genuine cache/routing gap (see faq.py's _CONTRAST_FORMS "
                    "or programs.py's aliases, depending on which module actually owns "
                    "this dimension)."),
        "signature": list(pattern["signature"]),
        "count": pattern["count"],
        "sample_questions": [e.get("question", "") for e in pattern["entries"][:5]],
        "proposed_at": time.time(),
    }


def apply_safe(group, canonical, word, pattern):
    """Applies a human-confirmed synonym addition for a SAFE_TO_AUTOMATE
    pattern - thin wrapper over faq.add_learned_discriminator that also
    shapes the evidence string from the pattern, so every overlay entry's
    audit trail reads the same way regardless of caller.
    """
    from .faq import add_learned_discriminator

    evidence = f"{pattern['count']} flagged entries sharing signature {pattern['signature']}"
    return add_learned_discriminator(group, canonical, word, evidence=evidence)
