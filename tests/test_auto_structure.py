from golf_props.events.auto_structure import (
    DECISION_EXCLUDE,
    DECISION_INCLUDE,
    classify_event,
)


def test_registry_override_wins_and_is_logged():
    registry_structure = {
        "event_name": "TOUR Championship",
        "season": 2026,
        "format": "72_hole_stroke_play",
        "rounds": 4,
        "cut_rule": "no_cut",
        "cut_size": 0,
        "decision_status": "reviewed",
        "reviewed_at_utc": "2026-08-21T00:00:00Z",
        "notes": "",
    }
    decision = classify_event("TOUR Championship", 2026, registry_structure)
    assert decision["decision"] == DECISION_INCLUDE
    assert decision["cut_rule"] == "no_cut"
    assert decision["structure_source"] == "registry_override"


def test_ordinary_event_auto_included():
    decision = classify_event("Biltmore Championship Asheville", 2026, None)
    assert decision["decision"] == DECISION_INCLUDE
    assert decision["cut_rule"] == "top_n_and_ties"
    assert decision["cut_size"] == 65
    assert decision["structure_source"] == "auto_default_policy"


def test_team_event_excluded():
    for name in ("Presidents Cup", "Ryder Cup", "The Solheim Cup"):
        decision = classify_event(name, 2026, None)
        assert decision["decision"] == DECISION_EXCLUDE


def test_qschool_and_proam_excluded():
    assert classify_event("PGA TOUR Q-School presented by Korn Ferry", 2026, None)[
        "decision"
    ] == DECISION_EXCLUDE
    assert classify_event("Grant Thornton Invitational", 2026, None)[
        "decision"
    ] == DECISION_EXCLUDE


def test_playoff_event_auto_included_no_cut_without_registry():
    # Playoff events are no-cut: auto-include under the explicit no_cut rule
    # rather than withholding, so no top-65 cut is ever guessed onto them.
    for name in (
        "TOUR Championship",
        "FedEx St. Jude Championship",
        "BMW Championship",
    ):
        decision = classify_event(name, 2026, None)
        assert decision["decision"] == DECISION_INCLUDE
        assert decision["cut_rule"] == "no_cut"
        assert decision["cut_size"] == 0
        assert decision["rounds"] == 4
        assert decision["structure_source"] == "auto_playoff_no_cut"


def test_playoff_registry_override_still_wins():
    registry_structure = {
        "event_name": "TOUR Championship",
        "season": 2026,
        "format": "72_hole_stroke_play",
        "rounds": 4,
        "cut_rule": "top_n_and_ties",
        "cut_size": 65,
        "decision_status": "reviewed",
        "reviewed_at_utc": "2026-08-21T00:00:00Z",
        "notes": "",
    }
    decision = classify_event("TOUR Championship", 2026, registry_structure)
    assert decision["decision"] == DECISION_INCLUDE
    assert decision["cut_rule"] == "top_n_and_ties"
    assert decision["structure_source"] == "registry_override"
