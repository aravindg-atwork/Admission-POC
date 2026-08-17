"""Regression tests for core/programs.py — programme detection and clarification.

Every test here locks down a bug that programs.py's own comments record as
having actually happened. The module is dense with hard-won tuning (marker sets
narrowed and re-narrowed against measured section scores), and until now the
only thing protecting any of it was a 75-question eval that costs money and
minutes to run. Each test names the failure it prevents.

Pure functions, no network, no keys.
"""

import unittest

from backend.core import programs


class DetectProgram(unittest.TestCase):
    """detect_program / detect_programs_multi — which programme is named."""

    def test_plain_aliases(self):
        self.assertEqual(programs.detect_program("what is the B.V.Sc. fee"), "bvsc")
        self.assertEqual(programs.detect_program("B.F.Sc. eligibility"), "bfsc")
        self.assertEqual(programs.detect_program("btech dairy seats"), "btech-dairy")

    def test_punctuation_and_spacing_are_irrelevant(self):
        """_normalize collapses 'B.V.Sc.', 'BVSc' and 'B V Sc' to one form."""
        for spelling in ("B.V.Sc.", "BVSc", "B V Sc", "bvsc"):
            self.assertEqual(programs.detect_program(spelling), "bvsc", spelling)

    def test_veterinary_is_a_bvsc_alias(self):
        """2026-08-14: detect_program("veterinary") returned None, so
        "Can I apply for veterinary at MAFSU?" named no programme as far as the
        deterministic matcher was concerned, fell through to the router, and was
        answered about B.Tech. (Dairy Technology).
        """
        self.assertEqual(programs.detect_program("veterinary"), "bvsc")
        self.assertEqual(
            programs.detect_program("Can I apply for veterinary at MAFSU?"), "bvsc")

    def test_devanagari_programme_names_are_detected(self):
        """2026-08-13: only Latin spellings were listed, so a student writing
        their programme in their own script could never satisfy the check and
        was asked "which programme did you mean?" no matter what they typed.

        The aliases are POST-_normalize skeletons: Devanagari matras and viramas
        are combining marks, so "बी.व्ही.एस्सी." reduces to "बवहएसस".
        """
        self.assertEqual(programs.detect_program("बी.व्ही.एस्सी. फी"), "bvsc")

    def test_multi_orders_by_position_in_the_question(self):
        """Text order, not dict order, so a mixed mention lists the programmes
        the way the student actually asked about them.
        """
        self.assertEqual(
            programs.detect_programs_multi("B.F.Sc. or B.V.Sc.?"), ["bfsc", "bvsc"])

    def test_own_prior_degree_is_not_the_programme_asked_about(self):
        """2026-08-12: "I completed my B.V.Sc. abroad. Do I need to appear for
        AIEEA?" wrongly triggered the cross-programme comparison path — B.V.Sc.
        there is background about the student's own degree, not a programme to
        compare against.
        """
        found = programs.detect_programs_multi(
            "I completed my B.V.Sc. abroad. Do I need to appear for AIEEA?")
        self.assertNotIn("bvsc", found)

    def test_self_credential_window_stops_at_the_clause_boundary(self):
        """The window is bounded to the credential's own clause so a second,
        unrelated programme named right after is still counted.
        """
        found = programs.detect_programs_multi(
            "I completed my B.V.Sc., is B.F.Sc. eligibility different?")
        self.assertIn("bfsc", found)


