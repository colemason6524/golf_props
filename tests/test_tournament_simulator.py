import csv

from golf_props.cli import main
from golf_props.models.round_strength import ROUND_STRENGTH_COLUMNS
from golf_props.models.tournament_simulator import (
    SIMULATION_COLUMNS,
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
