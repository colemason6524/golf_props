"""Round-score O/U scaffold self-check: projection math, FanDuel parse, grading."""
import pandas as pd

from golf_props.props_ou import grade, ledger, lines, project, publish, shadow


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


def test_pick_id_is_source_aware():
    """One row per (player, round, book): same line at two books is two rows."""
    base = {"date": "d", "player_id": "p", "event_id": "E", "round_number": 1,
            "line": 67.5, "side": "OVER"}
    a = dict(base, source="draftkings-browser-read")
    b = dict(base, source="fanatics-observed")
    assert ledger.pick_id(a) != ledger.pick_id(b)


def test_folded_name_resolves_amateur_and_diacritics():
    table = pd.DataFrame([
        {"player_id": "p_koivun", "player_name": "Jackson Koivun (a)"},
        {"player_id": "p_val", "player_name": "Sami V\u00e4lim\u00e4ki"},
        {"player_id": "p_thor", "player_name": "Michael Thorbjornsen (a)"},
        {"player_id": "p_pro", "player_name": "Michael Thorbjornsen"},
    ]).assign(event_date_end="2026-01-01")
    index, folded = shadow._name_index(table), shadow._fold_index(table)
    assert shadow.resolve_player(index, folded, "Jackson Koivun") == "p_koivun"
    assert shadow.resolve_player(index, folded, "Sami Valimaki") == "p_val"
    # exact match wins: never resolves through the amateur row
    assert shadow.resolve_player(index, folded, "Michael Thorbjornsen") == "p_pro"
    assert shadow.resolve_player(index, folded, "Nobody Here") is None


def test_unpriced_rows_do_not_block_a_clean_event():
    rows = [{"event_id": "E", "event_name": "E", "tier": "PLAYABLE",
             "result": "win", "units": 0.9},
            {"event_id": "E", "event_name": "E", "tier": "NO_VALUE",
             "result": "no_pick", "units": 0.0}]
    ev = publish.settled_events(rows)["E"]
    assert ev["no_pick"] == 1 and ev["open"] == 0 and ev["clean"] is True


def _ingest_cli():
    import sys
    from pathlib import Path
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import props_ou_ingest
    return props_ou_ingest


def test_ingest_lines_file_parser(tmp_path):
    """Verbatim rows survive; a malformed row raises instead of guessing."""
    cli = _ingest_cli()
    f = tmp_path / "lines.csv"
    f.write_text("player,line,over,under\n"
                 "Harris English,68.5,102,-138\n"
                 "Michael Thorbjornsen,67.5,-120,\n", encoding="utf-8")
    assert cli.load_lines(f) == [("Harris English", 68.5, 102, -138),
                                ("Michael Thorbjornsen", 67.5, -120, None)]
    f.write_text("player,line,over,under\nHarris English,abc,102,-138\n",
                 encoding="utf-8")
    try:
        cli.load_lines(f)
    except ValueError as err:
        assert "lines.csv:2" in str(err)
    else:
        raise AssertionError("malformed line was accepted")
