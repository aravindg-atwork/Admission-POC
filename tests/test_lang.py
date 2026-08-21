"""Regression tests for core/lang.py — script and language detection.

Routing between the English and Indic lanes, plus the two word-list heuristics
that tell Hindi from Marathi. Both heuristics carry deliberately different
hit thresholds for a reason the tests below pin down.

Pure functions, no network, no keys.
"""

import unittest

from backend.core import lang


class DetectScript(unittest.TestCase):

    def test_plain_english_is_latin(self):
        self.assertEqual(lang.detect_script("what is the fee"), "latin")

    def test_devanagari_is_detected(self):
        self.assertEqual(lang.detect_script("फी किती आहे?"), "devanagari")

    def test_tamil_is_detected(self):
        self.assertEqual(lang.detect_script("கட்டணம் என்ன?"), "tamil")

    def test_latin_punctuation_and_digits_stay_latin(self):
        self.assertEqual(lang.detect_script("50% in PCB?"), "latin")

    def test_mixed_script_takes_the_indic_lane(self):
        """A question with an English loanword in a Devanagari sentence is
        still a Devanagari question.
        """
        self.assertEqual(lang.detect_script("B.V.Sc. ची फी किती आहे?"), "devanagari")

    def test_is_indic_covers_both_scripts(self):
        self.assertTrue(lang.is_indic("फी किती आहे?"))
        self.assertTrue(lang.is_indic("கட்டணம் என்ன?"))
        self.assertFalse(lang.is_indic("what is the fee"))

    def test_empty_text_is_latin(self):
        self.assertEqual(lang.detect_script(""), "latin")


class RomanizedIndic(unittest.TestCase):
    """Hinglish — Latin script, indistinguishable from English by Unicode."""

    def test_hindi_is_detected(self):
        self.assertEqual(lang.detect_romanized_indic("mera fees kitna hai"), "hi")

    def test_marathi_is_detected(self):
        self.assertEqual(lang.detect_romanized_indic("fee kiti ahe"), "mr")

    def test_genuine_english_is_not_romanized_indic(self):
        for text in ("what is the fee", "how do I apply for admission"):
            self.assertIsNone(lang.detect_romanized_indic(text), text)

    def test_one_marker_is_not_enough(self):
        """>=2 hits, not 1 — a single ambiguous or borrowed word must not flip
        an English sentence into the Indic lane.
        """
        self.assertIsNone(lang.detect_romanized_indic("is the fee kitna"))

    def test_punctuation_stuck_to_a_marker_still_counts(self):
        """A real 2-hit sentence measured as 1 because the second marker had a
        "?" attached, missing the threshold entirely.
        """
        self.assertEqual(lang.detect_romanized_indic("fees kitna hai?"), "hi")

    def test_a_mix_leans_hindi(self):
        """Ties lean Hindi, the more common default."""
        self.assertEqual(lang.detect_romanized_indic("mera fee kitna ahe hai"), "hi")


class DevanagariHindiMarathi(unittest.TestCase):
    """Native script — same technique, but min_hits=1, and that matters."""

    def test_marathi_is_detected(self):
        self.assertEqual(lang.detect_devanagari_hi_mr("फी किती आहे?"), "mr")

    def test_hindi_is_detected(self):
        self.assertEqual(lang.detect_devanagari_hi_mr("फीस कितनी है?"), "hi")

    def test_a_single_marker_is_enough_here(self):
        """A real short question carries exactly one marker ("आहे"), so
        min_hits=2 would return None on precisely the short-question case this
        exists to catch. Native Devanagari is never used to write English, so
        the collision risk that forces 2 hits for romanized text is absent.
        """
        self.assertEqual(
            lang.detect_devanagari_hi_mr("वसतिगृह उपलब्ध आहे का?"), "mr")

    def test_danda_punctuation_is_stripped(self):
        """Devanagari sentences end in "।", not ".", and a marker with one
        attached must still match.
        """
        self.assertEqual(lang.detect_devanagari_hi_mr("मुझे बताइए।"), "hi")

    def test_devanagari_without_any_marker_is_none(self):
        """No marker means no claim — the caller falls back to ui_language
        rather than guessing.
        """
        self.assertIsNone(lang.detect_devanagari_hi_mr("पशुवैद्यकीय"))


if __name__ == "__main__":
    unittest.main()
