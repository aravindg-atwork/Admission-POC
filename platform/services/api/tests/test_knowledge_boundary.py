from app.agent import guards, knowledge_boundary


def test_ambiguous_university_head_requests_targeted_clarification():
    result = guards.run_guards("hey what the name head of university?", {}, "bvsc")
    assert result["source"] == "clarification"
    assert result["interviewField"] == "universityOffice"


def test_nri_routes_are_not_limited_to_bvsc():
    result = guards.run_guards(
        "so nri is not eligible for btech and bfsc?", {}, "bvsc"
    )
    answer = result["answer"].lower()
    assert "all three" in answer
    assert "b.f.sc" in answer and "b.tech" in answer and "b.v.sc" in answer
    assert "does not by itself confirm" in answer


def test_sure_rechecks_previous_nri_answer():
    result = guards.run_guards("sure?", {
        "lastAssistantAnswer": "NRI routes exist for all three programmes."
    }, "bvsc")
    assert result["source"] == "verified-policy"
    assert "not your personal eligibility" in result["answer"]


def test_boundary_rewrites_university_blame_and_internal_rag_terms():
    for unsafe in (
        "The prospectus does not specify that.",
        "The retrieved context does not contain an answer.",
        "The RAG knowledge base has no matching chunks.",
    ):
        safe = knowledge_boundary.apply(unsafe)
        assert safe.startswith("I don't have enough verified information")
        assert "prospectus does not" not in safe.lower()
