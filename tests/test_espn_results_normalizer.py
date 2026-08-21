import csv
from pathlib import Path

from golf_props.cli import main
from golf_props.normalization.espn_results import normalize_file
from golf_props.schemas import (
    COURSES_COLUMNS,
    EVENTS_COLUMNS,
    PLAYER_EVENT_RESULTS_COLUMNS,
    PLAYERS_COLUMNS,
    ROUND_SCORES_COLUMNS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_espn_pga_results.tsv"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_espn_normalizer_writes_canonical_tables(tmp_path):
    normalize_file(FIXTURE, tmp_path)

    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "courses.csv").exists()
    assert (tmp_path / "players.csv").exists()
    assert (tmp_path / "player_event_results.csv").exists()
    assert (tmp_path / "round_scores.csv").exists()
    assert (tmp_path / "data_quality_report.txt").exists()


def test_espn_normalizer_parses_statuses_and_rounds(tmp_path):
    normalize_file(FIXTURE, tmp_path)

    events = read_csv(tmp_path / "events.csv")
    courses = read_csv(tmp_path / "courses.csv")
    players = read_csv(tmp_path / "players.csv")
    results = read_csv(tmp_path / "player_event_results.csv")
    round_scores = read_csv(tmp_path / "round_scores.csv")

    assert list(events[0].keys()) == EVENTS_COLUMNS
    assert list(courses[0].keys()) == COURSES_COLUMNS
    assert list(players[0].keys()) == PLAYERS_COLUMNS
    assert list(results[0].keys()) == PLAYER_EVENT_RESULTS_COLUMNS
    assert list(round_scores[0].keys()) == ROUND_SCORES_COLUMNS

    assert len(events) == 2
    assert len(courses) == 2
    assert len(players) == 3
    assert len(results) == 4
    assert len(round_scores) == 11

    cut = next(row for row in results if row["finish_text"] == "CUT")
    wd = next(row for row in results if row["finish_text"] == "WD")
    tied = next(row for row in results if row["finish_text"] == "T2")

    assert cut["made_cut"] == "False"
    assert cut["finish_position"] == ""
    assert wd["withdrawn"] == "True"
    assert wd["made_cut"] == "False"
    assert tied["finish_position"] == "2"
    assert tied["earnings"] == "500000.5"


def test_cli_normalize_espn_results(tmp_path):
    exit_code = main(
        [
            "normalize-espn-results",
            "--input",
            str(FIXTURE),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "events.csv").exists()