class NeedsProgramClarification(unittest.TestCase):
    """The "ask, don't guess" gate — and the shared topics it must NOT ask on."""

    def test_programme_specific_topic_with_no_programme_asks(self):
        self.assertTrue(programs.needs_program_clarification("what is the fee?"))
        self.assertTrue(programs.needs_program_clarification("what is the eligibility?"))

    def test_naming_a_programme_never_asks(self):
        self.assertFalse(programs.needs_program_clarification("what is the B.F.Sc. fee?"))

    def test_shared_process_questions_do_not_ask(self):
        """Narrowed 2026-08-17. "admission"/"documents"/"deadline" are shared —
        one portal, one document list — and having them as markers meant
        "what documents are required?" was answered with "which programme?".
        Section D scored 6/12 that way against 12/12 without them.
        """
        for question in ("what documents are required?",
                         "how do I apply?",
                         "what is the deadline?"):
            self.assertFalse(programs.needs_program_clarification(question), question)

    def test_process_verbs_beat_a_programme_specific_noun(self):
        """A question can MENTION a programme-specific topic without asking for
        its value: "how do I PAY the application fee?" is one process for all
        three programmes, yet was bounced purely because "fee" appears in it.
        """
        self.assertFalse(
            programs.needs_program_clarification("how do I pay the application fee?"))
        self.assertFalse(
            programs.needs_program_clarification(
                "does qualifying for NEET guarantee admission?"))

    def test_single_character_typo_still_asks(self):
        """"what the eligbility" exact-matched nothing, so the question silently
        answered from whichever programme the widget happened to be scoped to —
        the exact "ask, don't guess" guarantee this module exists to give.
        """
        self.assertTrue(programs.needs_program_clarification("what the eligbility"))

    def test_short_markers_stay_exact_match(self):
        """Edit-distance-1 on a 3-letter marker would catch unrelated real
        words ("see"/"fee", "fed"/"fee"), which a typo fix must not do.
        """
        self.assertFalse(programs.needs_program_clarification("can you see me"))

    def test_devanagari_marker_survives_tokenisation(self):
        """A naive isalnum() split shatters Devanagari mid-token ("फी" -> "फ",
        dropping the matra), so this marker never fired on a Marathi question.
        """
        self.assertTrue(programs.needs_program_clarification("फी किती आहे?"))

    def test_devanagari_markers_match_inflected_forms(self):
        """Hindi/Marathi agglutinate case endings onto the noun, so an exact-set
        check missed every inflected form: "वसतिगृहाची" never matched "वसतिगृह".
        """
        self.assertTrue(
            programs.needs_program_clarification("वसतिगृहाची सोय उपलब्ध आहे का?"))


class ForceAskMarkers(unittest.TestCase):
    """needs_program_clarification_strong — the subset safe to OR in against a
    router "no". The excluded words are the ones measured as unsafe.
    """

    def test_strong_still_asks_on_the_core_topics(self):
        self.assertTrue(programs.needs_program_clarification_strong("what is the eligibility?"))
        self.assertTrue(programs.needs_program_clarification_strong("what is the fee?"))

    def test_reservation_words_are_excluded(self):
        """OR-ing the full marker set back in reproduced the regression
        HANDOFF records: Section E 9/9 -> 5/9. "what is the reservation
        policy?" is one shared answer; only reading the sentence tells it apart
        from "what percentage do reserved candidates need?".
        """
        for question in ("what is the reservation policy?",
                         "what documents do I need to claim reservation?"):
            self.assertFalse(
                programs.needs_program_clarification_strong(question), question)

    def test_hostel_is_excluded(self):
        """"Is hostel accommodation compulsory?" (shared) vs "what is the hostel
        fee?" (differs) — same marker word, only reading them apart works.
        """
        self.assertFalse(
            programs.needs_program_clarification_strong(
                "Is hostel accommodation compulsory?"))

    def test_seat_family_is_excluded(self):
        """"Are there seats reserved for EWS candidates?" — the EWS percentage
        is a shared state-mandated figure, but seat COUNT varies per programme,
        and "seats" alone cannot tell which question this is.
        """
        self.assertFalse(
            programs.needs_program_clarification_strong(
                "Are there seats reserved for EWS candidates?"))

    def test_weak_set_still_covers_what_strong_excludes(self):
        """The exclusions are about forcing past the router, not about the topic
        being programme-neutral — the ordinary check still asks.
        """
        self.assertTrue(programs.needs_program_clarification("what is the hostel fee?"))


class BareProgramReply(unittest.TestCase):
    """Telling "answering the clarification" apart from "a new question"."""

    def test_bare_programme_name_is_a_reply(self):
        for text in ("btech", "B.F.Sc.", "the btech one please"):
            self.assertTrue(programs.is_bare_program_reply(text), text)

    def test_self_sufficient_question_is_not_a_reply(self):
        """Keyed on "carries no topic marker of its own", not word count:
        "btech dairy fees" is three words but must NOT be rewritten into
        whatever was asked before it.
        """
        self.assertFalse(programs.is_bare_program_reply("btech dairy fees"))

    def test_text_naming_no_programme_is_not_a_reply(self):
        self.assertFalse(programs.is_bare_program_reply("what is the fee"))


