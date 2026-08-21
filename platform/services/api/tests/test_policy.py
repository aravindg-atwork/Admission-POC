from app.core import policy


ABROAD_VARIANTS = (
    "I am NRI, completed 12th in USA, and did not write NEET. Am I eligible?",
    "OCI applicant: I finished high school in the United States and never took NEET.",
    "For the NRI quota, I passed XII abroad but have not appeared for NEET-UG-2026.",
    "Foreign national who studied outside India; no NEET attempt. Can I get admission?",
)


def test_nri_abroad_exception_beats_general_neet_rule():
    for question in ABROAD_VARIANTS:
        result = policy.evaluate("bvsc", question)
        decision = result.decisions["entrance_exam"]
        assert decision.rule_id == "bvsc.nri_abroad.neet_exempt"
        assert decision.outcome == "exempt"
        assert decision.priority == 100


def test_nri_india_keeps_neet_requirement():
    questions = (
        "I am an NRI candidate, completed my 12th in India, and did not appear for NEET.",
        "I am an NRI applicant but completed class 12 in India and did not appear for NEET.",
    )
    for question in questions:
        result = policy.evaluate("bvsc", question)
        decision = result.decisions["entrance_exam"]
        assert decision.rule_id == "bvsc.nri_india.neet_required"
        assert decision.outcome == "not_eligible"


def test_general_missing_neet_remains_lower_priority():
    result = policy.evaluate("bvsc", "I did not appear for NEET. Can I apply for B.V.Sc.?")
    decision = result.decisions["entrance_exam"]
    assert decision.rule_id == "bvsc.general.neet_required"
    assert decision.priority == 10


def test_exception_does_not_claim_final_eligibility():
    result = policy.evaluate("bvsc", ABROAD_VARIANTS[0])
    reply = policy.admission_reply(result)
    assert reply is not None
    answer = reply["answer"].lower()
    assert "does not by itself" in answer
    assert "50%" in answer
    assert "17 years" in answer
    assert reply["policyDecisions"][0]["dimension"] == "entrance_exam"


def test_policy_does_not_cross_programmes():
    result = policy.evaluate(
        "bfsc", "I am NRI, completed 12th in USA, and did not write NEET. Am I eligible?"
    )
    assert not result.decisions


def test_neet_exception_does_not_override_failed_nri_marks():
    result = policy.evaluate(
        "bvsc",
        "I am NRI, completed 12th in USA with 45% in PCBE, and did not take NEET. Am I eligible?",
    )
    assert result.decisions["entrance_exam"].outcome == "exempt"
    assert result.decisions["qualifying_marks"].outcome == "not_eligible"
    reply = policy.admission_reply(result)
    assert reply is not None
    assert reply["answer"].startswith("No,")
    assert {item["dimension"] for item in reply["policyDecisions"]} == {
        "entrance_exam", "qualifying_marks"
    }


def test_nri_marks_satisfied_is_reported_without_final_overclaim():
    result = policy.evaluate(
        "bvsc",
        "OCI applicant, completed XII abroad with 55% in PCBE and never took NEET. Am I eligible?",
    )
    reply = policy.admission_reply(result)
    assert reply is not None
    assert result.decisions["qualifying_marks"].outcome == "satisfied"
    assert "55% meets" in reply["answer"]
    assert "Final eligibility still requires" in reply["answer"]


def test_age_cutoff_paraphrases_are_compounded_safely():
    cases = (
        ("I am NRI, did XII in USA, never took NEET and was born on 01/01/2010.", "satisfied"),
        ("OCI, passed 12th abroad without NEET; my date of birth is 10 January 2010.", "not_eligible"),
        ("Foreign national, studied outside India, no NEET; I turn 17 in February 2027.", "not_eligible"),
        ("NRI with XII from USA and no NEET; I will be 17 in December 2026.", "satisfied"),
    )
    for question, expected in cases:
        result = policy.evaluate("bvsc", question)
        assert result.decisions["age"].outcome == expected
        reply = policy.admission_reply(result)
        assert reply is not None
        if expected == "not_eligible":
            assert reply["answer"].startswith("No,")


def test_age_rule_is_programme_scoped_without_neet_reply_takeover():
    for project_id in ("bfsc", "btech-dairy"):
        result = policy.evaluate(project_id, "My date of birth is 10 January 2010. Am I eligible?")
        assert result.decisions["age"].outcome == "not_eligible"
        assert policy.admission_reply(result) is None


def test_reserved_category_does_not_reduce_nri_marks_threshold():
    result = policy.evaluate(
        "bvsc", "I am OBC and NRI, completed XII in USA with 48% PCBE and did not take NEET."
    )
    assert result.decisions["category"].outcome == "no_relaxation"
    assert result.decisions["qualifying_marks"].outcome == "not_eligible"
    assert policy.admission_reply(result)["answer"].startswith("No,")


def test_missing_ncl_affects_reservation_not_blanket_admission():
    for question in (
        "I am OBC but my NCL is not ready.",
        "OBC applicant with an expired Non-Creamy Layer certificate.",
        "I belong to OBC and do not have NCL yet.",
    ):
        decision = policy.evaluate("bvsc", question).decisions["reservation_documents"]
        assert decision.outcome == "reservation_not_established"
        assert "another valid category" in decision.explanation


def test_pending_cvc_is_provisional_not_final_rejection():
    for question in (
        "I am OBC and my caste validity certificate is pending.",
        "SC candidate with proof that my CVC proposal was submitted.",
        "I belong to OBC and have a receipt for my caste validity application.",
    ):
        decision = policy.evaluate("bfsc", question).decisions["caste_validity_document"]
        assert decision.outcome == "provisional_only"
        assert "programme-specific deadline" in decision.explanation
