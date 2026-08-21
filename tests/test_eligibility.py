"""Regression tests for core/eligibility.py — deterministic verdicts.

This module exists because a language model performing a comparison mid-sentence
got four eval questions wrong in the same way. The thresholds here are
transcribed from the prospectus PDFs, so a wrong number is a wrong answer to a
student about whether they can attend university — the highest-cost failure in
the system, and until now nothing tested it offline.

Pure functions, no network, no keys.
"""

import unittest

from backend.core import eligibility


class Thresholds(unittest.TestCase):
    """The figures themselves. Transcribed from the prospectuses."""

    def test_bvsc_reserved_is_47_5_not_40(self):
        """Q13 and Q28 both gave the reserved B.V.Sc. threshold as 40%. It is
        47.50%, and 40% is the OTHER two programmes' figure — which is what
        makes the slip so easy and so plausible-looking.
        """
        self.assertEqual(eligibility.threshold("bvsc", "reserved"), 47.50)

    def test_other_programmes_reserved_is_40(self):
        self.assertEqual(eligibility.threshold("bfsc", "reserved"), 40.0)
        self.assertEqual(eligibility.threshold("btech-dairy", "reserved"), 40.0)

    def test_unreserved_is_50_everywhere(self):
        for pid in eligibility.RULES:
            self.assertEqual(eligibility.threshold(pid, "unreserved"), 50.0, pid)

    def test_unknown_programme_has_no_threshold(self):
        self.assertIsNone(eligibility.threshold("mvsc", "reserved"))

    def test_every_rule_carries_its_source_page(self):
        """Thresholds are checked against the PDFs, not the bot's own output —
        the page is how that stays possible.
        """
        for pid, rule in eligibility.RULES.items():
            self.assertIsInstance(rule["page"], int, pid)


class Extract(unittest.TestCase):
    """Pulling the student's stated facts out of their message."""

    def test_q25_attributes_each_percentage_to_its_own_scope(self):
        """Q25 stated BOTH readings in one sentence, so which number attaches
        to which scope decides the verdict. A wide window saw "PCB" next to the
        51% too and scored an aggregate as a subject mark, flipping it.
        """
        facts = eligibility.extract("I have 51% overall in 12th but only 45% in PCB and English")
        self.assertEqual(facts["overall_percent"], 51.0)
        self.assertEqual(facts["subject_percent"], 45.0)

    def test_bare_percentage_stays_unassigned(self):
        """"I got 48%" with no qualifier either side is genuinely ambiguous —
        the caller asks rather than assuming.
        """
        facts = eligibility.extract("I got 48%")
        self.assertIsNone(facts["subject_percent"])
        self.assertIsNone(facts["overall_percent"])

    def test_impossible_percentage_is_ignored(self):
        facts = eligibility.extract("I scored 150% overall")
        self.assertIsNone(facts["overall_percent"])

    def test_programme_name_is_not_a_reserved_category(self):
        """"B.V.Sc." and "B.F.Sc." both tokenize to "sc", the Scheduled Caste
        marker, so every question naming a programme looked like a reserved-
        category question.
        """
        self.assertIsNone(eligibility.extract("what is the B.V.Sc. fee")["category"])
        self.assertIsNone(eligibility.extract("B.F.Sc. eligibility")["category"])

    def test_real_category_words_are_still_detected(self):
        self.assertEqual(eligibility.extract("I am an OBC candidate")["category"], "reserved")
        self.assertEqual(eligibility.extract("I am open category")["category"], "unreserved")

    def test_pcb_shorthand_expands(self):
        self.assertTrue(
            {"physics", "chemistry", "biology"} <= eligibility.extract("I took PCB")["subjects"])

    def test_pcm_shorthand_expands(self):
        self.assertTrue(
            {"physics", "chemistry", "mathematics"} <= eligibility.extract("I took PCM")["subjects"])

    def test_a_subject_named_only_to_say_it_is_absent_does_not_count(self):
        """Counting it as studied is how "can I apply with Biology instead of
        Mathematics?" came out as satisfying a Mathematics requirement.
        """
        subjects = eligibility.extract(
            "can I apply with Biology instead of Mathematics?")["subjects"]
        self.assertIn("biology", subjects)
        self.assertNotIn("mathematics", subjects)


