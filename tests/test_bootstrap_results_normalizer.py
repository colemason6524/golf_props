import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.normalization.bootstrap_results import normalize_file
from golf_props.schemas import (
    COURSES_COLUMNS,
    EVENT_COURSES_COLUMNS,
    EVENTS_COLUMNS,
    PLAYER_EVENT_RESULTS_COLUMNS,
    PLAYERS_COLUMNS,
    ROUND_SCORES_COLUMNS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pga_results.csv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_normalize_file_writes_canonical_tables(tmp_path):
    normalize_file(FIXTURE, tmp_path)

    expected_files = {
        "events.csv",
        "courses.csv",
        "players.csv",
        "event_courses.csv",
        "player_event_results.csv",
        "round_scores.csv",
        "data_quality_report.txt",
    }
    assert expected_files.issubset({path.name for path in tmp_path.iterdir()})


def test_normalized_tables_have_expected_rows_and_columns(tmp_path):
    normalize_file(FIXTURE, tmp_path)

    events = read_csv(tmp_path / "events.csv")
    courses = read_csv(tmp_path / "courses.csv")
    players = read_csv(tmp_path / "players.csv")
    event_courses = read_csv(tmp_path / "event_courses.csv")
    results = read_csv(tmp_path / "player_event_results.csv")
    round_scores = read_csv(tmp_path / "round_scores.csv")

    assert list(events[0].keys()) == EVENTS_COLUMNS
    assert list(courses[0].keys()) == COURSES_COLUMNS
    assert list(players[0].keys()) == PLAYERS_COLUMNS
    assert list(event_courses[0].keys()) == EVENT_COURSES_COLUMNS
    assert list(results[0].keys()) == PLAYER_EVENT_RESULTS_COLUMNS
    assert list(round_scores[0].keys()) == ROUND_SCORES_COLUMNS

    assert len(events) == 2
    assert len(courses) == 2
    assert len(players) == 3
    assert len(event_courses) == 2
    assert len(results) == 6
    assert len(round_scores) == 19


def test_round_scores_expand_one_row_per_available_round(tmp_path):
    normalize_file(FIXTURE, tmp_path)

    players = read_csv(tmp_path / "players.csv")
    results = read_csv(tmp_path / "player_event_results.csv")
    round_scores = read_csv(tmp_path / "round_scores.csv")

    spieth = next(row for row in players if row["player_name"] == "Jordan Spieth")
    spieth_results = [row for row in results if row["player_id"] == spieth["player_id"]]
    assert sorted(row["rounds_played"] for row in spieth_results) == ["1", "2"]

    spieth_rounds = [row for row in round_scores if row["player_id"] == spieth["player_id"]]
    assert len(spieth_rounds) == 3
    assert sorted(row["round_number"] for row in spieth_rounds) == ["1", "1", "2"]


def test_cli_normalize_bootstrap_results(tmp_path):
    exit_code = main(
        [
            "normalize-bootstrap-results",
            "--input",
            str(FIXTURE),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "data_quality_report.txt").exists()
