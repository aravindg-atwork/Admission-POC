from app.storage import answer_cache


def test_keys_are_programme_and_language_scoped():
    question = "  Am I   eligible? "
    assert answer_cache._key("bvsc", question, "en") == answer_cache._key(
        "bvsc", "am i eligible?", "en"
    )
    assert answer_cache._key("bvsc", question, "en") != answer_cache._key("bfsc", question, "en")
    assert answer_cache._key("bvsc", question, "en") != answer_cache._key("bvsc", question, "hi")


def test_unsafe_results_are_not_cached():
    assert not answer_cache.put(
        "bvsc", "unknown", {"answer": "not sure", "source": "low-confidence"}, "en"
    )