class SubjectVerdicts(unittest.TestCase):

    def test_biology_or_biotechnology_satisfies_the_same_slot(self):
        ok_bio, _ = eligibility.subject_verdict(
            "bvsc", {"physics", "chemistry", "biology"})
        ok_biotech, _ = eligibility.subject_verdict(
            "bvsc", {"physics", "chemistry", "biotechnology"})
        self.assertTrue(ok_bio)
        self.assertTrue(ok_biotech)

    def test_missing_english_is_not_disqualifying(self):
        """Students listing their science subjects very often just omit
        English; only a subject they'd have had to actively choose counts.
        """
        ok, missing = eligibility.subject_verdict(
            "btech-dairy", {"physics", "chemistry", "mathematics"})
        self.assertTrue(ok)
        self.assertNotIn("english", missing)

    def test_pcm_student_does_not_satisfy_bvsc(self):
        ok, missing = eligibility.subject_verdict(
            "bvsc", {"physics", "chemistry", "mathematics"})
        self.assertFalse(ok)
        self.assertTrue(missing)

    def test_no_subjects_named_is_not_a_verdict(self):
        """None, not False — "insufficient information" is a first-class
        result here, and guessing is what this module exists to stop.
        """
        ok, _ = eligibility.subject_verdict("bvsc", set())
        self.assertIsNone(ok)


class EligibleProgrammes(unittest.TestCase):
    """Q32/Q33 — answered with ONE programme when several or another applied."""

    def test_pcb_student_gets_both_biology_programmes(self):
        """Q32 said B.V.Sc. was the only option for a PCB student. B.F.Sc.
        also takes PCB.
        """
        found = eligibility.eligible_programmes({"physics", "chemistry", "biology"})
        self.assertIn("bvsc", found)
        self.assertIn("bfsc", found)

    def test_pcm_student_is_not_sent_to_bvsc(self):
        """Q33 sent a PCM student to B.V.Sc., which requires Biology and which
        they cannot enter.
        """
        found = eligibility.eligible_programmes({"physics", "chemistry", "mathematics"})
        self.assertIn("btech-dairy", found)
        self.assertNotIn("bvsc", found)

    def test_no_subjects_yields_nothing(self):
        self.assertEqual(eligibility.eligible_programmes(set()), [])


class QuestionShapes(unittest.TestCase):
    """Telling "what is the rule?" apart from "do I meet it?"."""

    def test_general_subject_question_is_not_a_personal_verdict(self):
        """"Is Mathematics compulsory for B.Tech. Dairy Technology?" was read
        as a student who had studied Mathematics and nothing else, and answered
        "You are not eligible" — a personal verdict on a general question,
        delivered to someone who never described their subjects.
        """
        self.assertFalse(eligibility.describes_own_subjects(
            "Is Mathematics compulsory for B.Tech. Dairy Technology?"))

    def test_a_student_describing_themselves_is_recognised(self):
        for text in ("I studied PCB", "I have Biology", "my subjects were PCM"):
            self.assertTrue(eligibility.describes_own_subjects(text), text)

    def test_threshold_question_is_recognised(self):
        """Q50: "what percentage is required for SC/ST/OBC candidates?" was
        answered "50%... the guidelines do not list a separate lower threshold
        for these categories" — a false rule stated with confidence, four
        questions before the real 47.50% appeared elsewhere.
        """
        self.assertTrue(eligibility.is_threshold_question(
            "what percentage is required for SC/ST/OBC candidates?"))

    def test_citing_own_marks_is_a_verdict_not_a_threshold_question(self):
        self.assertFalse(eligibility.is_threshold_question(
            "I have 55% in PCB, am I eligible?"))

    def test_unpinned_threshold_question_returns_every_programme(self):
        """The reserved threshold genuinely differs (47.50% vs 40%), so
        answering with a single figure is wrong however it is phrased.
        """
        rows = eligibility.thresholds_for("what percentage do reserved candidates need?")
        labels = {row[0] for row in rows}
        self.assertEqual(len(labels), len(eligibility.RULES))

    def test_which_programmes_question_needs_the_students_own_subjects(self):
        self.assertTrue(eligibility.is_which_programmes_question(
            "I have PCB, which courses can I apply for?"))
        self.assertFalse(eligibility.is_which_programmes_question(
            "which courses can I apply for?"))


class PercentageScopeReply(unittest.TestCase):
    """Recombining a bare reply with the pending question that carries the
    number — the reply itself never repeats it.
    """

    def test_bare_scope_reply_is_recognised(self):
        self.assertEqual(eligibility.is_bare_scope_reply("overall"), "overall")
        self.assertEqual(
            eligibility.is_bare_scope_reply("it's my subject combination score"), "subject")

    def test_a_new_question_containing_the_word_is_not_a_reply(self):
        """"which subjects are compulsory?" contains "subject" too, but is a
        self-sufficient new question and must not be swallowed into the
        pending one.
        """
        self.assertIsNone(eligibility.is_bare_scope_reply("which subjects are compulsory?"))

    def test_a_reply_carrying_its_own_percentage_is_refused(self):
        """Splicing the scope onto the STALE number from the pending question
        would discard the new figure and answer confidently on the wrong one.
        Falling through to the normal pipeline is the safe direction.
        """
        self.assertIsNone(eligibility.is_bare_scope_reply("55% in PCB"))

    def test_apply_scope_makes_extract_attribute_the_number(self):
        spliced = eligibility.apply_percentage_scope("I have 48%, am I eligible?", "subject")
        self.assertEqual(eligibility.extract(spliced)["subject_percent"], 48.0)

    def test_apply_scope_on_text_with_no_percentage_is_a_no_op(self):
        self.assertEqual(
            eligibility.apply_percentage_scope("am I eligible?", "overall"),
            "am I eligible?")


