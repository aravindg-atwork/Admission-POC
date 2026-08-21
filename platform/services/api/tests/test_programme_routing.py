from app.core.routing import effective_project


def test_explicit_programme_overrides_stale_selection():
    assert effective_project("What is B.Tech Dairy eligibility?", "bvsc") == "btech-dairy"
    assert effective_project("Tell me B.F.Sc. fees", "bvsc") == "bfsc"
    assert effective_project("Can I get veterinary B.V.Sc.?", "bfsc") == "bvsc"


def test_implicit_followup_keeps_current_programme():
    assert effective_project("What about the fees?", "btech-dairy") == "btech-dairy"
    assert effective_project(
        "Do I have to pay the special fee every semester?", "bfsc"
    ) == "bfsc"


def test_comparison_does_not_silently_pick_one_programme():
    assert effective_project("Compare B.V.Sc. and B.F.Sc.", "bvsc") == "bvsc"
