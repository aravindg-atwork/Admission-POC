from app.agent import guards, safety


def test_year_lock_rejects_other_cycle():
    result = guards.admission_year_guard("What were the fees for 2025-26?", {})
    assert result and result["source"] == "knowledge-boundary"
    assert "2026-27" in result["answer"] and "2025-26" in result["answer"]


def test_year_lock_accepts_current_cycle():
    assert guards.admission_year_guard("What are the 2026-27 fees?", {}) is None


def test_privacy_guard_catches_aadhaar():
    result = guards.pii_guard("My Aadhaar is 1234 5678 9012. Am I eligible?", {})
    assert result and result["source"] == "privacy-guard"
    assert "1234" not in result["answer"]


def test_privacy_guard_catches_application_id():
    assert guards.pii_guard("NEET application ID AB12345678", {}) is not None


def test_privacy_guard_does_not_confuse_percentile_with_identifier():
    assert guards.pii_guard("My CET percentile is 82", {}) is None


def test_prediction_is_not_invented():
    result = guards.prediction_guard("What are my chances of admission?", {})
    assert result and "cannot predict" in result["answer"]


def test_exam_contradiction_requires_clarification():
    result = guards.contradiction_guard("My CET percentile is 82", {"entranceExamStatus": "no"})
    assert result and result["source"] == "state-contradiction"
    assert result["interviewField"] == "entranceExamStatus"


def test_category_correction_replaces_old_fact():
    state, changes = safety.reconcile_state("Sorry, I am OBC, not General", {"category": "unreserved"})
    assert state["category"] == "reserved" and changes == {"category": "reserved"}


def test_source_trace_is_programme_and_year_locked():
    result = safety.finalize("Am I eligible?", "bfsc", {
        "answer": "You meet the stated requirements so far.", "source": "eligibility",
        "pages": [5, 5], "policyDecisions": [{"ruleId": "bfsc.marks", "pages": [5]}],
    })
    assert result["decisionState"] == "eligible_so_far"
    assert result["sourceTrace"] == {"programme": "bfsc", "admissionYear": "2026-27", "pages": [5], "ruleIds": ["bfsc.marks"]}


def test_unknown_is_never_classified_as_no():
    result = safety.finalize("Can you confirm?", "bvsc", {
        "answer": "I don't have enough verified information to confirm that.",
        "source": "low-confidence", "pages": [],
    })
    assert result["decisionState"] == "cannot_confirm"
    assert result["fallbackReason"] == "low-confidence"


def test_turn_facts_use_only_programme_exam():
    assert safety.turn_facts("I did not appear for MHT-CET", "bfsc") == {"entranceExamStatus": "no"}
    assert safety.turn_facts("I failed NEET", "bfsc") == {}


def test_repeated_character_input_never_reaches_retrieval():
    result = guards.malformed_input_guard("q" * 1100, {})
    assert result and result["source"] == "malformed-input"
    assert result["pages"] == []


def test_normal_short_question_is_not_malformed():
    assert guards.malformed_input_guard("What are the B.F.Sc. fees?", {}) is None