class EntranceExam(unittest.TestCase):
    """Q19 — the contradiction.

    "I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?" was
    answered "Yes, you can still get admission... you must also appear for
    MHT-CET." This module's docstring has named Q19 as one of the four failures
    it exists to fix since it was written, but `evaluate()` never had an
    entrance-exam check — `RULES` carried an unused "entrance" field and the
    question fell through to plain RAG with nothing deterministic constraining
    it.

    Grounded in the prospectuses, not in the assistant's own output:
      B.F.Sc.       p10  "the candidate should have also appeared for Common
                          Entrance Test (MHT-CET 2026)"
      B.Tech. (DT)  p5   same clause
      B.V.Sc.       p4   "admission ... shall be made on the basis of his/her
                          inter-se merit in the NEET-UG-2026 qualifying score"

    Without the exam there is no merit score to admit on, so this is a real
    disqualifier rather than a soft preference.
    """

    def test_q19_missing_mht_cet_disqualifies_bfsc(self):
        self.assertEqual(
            eligibility.missing_entrance_exam(
                "bfsc", "I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?"),
            "MHT-CET 2026")

    def test_q20_without_neet_disqualifies_bvsc(self):
        self.assertEqual(
            eligibility.missing_entrance_exam(
                "bvsc", "Can I get B.V.Sc. admission without NEET if I have high 12th marks?"),
            "NEET-UG-2026")

    def test_btech_dairy_also_requires_mht_cet(self):
        self.assertEqual(
            eligibility.missing_entrance_exam(
                "btech-dairy", "I have not appeared for MHT-CET"),
            "MHT-CET 2026")

    def test_the_wrong_exam_is_not_a_disqualifier(self):
        """B.F.Sc. is admitted on MHT-CET, so not sitting NEET says nothing
        about it. Treating any missed exam as disqualifying would turn away a
        student who is perfectly eligible.
        """
        self.assertIsNone(
            eligibility.missing_entrance_exam("bfsc", "I didn't appear for NEET"))
        self.assertIsNone(
            eligibility.missing_entrance_exam("bvsc", "I didn't appear for MHT-CET"))

    def test_phrasing_variants(self):
        for text in ("I did not appear for MHT-CET",
                     "I haven't appeared for MHT-CET",
                     "I never took MHT-CET",
                     "I missed the MHT-CET exam",
                     "I am not appearing for MHT-CET",
                     "Can I apply without MHT-CET?"):
            self.assertEqual(
                eligibility.missing_entrance_exam("bfsc", text), "MHT-CET 2026", text)

    def test_a_student_who_did_appear_is_not_disqualified(self):
        for text in ("I appeared for MHT-CET",
                     "I have given MHT-CET",
                     "I wrote MHT-CET and scored 90 percentile"):
            self.assertIsNone(eligibility.missing_entrance_exam("bfsc", text), text)

    def test_asking_whether_the_exam_is_needed_is_not_a_claim(self):
        """"Do I need to appear for MHT-CET?" is a question about the rule, not
        a statement that they skipped it. Answering it with "you are not
        eligible" would be the same class of error as delivering a personal
        verdict on a general subject question.
        """
        for text in ("Do I need to appear for MHT-CET?",
                     "Is MHT-CET compulsory for B.F.Sc.?",
                     "When is the MHT-CET exam?"):
            self.assertIsNone(eligibility.missing_entrance_exam("bfsc", text), text)

    def test_a_negation_about_something_else_does_not_fire(self):
        """The trap in a keyword negation list: these sentences contain a
        negation AND the exam name, but assert the exam IS required. Two
        separate guards catch them — an exemption is being negated, and the
        sentence is about candidates in general rather than the student.
        """
        for text in ("There is no exemption from MHT-CET",
                     "There is no waiver for MHT-CET",
                     "No candidate is admitted without MHT-CET",
                     "Students cannot be admitted without MHT-CET"):
            self.assertIsNone(eligibility.missing_entrance_exam("bfsc", text), text)

    def test_the_claim_must_be_about_the_student(self):
        """Mirrors describes_own_subjects: a general statement of the rule is
        not a personal circumstance to deliver a verdict on.
        """
        self.assertIsNone(
            eligibility.missing_entrance_exam(
                "bfsc", "Are candidates admitted who did not appear for MHT-CET?"))
        self.assertEqual(
            eligibility.missing_entrance_exam(
                "bfsc", "I did not appear for MHT-CET"),
            "MHT-CET 2026")

    def test_unknown_programme_has_no_entrance_rule(self):
        self.assertIsNone(eligibility.missing_entrance_exam("mvsc", "I didn't appear for NEET"))

    def test_every_rule_declares_which_exam_it_admits_on(self):
        for pid, rule in eligibility.RULES.items():
            self.assertIn("entrance_key", rule, pid)
            self.assertTrue(rule["entrance"], pid)


