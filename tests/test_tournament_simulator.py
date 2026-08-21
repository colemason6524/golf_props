import csv
import json

import pytest

from golf_props.cli import main
from golf_props.models.round_strength import ROUND_STRENGTH_COLUMNS
from golf_props.models.tournament_simulator import (
    CUT_RULE_NO_CUT,
    CUT_RULE_TOP_N_AND_TIES,
    SIMULATION_COLUMNS,
    TournamentSimulationError,
    run_tournament_simulation,
    simulate_tournament_rows,
)


def strength_rows():
    return [
        {
            "player_id": f"player_{index}",
            "player_name": name,
            "entry_status": "confirmed",
            "player_match_status": "matched_player_name",
            "as_of_date": "2026-07-30",
            "rounds_used": 100,
            "effective_rounds": 50,
            "history_start_date": "2020-01-01",
            "history_end_date": "2026-07-20",
            "long_term_mean_relative": strength,
            "recent_90_mean_relative": strength,
            "recent_365_mean_relative": strength,
            "weighted_mean_relative": strength,
            "shrunk_mean_relative": strength,
            "weighted_std_relative": 1.5,
            "shrunk_std_relative": 1.5,
        }
        for index, (name, strength) in enumerate(
            [
                ("Strong Player", 3.0),
                ("Above Average", 1.0),
                ("Below Average", -1.0),
                ("Weak Player", -3.0),
            ]
        )
    ]


def write_strengths(path):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROUND_STRENGTH_COLUMNS)
        writer.writeheader()
        writer.writerows(strength_rows())


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_simulator_is_seeded_field_aware_and_coherent():
    rows, summary = simulate_tournament_rows(
        strength_rows(),
        "Test Event",
        "2026-07-30",
        simulations=4000,
        seed=7,
        cut_size=2,
        batch_size=500,
    )
    repeated, repeated_summary = simulate_tournament_rows(
        strength_rows(),
        "Test Event",
        "2026-07-30",
        simulations=4000,
        seed=7,
        cut_size=2,
        batch_size=500,
    )
    by_name = {row["player_name"]: row for row in rows}

    assert rows == repeated
    assert summary == repeated_summary
    assert abs(summary["sum_winner_probability"] - 1.0) < 0.00001
    assert summary["average_players_making_cut"] >= 2
    assert by_name["Strong Player"]["winner_prob"] > by_name["Weak Player"][
        "winner_prob"
    ]
    assert by_name["Strong Player"]["make_cut_prob"] > by_name["Weak Player"][
        "make_cut_prob"
    ]
    for row in rows:
        assert row["winner_prob"] <= row["top5_prob"]
        assert row["top5_prob"] <= row["top10_prob"]
        assert row["top10_prob"] <= row["top20_prob"]
        assert row["top20_prob"] <= row["make_cut_prob"]


def test_cli_simulate_tournament(tmp_path):
    strengths = tmp_path / "strengths.csv"
    output_dir = tmp_path / "simulation"
    write_strengths(strengths)

    exit_code = main(
        [
            "simulate-tournament",
            "--strengths",
            str(strengths),
            "--output-dir",
            str(output_dir),
            "--event-name",
            "Test Event",
            "--event-date",
            "2026-07-30",
            "--simulations",
            "500",
            "--seed",
            "7",
            "--cut-size",
            "2",
        ]
    )
    rows = read_csv(output_dir / "predictions.csv")

    assert exit_code == 0
    assert list(rows[0]) == SIMULATION_COLUMNS
    assert len(rows) == 4
    assert (output_dir / "report.md").exists()
    assert (output_dir / "summary.json").exists()


def test_no_cut_makes_every_active_player_advance():
    rows, summary = simulate_tournament_rows(
        strength_rows(),
        "No Cut Event",
        "2026-08-01",
        simulations=2000,
        seed=11,
        cut_size=2,
        cut_rule=CUT_RULE_NO_CUT,
        batch_size=500,
    )

    assert summary["cut_rule"] == CUT_RULE_NO_CUT
    assert summary["cut_applied"] is False
    assert summary["configured_cut_size"] == 2
    assert summary["cut_size"] == 4
    assert summary["average_players_making_cut"] == 4.0
    assert all(row["make_cut_prob"] == 1.0 for row in rows)
    for row in rows:
        assert row["winner_prob"] <= row["top5_prob"]
        assert row["top5_prob"] <= row["top10_prob"]
        assert row["top10_prob"] <= row["top20_prob"]
        assert row["top20_prob"] <= row["make_cut_prob"]


