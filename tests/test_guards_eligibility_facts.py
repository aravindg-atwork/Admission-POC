"""The verdict is handed to the model as a decided fact, not as numbers.

`_eligibility_facts` is the seam between the deterministic verdict and the
model that phrases it. It branches on `reason`, and every branch reads fields
only some verdicts carry — so a new verdict reason that nobody taught it about
raises KeyError on a live request rather than at import.

No network, no keys — the formatter is a pure function.
"""

import unittest

from backend.core import eligibility
from backend.rag import guards


class EveryVerdictCanBePhrased(unittest.TestCase):
    """Guards against the KeyError: each reason evaluate() can return must
    have a branch here.
    """

    def _facts_for(self, project_id, text):
        result = eligibility.evaluate(project_id, text)
        self.assertIn(result["verdict"], ("eligible", "not_eligible"),
                      f"{text!r} did not produce a verdict")
        return guards._eligibility_facts(result), result

    def test_entrance_exam_refusal(self):
        facts, _ = self._facts_for("bfsc", "I didn't appear for MHT-CET")
        self.assertIn("MHT-CET 2026", facts)
        self.assertIn("NOT", facts)

    def test_subjects_refusal(self):
        facts, _ = self._facts_for("bvsc", "I studied PCM and got 90% in those subjects")
        self.assertIn("NOT", facts)

    def test_percentage_verdicts(self):
        for text in ("I have 65% in PCB and English",
                     "I have 30% in PCB and English"):
            facts, _ = self._facts_for("bvsc", text)
            self.assertIn("VERDICT", facts, text)

    def test_every_reason_evaluate_emits_is_handled(self):
        """The actual contract. If evaluate() grows a reason, this fails."""
        cases = [
            ("bfsc", "I didn't appear for MHT-CET"),
            ("bvsc", "I studied PCM and got 90% in those subjects"),
            ("bvsc", "I have 65% in PCB and English"),
            ("bvsc", "I am SC category with 48% in PCB and English"),
        ]
        for project_id, text in cases:
            with self.subTest(text=text):
                facts, _ = self._facts_for(project_id, text)
                self.assertTrue(facts.startswith("VERDICT"), text)


class EntranceExamPhrasing(unittest.TestCase):
    """Q19's answer was not a wrong figure — it was a contradiction. The
    instructions have to close the escape routes explicitly.
    """

    def setUp(self):
        result = eligibility.evaluate(
            "bfsc", "I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?")
        self.facts = guards._eligibility_facts(result)

    def test_it_demands_a_no_up_front(self):
        self.assertIn("'No'", self.facts)
        self.assertIn("first sentence", self.facts)

    def test_it_forbids_the_exact_phrase_that_went_wrong(self):
        """The eval case forbids "Yes, you can still" for this question."""
        self.assertIn("still get admission", self.facts)
        self.assertIn("Do NOT", self.facts)

    def test_it_closes_the_marks_escape_route(self):
        """Strong 12th marks are what made the model lead with "Yes"."""
        self.assertIn("marks", self.facts)

    def test_it_names_the_exam_so_the_answer_can_cite_it(self):
        self.assertIn("MHT-CET 2026", self.facts)


if __name__ == "__main__":
    unittest.main()
