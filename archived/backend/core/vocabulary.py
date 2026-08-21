"""Student vocabulary -> prospectus vocabulary, for the lexical half of retrieval.

The gap this closes, measured
-----------------------------
tools/eval_retrieval.py scored recall@15 = 0.86, and both misses were the same
shape: the student's words never appear in the source document.

  "What percentage is required for SC/ST/OBC candidates?"
      the prospectus says "47.50% marks in case of Reserved category" and
      never writes SC, ST or OBC anywhere near it. No lexical overlap, and
      the embedding does not bridge it either.
  "can i do dairy tech with biology"
      the prospectus says "Dairy Technology" and "Physics, Chemistry,
      Mathematics and English".

The first of those is not a hypothetical: it is the retrieval half of the Q50
failure, where the assistant answered "the guidelines do not list a separate
lower threshold for these categories" - a false rule, produced from excerpts
that genuinely did not contain the answer, because the answer was never
retrieved.

Why a term map rather than an LLM rewrite
-----------------------------------------
The failing step is lexical overlap against a fixed, small, English corpus
whose wording does not change between admission years. A model call per
question would cost a round trip on the hot path to produce, for these cases,
exactly the substitution written below. Deterministic, free, and testable
beats clever here - the same reasoning that moved eligibility verdicts out of
the model.

An LLM rewrite is still the right tool for what this cannot do: genuinely
novel phrasings, multi-hop questions, and follow-ups that need conversation
context (the router's resolved_question already covers that last one). Add it
when eval_retrieval.py shows a miss this map cannot fix, not before.

Expansion is ADDITIVE and lexical-only
--------------------------------------
Terms are appended, never substituted, so a question that was already
retrieving correctly keeps every signal it had. And the result feeds only the
keyword half of the hybrid score and the table lookup - the vector half still
embeds what the student actually typed (see helpers._build_retrieval_text),
so padding the query cannot drag the embedding off the student's meaning.
"""

import re

# Each entry: a pattern the student might type -> the words the PROSPECTUS
# uses for the same thing. Kept narrow and evidence-led; every line here
# should be traceable to a real retrieval miss or an obvious register gap,
# not to speculation about what someone might one day ask.
_TERM_MAP = (
    # Reservation categories - the entry with a measured failure behind it.
    # The prospectus states thresholds only against "Reserved category" while
    # students name their own specific category, so there was no lexical
    # overlap at all: MISS before this, rank 6 after.
    (r"\b(sc|st|obc|vj|dt|nt|sbc|sebc|ews|scheduled caste|scheduled tribe|"
     r"other backward|nomadic|backward class|caste|reservation|reserved|"
     r"quota)\b", "Reserved category candidate reservation"),
    (r"\b(open|general|unreserved|ur)\s+(category|candidate|student)?\b",
     "Unreserved category"),

    # Programme names as students shorten them - "dairy tech" and "vet" appear
    # nowhere in the source documents.
    (r"\b(vet|veterinary|bvsc|b\.?v\.?sc)\b",
     "Veterinary Science and Animal Husbandry"),
    (r"\b(dairy\s*tech\w*|btech\s*dairy|b\.?tech)\b", "Dairy Technology"),
    (r"\b(fishery|fisheries|fish|bfsc|b\.?f\.?sc)\b", "Fishery Science"),

    # Qualifying exam, written a dozen ways.
    (r"\b(12th|12 th|twelfth|xii|hsc|plus two|\+2|10\+2|higher secondary)\b",
     "XII Std 10+2 qualifying examination"),
    (r"\b(marks?|score|percentage|percent|cut ?off|aggregate)\b",
     "minimum marks percentage"),

    # Entrance exams.
    (r"\b(cet|mht ?cet|mhtcet|entrance|entrance exam)\b",
     "MHT-CET Common Entrance Test"),
    (r"\bneet\b", "NEET-UG"),

    # Recurring topics whose prospectus heading differs from the spoken word.
    (r"\b(hostel|accommodation|room|mess)\b", "hostel accommodation"),
    (r"\b(fees?|cost|charges?|payment|amount)\b", "fee structure"),
    (r"\b(documents?|certificates?|papers?)\b",
     "documents certificate required"),
    (r"\b(seats?|intake|vacanc\w+)\b", "availability of seats intake"),
    (r"\b(domicile|resident|residence|maharashtra state)\b",
     "domicile residence certificate Maharashtra State"),
    (r"\b(subjects?|stream|pcb|pcm)\b", "Physics Chemistry subjects"),
)

# The breadth here was tested against a narrower, "only what a measured miss
# proves" version, on the instinct that a query expansion should be minimal.
# The measurement disagreed, and the narrow map is not what shipped:
#
#   no expansion   recall 0.86   MRR 0.652
#   this map       recall 0.93   MRR 0.649
#   narrow map     recall 0.93   MRR 0.588
#
# Both lift recall identically; the narrow one costs 0.064 MRR for nothing,
# pushing the very question it was built for from rank 6 to rank 10, because
# the terms it dropped ("reservation", "quota", "minimum marks") are what
# lifted that chunk in the first place. This map costs 0.003 MRR, which is
# noise at 14 cases.
#
# Entries still earn their place by measurement, not by theory - the rule just
# runs both ways, and "obviously too broad" was wrong here. Re-run
# tools/eval_retrieval.py before adding or removing anything.

_COMPILED = tuple((re.compile(pattern, re.IGNORECASE), addition)
                  for pattern, addition in _TERM_MAP)


def expansion_terms(text):
    """Prospectus wording implied by this question, as a list of phrases.

    Deduplicated and order-stable so the same question always produces the
    same retrieval text - a query expansion that varies run to run would make
    retrieval itself nondeterministic, which is the opposite of the point.
    """
    if not text:
        return []
    found = []
    for pattern, addition in _COMPILED:
        if pattern.search(text) and addition not in found:
            found.append(addition)
    return found


def expand(text):
    """`text` plus the prospectus wording it implies, for lexical matching."""
    terms = expansion_terms(text)
    return f"{text} {' '.join(terms)}" if terms else text