def test_no_cut_is_reproducible_and_ranked_like_top_n():
    first, first_summary = simulate_tournament_rows(
        strength_rows(),
        "No Cut Event",
        "2026-08-01",
        simulations=4000,
        seed=9,
        cut_size=2,
        cut_rule=CUT_RULE_NO_CUT,
        batch_size=500,
    )
    second, second_summary = simulate_tournament_rows(
        strength_rows(),
        "No Cut Event",
        "2026-08-01",
        simulations=4000,
        seed=9,
        cut_size=2,
        cut_rule=CUT_RULE_NO_CUT,
        batch_size=500,
    )
    by_name = {row["player_name"]: row for row in first}

    assert first == second
    assert first_summary == second_summary
    assert by_name["Strong Player"]["winner_prob"] > by_name["Weak Player"][
        "winner_prob"
    ]
    assert by_name["Strong Player"]["top20_prob"] == 1.0
    assert by_name["Weak Player"]["top20_prob"] == 1.0


def test_no_cut_excludes_inactive_entries():
    rows = strength_rows()
    rows.append(
        {
            "player_id": "player_inactive",
            "player_name": "Inactive Player",
            "entry_status": "withdrawn",
            "player_match_status": "matched_player_name",
            "as_of_date": "2026-07-30",
            "rounds_used": 100,
            "effective_rounds": 50,
            "history_start_date": "2020-01-01",
            "history_end_date": "2026-07-20",
            "long_term_mean_relative": 0.0,
            "recent_90_mean_relative": 0.0,
            "recent_365_mean_relative": 0.0,
            "weighted_mean_relative": 0.0,
            "shrunk_mean_relative": 0.0,
            "weighted_std_relative": 1.5,
            "shrunk_std_relative": 1.5,
        }
    )
    rows, summary = simulate_tournament_rows(
        rows,
        "No Cut Event",
        "2026-08-01",
        simulations=500,
        seed=3,
        cut_rule=CUT_RULE_NO_CUT,
        batch_size=500,
    )

    assert summary["field_size"] == 4
    assert summary["inactive_rows_excluded"] == 1
    assert len(rows) == 4
    assert all(row["make_cut_prob"] == 1.0 for row in rows)


def test_invalid_cut_rule_is_rejected():
    with pytest.raises(TournamentSimulationError, match="unsupported cut_rule"):
        simulate_tournament_rows(
            strength_rows(),
            "Bad Rule",
            "2026-08-01",
            simulations=100,
            cut_rule="not_a_rule",
        )


def test_nonpositive_cut_size_is_rejected_in_cut_mode():
    with pytest.raises(TournamentSimulationError, match="cut_size"):
        simulate_tournament_rows(
            strength_rows(),
            "Bad Cut",
            "2026-08-01",
            simulations=100,
            cut_size=0,
            cut_rule=CUT_RULE_TOP_N_AND_TIES,
        )


def test_cli_simulate_tournament_no_cut(tmp_path):
    strengths = tmp_path / "strengths.csv"
    output_dir = tmp_path / "simulation_no_cut"
    write_strengths(strengths)

    exit_code = main(
        [
            "simulate-tournament",
            "--strengths",
            str(strengths),
            "--output-dir",
            str(output_dir),
            "--event-name",
            "No Cut Event",
            "--event-date",
            "2026-08-01",
            "--simulations",
            "500",
            "--seed",
            "7",
            "--cut-rule",
            CUT_RULE_NO_CUT,
        ]
    )
    rows = read_csv(output_dir / "predictions.csv")
    summary = json.loads((output_dir / "summary.json").read_text())

    assert exit_code == 0
    assert summary["cut_rule"] == CUT_RULE_NO_CUT
    assert summary["cut_applied"] is False
    assert all(row["make_cut_prob"] == "1.0" for row in rows)
    report = (output_dir / "report.md").read_text()
    assert "no cut" in report
    assert "make_cut_prob is structural" in report
