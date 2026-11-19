"""Round-score O/U scaffold self-check: projection math, FanDuel parse, grading."""
import pandas as pd

from golf_props.props_ou import grade, ledger, lines, project, publish


def test_prob_over_symmetry():
    assert abs(project.prob_over(70.0, 70.0, 2.95) - 0.5) < 1e-9
    assert project.prob_over(69.0, 71.5, 2.95) < 0.25
    assert project.prob_over(74.0, 71.5, 2.95) > 0.75


def test_parse_round_score_markets():
    payload = {"attachments": {
        "events": {"E1": {"name": "PGA Test Event"}},
        "markets": {"M1": {
            "marketId": "M1", "eventId": "E1",
            "marketName": "Scheffler Round 1 Score",
            "runners": [
                {"runnerName": "Over 68.5",
                 "winRunnerOdds": {"americanOdds": -110}, "handicap": 0},
                {"runnerName": "Under 68.5",
                 "winRunnerOdds": {"americanOdds": -110}, "handicap": 0}],
        }},
    }}
    out = lines.parse_round_score_markets(payload, "2026-11-19T00:00:00+00:00")
    assert len(out) == 1
    ln = out[0]
    assert (ln.player_name, ln.round_number, ln.line) == ("Scheffler", 1, 68.5)
    assert (ln.over_american, ln.under_american) == (-110, -110)


def test_parse_skips_non_ou():
    payload = {"attachments": {"events": {}, "markets": {"M9": {
        "marketId": "M9", "eventId": "E1", "marketName": "Winner",
        "runners": [{"runnerName": "A", "winRunnerOdds": {"americanOdds": 500}}]}}}}
    assert lines.parse_round_score_markets(payload, "t") == []


def test_grade_win_loss_void():
    table = pd.DataFrame([
        {"player_id": "p1", "player_name": "Ann One", "event_id": "E",
         "round_number": 1, "score": 69.0},
        {"player_id": "p2", "player_name": "Bet Two", "event_id": "E",
         "round_number": 1, "score": 72.0},
    ])
    rows = [
        {"player_id": "p1", "event_id": "E", "round_number": 1, "line": 70.5,
         "side": "UNDER", "decimal": 1.909, "result": "open", "units": 0.0},
        {"player_id": "p2", "event_id": "E", "round_number": 1, "line": 70.5,
         "side": "UNDER", "decimal": 1.909, "result": "open", "units": 0.0},
        {"player_id": "p3", "event_id": "E", "round_number": 3, "line": 71.5,
         "side": "OVER", "decimal": 1.909, "result": "open", "units": 0.0},
    ]
    # p3 never appears in this event's history slice -> void_unmatched here
    got = grade.settle(rows, table)
    assert [r["result"] for r in got] == ["win", "loss", "void_unmatched"]
    s = ledger.summary(got)
    assert s["settled"] == 2 and abs(s["units"] - (0.909 - 1.0)) < 1e-9


def test_gates_closed_on_empty():
    assert publish.soft_publish_gate([]) == (False, "no fully settled shadow event yet")
    ok, _ = publish.graduation([])
    assert not ok


def test_parse_strokes_variant():
    payload = {"attachments": {
        "events": {"E9": {"name": "PGA The RSM Classic 2026"}},
        "markets": {"M9": {
            "marketId": "M9", "eventId": "E9",
            "marketName": "Michael Thorbjornsen Round 1 Strokes",
            "runners": [
                {"runnerName": "Over 67.5",
                 "winRunnerOdds": {"americanOdds": -120}, "handicap": 0},
                {"runnerName": "Under 67.5",
                 "winRunnerOdds": {"americanOdds": 100}, "handicap": 0}],
        }},
    }}
    out = lines.parse_round_score_markets(payload, "2026-11-19T00:00:00+00:00")
    assert len(out) == 1
    ln = out[0]
    assert (ln.player_name, ln.round_number, ln.line) == ("Michael Thorbjornsen", 1, 67.5)
    assert (ln.over_american, ln.under_american) == (-120, 100)


def test_observed_line_one_sided():
    from golf_props.props_ou import shadow
    ln = lines.observed_line(
        "Michael Thorbjornsen", 1, 67.5, -120, None,
        "Michael Thorbjornsen Round 1 Strokes", "rsm-classic-2026",
        "PGA The RSM Classic 2026", "Cole", "2026-11-19T04:30:00+00:00")
    assert ln.source == "fanatics-observed"
    row = shadow.pick_row(70.08, 3.30, ln)
    assert row["side"] == "OVER" and row["tier"] == "OBSERVED_LEAN"
    assert row["ev"] is None and row["p_market"] is None
    assert row["p_model"] > 0.75