class NeedsComparison(unittest.TestCase):

    def test_two_named_programmes_compare(self):
        self.assertTrue(programs.needs_comparison("compare B.V.Sc. and B.F.Sc."))

    def test_exactly_one_named_programme_is_never_a_comparison(self):
        self.assertFalse(programs.needs_comparison("what is the B.Tech Dairy fee"))

    def test_generic_which_courses_question_compares(self):
        self.assertTrue(programs.needs_comparison("which courses require NEET"))

    def test_typo_in_the_noun_still_compares(self):
        """"what all couse i can apply for" (one missing letter) failed the noun
        check, so a genuinely cross-programme question got "which programme did
        you mean?" instead of an answer.
        """
        self.assertTrue(
            programs.needs_comparison(
                "what all couse i can apply for if my score is 60%"))

    def test_trigger_without_a_course_noun_does_not_compare(self):
        self.assertFalse(programs.needs_comparison("which documents are required"))

    def test_course_noun_without_a_trigger_does_not_compare(self):
        self.assertFalse(programs.needs_comparison("what is the duration of the course"))


class ComparisonTargets(unittest.TestCase):

    def test_named_programmes_win(self):
        self.assertEqual(
            programs.comparison_targets("compare B.V.Sc. and B.F.Sc."), ["bvsc", "bfsc"])

    def test_all_means_every_programme(self):
        self.assertEqual(
            sorted(programs.comparison_targets("is this fee same for all courses")),
            sorted(programs.PROGRAM_NAMES))

    def test_default_excludes_the_general_entry_point(self):
        """"default" has no corpus since the 2026-08-16 split. Including it
        would reintroduce the bug the split removed — a question naming no
        programme answering from B.V.Sc.
        """
        self.assertNotIn("default", programs.comparison_targets("which courses require NEET"))

    def test_scoped_widget_contrast_is_not_an_explicit_comparison(self):
        """A student inside the B.Tech widget asking "can I apply if I took
        Biology instead of Maths?" is asking about B.Tech; needs_comparison sees
        the contrast and the default set would open the reply on B.V.Sc.
        """
        self.assertFalse(
            programs.comparison_is_explicit(
                "can I apply if I took Biology instead of Maths?"))


class MentionsForeignCourse(unittest.TestCase):
    """Corroboration for the unknown-programme refusal — refusing an in-scope
    question is a worse failure than the one the refusal prevents.
    """

    def test_the_institutions_own_name_is_not_a_course(self):
        """The router read "MAFSU" as a course and refused two of the most
        ordinary questions there are.
        """
        for question in ("How do I apply for MAFSU admission?",
                         "Where can I find the MAFSU prospectus?"):
            self.assertFalse(programs.mentions_foreign_course(question), question)

    def test_our_own_programmes_are_not_foreign(self):
        self.assertFalse(programs.mentions_foreign_course("what is the B.V.Sc. fee"))

    def test_unrelated_courses_are_foreign(self):
        for question in ("Can I do an MBA here?", "MBBS admission process"):
            self.assertTrue(programs.mentions_foreign_course(question), question)

    def test_retired_postgraduate_markers_decide_first(self):
        """Two PG markers collide with our own aliases: "M.Tech. Dairy
        Technology" contains "dairy", and "M.V.Sc." shares its tail with
        "B.V.Sc." — which is how a Ph.D. question came back quoting B.V.Sc.'s
        47.5%. _words() splits "Ph.D." into "ph" and "d", so this needs the
        regex, not the word list.
        """
        for question in ("Ph.D. admission requirements",
                         "PhD admission requirements",
                         "M.V.Sc. eligibility",
                         "M.Tech. Dairy Technology fee"):
            self.assertTrue(programs.mentions_foreign_course(question), question)

    def test_unlisted_degree_shape_is_caught_as_a_fallback(self):
        self.assertTrue(programs.mentions_foreign_course("Do you offer B.Arch?"))


if __name__ == "__main__":
    unittest.main()
