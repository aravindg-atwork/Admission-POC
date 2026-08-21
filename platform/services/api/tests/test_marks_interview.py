from app.agent.guards import eligibility_guard
from app.core import eligibility


def test_named_subject_marks_and_group_marks_are_extracted():
    named = eligibility.extract_subject_marks(
        "physics-45, chemistry-65, biology-72, math-80"
    )
    assert named == {
        "physics": 45.0, "chemistry": 65.0,
        "biology": 72.0, "mathematics": 80.0,
    }
    grouped = eligibility.extract_subject_marks("I scored 45,65,72,80 on PCBM")
    assert grouped == named


def test_pcbm_marks_prompt_for_mandatory_english():
    result = eligibility_guard(
        "I scored 45,65,72,80 on PCBM. Am I eligible?", {}, "btech-dairy"
    )
    assert result["interviewField"] == "subjectMarks"
    assert "English" in result["answer"]
    assert result["slotUpdate"]["subjectMarks"]["mathematics"] == 80.0


def test_english_followup_computes_btech_required_combination():
    first = eligibility_guard(
        "I scored 45,65,72,80 on PCBM. Am I eligible?", {}, "btech-dairy"
    )
    state = first["slotUpdate"]
    state["carryQuestion"] = first["carryQuestion"]
    second = eligibility_guard("English-70", state, "btech-dairy")
    assert second["interviewField"] == "entranceExamStatus"
    assert second["slotUpdate"]["subjectPercent"] == 65.0


def test_total_fraction_is_converted_but_not_used_as_subject_percentage():
    result = eligibility_guard("I scored 500/600 in 12th. Am I eligible?", {}, "bfsc")
    assert result["source"] == "clarify-percentage"
    assert "83.33% overall" in result["answer"]
    assert "required subjects" in result["answer"]


def test_bare_percentage_asks_scope_then_preserves_value():
    first = eligibility_guard("I have 48%. Am I eligible?", {}, "bfsc")
    assert first["interviewField"] == "percentageScope"
    assert first["slotUpdate"]["pendingPercent"] == 48.0
    state = first["slotUpdate"]
    state["carryQuestion"] = first["carryQuestion"]
    second = eligibility_guard("It is my subject combination percentage", state, "bfsc")
    assert second["interviewField"] == "entranceExamStatus"
    assert second["slotUpdate"]["subjectPercent"] == 48.0


def test_completed_interview_answers_can_apply_question_conversationally():
    state = {
        "intent": "eligibility_resolved",
        "programme": "bvsc",
        "entranceExamStatus": "yes",
        "category": "reserved",
        "subjectPercent": 48.0,
    }
    result = eligibility_guard("So can I apply for BVSc?", state, "bvsc")
    assert result is not None
    assert result["answer"].startswith("Yes — based on the details you've shared")
    assert "Final allotment depends" in result["answer"]


def test_bfsc_neet_concern_is_answered_before_mht_cet_interview():
    result = eligibility_guard(
        "If I appeared for NEET and didn't pass, am I eligible?",
        {"programme": "bfsc"},
        "bfsc",
    )
    assert result["interviewField"] == "entranceExamStatus"
    assert "not passing NEET does not by itself make you ineligible" in result["answer"]
    assert "uses MHT-CET 2026, not NEET" in result["answer"]


def test_bvsc_appeared_but_failed_neet_is_not_asked_twice():
    result = eligibility_guard(
        "If I appeared for NEET and didn't pass, am I eligible?",
        {
            "programme": "bvsc",
            "intent": "programme_awaiting_choice",
            "carryQuestion": "If I appeared for NEET and didn't pass, am I eligible?",
        },
        "bvsc",
    )
    assert result["source"] == "eligibility"
    assert result.get("interviewField") is None
    assert "merely appearing" in result["answer"]
    assert "qualifying NEET-UG-2026 score" in result["answer"]
    assert result["slotUpdate"]["entranceExamStatus"] == "not_qualified"


def test_bfsc_final_answer_preserves_original_neet_concern():
    state = {
        "intent": "eligibility_awaiting_subject_percent",
        "programme": "bfsc",
        "entranceExamStatus": "yes",
        "category": "reserved",
        "carryQuestion": "If I appeared for NEET and didn't pass, am I eligible?",
    }
    result = eligibility_guard("49%", state, "bfsc")
    assert result["answer"].startswith("Yes")
    assert "NEET result does not affect regular B.F.Sc. eligibility" in result["answer"]
    assert "age rule" in result["answer"]


def test_bvsc_interview_asks_qualification_not_appearance():
    result = eligibility_guard("Am I eligible?", {"programme": "bvsc"}, "bvsc")
    assert result["answer"] == "Have you qualified NEET-UG-2026?"
    assert result["interviewOptions"][0] == {
        "label": "Yes, I qualified", "value": "yes"
    }
    assert result["interviewOptions"][1]["value"] == "not_qualified"


def test_bvsc_not_qualified_option_stops_interview():
    result = eligibility_guard(
        "I appeared but did not qualify",
        {"programme": "bvsc", "intent": "eligibility_awaiting_entrance"},
        "bvsc",
    )
    assert result.get("interviewField") is None
    assert "Merely appearing" in result["answer"]


def test_bvsc_positive_final_says_qualified_not_appeared():
    result = eligibility_guard(
        "48%",
        {
            "programme": "bvsc",
            "intent": "eligibility_awaiting_subject_percent",
            "entranceExamStatus": "yes",
            "category": "reserved",
        },
        "bvsc",
    )
    assert "qualified NEET-UG-2026" in result["answer"]
    assert "appeared for NEET" not in result["answer"]
