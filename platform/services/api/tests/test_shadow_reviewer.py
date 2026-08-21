from app.review import reviewer
from app.storage.conversations import _needs_machine_review


def test_machine_review_cannot_cite_unavailable_page():
    result = reviewer.normalize({
        "verdict": "critical", "severity": "critical",
        "issues": ["eligibility_disagreement", "invented_label"],
        "explanation": "Threshold conflict", "suggestedCorrection": "Review it",
        "evidencePages": [4, 999],
    }, [4, 7])
    assert result["evidencePages"] == [4]
    assert result["issues"] == ["eligibility_disagreement"]


def test_pass_cannot_smuggle_a_correction():
    result = reviewer.normalize({
        "verdict": "pass", "severity": "low", "issues": ["overclaim"],
        "suggestedCorrection": "Publish me", "evidencePages": [],
    }, [])
    assert result["issues"] == [] and result["suggestedCorrection"] == ""


def test_invalid_labels_degrade_to_human_review():
    result = reviewer.normalize({"verdict": "approve-and-publish", "severity": "urgent"}, [])
    assert result["verdict"] == "review" and result["severity"] == "medium"


def test_high_risk_answer_is_queued():
    assert _needs_machine_review({
        "source": "eligibility", "decisionState": "eligible_so_far",
        "answer": "You meet the marks requirement.",
    })


def test_greeting_is_not_queued():
    assert not _needs_machine_review({"source": "greeting", "answer": "Hi!"})