class EvaluateEntranceExam(unittest.TestCase):
    """The verdict, end to end."""

    def test_q19_is_now_a_deterministic_refusal(self):
        result = eligibility.evaluate(
            "bfsc", "I didn't appear for MHT-CET. Can I still get admission to B.F.Sc.?")
        self.assertEqual(result["verdict"], "not_eligible")
        self.assertEqual(result["reason"], "entrance_exam")
        self.assertEqual(result["entrance"], "MHT-CET 2026")

    def test_q20_is_now_a_deterministic_refusal(self):
        result = eligibility.evaluate(
            "bvsc", "Can I get B.V.Sc. admission without NEET if I have high 12th marks?")
        self.assertEqual(result["verdict"], "not_eligible")
        self.assertEqual(result["reason"], "entrance_exam")

    def test_the_verdict_carries_its_source_page(self):
        result = eligibility.evaluate("bfsc", "I didn't appear for MHT-CET")
        self.assertEqual(result["page"], eligibility.RULES["bfsc"]["page"])

    def test_a_missed_exam_outranks_good_marks(self):
        """The whole failure mode: strong marks made the answer open with
        "Yes", and the exam requirement was appended afterwards as a
        contradiction.
        """
        result = eligibility.evaluate(
            "bfsc", "I didn't appear for MHT-CET but I have 90% in PCB and English")
        self.assertEqual(result["verdict"], "not_eligible")
        self.assertEqual(result["reason"], "entrance_exam")

    def test_the_wrong_exam_does_not_change_an_ordinary_verdict(self):
        result = eligibility.evaluate(
            "bfsc", "I didn't appear for NEET but I have 90% in PCB and English")
        self.assertEqual(result["verdict"], "eligible")


class Evaluate(unittest.TestCase):
    """The verdict itself."""

    def test_q25_subject_marks_below_threshold_is_not_eligible(self):
        """The rule is explicitly on the SUBJECT COMBINATION. Comparing the 51%
        aggregate against it is what made Q25 tell an ineligible student to
        apply.
        """
        result = eligibility.evaluate(
            "bvsc", "I have 51% overall in 12th but only 45% in PCB and English")
        self.assertEqual(result["verdict"], "not_eligible")

    def test_an_aggregate_alone_cannot_answer_a_subject_rule(self):
        """Silently substituting one for the other is exactly the Q25 failure —
        so it asks instead.
        """
        result = eligibility.evaluate("bvsc", "I have 51% overall in 12th")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["reason"], "overall_not_subject")

    def test_comfortably_above_threshold_is_eligible(self):
        result = eligibility.evaluate("bvsc", "I have 65% in PCB and English")
        self.assertEqual(result["verdict"], "eligible")

    def test_reserved_category_uses_the_lower_threshold(self):
        """48% in PCB is below the 50% unreserved bar and above B.V.Sc.'s
        47.50% reserved one — the exact band Q13/Q28 got wrong.
        """
        result = eligibility.evaluate("bvsc", "I am SC category with 48% in PCB and English")
        self.assertEqual(result["verdict"], "eligible")
        self.assertEqual(result["required"], 47.50)

    def test_assumed_category_is_flagged_as_assumed(self):
        result = eligibility.evaluate("bvsc", "I have 65% in PCB and English")
        self.assertTrue(result["category_assumed"])

    def test_wrong_subjects_are_refused_before_any_percentage_is_read(self):
        result = eligibility.evaluate(
            "bvsc", "I studied PCM and got 90% in those subjects")
        self.assertEqual(result["verdict"], "not_eligible")
        self.assertEqual(result["reason"], "subjects")

    def test_no_marks_at_all_is_insufficient(self):
        result = eligibility.evaluate("bvsc", "am I eligible?")
        self.assertEqual(result["verdict"], "insufficient")

    def test_unknown_programme_is_insufficient(self):
        result = eligibility.evaluate("mvsc", "I have 65% in PCB")
        self.assertEqual(result["verdict"], "insufficient")
        self.assertEqual(result["reason"], "unknown_programme")


if __name__ == "__main__":
    unittest.main()
