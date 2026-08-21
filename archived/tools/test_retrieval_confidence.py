"""Regression coverage for the 2026-08-20 retrieval-confidence gate and
chain-of-thought split (rag/helpers.py's retrieval_is_confident/
split_reasoning, wired into answer.py's _pipeline and orchestrator.py's
answer_complex).

Pure logic, no backend needed - same style as tools/test_comparison_
retry.py and tools/test_programme_typo_tolerance.py. retrieval_is_confident
takes plain dicts (what vectorstore.search returns), so no embedding
service or network call is involved; split_reasoning is pure string
parsing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.rag.helpers import retrieval_is_confident, split_reasoning  # noqa: E402

results = []


def check(label, ok):
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    results.append(ok)


# --- retrieval_is_confident ------------------------------------------------

floor = config.RETRIEVAL_CONFIDENCE_FLOOR

check("empty top is never confident",
      retrieval_is_confident([]) is False)

check("top score clearly above the floor is confident",
      retrieval_is_confident([{"score": floor + 0.2}, {"score": 0.1}]) is True)

check("top score clearly below the floor is not confident",
      retrieval_is_confident([{"score": floor - 0.2}, {"score": 0.01}]) is False)

check("top score exactly AT the floor counts as confident (>=, not >)",
      retrieval_is_confident([{"score": floor}]) is True)

check("only the #1-ranked entry matters - a low top score isn't rescued "
      "by a high score further down the list",
      retrieval_is_confident([{"score": floor - 0.01}, {"score": 0.99}]) is False)

check("a missing 'score' key degrades to 0, not a crash",
      retrieval_is_confident([{"text": "no score field"}]) is False)


# --- split_reasoning --------------------------------------------------------

check("empty text passes through unchanged",
      split_reasoning("") == ("", None))

check("no marker at all - whole text is the answer, reasoning is None",
      split_reasoning("Just a plain answer with no marker.")
      == ("Just a plain answer with no marker.", None))

check("well-formed marker splits reasoning from the real answer",
      split_reasoning(
          "The excerpts cover the fee fully.\n---REPLY---\nThe fee is Rs. 5000.")
      == ("The fee is Rs. 5000.", "The excerpts cover the fee fully."))

check("marker is case-insensitive and tolerates extra dashes/spacing",
      split_reasoning("Looks complete.\n-----reply-----\nHere is the answer.")
      == ("Here is the answer.", "Looks complete."))

check("marker with nothing after it falls back to the whole text as the "
      "answer (fail-open, never serve an empty reply)",
      split_reasoning("Some reasoning text ---REPLY---   ")
      == ("Some reasoning text ---REPLY---   ", None))

check("a genuine answer that happens to contain the word 'reply' (not the "
      "marker shape) is left alone",
      split_reasoning("You can reply to the offer letter within 7 days.")
      == ("You can reply to the offer letter within 7 days.", None))

check("no reasoning text before the marker still yields a clean split "
      "with reasoning=None rather than an empty string",
      split_reasoning("---REPLY---\nJust the answer.")
      == ("Just the answer.", None))


print()
if all(results):
    print(f"ALL {len(results)} RETRIEVAL-CONFIDENCE/REASONING CHECKS PASSED")
else:
    print(f"{sum(results)}/{len(results)} PASSED - see FAIL lines above")
    sys.exit(1)
