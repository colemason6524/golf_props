import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.features.round_performance import build_round_performance
from golf_props.models.round_strength import (
    ROUND_STRENGTH_COLUMNS,
    build_round_strength_snapshot,
    estimate_strength_rows,
    prepare_round_history,
)
from golf_props.normalization.bootstrap_results import normalize_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prepare_inputs(tmp_path):
    processed = tmp_path / "processed"
    round_performance = tmp_path / "round_performance.csv"
    field = tmp_path / "field.csv"
    normalize_file(FIXTURE, processed)
    build_round_performance(processed, round_performance)
    field.write_text(
        "player_name,entry_status\n"
        "Scottie Scheffler,confirmed\n"
        "Rory McIlroy,confirmed\n"
        "New Player,confirmed\n",
        encoding="utf-8",
    )
    return round_performance, field


def test_round_strength_is_point_in_time_and_shrunk(tmp_path):
    round_performance, field = prepare_inputs(tmp_path)
    output = tmp_path / "strength.csv"

    build_round_strength_snapshot(
        round_performance,
        field,
        output,
        "2025-04-01",
        half_life_days=180,
        prior_rounds=4,
    )
    rows = read_csv(output)
    scottie = next(row for row in rows if row["player_name"] == "Scottie Scheffler")
    rory = next(row for row in rows if row["player_name"] == "Rory McIlroy")
    new_player = next(row for row in rows if row["player_name"] == "New Player")

    assert list(rows[0]) == ROUND_STRENGTH_COLUMNS
    assert scottie["rounds_used"] == "4"
    assert scottie["history_end_date"] == "2025-03-16"
    assert float(rory["shrunk_mean_relative"]) > float(
        scottie["shrunk_mean_relative"]
    )
    assert abs(float(scottie["shrunk_mean_relative"])) < abs(
        float(scottie["weighted_mean_relative"])
    )
    assert new_player["player_match_status"] == "unmatched_player_name"
    assert new_player["rounds_used"] == "0"


def test_round_strength_excludes_event_not_completed_at_cutoff(tmp_path):
    round_performance, field = prepare_inputs(tmp_path)
    output = tmp_path / "strength.csv"

    build_round_strength_snapshot(
        round_performance,
        field,
        output,
        "2025-03-16",
    )
    rows = read_csv(output)
    scottie = next(row for row in rows if row["player_name"] == "Scottie Scheffler")

    assert scottie["rounds_used"] == "0"
    assert scottie["player_match_status"] == "matched_no_prior_rounds"


def test_stale_rounds_lose_reliability():
    round_rows = []
    for player_id, player_name, performance in [
        ("player_old", "Old Player", "5.0"),
        ("player_other", "Other Player", "-5.0"),
    ]:
        round_rows.extend(
            {
                "event_id": "old_event",
                "event_date_start": "2020-01-01",
                "event_date_end": "2020-01-04",
                "player_id": player_id,
                "player_name": player_name,
                "relative_to_field": performance,
            }
            for _ in range(20)
        )
    rows, _ = estimate_strength_rows(
        round_rows,
        [{"player_id": "player_old", "player_name": "Old Player"}],
        "2026-01-01",
        half_life_days=180,
        prior_rounds=4,
    )

    assert float(rows[0]["effective_rounds"]) < 0.01
    assert abs(float(rows[0]["shrunk_mean_relative"])) < 0.01


def test_prepared_history_matches_direct_estimate(tmp_path):
    round_performance, _ = prepare_inputs(tmp_path)
    round_rows = read_csv(round_performance)
    field_rows = [
        {"player_name": "Scottie Scheffler"},
        {"player_name": "Rory McIlroy"},
    ]

    direct_rows, direct_summary = estimate_strength_rows(
        round_rows,
        field_rows,
        "2025-04-01",
    )
    indexed_rows, indexed_summary = estimate_strength_rows(
        round_rows,
        field_rows,
        "2025-04-01",
        prepared_history=prepare_round_history(round_rows),
    )

    assert indexed_rows == direct_rows
    assert indexed_summary == direct_summary


def test_cli_build_round_strength(tmp_path):
    round_performance, field = prepare_inputs(tmp_path)
    output = tmp_path / "strength.csv"
    report = tmp_path / "strength.report.md"

    exit_code = main(
        [
            "build-round-strength",
            "--round-performance",
            str(round_performance),
            "--field",
            str(field),
            "--output",
            str(output),
            "--report-output",
            str(report),
            "--as-of-date",
            "2025-04-01",
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert report.exists()
